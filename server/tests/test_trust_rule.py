"""The trust rule, server side (docs/adapters.md): a request, a query string, entity data, a project file or an
export bundle can choose an adapter by id and nothing more. Every attempt to add a program, an argument, an
environment variable or a model path fails closed: refused with 422, or the command the run starts is exactly the
one it starts without the attempt. pipeline/tests/test_trust_rule.py covers pipeline files and resolved jobs."""

import json
import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from studio_test_support import stand_in_config
from test_api_v1 import Api, entity

from authoring import pipeline_job
from authoring.jobs import Dispatcher
from authoring.offered import offers
from authoring.server import handler
from core.errors import Invalid
from core.project_file import ProjectFileError, load_project_file
from core.registry import RegistryFile
from core.workspace import Workspace
from export.bundle import MANIFEST, plan_bundle, validate_manifest, write_bundle
from export.engines.godot_example.godot_import import import_bundle
from export.tests.support import make_scene

COMMANDS: dict[str, Any] = {
    "command": "/bin/sh -c id",
    "argv": ["/bin/sh", "-c", "id"],
    "env": {"LD_PRELOAD": "/tmp/x.so"},
    "cwd": "/",
    "python": "/bin/sh",
    "adapter": {"argv": ["/bin/sh"]},
    "models": {"concept": "/bin/sh"},
    "model_paths": {"concept": "/tmp/weights"},
    "concept_model_path": "/tmp/weights",
}
IDS = sorted(offers())
KIND_OF_RECORD = {"prop": "prop", "mesh": "prop", "character": "character", "head": "character"}
REQUEST = {"prompt": "a key", "adapters": {"image": "standin-image"}, "choices": {"seed": 3}}


@dataclass
class Spawned:
    argv: list[str]
    cwd: str | None
    env: object


class FakeProcess:
    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        SPAWNED.append(Spawned([str(a) for a in argv], kwargs.get("cwd"), kwargs.get("env")))
        self.stdout: Iterator[str] = iter(())
        self.returncode = 1

    def wait(self) -> int:
        return 1


SPAWNED: list[Spawned] = []


@pytest.fixture
def served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Api, Dispatcher, Callable[[str], str]]]:
    SPAWNED.clear()
    monkeypatch.setattr(pipeline_job.subprocess, "Popen", FakeProcess)
    config = stand_in_config(tmp_path)
    workspace = Workspace(RegistryFile(tmp_path / "registry.json"), run_exists=lambda run_id: False)
    dispatcher = Dispatcher(config)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(config, workspace, dispatcher))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api = Api(server.server_port, tmp_path)
        api.ok(
            "POST",
            "/api/v1/projects",
            {"folder": str(tmp_path / "p"), "slug": "p", "name": "P"},
            201,
        )

        def jobs_path(pipeline: str) -> str:
            record = entity(
                api, "/api/v1/projects/p", KIND_OF_RECORD.get(pipeline, "setting"), "Key"
            )
            return f"/api/v1/projects/p/entities/{record['id']}/jobs"

        yield api, dispatcher, jobs_path
    finally:
        server.shutdown()
        server.server_close()


def started(api: Api, dispatcher: Dispatcher, path: str, body: dict[str, Any]) -> Spawned:
    """Start a job and run it; what it spawned, with its job id written as JOB so two runs compare."""
    job = api.ok("POST", path, body, 202)["job"]
    assert dispatcher.run_next(timeout=0)
    spawned = SPAWNED[-1]
    return Spawned([a.replace(job["id"], "JOB") for a in spawned.argv], spawned.cwd, spawned.env)


Served = tuple[Api, Dispatcher, Callable[[str], str]]


@pytest.mark.parametrize("pipeline", IDS)
def test_a_job_request_cannot_carry_a_command(served: Served, pipeline: str) -> None:
    api, _, path = served
    where = path(pipeline)
    request = {**REQUEST, "pipeline": pipeline}
    for key in sorted(COMMANDS):
        api.fails("POST", where, {**request, key: COMMANDS[key]}, 422, "invalid", f"/{key}")
        api.fails(
            "POST",
            where,
            {**request, "choices": {key: COMMANDS[key]}},
            422,
            "invalid",
            f"/choices/{key}",
        )
        api.fails(
            "POST",
            where,
            {**request, "adapters": {key: "standin-image"}},
            422,
            "invalid",
            f"/adapters/{key}",
        )
    for key in (
        "generation",
        "model",
        "mesh_model",
        "component",
    ):  # the keys of the retired request shape
        api.fails("POST", where, {**request, key: "standin-image"}, 422, "invalid", f"/{key}")


