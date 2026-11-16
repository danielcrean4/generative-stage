"""Read what each pipeline run did, step by step, from the files already on disk.

Pure functions over a runs root (MachineConfig.runs_root); no HTTP, no writes. The layout read:

    <runs_root>/<run_id>/latest.json                      pointer to the newest attempt
    <runs_root>/<run_id>/attempts/<attempt_id>/attempt.json
    <runs_root>/<run_id>/attempts/<attempt_id>/<stage>/   stage.json, reports, outputs, step.log
    <runs_root>/<run_id>/<file>                           heads and icon runs keep files here

Stage names are never listed in this file: they come from attempt.json and the folders that
exist. Every id and path segment is checked against a strict pattern and every file is resolved
(symlinks included) to stay inside its run folder; anything else raises NotFound.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
MAX_PATH_SEGMENTS = 4
LOG_TAIL_BYTES = 200 * 1024
ROOT_STAGE = "_root"
MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "glb": "model/gltf-binary",
    "json": "application/json",
    "log": "text/plain; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}
# Reports a stage can leave; each is shown as a gate. The report's own content says pass or fail.
GATE_FILES = ("image-validation.json", "matte.json", "mesh-validation.json")
POINTER_FILE = "latest.json"
API = "/api/ro/runs"


class NotFound(LookupError):
    """The id, path or file does not exist or is not allowed; the message is safe to show."""


class BadData(RuntimeError):
    """A file on disk does not have the shape this reader needs; the message names the file."""


@dataclass(frozen=True)
class ServedFile:
    path: Path
    media_type: str
    size: int  # bytes on disk
    truncated: bool  # only the last LOG_TAIL_BYTES are to be sent


def media_type(name: str) -> str | None:
    return MEDIA_TYPES.get(name.rpartition(".")[2].lower()) if "." in name else None


def _id(value: str, what: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise NotFound(f"no such {what}")
    return value


def _inside(path: Path, base: Path) -> Path:
    """The resolved path, or NotFound if it (after symlinks) is not inside the resolved base."""
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise NotFound("no such file") from error
    if not real.is_relative_to(base):
        raise NotFound("no such file")
    return real


def _run_dir(runs_root: Path, run_id: str) -> Path:
    base = runs_root.resolve()
    run = _inside(base / _id(run_id, "run"), base)
    if not run.is_dir():
        raise NotFound("no such run")
    return run


def run_exists(runs_root: Path, run_id: str) -> bool:
    """Whether a run with this id is in the runs root (the check the world model is given)."""
    try:
        _run_dir(runs_root, run_id)
    except NotFound:
        return False
    return True


def _attempt_dir(runs_root: Path, run_id: str, attempt_id: str) -> Path:
    run = _run_dir(runs_root, run_id)
    attempt = _inside(run / "attempts" / _id(attempt_id, "attempt"), run)
    if not attempt.is_dir():
        raise NotFound("no such attempt")
    return attempt


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BadData(f"{path}: cannot read as JSON ({error})") from error


def _read_object(path: Path) -> dict[str, Any]:
    doc = _read_json(path)
    if not isinstance(doc, dict):
        raise BadData(f"{path}: expected a JSON object, got {type(doc).__name__}")
    return doc


def _attempt_ids(run: Path) -> list[str]:
    """Attempt folder names, newest first (their names start with a UTC timestamp)."""
    folder = run / "attempts"
    if not folder.is_dir():
        return []
    names = [
        e.name
        for e in os.scandir(folder)
        if e.is_dir(follow_symlinks=False) and ID_PATTERN.fullmatch(e.name)
    ]
    return sorted(names, reverse=True)


def _stage_dirs(attempt: Path) -> list[Path]:
    return [
        Path(e.path)
        for e in os.scandir(attempt)
        if e.is_dir(follow_symlinks=False) and SEGMENT_PATTERN.fullmatch(e.name)
    ]


def _rank(name: str, wanted: list[str]) -> int:
    return wanted.index(name) if name in wanted else len(wanted)


def _stage_ids(attempt: Path, doc: dict[str, Any] | None) -> list[str]:
    """Stage ids in the order the attempt recorded them, then folders it did not record
    (a stage that failed or was interrupted), by recipe order, then oldest first."""
    recorded = list(doc.get("stages", {})) if doc and isinstance(doc.get("stages"), dict) else []
    recipe = doc.get("recipe") if doc else None
    wanted = recipe.get("stages", []) if isinstance(recipe, dict) else []
    job = doc.get("resolved_job") if doc else None
    if isinstance(job, dict) and isinstance(job.get("stages"), list):
        # The forge's pipeline runner saves attempt.json with sorted keys, so the order the stages ran in is
        # the resolved job's stage order (a retried stage's folder is `<id>.try<k>`, kept after its first try).
        wanted = [str(s.get("id")) for s in job["stages"] if isinstance(s, dict)]
        recorded.sort(key=lambda n: (_rank(n.split(".try")[0], wanted), n))
    extra = [d for d in _stage_dirs(attempt) if d.name not in recorded]
    extra.sort(
        key=lambda d: (
            _rank(d.name, wanted),
            d.stat().st_mtime_ns,
            d.name,
        )
    )
    return [*recorded, *(d.name for d in extra)]


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_attempt(attempt: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The attempt.json object and None, or None and a problem text (missing, unreadable)."""
    file = attempt / "attempt.json"
    if not file.is_file():
        return None, "attempt.json is missing (the attempt may still be running)"
    try:
        return _read_object(file), None
    except BadData as error:
        return None, str(error)


