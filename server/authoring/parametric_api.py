"""The parametric routes under /api/v1/projects/<slug>/parametric (docs/parametric.md).

    GET  parametric/<kind>                       what the kind offers: its parameters, kit and gates, the adapters
    POST parametric/<kind>/preview               one row rendered and measured: the slider page's live preview
    POST parametric/<kind>/candidates            keep a previewed row as a run of its own (a candidate to choose)
    POST parametric/<kind>/batches               the rules stage, then render and measure for every row
    GET  parametric/batches/<id>                 a batch and its triage
    PUT  parametric/batches/<id>/triage          {tile id: {"verdict": keep|fix|improve|remove, "note": text}}
    GET  parametric/batches/<id>/files/<path>    a still of a batch
    GET  parametric/previews/<id>/<file>         a still of a preview

A batch is a run folder in the runs root, so a tile's still is a candidate a record can choose like any other. This
module reads requests and shapes replies; the stages are pipeline/param_run.py, the commands are the machine config's.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from authoring.machine_config import MachineConfig
from authoring.offered import PIPELINE_DIR
from authoring.replies import FileBody
from authoring.run_view import media_type
from core.errors import Invalid, NotFound
from core.ids import NAME_ID
from core.world import World

sys.path.insert(0, str(PIPELINE_DIR))
import adapter_config  # noqa: E402
import adapter_run  # noqa: E402
import kit_table  # noqa: E402
import param_gates  # noqa: E402
import param_run  # noqa: E402

type Reply = tuple[int, Any]
DATA_FOLDER = "parametric"
VERDICTS = ("keep", "fix", "improve", "remove")
ADAPTER_KINDS = ("rules", "render", "measure")
FILE_PART = "[A-Za-z0-9][A-Za-z0-9._-]*"
MAX_NOTE = 2000
MAX_FILE_BYTES = 32 * 1024 * 1024
_TRIAGE_LOCKS: dict[Path, threading.Lock] = {}
_TRIAGE_LOCKS_GUARD = threading.Lock()


def _fail(message: str, code: str = "parametric_failed") -> Invalid:
    return Invalid(message, code)


def _kind(world: World, kind_id: str) -> dict[str, Any]:
    if not NAME_ID.fullmatch(kind_id):
        raise NotFound(f"no kind {kind_id!r}", "kind_not_found")
    kind: dict[str, Any] = world.kind(kind_id)
    if kind["parameters"] is None:
        raise _fail(
            f"the {kind_id!r} kind has no parameters (a number with a minimum and a maximum)",
            "not_parametric",
        )
    return kind


def _data(world: World, kind_id: str, name: str) -> Path:
    return world.project.root / DATA_FOLDER / f"{kind_id}.{name}.json"


def _load(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise _fail(
            f"the project has no {what} at {DATA_FOLDER}/{path.name}", "parametric_data_missing"
        ) from None
    except ValueError as error:
        raise _fail(
            f"{DATA_FOLDER}/{path.name}: not valid JSON ({error})", "parametric_data_invalid"
        ) from error


def _kit(world: World, kind: dict[str, Any]) -> Any:
    kit = _load(_data(world, kind["id"], "kit"), "kit table")
    problems = kit_table.validate(kit, kind["parameters"], kind["schema"].get("properties", {}))
    if problems:
        raise _fail(
            f"{DATA_FOLDER}/{kind['id']}.kit.json: " + "; ".join(problems),
            "parametric_data_invalid",
        )
    return kit


def _gates(world: World, kind_id: str) -> list[dict[str, Any]]:
    path = _data(world, kind_id, "gates")
    if not path.is_file():
        return []
    try:
        gates: list[dict[str, Any]] = param_gates.validate(_load(path, "gates"))
    except param_gates.GateError as error:
        raise _fail(
            f"{DATA_FOLDER}/{path.name}: " + "; ".join(error.problems), "parametric_data_invalid"
        ) from error
    return gates


def _adapters(body: dict[str, Any]) -> tuple[Any, dict[str, str]]:
    """The machine's adapters and the ids this request chose (by id and kind only; the command is never in a request)."""
    given = body.get("adapters", {})
    if not isinstance(given, dict) or set(given) - set(ADAPTER_KINDS):
        raise Invalid(
            f"/adapters: expected an object with only {', '.join(ADAPTER_KINDS)}", field="/adapters"
        )
    try:
        found = adapter_config.from_machine()
        for kind, chosen in given.items():
            found.pick(chosen, kind)
    except adapter_config.AdapterError as error:
        raise Invalid(str(error), "bad_adapter", "/adapters") from error
    return found, dict(given)


