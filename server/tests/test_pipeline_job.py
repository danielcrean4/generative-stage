"""The pipelines a job can run (authoring/offered.json): the catalog routes, the request checks, the command each one
starts and a run of each on the stand-in adapters, end to end through the HTTP API, the dispatcher and
pipeline/pipeline_run.py."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from running_server import Running
from studio_test_support import stand_in_config
from test_api_v1 import entity

from authoring import jobs as dispatching
from authoring import pipeline_job
from authoring.job_store import JobStore
from authoring.machine_config import MachineConfig
from authoring.offered import offers
from authoring.pipeline_job import describe_pipeline_steps
from authoring.steps import attempt_is_current
from mcp_server.tools import ADAPTER_KINDS, CHOICES

IDS = ["character", "concept", "head", "icon", "mesh", "prop"]
KIND_OF_RECORD = {"prop": "prop", "mesh": "prop", "character": "character", "head": "character"}


def start(running: Running, kind: str, body: dict[str, Any]) -> dict[str, Any]:
    record = entity(running.api, running.project, kind, "Sample")
    path = f"{running.project}/entities/{record['id']}/jobs"
    answer: dict[str, Any] = running.api.ok("POST", path, body, 202)
    return answer


def refused(running: Running, body: dict[str, Any], field: str, kind: str = "prop") -> None:
    record = entity(running.api, running.project, kind, "Other")
    path = f"{running.project}/entities/{record['id']}/jobs"
    running.api.fails("POST", path, {"prompt": "a key", **body}, 422, "invalid", field)


def test_the_adapter_list_shows_ids_and_never_a_command(running: Running) -> None:
    adapters = running.api.ok("GET", "/api/v1/adapters")["adapters"]
    assert {a["id"] for a in adapters} >= {"standin-image", "standin-mesh"}
    for row in adapters:
        assert set(row) == {"id", "kind", "description", "default", "runnable", "unmet"}
    defaults = {a["kind"]: a["id"] for a in adapters if a["default"]}
    assert defaults["image"] == "standin-image"
    assert "argv" not in json.dumps(adapters) and "standin.py" not in json.dumps(adapters)
    running.api.fails("POST", "/api/v1/adapters", {}, 405, "method_not_allowed")


def test_a_configured_command_never_reaches_the_adapter_list(
    running: Running, bare_pipeline_environment: Path
) -> None:
    entry = {
        "id": "marked",
        "kind": "image",
        "description": "a marked adapter",
        "argv": ["/opt/marker-program-xyz", "--prompt", "{prompt}", "--output", "{output}"],
        "env": {"MARKER_ENV": "marker-value-xyz"},
        "sandbox": {"network": "deny"},
        "licence": "test",
    }
    bare_pipeline_environment.write_text(json.dumps({"adapters": [entry]}))
    text = json.dumps(running.api.ok("GET", "/api/v1/adapters"))
    assert "marked" in text and "marker" not in text.replace("a marked adapter", "")


def test_every_offer_is_complete_and_its_adapter_kinds_are_known_to_the_tools() -> None:
    assert sorted(offers()) == IDS
    for offer in offers().values():
        assert offer.missing_files() == []
        assert {"style", "motif", "seed", "candidates"} <= set(offer.pipeline.choices), offer.id
        assert set(offer.pipeline.choices) <= set(CHOICES), offer.id
        assert set(offer.adapter_kinds()) <= set(ADAPTER_KINDS), offer.id
    assert set(CHOICES) == {"style", "motif", "seed", "candidates", "hair_colour", "start_image"}


def test_the_pipeline_list_names_the_stages_their_adapter_kinds_and_the_choices(
    running: Running,
) -> None:
    pipelines = running.api.ok("GET", "/api/v1/pipelines")["pipelines"]
    assert sorted(p["id"] for p in pipelines) == IDS
    prop = next(p for p in pipelines if p["id"] == "prop")
    kinds = {s["tool"]: s["adapter_kind"] for s in prop["stages"]}
    assert kinds["concept"] == "image" and kinds["mesh"] == "image-to-mesh"
    assert kinds["matte"] is None
    assert prop["choices"]["style"] == {
        "label": "Style",
        "options": ["clay", "vinyl_toy"],
        "default": "clay",
    }
    assert prop["choices"]["seed"]["min"] == 0 and prop["entity_kinds"] == ["prop"]
    assert next(p for p in pipelines if p["id"] == "concept")["entity_kinds"] is None


def test_the_pipeline_list_can_be_narrowed_to_a_kind_of_record(running: Running) -> None:
    def ids(kind: str) -> list[str]:
        found = running.api.ok("GET", f"/api/v1/pipelines?entity_kind={kind}")["pipelines"]
        return sorted(p["id"] for p in found)

    assert ids("prop") == ["concept", "icon", "mesh", "prop"]
    assert ids("character") == ["character", "concept", "head", "icon"]
    assert ids("setting") == ["concept", "icon"]


def test_a_request_must_name_a_pipeline_this_server_offers_for_that_kind(running: Running) -> None:
    refused(running, {}, "/pipeline")
    refused(running, {"pipeline": "asset_job"}, "/pipeline")
    refused(running, {"pipeline": "../prop"}, "/pipeline")
    refused(running, {"pipeline": "character"}, "/pipeline", kind="prop")
    refused(running, {"pipeline": "prop"}, "/pipeline", kind="setting")
    record = entity(running.api, running.project, "prop", "Key")
    path = f"{running.project}/entities/{record['id']}/jobs"
    running.api.fails("POST", path, {"pipeline": "prop"}, 422, "invalid", "/prompt")
    running.api.fails("POST", path, {"pipeline": "prop", "prompt": "  "}, 422, "invalid", "/prompt")


@pytest.mark.parametrize(
    ("choices", "field"),
    [
        ({"style": "marble"}, "/choices/style"),
        ({"style": "../../etc"}, "/choices/style"),
        ({"style": ["clay"]}, "/choices/style"),
        ({"motif": "nothing"}, "/choices/motif"),
        ({"seed": -1}, "/choices/seed"),
        ({"seed": 2**32}, "/choices/seed"),
        ({"seed": "7"}, "/choices/seed"),
        ({"seed": True}, "/choices/seed"),
        ({"candidates": 0}, "/choices/candidates"),
        ({"candidates": 5}, "/choices/candidates"),
        ({"width": 64}, "/choices/width"),
        ({"contract": "/etc/passwd"}, "/choices/contract"),
    ],
)
def test_a_choice_must_be_declared_by_the_pipeline_and_inside_its_range(
    running: Running, choices: dict[str, Any], field: str
) -> None:
    refused(running, {"pipeline": "prop", "choices": choices}, field)


def test_choices_that_are_not_an_object_are_refused(running: Running) -> None:
    refused(running, {"pipeline": "prop", "choices": ["clay"]}, "/choices")
    refused(running, {"pipeline": "prop", "adapters": "standin-image"}, "/adapters")


@pytest.mark.parametrize(
    ("adapters", "field"),
    [
        (
            {"image-to-mesh": "standin-mesh"},
            "/adapters/image-to-mesh",
        ),  # concept runs no mesh model
        ({"rig": "standin-rig"}, "/adapters/rig"),
        ({"image": "standin-mesh"}, "/adapters/image"),  # the right id for the wrong kind
        ({"image": "no-such-adapter"}, "/adapters/image"),
        ({"image": "/bin/sh"}, "/adapters/image"),
        ({"image": "x y"}, "/adapters/image"),
        ({"image": ["sh"]}, "/adapters/image"),
        ({"image": {"argv": ["sh"]}}, "/adapters/image"),
        ({"image": ""}, "/adapters/image"),
    ],
)
def test_an_adapter_is_named_by_id_for_a_kind_the_pipeline_runs(
    running: Running, adapters: dict[str, Any], field: str
) -> None:
    refused(running, {"pipeline": "concept", "adapters": adapters}, field)


def test_a_request_without_choices_runs_on_the_declared_defaults(running: Running) -> None:
    made = start(running, "prop", {"pipeline": "prop", "prompt": "a key"})
    assert made["job"]["recipe"]["choices"] == {
        "style": "clay",
        "motif": "repair_shop",
        "seed": 1,
        "candidates": 1,
    }
    assert made["job"]["recipe"]["adapters"] == {}
    sent = start(
        running,
        "prop",
        {
            "pipeline": "prop",
            "prompt": "a key",
            "adapters": {"image": "standin-image", "image-to-mesh": "standin-mesh"},
            "choices": {"style": "vinyl_toy", "seed": 12, "candidates": 3},
        },
    )
    recipe = sent["job"]["recipe"]
    assert recipe["choices"]["style"] == "vinyl_toy" and recipe["choices"]["motif"] == "repair_shop"
    assert recipe["choices"]["seed"] == 12 and recipe["choices"]["candidates"] == 3
    assert recipe["adapters"] == {"image": "standin-image", "image-to-mesh": "standin-mesh"}


class Fake:
    """Records the command a run would start and fails it, so nothing runs."""

    started: list[list[str]] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        Fake.started.append([str(a) for a in argv])
        self.stdout = iter(["refused by the test\n"])

    def wait(self) -> int:
        return 1


@pytest.mark.parametrize("pipeline", IDS)
def test_each_pipeline_starts_one_fixed_command_for_all_its_candidates(
    running: Running, monkeypatch: pytest.MonkeyPatch, pipeline: str
) -> None:
    monkeypatch.setattr(subprocess, "Popen", Fake)
    Fake.started = []
    kind = KIND_OF_RECORD.get(pipeline, "prop")
    choices = {"seed": 40, "candidates": 2}
    made = start(running, kind, {"pipeline": pipeline, "prompt": "a key", "choices": choices})
    assert running.dispatcher.run_next(timeout=0)
    job_id = made["job"]["id"]
    run = running.api.ok("GET", f"{running.project}/jobs/{job_id}")["runs"][0]
    assert (
        run["status"] == "failed" and "seeds 40 to 41: the runner exited with 1" in run["log_tail"]
    )
    assert len(Fake.started) == 1  # one process, so one GPU lock for both candidates
    offer = offers()[pipeline]
    root = str(running.config.runs_root / job_id)
    argv = Fake.started[0]
    flags = argv[3::2]
    values = dict(zip(argv[3::2], argv[4::2], strict=False))
    assert argv[2].endswith("pipeline_run.py") and argv[1] == "-I"
    assert (values["--seed"], values["--candidates"]) == ("40", "2")
    assert values["--out-root"] == root
    assert values["--final-dir"] == f"{root}/final"
    assert values["--pipeline"] == f"{root}/pipeline_inputs/{pipeline}.pipeline.json"
    assert values["--subject"] == f"{root}/pipeline_inputs/subject.json"
    # style, motif and contract are files of the offer, looked up by the declared ids
    assert values["--style"] == str(offer.style(offer.pipeline.choices["style"]["default"]))
    assert values["--motif"] == str(offer.motif(offer.pipeline.choices["motif"]["default"]))
    assert values["--contract"] == str(offer.contract)
    assert ("--review-sheet" in flags) == (offer.sheet is not None)


def test_a_choice_picks_the_style_and_motif_files_and_nothing_else(
    running: Running, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", Fake)
    Fake.started = []
    choices = {"style": "vinyl_toy", "motif": "plain"}
    start(running, "prop", {"pipeline": "prop", "prompt": "a key", "choices": choices})
    assert running.dispatcher.run_next(timeout=0)
    values = dict(zip(Fake.started[0][3::2], Fake.started[0][4::2], strict=False))
    assert values["--style"].endswith("examples/prop/styles/vinyl_toy")
    assert values["--motif"].endswith("examples/prop/motifs/plain.json")


def test_the_command_line_holds_nothing_from_the_request_but_numbers(tmp_path: Path) -> None:
    recipe = {
        "prompt": "x --output /etc/passwd; rm -rf ~",
        "adapters": {"image": "m"},
        "choices": {"style": "clay", "motif": "plain", "seed": 3, "candidates": 1},
    }
    offer = offers()["prop"]
    subject, pipeline = pipeline_job.prepare(tmp_path, "job1", recipe, offer)
    argv = pipeline_job.command(offer, tmp_path, subject, pipeline, recipe["choices"])
    assert not any("passwd" in part or "rm -rf" in part for part in argv)
    assert json.loads(subject.read_text())["text"] == recipe["prompt"]
    assert json.loads(subject.read_text())["kind"] == "prop"
    stages = json.loads(pipeline.read_text())["stages"]
    assert [s.get("model") for s in stages if s["tool"] == "concept"] == ["m"]
    assert [s.get("model") for s in stages if s["tool"] == "mesh"] == [None]


def finished(running: Running, made: dict[str, Any]) -> dict[str, Any]:
    assert running.dispatcher.run_next(timeout=0)
    done: dict[str, Any] = running.api.ok("GET", f"{running.project}/jobs/{made['job']['id']}")
    return done


@pytest.mark.parametrize(
    ("pipeline", "kind", "expect"),
    [
        ("concept", "setting", ["final/seed-5/"]),
        ("icon", "setting", ["final/seed-5/"]),
        pytest.param(
            "character",
            "character",
            ["image.png", "final/seed-5/"],
            marks=pytest.mark.skipif(
                shutil.which("blender") is None, reason="Blender is not on PATH"
            ),
        ),
        ("mesh", "prop", ["image.png", "final/seed-5/"]),
        ("prop", "prop", ["image.png", "final/seed-5/"]),
    ],
)
def test_a_pipeline_runs_on_the_stand_in_and_leaves_a_trace(
    tmp_path: Path, standin_environment: Path, pipeline: str, kind: str, expect: list[str]
) -> None:
    found = Running(tmp_path)
    try:
        api, project = found.api, found.project
        record = entity(api, project, kind, "Sample")
        request = {
            "pipeline": pipeline,
            "prompt": "a brass key",
            "adapters": {"image": "standin-image"},
            "choices": {"seed": 5},
        }
        made = api.ok("POST", f"{project}/entities/{record['id']}/jobs", request, 202)
        done = finished(found, made)
        job_id = made["job"]["id"]
        assert [r["status"] for r in done["runs"]] == ["succeeded"], done["runs"][0]["log_tail"]
        assert [s["status"] for s in done["runs"][0]["steps"]].count("succeeded") >= 1
        refs = [c["candidate"] for c in done["candidates"]]
        for wanted in expect:
            assert any(wanted in r for r in refs), (wanted, refs)
        assert len(refs) == len(expect)
        runs = api.ok("GET", f"{project}/entities/{record['id']}/runs")["runs"]
        assert [r["run_id"] for r in runs] == [job_id]
        trace = api.ok("GET", f"{project}/entities/{record['id']}/runs/{job_id}/trace")
        first = trace["stages"][0]  # the concept stage, whatever the pipeline calls it
        assert first["adapter"]["adapter_id"] == "standin-image"
        assert "a brass key" in first["prompt"]
        if pipeline == "prop":
            by_stage = {s["id"]: s for s in trace["stages"]}
            assert by_stage["mesh"]["adapter"]["adapter_id"] == "standin-mesh"
    finally:
        found.close()


def test_a_head_that_fails_its_shape_gate_is_a_failed_run_that_says_which_measure(
    tmp_path: Path, standin_environment: Path
) -> None:
    """The stand-in mesh is a sphere, so the head pipeline's shape gate stops it; the run says so and makes no candidate."""
    found = Running(tmp_path)
    try:
        record = entity(found.api, found.project, "character", "Ines")
        request = {"pipeline": "head", "prompt": "a friendly adult", "choices": {"seed": 5}}
        made = found.api.ok("POST", f"{found.project}/entities/{record['id']}/jobs", request, 202)
        done = finished(found, made)
        run = done["runs"][0]
        assert run["status"] == "failed" and done["candidates"] == []
        assert "above max_" in run["log_tail"] and "seed 5: failed, 0 file(s)" in run["log_tail"]
        assert [s["label"] for s in run["steps"]][:2] == ["Concept bust", "Crop to head and neck"]
        # the failed run is attached to the entity, so its trace can be opened
        runs = found.api.ok("GET", f"{found.project}/entities/{record['id']}/runs")["runs"]
        assert [r["run_id"] for r in runs] == [made["job"]["id"]]
        base = f"{found.project}/entities/{record['id']}/runs/{made['job']['id']}"
        trace = found.api.ok("GET", f"{base}/trace")
        assert trace["status"] == "failed" and trace["stages"][0]["prompt_parts"]
        assert run["steps"][-1]["status"] == "failed" or "failed" in {
            s["status"] for s in run["steps"]
        }
    finally:
        found.close()


