"""Which runs of a project read which shared sources (authoring/source_catalog.py), by scanning the runs attached to its
entities. Nothing is stored: each request reads the newest attempt's `sources` record of every attached run, so the answer
is always what the run folders say.

Thumbnails: the first picture the run offered as a candidate, else the picture of its concept stage, as a URL on the
entity's run-file route.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from authoring import run_view, source_catalog
from authoring.job_store import JobStore
from authoring.offered import offers
from core.errors import NotFound
from core.world import World

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

FileUrl = Callable[[str, str, str], str]  # (entity id, run id, candidate path) -> URL


def set_of(store: JobStore, run_id: str) -> str | None:
    """The data folder name of the pipeline a job run used, or None for a run that no job of this project made."""
    try:
        pipeline = store.job(run_id)["pipeline"]
    except NotFound:
        return None
    offer = offers().get(pipeline)
    return offer.data.name if offer else None


def _read_by_later_stages(record: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    """The part of an attempt's `sources` it actually read. A run that started at a later stage with saved files
    (`start_at`) never ran the earlier stages, so a source only they read (the style and motif of the concept stage) is left
    out; the record still holds every source it was resolved with."""
    start = record.get("start_at")
    stages = (record.get("resolved_job") or {}).get("stages")
    if start is None or not isinstance(stages, list):
        return sources
    ids = [s.get("id") for s in stages]
    if start not in ids:
        return sources
    reads = {name for s in stages[ids.index(start) :] for name in s.get("reads") or {}}
    keep = {
        "style": any(r.startswith("style.") for r in reads),
        "motif": "motif" in reads,
        "contract": "contract" in reads,
        "pipeline": any(r.startswith("capture") for r in reads),
    }
    return {name: value for name, value in sources.items() if keep.get(name, True)}


def latest_sources(
    runs_root: Path, run_id: str
) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    """(attempt id, attempt record, the `sources` it read) of the newest attempt of a run that recorded sources, else None."""
    try:
        attempt = run_view.get_run(runs_root, run_id)["latest_attempt_id"]
    except run_view.NotFound:
        return None
    record = run_view.attempt_record(runs_root, run_id, attempt) if attempt else None
    sources = (record or {}).get("sources")
    if not (attempt and record and isinstance(sources, dict)):
        return None
    return attempt, record, _read_by_later_stages(record, sources)


def _thumbnail(
    runs_root: Path,
    store: JobStore,
    entity_id: str,
    run_id: str,
    attempt: tuple[str, dict[str, Any]],
    file_url: FileUrl,
) -> str | None:
    root = (runs_root / run_id).resolve()
    for candidate in store.candidates(run_id):
        try:
            ref = Path(candidate["output_ref"]).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if ref.lower().endswith(IMAGE_SUFFIXES):
            return file_url(entity_id, run_id, ref)
    attempt_id, record = attempt
    for entry in (record.get("stages") or {}).values():
        if entry.get("tool") == "concept" and isinstance(entry.get("folder"), str):
            ref = f"attempts/{attempt_id}/{entry['folder']}/image.png"
            if (root / ref).is_file():
                return file_url(entity_id, run_id, ref)
    return None


def feeds(world: World, store: JobStore, runs_root: Path, entity_id: str) -> dict[str, Any]:
    """The shared sources the entity's newest run read (the newest attached run that has an attempt with sources)."""
    for run in world.runs(entity_id):
        found = latest_sources(runs_root, run["run_id"])
        if found:
            attempt, _, sources = found
            return {
                "run_id": run["run_id"],
                "attempt_id": attempt,
                "sources": source_catalog.refs_of(sources, set_of(store, run["run_id"])),
            }
    return {"run_id": None, "attempt_id": None, "sources": []}


def readers(
    world: World, store: JobStore, runs_root: Path, source_id: str, file_url: FileUrl
) -> list[dict[str, Any]]:
    """Every attached run whose newest attempt read the source, newest first: the entity, the run, its time and status,
    whether the source has changed since, and a thumbnail."""
    rows: list[dict[str, Any]] = []
    for entity in world.list_entities(include_archived=True):
        for run in world.runs(entity["id"]):
            found = latest_sources(runs_root, run["run_id"])
            if not found:
                continue
            attempt, record, sources = found
            ref = next(
                (
                    r
                    for r in source_catalog.refs_of(sources, set_of(store, run["run_id"]))
                    if r["id"] == source_id
                ),
                None,
            )
            if ref is None:
                continue
            rows.append(
                {
                    "entity": {
                        "id": entity["id"],
                        "kind": entity["kind"],
                        "title": entity["title"],
                    },
                    "run_id": run["run_id"],
                    "attempt_id": attempt,
                    "started": record.get("started_utc"),
                    "status": record.get("status"),
                    "changed": ref["changed"],
                    "thumbnail": _thumbnail(
                        runs_root, store, entity["id"], run["run_id"], (attempt, record), file_url
                    ),
                }
            )
    rows.sort(key=lambda r: r["started"] or "", reverse=True)
    return rows


def add_links(stages: list[dict[str, Any]], set_name: str | None, entity: dict[str, Any]) -> None:
    """Give the source of every prompt part a `link` to its page: a shared source file, or, for the subject text, the
    entity the run was made for. Parts of glue and of the pipeline's own words have none."""
    for stage in stages:
        for name in ("prompt_parts", "negative_parts"):
            for part in stage.get(name) or []:
                source = part["source"]
                if source.get("kind") == "subject":
                    source["link"] = {"type": "entity", "id": entity["id"], "kind": entity["kind"]}
                else:
                    source["link"] = source_catalog.link_for(source, set_name)