def _check_row(world: World, kind: dict[str, Any], row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise Invalid("/row: expected an object", field="/row")
    checked: dict[str, Any] = world.catalogue.kind(kind["id"]).check(row, "/row")
    return checked


def _schema_file(folder: Path, kind: dict[str, Any]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "schema.json"
    path.write_text(json.dumps(kind["schema"]))
    return path


def _stage(call: Any) -> Any:
    try:
        return call()
    except (
        adapter_run.Refused,
        adapter_config.AdapterError,
        RuntimeError,
        kit_table.KitError,
        ValueError,
    ) as error:
        raise _fail(str(error)) from error


def _int(body: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = body.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise Invalid(f"/{key}: expected a whole number from {low} to {high}", field=f"/{key}")
    return value


def info(world: World, kind_id: str) -> dict[str, Any]:
    kind = _kind(world, kind_id)
    kit_file = _data(world, kind_id, "kit")
    gates = _gates(world, kind_id)
    kit = _kit(world, kind) if kit_file.is_file() else None
    properties = kind["schema"].get("properties", {})
    subject = {name: properties[name].get("enum") for name in (kit or {}).get("subject_fields", [])}
    try:
        found = adapter_config.from_machine()
    except adapter_config.AdapterError as error:
        raise Invalid(str(error), "bad_adapter") from error
    chosen = {k: found.defaults.get(k) for k in ADAPTER_KINDS}
    return {
        "kind": kind_id,
        "parameters": kind["parameters"],
        "has_kit": kit is not None,
        "subject_fields": subject,
        "gates": [
            {k: g[k] for k in ("id", "about", "measure", "min", "max", "verdict") if k in g}
            for g in gates
        ],
        "adapters": {
            k: [e.id for e in found.entries.values() if e.kind == k] for k in ADAPTER_KINDS
        },
        "defaults": chosen,
    }


def _preview_id(
    kind: dict[str, Any], row: dict[str, Any], chosen: dict[str, str], gates: Any, found: Any
) -> str:
    key = json.dumps(
        [
            kind["id"],
            row,
            chosen,
            {k: found.pick(chosen.get(k), k).id for k in ("render", "measure")},
            [g.get("id") for g in gates],
            kind["schema"],
        ],
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def preview(
    config: MachineConfig, world: World, kind_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    kind = _kind(world, kind_id)
    row = _check_row(world, kind, body.get("row"))
    found, chosen = _adapters(body)
    gates = _gates(world, kind_id)
    ident = _preview_id(kind, row, chosen, gates, found)
    folder = config.runs_root.parent / "parametric-previews" / ident
    record = folder / "preview.json"
    if not record.is_file():
        schema = _schema_file(folder, kind)
        result = _stage(lambda: param_run.render_one(found, chosen, schema, row, 0, folder, gates))
        record.write_text(json.dumps(result))
    view: dict[str, Any] = json.loads(record.read_text())
    return {"id": ident, "row": row, **view}


def keep_candidate(
    config: MachineConfig, world: World, kind_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Make the previewed row a run of its own in the runs root, so a record can attach and choose its still."""
    shown = preview(config, world, kind_id, body)
    source = config.runs_root.parent / "parametric-previews" / shown["id"]
    run_id = f"param-{uuid.uuid4().hex[:12]}"
    target = config.runs_root / run_id
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("*.log"))
    return {
        "run_id": run_id,
        "candidate": shown["still"],
        "row": shown["row"],
        "numbers": shown["numbers"],
        "verdict": shown["verdict"],
    }


def make_batch(
    config: MachineConfig, world: World, kind_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    kind = _kind(world, kind_id)
    kit = _kit(world, kind)
    subject = body.get("subject", {})
    cross = body.get("cross", {})
    if not isinstance(subject, dict) or not isinstance(cross, dict):
        raise Invalid("/subject and /cross: expected objects", field="/subject")
    if not all(isinstance(v, list) for v in cross.values()):
        raise Invalid("/cross: expected {field: [values]}", field="/cross")
    for name in (*subject, *cross):
        if name not in kit.get("subject_fields", []):
            raise Invalid(
                f"/subject: {name!r} is not one of the kit's subject fields", field="/subject"
            )
    seed = _int(body, "seed", 1, 0, 2**32 - 1)
    count = _int(body, "count", 5, 1, 200)
    found, chosen = _adapters(body)
    run_id = f"param-{uuid.uuid4().hex[:12]}"
    folder = config.runs_root / run_id
    schema = _schema_file(folder / "inputs", kind)
    batch = _stage(
        lambda: param_run.run_batch(
            found,
            chosen,
            schema,
            _data(world, kind_id, "kit"),
            _gates(world, kind_id),
            {"subject": subject, "cross": cross},
            seed,
            count,
            folder,
        )
    )
    for tile in batch[
        "tiles"
    ]:  # the rules stage checks its rows; the schema checks them again here
        world.catalogue.kind(kind_id).check(tile["row"], f"/tiles/{tile['id']}")
    batch["project"] = world.project.slug  # every batch route checks it (see _batch_folder)
    (folder / "parametric.json").write_text(json.dumps(batch, indent=1) + "\n")
    return {"id": run_id, "kind": kind_id, **batch, "triage": {}}


def _batch_folder(config: MachineConfig, batch_id: str, project: str) -> Path:
    """The batch's run folder; a batch of another project answers as if it did not exist.

    Batches made before the project was recorded have no "project" key: they are treated as unscoped and stay
    readable from every project, so older batches keep working.
    """
    folder = config.runs_root / batch_id
    meta = folder / "parametric.json"
    if not batch_id.startswith("param-") or not meta.is_file():
        raise NotFound(f"no parametric batch {batch_id!r}", "batch_not_found")
    owner = _json_or(meta, {}).get("project")
    if owner is not None and owner != project:
        raise NotFound(f"no parametric batch {batch_id!r}", "batch_not_found")
    return folder


def _json_or(path: Path, fallback: Any) -> Any:
    """The JSON in PATH, or FALLBACK when it is missing or unreadable (e.g. cut short by a crash)."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def read_batch(config: MachineConfig, batch_id: str, project: str) -> dict[str, Any]:
    folder = _batch_folder(config, batch_id, project)
    batch: dict[str, Any] = json.loads((folder / "parametric.json").read_text())
    triage = _json_or(folder / "triage.json", {})
    return {"id": batch_id, **batch, "triage": triage if isinstance(triage, dict) else {}}


def _triage_lock(folder: Path) -> threading.Lock:
    with _TRIAGE_LOCKS_GUARD:
        return _TRIAGE_LOCKS.setdefault(folder, threading.Lock())


def triage(
    config: MachineConfig, batch_id: str, body: dict[str, Any], project: str
) -> dict[str, Any]:
    """Merge the given marks into the batch's triage; a tile with {"verdict": null} loses its mark."""
    folder = _batch_folder(config, batch_id, project)
    with _triage_lock(folder):  # read, merge and write as one step, so parallel saves all land
        current = read_batch(config, batch_id, project)
        tiles = {t["id"] for t in current["tiles"]}
        marks = dict(current["triage"])
        for tile, mark in body.items():
            if tile not in tiles or not isinstance(mark, dict) or set(mark) - {"verdict", "note"}:
                raise Invalid(
                    f"/{tile}: expected a tile of this batch with {{verdict, note}}",
                    field=f"/{tile}",
                )
            verdict, note = mark.get("verdict"), mark.get("note", "")
            if verdict is not None and verdict not in VERDICTS:
                raise Invalid(
                    f"/{tile}/verdict: expected one of {', '.join(VERDICTS)}",
                    field=f"/{tile}/verdict",
                )
            if not isinstance(note, str) or len(note) > MAX_NOTE:
                raise Invalid(
                    f"/{tile}/note: expected text up to {MAX_NOTE} characters",
                    field=f"/{tile}/note",
                )
            if verdict is None:
                marks.pop(tile, None)
            else:
                marks[tile] = {"verdict": verdict, "note": note}
        scratch = folder / f"triage.json.{uuid.uuid4().hex[:8]}.tmp"
        scratch.write_text(json.dumps(marks, indent=1) + "\n")
        os.replace(scratch, folder / "triage.json")
    return {**current, "triage": marks}


def _still(file: Path, root: Path) -> FileBody:
    """FILE as a reply; it must be a regular file whose real path (links followed) is inside ROOT, and not huge."""
    kind = media_type(file.name)
    real = file.resolve()
    if kind is None or not real.is_relative_to(root.resolve()) or not real.is_file():
        raise NotFound(f"no file {file.name!r}", "file_not_found")
    if real.stat().st_size > MAX_FILE_BYTES:
        raise NotFound(f"no file {file.name!r}", "file_not_found")
    return FileBody(real.read_bytes(), kind, file.name, inline=kind.startswith("image/"))


def route(
    config: MachineConfig, world: World, method: str, rest: list[str], body: dict[str, Any]
) -> Reply | None:
    """The reply for /parametric/<rest>, or None when the route or method is not one of these."""
    if len(rest) >= 2 and rest[0] == "batches":
        if len(rest) == 2 and method == "GET":
            return 200, read_batch(config, rest[1], world.project.slug)
        if len(rest) == 3 and rest[2] == "triage" and method == "PUT":
            return 200, triage(config, rest[1], body, world.project.slug)
        if len(rest) >= 4 and rest[2] == "files" and method == "GET":
            parts = rest[3:]
            if all(re.fullmatch(FILE_PART, p) for p in parts):
                folder = _batch_folder(config, rest[1], world.project.slug)
                return 200, _still(folder.joinpath(*parts), folder)
        return None
    if len(rest) == 3 and rest[0] == "previews" and method == "GET":
        if re.fullmatch(r"[0-9a-f]{20}", rest[1]) and re.fullmatch(FILE_PART, rest[2]):
            previews = config.runs_root.parent / "parametric-previews" / rest[1]
            return 200, _still(previews / rest[2], previews)
        return None
    if len(rest) == 1 and method == "GET":
        return 200, info(world, rest[0])
    if len(rest) == 2 and method == "POST":
        if rest[1] == "preview":
            return 200, preview(config, world, rest[0], body)
        if rest[1] == "candidates":
            return 201, keep_candidate(config, world, rest[0], body)
        if rest[1] == "batches":
            return 201, make_batch(config, world, rest[0], body)
    return None
