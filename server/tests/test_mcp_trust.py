"""The trust rule for the MCP server (docs/adapters.md): no tool can carry a command, argument list, environment, file,
folder or address, and a crafted call cannot change what a run starts."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from running_server import Running
from test_api_v1 import entity

from authoring import pipeline_job
from authoring.job_store import JobStore
from mcp_server.app import Context, ToolError, call, request_for
from mcp_server.client import ApiClient, ApiError, segment
from mcp_server.tools import BY_NAME, TOOLS

# Words that name a command, an argument list, an environment, a file, a folder or an address. A property whose name
# has one of these as a part (split on `_` and camel case) is refused.
FORBIDDEN = {
    "command", "cmd", "argv", "args", "arg", "env", "environ", "environment", "path", "paths", "file",
    "files", "folder", "dir", "directory", "url", "uri", "href", "cwd", "exec", "executable", "shell",
    "program", "binary", "script", "weights", "generation", "contract", "host", "port",
}  # fmt: skip
# `style` and `motif` are not in the list: a choice names one of the ids the pipeline file declares, the server refuses
# anything else (test_choices_are_checked_against_the_pipelines_own_declaration) and the id is looked up, never joined.
# The one open object: the record's own data, which the server checks against the kind's schema.
OPEN_OBJECTS = {
    ("create_entity", "data"),
    ("update_entity", "data"),
    ("check_condition", "condition"),
}


def words(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {part.lower() for part in re.split(r"[_\-.\s]+", spaced) if part}


def walk(tool: str, schema: Any, found: list[str], at: str = "") -> None:
    """Collect every problem in a schema: a forbidden property name, or an object that is not closed."""
    if isinstance(schema, list):
        for item in schema:
            walk(tool, item, found, at)
        return
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties", {})
    is_object = schema.get("type") == "object" or properties
    if is_object and schema.get("additionalProperties") is not False:
        name = at.rsplit("/", 1)[-1]
        if (tool, name) not in OPEN_OBJECTS or properties:
            found.append(f"{tool}{at or '/'}: object is not closed")
    for key in ("patternProperties", "propertyNames", "$ref", "$defs"):
        if key in schema:
            found.append(f"{tool}{at}: {key} is not used in tool schemas")
    for name, sub in properties.items():
        if words(name) & FORBIDDEN:
            found.append(f"{tool}{at}/{name}: a name for a command, file, folder or address")
        walk(tool, sub, found, f"{at}/{name}")
    for key in ("items", "anyOf", "oneOf", "allOf", "not"):
        if key in schema:
            walk(tool, schema[key], found, at)


def test_no_tool_schema_has_a_field_for_a_command_file_folder_or_address() -> None:
    found: list[str] = []
    for tool in TOOLS:
        walk(tool.name, tool.schema(), found)
    assert found == []


def test_the_one_reference_that_looks_like_a_path_is_pattern_bound() -> None:
    properties = next(t for t in TOOLS if t.name == "choose_candidate").properties
    assert "pattern" in properties["candidate"]


def test_the_walk_catches_what_it_is_for() -> None:
    for bad in (
        {"type": "object", "properties": {"command": {"type": "string"}}, "additionalProperties": False},
        {"type": "object", "properties": {"adapterPath": {"type": "string"}}, "additionalProperties": False},
        {"type": "object", "properties": {"x": {"type": "object"}}, "additionalProperties": False},
        {"type": "object", "properties": {"x": {"type": "string"}}},
        {"type": "object", "properties": {"x": {"type": "array", "items": {"type": "object"}}},
         "additionalProperties": False},
    ):  # fmt: skip
        found: list[str] = []
        walk("t", bad, found)
        assert found, bad


def test_every_tool_has_a_closed_schema_and_a_description() -> None:
    assert len({t.name for t in TOOLS}) == len(TOOLS)
    for tool in TOOLS:
        assert tool.description and tool.schema()["additionalProperties"] is False


CRAFTED_FIELDS = {
    "command": ["/bin/sh", "-c", "id"],
    "argv": ["/bin/sh"],
    "env": {"PATH": "/tmp"},
    "cwd": "/",
    "path": "/etc/passwd",
    "url": "http://example.com",
    "generation": {"contract": "/etc/passwd", "stages": ["concept"]},
    "contract": "/etc/passwd",
    "model": "standin-image",
    "mesh_model": "standin-mesh",
    "image_adapter": "standin-image",
    "seed": 4,
}


def start_arguments(entity_id: str, **more: Any) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "pipeline": "prop",
        "prompt": "a brass key",
        "adapters": {"image": "standin-image"},
        "choices": {"seed": 4},
        **more,
    }


@pytest.fixture
def prop(running: Running) -> tuple[Running, Context, str]:
    key = entity(running.api, running.project, "prop", "Key")
    context = Context(ApiClient(f"http://127.0.0.1:{running.api.port}"), "sample")
    return running, context, key["id"]


def jobs_of(running: Running, entity_id: str) -> list[dict[str, Any]]:
    folder = running.api.ok("GET", f"{running.project}")["folder"]
    return JobStore.for_project(Path(folder)).jobs_of(entity_id)


@pytest.mark.parametrize("field", sorted(CRAFTED_FIELDS))
def test_a_crafted_extra_field_is_refused_and_no_job_is_made(
    prop: tuple[Running, Context, str], field: str
) -> None:
    running, context, entity_id = prop
    arguments = start_arguments(entity_id, **{field: CRAFTED_FIELDS[field]})
    with pytest.raises(ToolError, match="Additional properties|unexpected"):
        call(context, "start_run", arguments)
    assert jobs_of(running, entity_id) == []


@pytest.mark.parametrize(
    "value",
    ["/bin/sh", "standin-image; id", "../x", "a b", "$(id)", "x" * 200, "", ["sh"], {"a": 1}],
)
def test_an_adapter_or_pipeline_that_is_not_an_id_is_refused(
    prop: tuple[Running, Context, str], value: Any
) -> None:
    running, context, entity_id = prop
    for more in (
        {"pipeline": value},
        {"adapters": {"image": value}},
        {"adapters": {"image-to-mesh": value}},
        {"choices": {"style": value}},
        {"choices": {"motif": value}},
    ):
        with pytest.raises(ToolError):
            call(context, "start_run", start_arguments(entity_id, **more))
    assert jobs_of(running, entity_id) == []


@pytest.mark.parametrize(
    "choices",
    [
        {"style": "marble"},
        {"motif": "not-a-motif"},
        {"seed": -1},
        {"seed": 2**32},
        {"candidates": 0},
        {"candidates": 9},
        {"width": 64},
        {"seed": 1.5},
    ],
)
def test_a_choice_the_pipeline_does_not_declare_or_a_value_out_of_range_never_makes_a_job(
    prop: tuple[Running, Context, str], choices: dict[str, Any]
) -> None:
    running, context, entity_id = prop
    with pytest.raises((ToolError, ApiError)):
        call(context, "start_run", start_arguments(entity_id, choices=choices))
    assert jobs_of(running, entity_id) == []


def test_every_adapter_kind_in_the_schema_is_a_kind_a_pipeline_stage_can_run() -> None:
    import pipeline_file

    kinds = {t.kind for t in pipeline_file.TOOLS.values() if t.kind}
    schema = BY_NAME["start_run"].properties["adapters"]["properties"]
    assert set(schema) == kinds
    choices = BY_NAME["start_run"].properties["choices"]["properties"]
    assert set(choices) == set(pipeline_file.CHOICE_NAMES)


def test_an_id_with_slashes_cannot_change_the_route(prop: tuple[Running, Context, str]) -> None:
    _, context, _ = prop
    for hostile in ("../jobs/x", "a/b", "%2e%2e", "x?y=1"):
        with pytest.raises(ToolError):
            call(context, "get_entity", {"entity_id": hostile})
    for dots in (".", "..", "...", ".hidden"):
        with pytest.raises(ToolError):
            call(context, "delete_link", {"link_id": dots})
    assert segment("x/../y?z#") == "x%2F..%2Fy%3Fz%23"
    # Even a value that got past a schema is one path segment.
    tool = next(t for t in TOOLS if t.name == "get_run")
    made = request_for(tool, {"run_id": "../../entities"}, "sample")
    assert made["path"] == "/projects/sample/jobs/..%2F..%2Fentities"


class FakePopen:
    """Records the command a run would start and fails it, so nothing runs."""

    started: list[list[str]] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        FakePopen.started.append(list(argv))
        self.stdout = iter(["refused by the test\n"])

    def wait(self) -> int:
        return 1


def started_command(running: Running, context: Context, entity_id: str, **more: Any) -> list[str]:
    FakePopen.started = []
    answer = call(context, "start_run", start_arguments(entity_id, **more))
    assert running.dispatcher.run_next(timeout=0)
    assert len(FakePopen.started) == 1
    job_id = answer["job"]["id"]
    return [part.replace(job_id, "JOB") for part in FakePopen.started[0]]


def test_a_crafted_prompt_changes_a_file_and_nothing_in_the_command(
    prop: tuple[Running, Context, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    running, context, entity_id = prop
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    plain = started_command(running, context, entity_id)
    crafted = started_command(
        running,
        context,
        entity_id,
        prompt="x --output /etc/passwd; $(id) `id` {out_dir} --model /bin/sh",
        adapters={"image": "standin-image", "image-to-mesh": "standin-mesh"},
    )
    assert crafted == plain
    job = jobs_of(running, entity_id)[0]
    subject = Path(running.config.runs_root) / job["id"] / pipeline_job.INPUTS_DIR / "subject.json"
    assert "/etc/passwd" in json.loads(subject.read_text())["text"]


def test_the_api_refuses_what_the_schema_would_have(prop: tuple[Running, Context, str]) -> None:
    """Defence in depth: skip the schema and the server still refuses a key it does not know."""
    running, _, entity_id = prop
    jobs = f"{running.project}/entities/{entity_id}/jobs"
    for extra in ({"argv": ["sh"]}, {"command": "sh"}, {"env": {"A": "b"}}):
        running.api.fails(
            "POST",
            jobs,
            {"pipeline": "prop", "prompt": "x", "adapters": {"image": "standin-image"}, **extra},
            422,
            "invalid",
        )


def test_an_api_error_reaches_the_agent_with_its_code(prop: tuple[Running, Context, str]) -> None:
    _, context, _ = prop
    with pytest.raises(ApiError) as caught:
        call(context, "get_entity", {"entity_id": "no-such-record"})
    assert caught.value.code == "entity_not_found"


@pytest.mark.parametrize(
    "candidate",
    ["/etc/passwd", "../x", "a/../b", "~/x", "a\\b", "attempts//x", "file:///etc/passwd", "a/", ""],
)
def test_a_candidate_is_a_relative_name_inside_a_run(
    prop: tuple[Running, Context, str], candidate: str
) -> None:
    _, context, entity_id = prop
    arguments = {"entity_id": entity_id, "run_id": "r1", "candidate": candidate}
    with pytest.raises(ToolError):
        call(context, "choose_candidate", arguments)


def test_the_names_a_run_offers_are_accepted_and_no_file_place_is_shown(
    prop: tuple[Running, Context, str],
) -> None:
    for name in (
        "attempts/20261113T031500Z-ab12cd34/concept/image.png",
        "final/clay/hand_drill.glb",
        "concept.png",
    ):
        request = request_for(
            next(t for t in TOOLS if t.name == "choose_candidate"),
            {"entity_id": "e", "run_id": "r", "candidate": name},
            "sample",
        )
        assert request["body"]["candidate"] == name
    from mcp_server.tools import BY_NAME

    shown = BY_NAME["get_run"].view(
        {"job": {}, "candidates": [{"candidate": "c.png", "output_ref": "/home/x/c.png"}]}
    )  # type: ignore[misc]
    assert shown["candidates"] == [{"candidate": "c.png"}]
