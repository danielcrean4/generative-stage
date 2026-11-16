"""Numbers about a project's runs, worked out from the files on disk.

`read_attempts` reads each attempt of the given runs; `summarise` turns those rows, plus the
counts the project already holds (candidates, choices, entities), into the figures the statistics
page draws. Both are plain functions; `summarise` touches no files.

A "run" in these figures is one attempt: one execution of a pipeline, which is what takes time
and ends completed or errored. Completed means the attempt finished (its gates passed, or one
asked for a review); errored means it failed or was interrupted; anything else is still going or
left no record.
"""

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from authoring import run_view

COMPLETED = ("generated", "review", "succeeded")
ERRORED = ("failed", "interrupted")


def _outcome(status: object) -> str:
    if status in COMPLETED:
        return "completed"
    if status in ERRORED:
        return "errored"
    return "other"


def _seconds(doc: dict[str, Any]) -> float | None:
    wall = doc.get("wall_seconds")
    if isinstance(wall, int | float):
        return float(wall)
    try:
        started = datetime.fromisoformat(str(doc.get("started_utc")))
        finished = datetime.fromisoformat(str(doc.get("finished_utc")))
    except ValueError:
        return None
    return (finished - started).total_seconds()


def _stage_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    stages = doc.get("stages")
    rows = []
    for folder, entry in stages.items() if isinstance(stages, dict) else []:
        if not isinstance(entry, dict):
            continue
        timing = entry.get("timing")
        seconds = timing.get("seconds") if isinstance(timing, dict) else None
        rows.append(
            {
                "stage": str(entry.get("stage") or folder.partition(".try")[0]),
                "seconds": float(seconds) if isinstance(seconds, int | float) else 0.0,
                "reused": bool(entry.get("reused")),
                "errored": bool(entry.get("failed")),
            }
        )
    return rows


def read_attempts(runs_root: Path, run_ids: Iterable[str]) -> list[dict[str, Any]]:
    """One row per attempt of the named runs: run, attempt, day (UTC), outcome, seconds, stages.
    A run that is not in the runs root is skipped; an attempt with no readable record counts as
    `other`."""
    rows: list[dict[str, Any]] = []
    for run_id in sorted(set(run_ids)):
        try:
            attempts = run_view.get_run(runs_root, run_id)["attempts"]
        except run_view.NotFound:
            continue
        for attempt in attempts:
            doc = run_view.attempt_record(runs_root, run_id, attempt["attempt_id"]) or {}
            started = str(doc.get("started_utc") or attempt["started"] or "")
            rows.append(
                {
                    "run_id": run_id,
                    "attempt_id": attempt["attempt_id"],
                    "day": started[:10] or None,
                    "outcome": _outcome(doc.get("status")),
                    "seconds": _seconds(doc),
                    "stages": _stage_rows(doc),
                }
            )
    return rows


def _by_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    days: dict[str, dict[str, int]] = {}
    for row in rows:
        if row["day"] is None:
            continue
        day = days.setdefault(row["day"], {"completed": 0, "errored": 0, "other": 0})
        day[row["outcome"]] += 1
    return [{"day": d, **days[d]} for d in sorted(days)]


def _by_stage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per stage id: how many times it ran (reused stages are counted apart and add no time),
    the total and average seconds, the slowest run and how many times it errored."""
    stages: dict[str, dict[str, Any]] = {}
    for row in rows:
        for s in row["stages"]:
            found = stages.setdefault(
                s["stage"],
                {
                    "stage": s["stage"],
                    "ran": 0,
                    "reused": 0,
                    "errored": 0,
                    "total": 0.0,
                    "max": 0.0,
                },
            )
            if s["reused"]:
                found["reused"] += 1
                continue
            found["ran"] += 1
            found["errored"] += s["errored"]
            found["total"] += s["seconds"]
            found["max"] = max(found["max"], s["seconds"])
    result = []
    for found in stages.values():
        ran = found["ran"]
        result.append(
            {
                "stage": found["stage"],
                "ran": ran,
                "reused": found["reused"],
                "errored": found["errored"],
                "total_seconds": round(found["total"], 2),
                "average_seconds": round(found["total"] / ran, 2) if ran else 0.0,
                "slowest_seconds": round(found["max"], 2),
            }
        )
    return sorted(result, key=lambda r: (-r["total_seconds"], r["stage"]))


def summarise(
    rows: list[dict[str, Any]],
    *,
    candidates: int,
    choices: int,
    chosen_slots: int,
    entities: int,
    entities_with_choice: int,
) -> dict[str, Any]:
    """The figures for one project. `choices` is every choice ever made, `chosen_slots` the
    choices in force now (one per entity and slot)."""
    counts = {"completed": 0, "errored": 0, "other": 0}
    seconds = 0.0
    for row in rows:
        counts[row["outcome"]] += 1
        seconds += row["seconds"] or 0.0
    return {
        "runs": {"total": len(rows), **counts, "seconds": round(seconds, 2)},
        "by_day": _by_day(rows),
        "by_stage": _by_stage(rows),
        "assets": {
            "candidates": candidates,
            "choices": choices,
            "chosen_slots": chosen_slots,
            "entities": entities,
            "entities_with_choice": entities_with_choice,
        },
    }
