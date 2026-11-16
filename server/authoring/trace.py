"""One run's trace: what each stage did, with the exact prompt and context, as plain JSON.

Pure functions over a runs root; no HTTP, no writes. They join what the run view already reads
(stage folders, gate reports, files) with the attempt's own record (`attempt.json`: timing, model
identity, inputs, the resolved job). Nothing is invented: a field the run did not record is null
or left out, and `times` says when a start or end time is worked out rather than recorded.

A stage ends up `completed`, `supplied` (a saved file stood in for it; it did not run), `errored` (the tool failed, or the attempt stopped inside it; the
error text is shown), `running` or `not_run` (planned, never reached).
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from authoring import run_view
from core.errors import NotFound
from export.provenance import identity

MAX_MEASURES = 40
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FINISHED = ("generated", "review", "succeeded")

FileUrl = Callable[[str], str]  # a candidate path inside the run -> the URL it is served at


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _stamp(moment: datetime) -> str:
    return moment.strftime(TIME_FORMAT)


def _split_folder(folder: str) -> tuple[str, int]:
    """`mesh.try2` is the second retry of `mesh`; any other name is its own stage, try 0."""
    base, _, rest = folder.partition(".try")
    if rest.isdigit():
        return base, int(rest)
    return folder, 0


def _kind(media_type: str | None) -> str:
    if media_type and media_type.startswith("image/"):
        return "image"
    if media_type and media_type.startswith("model/"):
        return "model"
    return "other"


def _flat(value: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Measures as `[{name, value}]`: nested objects become dotted names, lists are shown whole
    as short text, and at most MAX_MEASURES are kept."""
    found: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, inner in value.items():
            found += _flat(inner, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        if all(isinstance(v, int | float | str) for v in value) and len(value) <= 8:
            found.append({"name": prefix or "value", "value": ", ".join(str(v) for v in value)})
        else:
            found.append({"name": prefix or "value", "value": f"{len(value)} items"})
    elif value is not None:
        found.append({"name": prefix or "value", "value": value})
    return found[:MAX_MEASURES]


def _gate(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "file": raw.get("file"),
        "outcome": run_view.gate_outcome(dict(raw)),
        "reasons": [str(r) for r in raw.get("reasons") or []],
        "measures": _flat(raw.get("measures")),
        "limits": _flat(raw.get("thresholds")),
    }


def _gates(view: Mapping[str, Any], entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The stage's gate reports; when it left none, the gate result kept in attempt.json."""
    gates = [_gate(g) for g in view["gates"]]
    recorded = entry.get("gate")
    if not gates and isinstance(recorded, Mapping):
        gates = [
            {
                "file": None,
                "outcome": recorded.get("verdict"),
                "reasons": [str(r) for r in recorded.get("reasons") or []],
                "measures": _flat(recorded.get("measures")),
                "limits": [],
            }
        ]
    return gates


def _inputs(detail: Mapping[str, Any], entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = detail.get("inputs") or entry.get("inputs")
    if not isinstance(raw, Mapping):
        return []
    found = []
    for name, value in sorted(raw.items()):
        source = value.get("from") if isinstance(value, Mapping) else value
        digest = value.get("sha256") if isinstance(value, Mapping) else None
        found.append({"name": str(name), "from": source, "sha256": digest})
    return found


def _parts(raw: object, text: str | None) -> list[dict[str, Any]] | None:
    """The recorded parts of a prompt, when they are well formed and add up to exactly TEXT; else None (the page then shows
    the plain text). Each part keeps its text, its source and its offsets."""
    if text is None or not isinstance(raw, list) or not raw:
        return None
    parts = []
    for item in raw:
        if not (
            isinstance(item, Mapping)
            and isinstance(item.get("text"), str)
            and isinstance(item.get("source"), Mapping)
            and isinstance(item["source"].get("kind"), str)
        ):
            return None
        parts.append(
            {
                "text": item["text"],
                "source": dict(item["source"]),
                "start": item.get("start"),
                "end": item.get("end"),
            }
        )
    return parts if "".join(p["text"] for p in parts) == text else None


def _stage(
    runs_root: Path,
    view: Mapping[str, Any],
    run_id: str,
    attempt_id: str,
    doc: Mapping[str, Any] | None,
    planned: Mapping[str, Mapping[str, Any]],
    file_url: FileUrl,
) -> dict[str, Any]:
    folder = view["stage"]
    stage_id, retry = _split_folder(folder)
    entry = ((doc or {}).get("stages") or {}).get(folder) or {}
    detail = run_view.stage_record(runs_root, run_id, attempt_id, folder)
    plan = planned.get(stage_id, {})
    supplied = {str(ref).split("/", 1)[0] for ref in (doc or {}).get("supplied") or {}}
    failed = entry.get("failed")
    files = [
        {
            "name": f["name"],
            "kind": _kind(f["media_type"]),
            "media_type": f["media_type"],
            "size": f["size"],
            "candidate": f"attempts/{attempt_id}/{folder}/{f['name']}",
            "url": file_url(f"attempts/{attempt_id}/{folder}/{f['name']}"),
        }
        for f in view["files"]
    ]
    is_supplied = (
        not entry and stage_id in supplied
    )  # a saved file stood in for this stage; it did not run
    prompt = (
        None if is_supplied else detail.get("prompt") or entry.get("prompt") or plan.get("prompt")
    )
    negative = detail.get("negative") or entry.get("negative")
    seconds = (entry.get("timing") or {}).get("seconds")
    prompt = prompt if isinstance(prompt, str) else None
    negative = negative if isinstance(negative, str) else None
    return {
        "id": stage_id,
        "folder": folder,
        "retry": retry,
        "label": plan.get("label") or stage_id,
        "tool": entry.get("tool") or plan.get("tool"),
        "status": "errored"
        if failed
        else "supplied"
        if is_supplied
        else "completed"
        if entry
        else None,
        "error": "; ".join(str(r) for r in failed) if failed else None,
        "reused": bool(entry.get("reused")),
        "reused_from": entry.get("reused_from"),
        "seconds": seconds if isinstance(seconds, int | float) else None,
        "started": None,
        "finished": None,
        "times": None,
        "seed": entry.get("seed", view.get("seed_used", view.get("seed"))),
        "key": entry.get("key") or view.get("cache_key"),
        "adapter": identity(entry.get("model") or detail.get("model")),
        "prompt": prompt,
        "negative": negative,
        "prompt_parts": _parts(detail.get("prompt_parts") or plan.get("prompt_parts"), prompt),
        "negative_parts": _parts(
            detail.get("negative_parts") or plan.get("negative_parts"), negative
        ),
        "params": plan.get("params"),
        "reads": plan.get("reads"),
        "inputs": _inputs(detail, entry),
        "gates": _gates(view, entry),
        "files": files,
    }


def _not_run(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": plan["id"],
        "folder": None,
        "retry": 0,
        "label": plan.get("label") or plan["id"],
        "tool": plan.get("tool"),
        "status": "not_run",
        "error": None,
        "reused": False,
        "reused_from": None,
        "seconds": None,
        "started": None,
        "finished": None,
        "times": None,
        "seed": None,
        "key": None,
        "adapter": {},
        "prompt": plan.get("prompt") if isinstance(plan.get("prompt"), str) else None,
        "negative": None,
        "prompt_parts": _parts(plan.get("prompt_parts"), plan.get("prompt")),
        "negative_parts": None,
        "params": plan.get("params"),
        "reads": plan.get("reads"),
        "inputs": [],
        "gates": [],
        "files": [],
    }


def _settle(stages: list[dict[str, Any]], doc: Mapping[str, Any] | None) -> None:
    """Give a stage with no record its status (the attempt stopped in it, or it is still going)
    and work out start and end times from the attempt's start and each stage's duration."""
    status = (doc or {}).get("status")
    crashed = doc is not None and status in ("failed", "interrupted")
    unrecorded = [s for s in stages if s["status"] is None]
    for stage in unrecorded:
        if doc is None or status == "running":
            stage["status"] = "running"
        else:
            stage["status"] = "errored" if crashed else "completed"
            if crashed:
                stage["error"] = str((doc or {}).get("error") or "the attempt stopped here")
    clock = _parse((doc or {}).get("started_utc"))
    if clock is None:
        return
    for stage in stages:
        if stage["status"] == "not_run" or stage["seconds"] is None:
            continue
        stage["started"] = _stamp(clock)
        clock += timedelta(seconds=stage["seconds"])
        stage["finished"] = _stamp(clock)
        stage["times"] = "worked out from the attempt start and each stage's duration"


def build_trace(
    runs_root: Path, run_id: str, attempt_id: str | None, file_url: FileUrl
) -> dict[str, Any]:
    """The trace of one attempt of a run (the newest when `attempt_id` is None).

    `file_url` turns a path inside the run folder into the URL that serves it."""
    try:
        run = run_view.get_run(runs_root, run_id)
        wanted = attempt_id or run["latest_attempt_id"]
        if wanted is None:
            raise NotFound(f"run {run_id!r} has no attempts yet", "attempt_not_found")
        view = run_view.get_attempt(runs_root, run_id, wanted)
    except run_view.NotFound as error:
        raise NotFound(str(error), "trace_not_found") from error
    doc = run_view.attempt_record(runs_root, run_id, wanted)
    job = (doc or {}).get("resolved_job")
    plans = job.get("stages") if isinstance(job, Mapping) else None
    planned = {str(p["id"]): p for p in plans or [] if isinstance(p, Mapping) and "id" in p}
    stages = [_stage(runs_root, v, run_id, wanted, doc, planned, file_url) for v in view["stages"]]
    seen = {s["id"] for s in stages}
    stages += [_not_run(p) for pid, p in planned.items() if pid not in seen]
    order = {
        pid: i for i, pid in enumerate(planned)
    }  # the pipeline's order, a retry after its first try
    stages.sort(key=lambda s: (order.get(s["id"], len(order)), s["retry"]))
    _settle(stages, doc)
    seconds = (doc or {}).get("wall_seconds")
    return {
        "run_id": run_id,
        "attempt_id": wanted,
        "attempts": [
            {"attempt_id": a["attempt_id"], "status": a["status"], "started": a["started"]}
            for a in run["attempts"]
        ],
        "status": view["status"],
        "error": view["error"],
        "problem": view["problem"],
        "started": view["started"],
        "finished": view["finished"],
        "seconds": seconds if isinstance(seconds, int | float) else None,
        "seed": view["seed"],
        "sources": (doc or {}).get("sources"),
        "tries": (doc or {}).get("tries") or [],
        "stages": stages,
    }