def _seed(doc: dict[str, Any]) -> Any:
    recipe = doc.get("recipe")
    if isinstance(recipe, dict):
        return recipe.get("seed")
    return doc.get("seed")  # an attempt from the forge's pipeline runner keeps its seed at the top


def _attempt_row(run_id: str, attempt: Path) -> dict[str, Any]:
    doc, problem = _load_attempt(attempt)
    row: dict[str, Any] = {
        "attempt_id": attempt.name,
        "status": doc.get("status") if doc else None,
        "error": doc.get("error") if doc else None,
        "started": doc.get("started_utc") if doc else None,
        "finished": doc.get("finished_utc") if doc else None,
        "seed": _seed(doc) if doc else None,
        "stages": _stage_ids(attempt, doc),
    }
    if problem:
        row["problem"] = problem
    return row


def _latest_attempt_id(run: Path) -> str | None:
    """The attempt latest.json points at when that folder exists, else the newest folder."""
    pointer = run / POINTER_FILE
    if pointer.is_file():
        try:
            named = Path(str(_read_object(pointer).get("attempt", ""))).name
        except BadData:
            named = ""
        if ID_PATTERN.fullmatch(named) and (run / "attempts" / named).is_dir():
            return named
    ids = _attempt_ids(run)
    return ids[0] if ids else None


def list_runs(runs_root: Path, limit: int = 50) -> dict[str, Any]:
    """The newest runs (by folder modification time), each with its latest attempt's summary."""
    base = runs_root.resolve()
    folders = [
        e
        for e in os.scandir(base)
        if e.is_dir(follow_symlinks=False) and ID_PATTERN.fullmatch(e.name)
    ]
    folders.sort(key=lambda e: (e.stat().st_mtime, e.name), reverse=True)
    runs = []
    for entry in folders[:limit]:
        run = Path(entry.path)
        latest = _latest_attempt_id(run)
        row: dict[str, Any] = {"run_id": entry.name, "latest_attempt_id": latest}
        if latest:
            summary = _attempt_row(entry.name, run / "attempts" / latest)
            row.update(
                {k: summary[k] for k in ("status", "error", "started", "finished", "stages")}
            )
            if "problem" in summary:
                row["problem"] = summary["problem"]
        else:
            row.update(status=None, error=None, started=None, finished=None, stages=[])
        row["modified"] = _iso(entry.stat().st_mtime)
        runs.append(row)
    return {"runs": runs, "total": len(folders), "limit": limit}


def _file_entry(real: Path, shown: str, url: str) -> dict[str, Any]:
    return {
        "name": shown,
        "size": real.stat().st_size,
        "media_type": media_type(real.name),
        "url": url,
    }


def _servable_files(folder: Path, base: Path, url_for: Any, max_depth: int) -> list[dict[str, Any]]:
    """Files of an allowed type under `folder`, to `max_depth` folder levels, that resolve
    inside `base`. Symlinks are not followed for folders; a file link out of `base` is skipped."""
    found: list[dict[str, Any]] = []

    def walk(current: Path, parts: tuple[str, ...]) -> None:
        for entry in sorted(os.scandir(current), key=lambda e: e.name):
            if not SEGMENT_PATTERN.fullmatch(entry.name):
                continue
            if entry.is_dir(follow_symlinks=False):
                if len(parts) < max_depth:
                    walk(Path(entry.path), (*parts, entry.name))
            elif entry.is_file() and media_type(entry.name):
                try:
                    real = _inside(Path(entry.path), base)
                except NotFound:
                    continue
                shown = "/".join((*parts, entry.name))
                found.append(_file_entry(real, shown, url_for(shown)))

    walk(folder, ())
    return found


def _quote_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in path.split("/"))