def test_choices_change_what_runs_and_each_candidate_has_its_own_seed(
    tmp_path: Path, standin_environment: Path
) -> None:
    found = Running(tmp_path)
    try:
        api, project = found.api, found.project
        record = entity(api, project, "prop", "Key")
        request = {
            "pipeline": "concept",
            "prompt": "a brass key",
            "choices": {"style": "sketch", "seed": 20, "candidates": 3},
        }
        made = api.ok("POST", f"{project}/entities/{record['id']}/jobs", request, 202)
        done = finished(found, made)
        assert done["runs"][0]["status"] == "succeeded", done["runs"][0]["log_tail"]
        notes = sorted(c["note"].split(" seed ")[1] for c in done["candidates"])
        assert notes == ["20", "21", "22"]
        run_root = found.config.runs_root / made["job"]["id"]
        records = [
            json.loads(p.read_text()) for p in sorted(run_root.glob("attempts/*/attempt.json"))
        ]
        assert sorted(r["seed"] for r in records) == [20, 21, 22]
        assert {r["sources"]["style"]["id"] for r in records} == {"sketch"}
        assert {r["sources"]["motif"]["id"] for r in records} == {"plain"}
        prompt = records[0]["resolved_job"]["stages"][0]["reads"]["style.prompt"]["template"]
        assert (
            "pencil sketch" in prompt
            if isinstance(prompt, str)
            else "pencil sketch" in json.dumps(records[0])
        )
    finally:
        found.close()