@pytest.mark.parametrize("pipeline", IDS)
def test_a_job_chooses_an_adapter_by_id_only(served: Served, pipeline: str) -> None:
    api, _, path = served
    kind = offers()[pipeline].adapter_kinds()[0]
    for model in (
        "/bin/sh",
        "/bin/sh -c id",
        "a b",
        "../x",
        "",
        ["/bin/sh"],
        {"argv": ["/bin/sh"]},
        7,
    ):
        request = {**REQUEST, "pipeline": pipeline, "adapters": {kind: model}}
        api.fails("POST", path(pipeline), request, 422, "invalid", f"/adapters/{kind}")


CRAFTED_CHOICES = [
    ("style", "../../../etc"),
    ("style", "/bin/sh"),
    ("style", "clay/../../x"),
    ("motif", "../../../etc/passwd"),
    ("motif", "/bin/sh"),
    ("seed", "1; id"),
    ("seed", 10**12),
    ("candidates", 10**6),
]


@pytest.mark.parametrize("pipeline", IDS)
def test_choices_are_checked_against_the_pipelines_own_declaration(
    served: Served, pipeline: str
) -> None:
    api, _, path = served
    for key, value in CRAFTED_CHOICES:
        request = {**REQUEST, "pipeline": pipeline, "choices": {key: value}}
        api.fails("POST", path(pipeline), request, 422, "invalid", f"/choices/{key}")


@pytest.mark.parametrize("pipeline", IDS)
def test_a_query_string_changes_nothing(served: Served, pipeline: str) -> None:
    api, dispatcher, path = served
    body = {**REQUEST, "pipeline": pipeline}
    plain = started(api, dispatcher, path(pipeline), body)
    query = "?argv=/bin/sh&command=id&model=x&env=LD_PRELOAD%3D/tmp/x.so&python=/bin/sh&style=../x"
    assert started(api, dispatcher, path(pipeline) + query, body) == plain


@pytest.mark.parametrize("pipeline", IDS)
def test_a_crafted_prompt_changes_a_file_and_nothing_in_the_command(
    served: Served, pipeline: str
) -> None:
    api, dispatcher, path = served
    body = {**REQUEST, "pipeline": pipeline}
    plain = started(api, dispatcher, path(pipeline), body)
    crafted = started(
        api,
        dispatcher,
        path(pipeline),
        {**body, "prompt": "x --output /etc/passwd; $(id) `id` {out_dir} --model /bin/sh"},
    )
    assert crafted == plain
    assert Path(SPAWNED[-1].argv[2]).name == "pipeline_run.py"


@pytest.mark.parametrize("pipeline", IDS)
def test_entity_data_never_reaches_a_command(served: Served, pipeline: str) -> None:
    api, dispatcher, path = served
    where = path(pipeline)
    project = where.split("/entities/")[0]
    for (
        key,
        value,
    ) in COMMANDS.items():  # the kind's schema refuses the keys, so no job can see them
        api.fails(
            "POST",
            f"{project}/entities",
            {"kind": "prop", "data": {"name": "Odd", key: value}},
            422,
            "invalid_entity",
        )
    started(api, dispatcher, where, {**REQUEST, "pipeline": pipeline})
    argv = SPAWNED[
        -1
    ].argv  # the command holds the runner, its flags, server-made paths and whole numbers
    flags = argv[3::2]
    assert flags[:2] == ["--pipeline", "--subject"] and all(f.startswith("--") for f in flags)
    values = dict(zip(flags, argv[4::2], strict=False))
    assert values["--seed"].isdigit() and values["--candidates"].isdigit()
    assert all(
        Path(v).is_absolute() for k, v in values.items() if k not in ("--seed", "--candidates")
    )
    inputs = Path(values["--subject"]).parent
    assert set(json.loads((inputs / "subject.json").read_text())) == {"id", "kind", "text"}
    assert SPAWNED[-1].env is None  # the run inherits the server's environment and adds nothing


def test_a_project_file_cannot_define_an_adapter(tmp_path: Path) -> None:
    for key in ("adapters", "defaults", *COMMANDS):
        file = tmp_path / "studio.project.json"
        file.write_text(json.dumps({"slug": "p", "name": "P", key: COMMANDS.get(key, [])}))
        with pytest.raises(ProjectFileError, match=f"key '{key}': unknown key"):
            load_project_file(file)


def test_an_export_bundle_cannot_carry_a_command_back_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = make_scene(tmp_path)
    bundle = write_bundle(plan_bundle(scene.world, scene.runs), tmp_path / "bundle")
    manifest = json.loads((bundle / MANIFEST).read_text())
    for key in ("adapters", *COMMANDS):
        with pytest.raises(Invalid):  # an earlier bundle is read back only through the schema
            validate_manifest({**manifest, key: COMMANDS.get(key, [])})
    (bundle / MANIFEST).write_text(json.dumps({**manifest, **COMMANDS}))

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("an import started a program")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    import_bundle(bundle, tmp_path / "game")  # copies files; the extra keys are inert
