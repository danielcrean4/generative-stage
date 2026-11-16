"""Figures for a project's runs, from fixtures."""

from pathlib import Path

from trace_fixture import FIRST, RUN, SECOND, make_run

from authoring.statistics import read_attempts, summarise


def rows(root: Path) -> list[dict]:  # type: ignore[type-arg]
    return read_attempts(root, [RUN, "missing-run"])


def test_each_attempt_is_one_row_and_missing_runs_are_skipped(tmp_path: Path) -> None:
    make_run(tmp_path)
    found = rows(tmp_path)
    assert sorted((r["attempt_id"], r["day"], r["outcome"]) for r in found) == [
        (FIRST, "2026-11-05", "completed"),
        (SECOND, "2026-11-06", "errored"),
    ]


def test_runs_are_counted_by_outcome_and_day(tmp_path: Path) -> None:
    make_run(tmp_path)
    figures = summarise(
        rows(tmp_path), candidates=4, choices=3, chosen_slots=1, entities=2, entities_with_choice=1
    )
    assert figures["runs"] == {
        "total": 2,
        "completed": 1,
        "errored": 1,
        "other": 0,
        "seconds": 270.0,
    }
    assert figures["by_day"] == [
        {"day": "2026-11-05", "completed": 1, "errored": 0, "other": 0},
        {"day": "2026-11-06", "completed": 0, "errored": 1, "other": 0},
    ]
    assert figures["assets"] == {
        "candidates": 4,
        "choices": 3,
        "chosen_slots": 1,
        "entities": 2,
        "entities_with_choice": 1,
    }


def test_time_per_stage_leaves_out_reused_stages(tmp_path: Path) -> None:
    make_run(tmp_path)
    by_stage = {
        s["stage"]: s
        for s in summarise(
            rows(tmp_path),
            candidates=0,
            choices=0,
            chosen_slots=0,
            entities=0,
            entities_with_choice=0,
        )["by_stage"]
    }
    assert by_stage["concept"] == {
        "stage": "concept",
        "ran": 2,
        "reused": 0,
        "errored": 0,
        "total_seconds": 105.0,
        "average_seconds": 52.5,
        "slowest_seconds": 60.0,
    }
    assert (by_stage["tidy"]["ran"], by_stage["tidy"]["reused"]) == (1, 1)
    assert by_stage["tidy"]["total_seconds"] == 10.0


def test_a_project_with_no_runs_has_zero_figures() -> None:
    figures = summarise(
        [], candidates=0, choices=0, chosen_slots=0, entities=0, entities_with_choice=0
    )
    assert figures["runs"]["total"] == 0 and figures["by_day"] == [] and figures["by_stage"] == []