def get_run(runs_root: Path, run_id: str) -> dict[str, Any]:
    """Every attempt of a run, newest first, plus the files kept at the run root."""
    run = _run_dir(runs_root, run_id)
    attempts = [_attempt_row(run_id, run / "attempts" / a) for a in _attempt_ids(run)]
    root_files = [
        f
        for f in _servable_files(
            run,
            run,
            lambda name: f"{API}/{run_id}/files/{ROOT_STAGE}/{_quote_path(name)}",
            max_depth=0,
        )
        if f["name"] != POINTER_FILE
    ]
    return {
        "run_id": run_id,
        "latest_attempt_id": _latest_attempt_id(run),
        "attempts": attempts,
        "root_files": root_files,
    }


def _trim_recipe(recipe: Any) -> Any:
    """A stage recipe without the bulky environment record: `versions` is dropped and a model's
    file hash table is replaced by its count. Everything else, such as the resolved prompt, stays."""
    if not isinstance(recipe, dict):
        return recipe
    trimmed = {k: v for k, v in recipe.items() if k != "versions"}
    model = trimmed.get("model")
    if isinstance(model, dict) and isinstance(model.get("files"), dict):
        trimmed["model"] = {
            **{k: v for k, v in model.items() if k != "files"},
            "file_count": len(model["files"]),
        }
    return trimmed


def _gate(stage_dir: Path, name: str, url: str) -> dict[str, Any]:
    """One report as a gate. A report with a `passed` key gives pass or fail; one without (the
    image check lists the images it opened and raises on failure) gives passed null."""
    report = _read_json(stage_dir / name)
    if not isinstance(report, dict):
        return {
            "file": name,
            "url": url,
            "passed": None,
            "verdict": None,
            "reasons": [],
            "measures": report,
        }
    measures = report.get("measures")
    if measures is None:
        measures = {k: v for k, v in report.items() if k not in ("passed", "reasons", "thresholds")}
    return {
        "file": name,
        "url": url,
        "passed": report.get("passed"),
        "verdict": report.get(
            "verdict"
        ),  # gate v2 says pass, review or fail; older reports have none
        "reasons": report.get("reasons", []),
        "measures": measures,
        "thresholds": report.get("thresholds"),
    }


def _stage_view(
    run_id: str, attempt_id: str, attempt: Path, stage: str, recorded: dict[str, Any] | None
) -> dict[str, Any]:
    folder = attempt / stage
    base = f"{API}/{run_id}/attempts/{attempt_id}/files/{stage}"

    def url_for(name: str) -> str:
        return f"{base}/{_quote_path(name)}"

    view: dict[str, Any] = {
        "stage": stage,
        "recorded": recorded is not None,
        "cache_key": recorded.get("key") if recorded else None,
        "reused": recorded.get("reused") if recorded else None,
        "status": recorded.get("status") if recorded else None,
        "seed": None,
        "seed_used": None,
        "tries": None,
        "recipe": None,
        "gates": [],
        "files": [],
    }
    if not folder.is_dir():
        return view
    stage_json = folder / "stage.json"
    detail = _read_object(stage_json) if stage_json.is_file() else {}
    recipe = detail.get("recipe")
    view["recipe"] = _trim_recipe(recipe)
    view["seed"] = recipe.get("seed") if isinstance(recipe, dict) else None
    view["seed_used"] = detail.get("seed_used", recorded.get("seed_used") if recorded else None)
    tries = detail.get("tries", recorded.get("tries") if recorded else None)
    view["tries"] = tries
    view["retry_errors"] = detail.get("retry_errors")
    view["gates"] = [_gate(folder, n, url_for(n)) for n in GATE_FILES if (folder / n).is_file()]
    # Each try keeps its own report; show it as a gate too, so a failed try is visible.
    for entry in tries if isinstance(tries, list) else []:
        report = entry.get("report") if isinstance(entry, dict) else None
        if isinstance(report, str) and all(SEGMENT_PATTERN.fullmatch(p) for p in report.split("/")):
            if (folder / report).is_file():
                view["gates"].append(_gate(folder, report, url_for(report)))
    view["files"] = _servable_files(folder, attempt, url_for, max_depth=2)
    return view


def get_attempt(runs_root: Path, run_id: str, attempt_id: str) -> dict[str, Any]:
    """The step-by-step view of one attempt."""
    attempt = _attempt_dir(runs_root, run_id, attempt_id)
    doc, problem = _load_attempt(attempt)
    recorded_stages = doc.get("stages") if doc else None
    recorded_stages = recorded_stages if isinstance(recorded_stages, dict) else {}
    stages = [
        _stage_view(run_id, attempt_id, attempt, name, recorded_stages.get(name))
        for name in _stage_ids(attempt, doc)
    ]
    recipe = doc.get("recipe") if doc else None
    return {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "status": doc.get("status") if doc else None,
        "error": doc.get("error") if doc else None,
        "started": doc.get("started_utc") if doc else None,
        "finished": doc.get("finished_utc") if doc else None,
        "seed": _seed(doc) if doc else None,
        "recipe": recipe,
        "problem": problem,
        "stages": stages,
    }