def test_a_run_that_makes_nothing_fails_and_says_why(
    tmp_path: Path, standin_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = Running(tmp_path)
    try:
        record = entity(found.api, found.project, "prop", "Key")
        request = {"pipeline": "concept", "prompt": "a key", "adapters": {"image": "standin-image"}}
        made = found.api.ok("POST", f"{found.project}/entities/{record['id']}/jobs", request, 202)
        monkeypatch.setenv("GENSTAGE_MACHINE_CONFIG", str(tmp_path / "gone.json"))
        done = finished(found, made)
        run = done["runs"][0]
        assert run["status"] == "failed" and "seed 1" in run["log_tail"]
        assert done["candidates"] == []
        # the runner started an attempt that failed, so the run is attached and its trace opens
        runs = found.api.ok("GET", f"{found.project}/entities/{record['id']}/runs")["runs"]
        assert [r["run_id"] for r in runs] == [made["job"]["id"]]
    finally:
        found.close()


def test_a_job_an_earlier_version_made_is_listed_but_not_run(running: Running) -> None:
    record = entity(running.api, running.project, "prop", "Old")
    folder = Path(running.api.ok("GET", running.project)["folder"])
    store = JobStore.for_project(folder)
    with store.connect() as db:
        db.execute(
            "INSERT INTO jobs VALUES('old1',?,1,'asset_job',NULL,?,'2026-11-01T00:00:00+00:00')",
            (
                record["id"],
                json.dumps(
                    {
                        "prompt": "a key",
                        "model": "m",
                        "seed": 1,
                        "generation": {"stages": ["concept"]},
                    }
                ),
            ),
        )
    run = store.create_run("old1")
    store.add_candidate("old1", str(running.config.runs_root / "old1" / "a.png"), "run")
    listed = running.api.ok("GET", f"{running.project}/entities/{record['id']}/jobs")["jobs"]
    assert [j["job"]["pipeline"] for j in listed] == ["asset_job"]
    assert listed[0]["runs"][0]["steps"] == []
    running.dispatcher.enqueue(store, run["id"], "old1")
    assert running.dispatcher.run_next(timeout=0)
    failed = store.get_run(run["id"])
    assert failed["status"] == "failed" and "Unknown pipeline: 'asset_job'" in failed["log_tail"]


def test_the_steps_are_the_pipeline_copys_stages_and_a_retry_does_not_inherit_old_progress(
    tmp_path: Path,
) -> None:
    config: MachineConfig = stand_in_config(tmp_path)
    offer = offers()["mesh"]
    root = config.runs_root / "j1"
    inputs = root / "pipeline_inputs"
    inputs.mkdir(parents=True)
    (inputs / "mesh.pipeline.json").write_text(offer.file.read_text())
    attempt = root / "attempts" / "20261109T170000Z-deadbeef"
    (attempt / "concept").mkdir(parents=True)
    (attempt / "concept" / "stage.json").write_text("{}")
    job = {"id": "j1", "pipeline": "mesh"}

    def statuses(run: dict[str, Any] | None) -> list[str]:
        return [s["status"] for s in describe_pipeline_steps(job, run, config)]

    assert statuses(None) == ["succeeded", "pending", "pending", "pending"]
    earlier = {"status": "running", "created_at": "2026-11-09T16:50:00+00:00"}
    assert statuses(earlier) == ["succeeded", "running", "pending", "pending"]
    later = {"status": "running", "created_at": "2026-11-09T17:10:00+00:00"}
    assert not attempt_is_current(attempt, later["created_at"])
    assert statuses(later) == ["running", "pending", "pending", "pending"]
    assert statuses({"status": "failed", "created_at": earlier["created_at"]}) == [
        "succeeded", "failed", "pending", "pending",
    ]  # fmt: skip


@pytest.mark.parametrize(("attempts", "attached"), [(True, 1), (False, 0)])
def test_a_failed_run_is_attached_only_when_it_got_as_far_as_an_attempt(
    running: Running, monkeypatch: pytest.MonkeyPatch, attempts: bool, attached: int
) -> None:
    def dies(store: JobStore, job: dict[str, Any], run_id: str, job_id: str, config: Any) -> None:
        if attempts:
            (config.runs_root / job_id / "attempts").mkdir(parents=True)
        store.update_run(run_id, status="failed", log_tail="the runner could not start")

    monkeypatch.setattr(dispatching, "run_pipeline_job", dies)
    record = entity(running.api, running.project, "prop", "Key")
    running.api.ok(
        "POST",
        f"{running.project}/entities/{record['id']}/jobs",
        {"pipeline": "concept", "prompt": "a key"},
        202,
    )
    assert running.dispatcher.run_next(timeout=0)
    runs = running.api.ok("GET", f"{running.project}/entities/{record['id']}/runs")["runs"]
    assert len(runs) == attached


def project_folder(running: Running) -> Path:
    return Path(running.api.ok("GET", running.project)["folder"])


def test_a_project_file_says_which_pipelines_serve_a_kind_and_without_it_the_defaults_hold(
    running: Running,
) -> None:
    def ids(kind: str) -> list[str]:
        found = running.api.ok("GET", f"{running.project}/pipelines?entity_kind={kind}")[
            "pipelines"
        ]
        return [p["id"] for p in found]

    assert ids("setting") == ["concept", "icon"]
    (project_folder(running) / "generation.json").write_text(
        json.dumps({"version": 1, "serves": {"setting": ["icon", "mesh"]}})
    )
    assert ids("setting") == ["icon", "mesh"]  # the project's list, in its order
    assert set(ids("prop")) == {"prop", "mesh", "concept", "icon"}  # other kinds keep the defaults
    record = entity(running.api, running.project, "setting", "Hall")
    path = f"{running.project}/entities/{record['id']}/jobs"
    running.api.fails(
        "POST", path, {"pipeline": "concept", "prompt": "a hall"}, 422, "invalid", "/pipeline"
    )
    running.api.ok("POST", path, {"pipeline": "mesh", "prompt": "a hall"}, 202)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            '{"version": 1, "serves": {"setting": ["nothing"]}}',
            "key 'serves.setting': no pipeline 'nothing'",
        ),
        ('{"version": 1, "serves": {"setting": "icon"}}', "key 'serves.setting': expected a list"),
        ('{"version": 2}', "key 'version': expected 1"),
        ('{"version": 1, "extra": 1}', "expected an object with the keys version and serves"),
        ("{not json", "cannot read as JSON"),
    ],
)
def test_a_wrong_generation_file_is_refused_naming_the_file_and_key(
    running: Running, content: str, message: str
) -> None:
    (project_folder(running) / "generation.json").write_text(content)
    error = running.api.fails(
        "GET", f"{running.project}/pipelines", None, 422, "bad_generation_file"
    )
    assert "generation.json" in error["message"] and message in error["message"]


