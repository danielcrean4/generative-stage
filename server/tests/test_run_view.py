"""Run view reading, directly over a fake runs root (no HTTP)."""

import json
from pathlib import Path

import pytest
from run_fixture import (
    BIG_LOG_BYTES,
    NEW_ATTEMPT,
    OLD_ATTEMPT,
    RUN_ICON,
    RUN_JOB,
    RUN_LINK,
    make_runs_root,
)
from studio_test_support import default_config

from authoring import run_view
from authoring.run_view import NotFound


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_runs_root(tmp_path)


def test_list_runs_summarises_latest_attempt(root: Path) -> None:
    listing = run_view.list_runs(root, 50)
    rows = {r["run_id"]: r for r in listing["runs"]}
    assert set(rows) == {RUN_JOB, RUN_ICON}  # the symlinked run and the stray file are not runs
    job = rows[RUN_JOB]
    assert job["latest_attempt_id"] == NEW_ATTEMPT
    assert (job["status"], job["started"], job["finished"]) == (
        "generated",
        "2026-11-02T00:00:00Z",
        "2026-11-02T00:05:00Z",
    )
    assert job["stages"] == ["concept", "matte", "mesh"]
    icon = rows[RUN_ICON]
    assert icon["latest_attempt_id"] is None and icon["status"] is None and icon["stages"] == []


def test_list_runs_limit_and_newest_first(root: Path) -> None:
    import os

    os.utime(root / RUN_ICON, (2_000_000_000, 2_000_000_000))
    listing = run_view.list_runs(root, 1)
    assert [r["run_id"] for r in listing["runs"]] == [RUN_ICON]
    assert listing["total"] == 2


def test_latest_falls_back_to_newest_folder_when_pointer_is_stale(root: Path) -> None:
    (root / RUN_JOB / "latest.json").write_text('{"attempt": "/gone/20200101T000000Z-zzzz"}')
    assert run_view.get_run(root, RUN_JOB)["latest_attempt_id"] == NEW_ATTEMPT


def test_get_run_lists_attempts_newest_first_with_errors(root: Path) -> None:
    run = run_view.get_run(root, RUN_JOB)
    assert [a["attempt_id"] for a in run["attempts"]] == [NEW_ATTEMPT, OLD_ATTEMPT]
    old = run["attempts"][1]
    assert old["status"] == "failed" and "matte failed" in old["error"] and old["seed"] == 7
    assert old["stages"] == ["concept", "matte"]  # matte is a folder the attempt never recorded
    assert [f["name"] for f in run["root_files"]] == ["bust_raw.png"]  # not leak.png, latest.json


def test_root_files_of_icon_run(root: Path) -> None:
    run = run_view.get_run(root, RUN_ICON)
    names = {f["name"]: f for f in run["root_files"]}
    assert set(names) == {"icon.png", "icon.source.json"}
    assert names["icon.png"]["media_type"] == "image/png"
    assert names["icon.png"]["url"] == f"/api/ro/runs/{RUN_ICON}/files/_root/icon.png"
    assert run["attempts"] == []


def test_attempt_view_follows_recorded_order_and_details(root: Path) -> None:
    view = run_view.get_attempt(root, RUN_JOB, NEW_ATTEMPT)
    assert [s["stage"] for s in view["stages"]] == ["concept", "matte", "mesh"]
    concept, matte, mesh = view["stages"]
    assert concept["cache_key"] == "kc" and concept["reused"] is True and concept["seed"] == 8
    assert concept["recipe"]["settings"]["prompt"] == "the resolved prompt"
    assert "versions" not in concept["recipe"]
    assert concept["recipe"]["model"] == {"path": "/m", "sha256": "ab", "file_count": 2}
    assert concept["gates"][0]["file"] == "image-validation.json"
    assert concept["gates"][0]["passed"] is None
    assert matte["gates"][0]["passed"] is True and matte["gates"][0]["measures"] == {
        "subject_share": 0.3
    }
    assert mesh["seed_used"] == 9 and len(mesh["tries"]) == 2
    gates = {g["file"]: g for g in mesh["gates"]}
    assert gates["mesh-validation.json"]["thresholds"] == {"min": 1}
    assert gates["try-0/mesh-validation.json"]["passed"] is False
    assert gates["try-0/mesh-validation.json"]["reasons"] == ["flat"]
    files = {f["name"]: f for f in mesh["files"]}
    assert "try-0/mesh.glb" in files and files["mesh.glb"]["media_type"] == "model/gltf-binary"
    assert files["mesh.glb"]["url"] == (
        f"/api/ro/runs/{RUN_JOB}/attempts/{NEW_ATTEMPT}/files/mesh/mesh.glb"
    )
    concept_files = {f["name"] for f in concept["files"]}
    assert concept_files == {
        "image.png",
        "image-validation.json",
        "stage.json",
        "step.log",
        "big.log",
    }


