"""The trace of a run: stages in order, what each did, and how it ended."""

import json
from pathlib import Path

import pytest
from trace_fixture import FIRST, NEGATIVE_PARTS, PARTS, PROMPT, RUN, SECOND, make_run

from authoring.trace import build_trace
from core.errors import NotFound


def url(candidate: str) -> str:
    return f"/files/{candidate}"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    make_run(tmp_path)
    return tmp_path


def test_a_finished_attempt_lists_every_stage_with_its_record(root: Path) -> None:
    trace = build_trace(root, RUN, FIRST, url)
    assert trace["status"] == "review" and trace["seconds"] == 180.0
    assert [(s["id"], s["status"]) for s in trace["stages"]] == [
        ("concept", "completed"),
        ("tidy", "completed"),
        ("shape", "completed"),
    ]
    concept = trace["stages"][0]
    assert concept["prompt"] == PROMPT and concept["negative"] == "blurry"
    assert concept["adapter"] == {
        "adapter_id": "stand-in",
        "adapter_version": "1",
        "weights_sha256": "ab12",
    }
    assert concept["inputs"] == [{"name": "seed_image", "from": "supplied", "sha256": "ef56"}]
    assert concept["params"] == {"width": 512} and concept["label"] == "Concept image"
    assert concept["seconds"] == 60.0
    image = next(f for f in concept["files"] if f["name"] == "image.png")
    assert image["kind"] == "image" and image["url"] == f"/files/attempts/{FIRST}/concept/image.png"
    assert image["candidate"] == f"attempts/{FIRST}/concept/image.png"
    assert [g["outcome"] for g in concept["gates"]] == ["pass"]


def test_the_prompt_comes_with_its_parts_when_they_add_up(root: Path) -> None:
    concept = build_trace(root, RUN, FIRST, url)["stages"][0]
    assert concept["prompt_parts"] == PARTS and concept["negative_parts"] == NEGATIVE_PARTS
    assert "".join(p["text"] for p in concept["prompt_parts"]) == concept["prompt"]


def test_an_attempt_without_parts_or_with_parts_that_do_not_add_up_has_none(root: Path) -> None:
    assert build_trace(root, RUN, SECOND, url)["stages"][0]["prompt_parts"] is None
    stage = root / RUN / "attempts" / FIRST / "concept" / "stage.json"
    record = json.loads(stage.read_text())
    record["prompt_parts"][0]["text"] = "a steel key"
    stage.write_text(json.dumps(record))
    concept = build_trace(root, RUN, FIRST, url)["stages"][0]
    assert concept["prompt_parts"] is None and concept["prompt"] == PROMPT


def test_times_follow_the_attempt_start_and_each_duration(root: Path) -> None:
    stages = build_trace(root, RUN, FIRST, url)["stages"]
    assert [(s["started"], s["finished"]) for s in stages] == [
        ("2026-11-05T10:00:00Z", "2026-11-05T10:01:00Z"),
        ("2026-11-05T10:01:00Z", "2026-11-05T10:01:00Z"),
        ("2026-11-05T10:01:00Z", "2026-11-05T10:03:00Z"),
    ]
    assert stages[0]["times"]


def test_a_reused_stage_says_where_it_came_from(root: Path) -> None:
    tidy = build_trace(root, RUN, FIRST, url)["stages"][1]
    assert tidy["reused"] is True and tidy["reused_from"] == "attempts/earlier/tidy"


def test_gate_measures_come_flat_with_their_limits(root: Path) -> None:
    gate = build_trace(root, RUN, FIRST, url)["stages"][2]["gates"][0]
    assert gate["outcome"] == "review" and gate["reasons"] == ["thin"]
    assert gate["measures"] == [
        {"name": "faces", "value": 900},
        {"name": "iou.front", "value": 0.55},
    ]
    assert gate["limits"] == [{"name": "iou", "value": 0.6}]


def test_the_stage_an_attempt_stopped_in_is_errored_with_the_error(root: Path) -> None:
    trace = build_trace(root, RUN, SECOND, url)
    assert trace["status"] == "failed" and trace["error"].endswith("out of memory")
    shape = trace["stages"][2]
    assert (shape["status"], shape["error"]) == ("errored", trace["error"])
    assert [s["status"] for s in trace["stages"][:2]] == ["completed", "completed"]


def test_planned_stages_that_never_started_are_not_run(root: Path) -> None:
    (root / RUN / "attempts" / SECOND / "shape").rmdir()
    stages = build_trace(root, RUN, SECOND, url)["stages"]
    assert [(s["id"], s["status"]) for s in stages][2] == ("shape", "not_run")


def test_the_newest_attempt_is_used_unless_one_is_named(root: Path) -> None:
    trace = build_trace(root, RUN, None, url)
    assert trace["attempt_id"] == SECOND
    assert [a["attempt_id"] for a in trace["attempts"]] == [SECOND, FIRST]


def test_unknown_runs_and_attempts_are_not_found(root: Path) -> None:
    for run, attempt in (("nope", None), (RUN, "nope"), ("../x", None)):
        with pytest.raises(NotFound):
            build_trace(root, run, attempt, url)
