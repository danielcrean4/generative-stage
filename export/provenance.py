"""Where a chosen asset's file is, and what made it, read from the run folder on disk.

A choice names a run and a candidate: a path relative to the run folder, such as
`attempts/<attempt>/mesh/mesh.glb` or `icon.png`. The file is found through the run view's
rules (strict path segments, symlinks resolved inside the run). What made it comes from the
attempt's `attempt.json` when the candidate names an attempt: the stage's prompt and seed and the
model or adapter identity of each stage, as recorded. Only ids, versions and hashes are copied;
paths on the machine that ran the job never leave it. A field the run did not record is left out.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from authoring.run_view import NotFound as RunNotFound
from authoring.run_view import attempt_record, run_file
from core.errors import NotFound

ATTEMPTS = "attempts"
IDENTITY_KEYS = (
    "adapter_id",
    "adapter_version",
    "model",
    "model_id",
    "reported_model",
    "weights_sha256",
    "runtime_sha256",
    "adapter_source_sha256",
)


@dataclass(frozen=True)
class Provenance:
    file: Path  # the candidate file on disk
    record: dict[str, Any]  # the manifest's `provenance` object


def _scalar(value: object) -> bool:
    if isinstance(value, bool | int | float):
        return True
    return isinstance(value, str) and not value.startswith(("/", "~")) and ":\\" not in value


def identity(raw: object) -> dict[str, Any]:
    """The ids, versions and hashes of one stage's model record (never its paths)."""
    if isinstance(raw, str):
        return {"model": raw} if _scalar(raw) else {}
    if not isinstance(raw, Mapping):
        return {}
    found = {key: raw[key] for key in IDENTITY_KEYS if key in raw and _scalar(raw[key])}
    if "adapter_id" not in found and _scalar(
        raw.get("adapter")
    ):  # the pipeline runner's name for it
        found["adapter_id"] = raw["adapter"]
    weights = raw.get("weights")
    if isinstance(weights, Mapping) and _scalar(weights.get("sha256")):
        found.setdefault("weights_sha256", weights["sha256"])
    return found


def _stage_record(doc: Mapping[str, Any], stage: str) -> Mapping[str, Any]:
    stages = doc.get("stages")
    if isinstance(stages, Mapping) and isinstance(stages.get(stage), Mapping):
        return stages[stage]  # type: ignore[no-any-return]
    if isinstance(stages, list):
        for entry in stages:
            if isinstance(entry, Mapping) and entry.get("stage") == stage:
                return entry
    return {}


def _prompt(doc: Mapping[str, Any], stage_doc: Mapping[str, Any]) -> str | None:
    if isinstance(stage_doc.get("prompt"), str):
        return str(stage_doc["prompt"])
    recipe = doc.get("recipe")
    concept = recipe.get("concept") if isinstance(recipe, Mapping) else None
    if isinstance(concept, Mapping) and isinstance(concept.get("prompt"), str):
        return str(concept["prompt"])
    stages = doc.get(
        "stages"
    )  # a later stage (a mesh) carries no prompt; the stage that drew it does
    entries = (
        stages.values()
        if isinstance(stages, Mapping)
        else stages
        if isinstance(stages, list)
        else []
    )
    for entry in entries:
        if isinstance(entry, Mapping) and isinstance(entry.get("prompt"), str):
            return str(entry["prompt"])
    return None


def _seed(doc: Mapping[str, Any], stage_doc: Mapping[str, Any]) -> int | None:
    recipe = doc.get("recipe")
    for value in (
        stage_doc.get("seed_used"),
        stage_doc.get("seed"),
        doc.get("seed"),
        recipe.get("seed") if isinstance(recipe, Mapping) else None,
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def candidate_file(runs_root: Path, run_id: str, candidate: str) -> Path:
    """The file of one candidate of a run, or NotFound naming it. Safe paths only: the file must
    stay inside the run folder (see the run view's rules)."""
    try:
        return run_file(runs_root, run_id, candidate)
    except RunNotFound as error:
        raise NotFound(
            f"the candidate {candidate!r} of run {run_id!r} is not a file in that run",
            "candidate_not_found",
        ) from error


def read_provenance(runs_root: Path, choice: Mapping[str, Any]) -> Provenance:
    """The file and provenance of one choice (core's `chosen` entry), or NotFound naming it."""
    run_id, candidate = choice["run_id"], choice["candidate"]
    file = candidate_file(runs_root, run_id, candidate)
    record: dict[str, Any] = {
        "run_id": run_id,
        "candidate": candidate,
        "entity_revision": choice["entity_revision"],
        "chosen_at": choice["chosen_at"],
    }
    if choice.get("note"):
        record["note"] = choice["note"]
    parts = candidate.split("/")
    if len(parts) >= 3 and parts[0] == ATTEMPTS:
        attempt, stage = parts[1], parts[2]
        record.update(attempt=attempt, stage=stage)
        doc = attempt_record(runs_root, run_id, attempt) or {}
        stage_doc = _stage_record(doc, stage)
        prompt, seed = _prompt(doc, stage_doc), _seed(doc, stage_doc)
        if prompt is not None:
            record["prompt"] = prompt
        if seed is not None:
            record["seed"] = seed
        models = doc.get("models")
        if isinstance(models, Mapping):
            found = {str(k): identity(v) for k, v in sorted(models.items())}
            if any(found.values()):
                record["models"] = {k: v for k, v in found.items() if v}
    elif len(parts) > 1:
        record["stage"] = parts[0]
    return Provenance(file, record)