def _served(real: Path, name: str) -> ServedFile:
    kind = media_type(name)
    if kind is None or not real.is_file():
        raise NotFound("no such file")
    size = real.stat().st_size
    return ServedFile(real, kind, size, name.endswith(".log") and size > LOG_TAIL_BYTES)


def _segments(path: str) -> list[str]:
    parts = path.split("/")
    if len(parts) > MAX_PATH_SEGMENTS or not all(SEGMENT_PATTERN.fullmatch(p) for p in parts):
        raise NotFound("no such file")
    return parts


def find_file(runs_root: Path, run_id: str, attempt_id: str, stage: str, path: str) -> ServedFile:
    """A stage output of one attempt, or NotFound."""
    attempt = _attempt_dir(runs_root, run_id, attempt_id)
    if stage == ROOT_STAGE:  # the run-root files, reachable from an attempt URL too
        return find_root_file(runs_root, run_id, path)
    parts = _segments(path)
    if not SEGMENT_PATTERN.fullmatch(stage):
        raise NotFound("no such stage")
    real = _inside(attempt.joinpath(stage, *parts), attempt)
    return _served(real, parts[-1])


def run_file(runs_root: Path, run_id: str, reference: str) -> Path:
    """A file inside a run folder named by its path relative to that folder (a chosen candidate
    such as `attempts/<attempt>/mesh/mesh.glb`), or NotFound. Every segment must match the strict
    pattern (so no `..`, no absolute path) and the file, symlinks resolved, must stay inside the run."""
    run = _run_dir(runs_root, run_id)
    parts = reference.split("/")
    if len(parts) > MAX_PATH_SEGMENTS + 2 or not all(SEGMENT_PATTERN.fullmatch(p) for p in parts):
        raise NotFound("no such file")
    real = _inside(run.joinpath(*parts), run)
    if not real.is_file():
        raise NotFound("no such file")
    return real


def candidate_verdict(runs_root: Path, run_id: str, candidate: str) -> str | None:
    """The gate outcome of the stage that made a candidate: `pass`, `review` or `fail`, the worst
    of that stage's reports. None when the candidate is not under `attempts/<attempt>/<stage>/`
    or its stage left no report."""
    parts = candidate.split("/")
    if len(parts) < 4 or parts[0] != "attempts":
        return None
    try:
        attempt = _attempt_dir(runs_root, run_id, parts[1])
        stage = _inside(attempt / _id(parts[2], "stage"), attempt)
        reports = [stage / n for n in GATE_FILES if (stage / n).is_file()]
        outcomes = [gate_outcome(_gate(stage, report.name, "")) for report in reports]
    except (NotFound, BadData):
        return None
    for worst in ("fail", "review", "pass"):
        if worst in outcomes:
            return worst
    return None


def gate_outcome(gate: dict[str, Any]) -> str | None:
    if gate["verdict"] in ("pass", "review", "fail"):
        return str(gate["verdict"])
    if gate["passed"] is None:
        return None
    return "pass" if gate["passed"] else "fail"


def stage_record(runs_root: Path, run_id: str, attempt_id: str, stage: str) -> dict[str, Any]:
    """A stage folder's stage.json as an object; empty when the stage left none or it is unreadable."""
    try:
        attempt = _attempt_dir(runs_root, run_id, attempt_id)
        file = _inside(attempt / _id(stage, "stage") / "stage.json", attempt)
        return _read_object(file)
    except (NotFound, BadData):
        return {}


def attempt_record(runs_root: Path, run_id: str, attempt_id: str) -> dict[str, Any] | None:
    """The attempt's attempt.json as an object, or None when it is missing or unreadable."""
    try:
        doc = _read_json(_attempt_dir(runs_root, run_id, attempt_id) / "attempt.json")
    except (NotFound, BadData):
        return None
    return doc if isinstance(doc, dict) else None


def find_root_file(runs_root: Path, run_id: str, name: str) -> ServedFile:
    """A file kept at the run root (not the latest.json pointer), or NotFound."""
    run = _run_dir(runs_root, run_id)
    parts = _segments(name)
    if len(parts) != 1 or name == POINTER_FILE:
        raise NotFound("no such file")
    return _served(_inside(run / name, run), name)