def test_a_hair_colour_is_a_choice_of_the_head_pipeline_and_lands_in_the_subject(
    running: Running, tmp_path: Path
) -> None:
    refused(
        running,
        {"pipeline": "head", "choices": {"hair_colour": "#ffffff"}},
        "/choices/hair_colour",
        "character",
    )
    refused(
        running,
        {"pipeline": "character", "choices": {"hair_colour": "#4d331f"}},
        "/choices/hair_colour",
        "character",
    )
    made = start(
        running,
        "character",
        {"pipeline": "head", "prompt": "a friendly adult", "choices": {"hair_colour": "#1c1a19"}},
    )
    assert made["job"]["recipe"]["choices"]["hair_colour"] == "#1c1a19"
    default = start(running, "character", {"pipeline": "head", "prompt": "a friendly adult"})
    assert (
        "hair_colour" not in default["job"]["recipe"]["choices"]
    )  # optional: left unset it is not in the subject
    recipe = made["job"]["recipe"]
    subject, _ = pipeline_job.prepare(tmp_path, "job1", recipe, offers()["head"])
    assert json.loads(subject.read_text())["hair_colour"] == "#1c1a19"
    subject, _ = pipeline_job.prepare(tmp_path, "job2", {**recipe, "choices": {}}, offers()["head"])
    assert "hair_colour" not in json.loads(subject.read_text())