def test_failed_attempt_shows_unrecorded_stage_folder(root: Path) -> None:
    view = run_view.get_attempt(root, RUN_JOB, OLD_ATTEMPT)
    assert view["status"] == "failed" and "matte failed" in view["error"]
    concept, matte = view["stages"]
    assert concept["recorded"] is True and matte["recorded"] is False
    assert matte["gates"][0]["passed"] is False and matte["gates"][0]["reasons"] == ["too big"]


def test_attempt_without_attempt_json_reports_a_problem(root: Path) -> None:
    (root / RUN_JOB / "attempts" / OLD_ATTEMPT / "attempt.json").unlink()
    view = run_view.get_attempt(root, RUN_JOB, OLD_ATTEMPT)
    assert view["status"] is None and "attempt.json is missing" in view["problem"]
    assert [s["stage"] for s in view["stages"]] == ["concept", "matte"]


def test_corrupt_stage_json_is_loud(root: Path) -> None:
    (root / RUN_JOB / "attempts" / NEW_ATTEMPT / "mesh" / "stage.json").write_text("{nope")
    with pytest.raises(run_view.BadData, match="stage.json"):
        run_view.get_attempt(root, RUN_JOB, NEW_ATTEMPT)


def test_find_file_serves_allowed_types_only(root: Path) -> None:
    served = run_view.find_file(root, RUN_JOB, NEW_ATTEMPT, "mesh", "try-1/mesh.glb")
    assert served.media_type == "model/gltf-binary" and not served.truncated
    with pytest.raises(NotFound):
        run_view.find_file(root, RUN_JOB, NEW_ATTEMPT, "concept", "tool.exe")
    with pytest.raises(NotFound):
        run_view.find_file(root, RUN_JOB, NEW_ATTEMPT, "concept", "missing.png")


def test_big_log_is_truncated_small_log_is_not(root: Path) -> None:
    big = run_view.find_file(root, RUN_JOB, NEW_ATTEMPT, "concept", "big.log")
    assert big.truncated and big.size == BIG_LOG_BYTES
    small = run_view.find_file(root, RUN_JOB, NEW_ATTEMPT, "concept", "step.log")
    assert not small.truncated


def test_root_file_through_attempt_alias(root: Path) -> None:
    direct = run_view.find_root_file(root, RUN_JOB, "bust_raw.png")
    alias = run_view.find_file(root, RUN_JOB, NEW_ATTEMPT, "_root", "bust_raw.png")
    assert direct.path == alias.path and alias.media_type == "image/png"


@pytest.mark.parametrize(
    "run_id, attempt_id, stage, path",
    [
        (RUN_JOB, NEW_ATTEMPT, "concept", "../../attempt.json"),
        (RUN_JOB, NEW_ATTEMPT, "concept", "%2e%2e/attempt.json"),
        (RUN_JOB, NEW_ATTEMPT, "concept", "/etc/passwd"),
        (RUN_JOB, NEW_ATTEMPT, "concept", "evil.png"),  # symlink out of the root
        (RUN_JOB, NEW_ATTEMPT, "..", "attempt.json"),
        (RUN_JOB, "..", "concept", "image.png"),
        ("..", NEW_ATTEMPT, "concept", "image.png"),
        (RUN_LINK, "x", "concept", "secret.png"),  # symlinked run folder
        (RUN_JOB, NEW_ATTEMPT, "_root", "leak.png"),  # symlinked root file
        (RUN_JOB, NEW_ATTEMPT, "_root", "latest.json"),
        (RUN_JOB, NEW_ATTEMPT, "concept", ".hidden.png"),
        (RUN_JOB, NEW_ATTEMPT, "concept", "a/b/c/d/e.png"),
    ],
)
def test_escapes_are_refused(
    root: Path, run_id: str, attempt_id: str, stage: str, path: str
) -> None:
    with pytest.raises(NotFound):
        run_view.find_file(root, run_id, attempt_id, stage, path)


def test_symlinked_run_is_not_readable(root: Path) -> None:
    with pytest.raises(NotFound):
        run_view.get_run(root, RUN_LINK)
    with pytest.raises(NotFound):
        run_view.get_attempt(root, RUN_LINK, "x")