def test_a_mesh_run_starts_from_the_image_already_chosen(
    tmp_path: Path, standin_environment: Path
) -> None:
    found = Running(tmp_path)
    try:
        api, project = found.api, found.project
        record = entity(api, project, "prop", "Key")
        base = f"{project}/entities/{record['id']}"
        mesh = {"pipeline": "mesh", "choices": {"start_image": "main"}}
        api.fails(
            "POST", f"{base}/jobs", mesh, 422, "invalid", "/choices/start_image"
        )  # nothing chosen yet
        concept = {"pipeline": "concept", "prompt": "a brass key", "choices": {"seed": 3}}
        first = finished(found, api.ok("POST", f"{base}/jobs", concept, 202))
        assert first["runs"][0]["status"] == "succeeded", first["runs"][0]["log_tail"]
        picture = first["candidates"][0]["candidate"]
        api.ok("POST", f"{base}/chosen", {"run_id": first["job"]["id"], "candidate": picture}, 201)
        made = api.ok(
            "POST", f"{base}/jobs", mesh, 202
        )  # no prompt: the record's title is the subject
        assert made["job"]["recipe"]["prompt"] == "Key"
        assert made["job"]["recipe"]["start_image"]["candidate"] == picture
        api.fails(
            "POST",
            f"{base}/jobs",
            {**mesh, "choices": {"start_image": "icon"}},
            422,
            "invalid",
            "/choices/start_image",
        )
        done = finished(found, made)
        run = done["runs"][0]
        assert run["status"] == "succeeded", run["log_tail"]
        root = found.config.runs_root / made["job"]["id"]
        attempt = json.loads(next(root.glob("attempts/*/attempt.json")).read_text())
        chosen_file = found.config.runs_root / first["job"]["id"] / picture
        assert attempt["start_at"] == "tidy_image"
        assert attempt["supplied"]["concept/image.png"]["path"] == str(chosen_file)
        assert attempt["status"] == "generated" and "concept" not in attempt["stages"]
        assert [c["candidate"].endswith(".glb") for c in done["candidates"]] == [True]
        # the run never ran the concept stage, so it is not credited with the style and motif only that stage reads
        # (and the 3D pipeline has no stage that reads a contract)
        feeds = api.ok("GET", f"{base}/sources")
        assert feeds["run_id"] == made["job"]["id"]
        assert [(s["type"], s["id"]) for s in feeds["sources"]] == [("pipeline", None)]
        style = first["job"]["recipe"]["choices"]["style"]
        picture_style = api.ok("GET", f"{project}/sources/style/concept.{style}")
        assert [r["run_id"] for r in picture_style["used_by"]] == [first["job"]["id"]]
        assert api.ok("GET", f"{project}/sources/style/prop.clay")["used_by"] == []
        trace = api.ok("GET", f"{base}/runs/{made['job']['id']}/trace")
        concept_stage = trace["stages"][0]
        assert (concept_stage["id"], concept_stage["status"], concept_stage["prompt"]) == (
            "concept",
            "supplied",
            None,
        )
    finally:
        found.close()