def test_symlinked_attempts_folder_is_not_followed(root: Path, tmp_path: Path) -> None:
    run = root / RUN_ICON
    (run / "attempts").symlink_to(tmp_path / "outside" / "attempts", target_is_directory=True)
    with pytest.raises(NotFound):
        run_view.get_attempt(root, RUN_ICON, "x")


def test_smoke_newest_real_run() -> None:
    real = default_config().runs_root
    if not real.is_dir() or not any(e.is_dir() for e in real.iterdir()):
        pytest.skip(f"no real runs root at {real}")
    runs = run_view.list_runs(real, 1)["runs"]
    assert runs
    attempt = runs[0]["latest_attempt_id"]
    if attempt is None:
        pytest.skip("newest real run has no attempt")
    view = run_view.get_attempt(real, runs[0]["run_id"], attempt)
    assert view["stages"] is not None


def test_an_attempt_from_the_forge_pipeline_runner_shows_its_seed_stages_verdict_and_sheet(
    tmp_path: Path,
) -> None:
    """pipeline_run's attempt.json keeps `seed` at the top, a stage per folder, and a gate v2 report whose verdict
    can be `review` (not a failure); the review sheet is an ordinary file in the gate stage's folder."""
    attempt = tmp_path / "run-h" / "attempts" / "20261111T120000Z-abcd0001"
    for stage in ("bust", "shape_gate"):
        (attempt / stage).mkdir(parents=True)
    (attempt / "shape_gate" / "mesh-validation.json").write_text(
        '{"verdict": "review", "passed": false, "reasons": ["deficit is close"], "measures": {"deficit": {"value": 0.1}}}'
    )
    (attempt / "shape_gate" / "review-sheet.png").write_bytes(b"png")
    (attempt / "attempt.json").write_text(
        '{"status": "review", "seed": 5, "started_utc": "2026-11-11T12:00:00Z",'
        ' "stages": {"bust": {"key": "k1", "reused": false}, "shape_gate": {"key": "k2", "reused": false}}}'
    )
    view = run_view.get_attempt(tmp_path, "run-h", "20261111T120000Z-abcd0001")
    assert view["seed"] == 5 and view["status"] == "review"
    assert [s["stage"] for s in view["stages"]] == ["bust", "shape_gate"]
    gate = view["stages"][1]["gates"][0]
    assert (gate["verdict"], gate["passed"]) == ("review", False)
    assert "review-sheet.png" in [f["name"] for f in view["stages"][1]["files"]]


def test_stages_of_a_forge_runner_attempt_keep_the_pipeline_order_not_the_sorted_key_order(
    tmp_path: Path,
) -> None:
    attempt = tmp_path / "run-o" / "attempts" / "20261111T120000Z-abcd0002"
    attempt.mkdir(parents=True)
    ids = ["bust", "crop", "mesh", "shape_gate"]
    for stage in ids:
        (attempt / stage).mkdir()
    # attempt.json is written with sorted keys, so `stages` lists them alphabetically
    stages = {name: {"key": name} for name in sorted(ids)}
    (attempt / "attempt.json").write_text(
        json.dumps(
            {
                "status": "generated",
                "stages": stages,
                "resolved_job": {"stages": [{"id": i} for i in ids]},
            }
        )
    )
    view = run_view.get_attempt(tmp_path, "run-o", "20261111T120000Z-abcd0002")
    assert [s["stage"] for s in view["stages"]] == ids


def test_a_candidate_verdict_is_the_worst_gate_of_its_stage(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    stage = root / "run-1" / "attempts" / "a1" / "mesh"
    stage.mkdir(parents=True)
    (stage / "mesh.glb").write_bytes(b"x")
    (stage / "mesh-validation.json").write_text(json.dumps({"verdict": "review"}))
    (stage / "matte.json").write_text(json.dumps({"passed": False}))
    assert run_view.candidate_verdict(root, "run-1", "attempts/a1/mesh/mesh.glb") == "fail"
    (stage / "matte.json").write_text(json.dumps({"passed": True}))
    assert run_view.candidate_verdict(root, "run-1", "attempts/a1/mesh/mesh.glb") == "review"
    (stage / "mesh-validation.json").unlink()
    assert run_view.candidate_verdict(root, "run-1", "attempts/a1/mesh/mesh.glb") == "pass"
    for other in (
        "mesh.glb",
        "attempts/a1/mesh.glb",
        "attempts/zz/mesh/mesh.glb",
        "attempts/a1/../mesh/m.glb",
    ):
        assert run_view.candidate_verdict(root, "run-1", other) is None
    assert run_view.candidate_verdict(root, "../run-1", "attempts/a1/mesh/mesh.glb") is None
