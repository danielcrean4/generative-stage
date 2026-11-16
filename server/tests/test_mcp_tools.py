"""The MCP tools as data: each call becomes one API request, the project comes from the operator, and the client sends
the write header."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from mcp_server.app import Context, ToolError, call, request_for
from mcp_server.client import ApiClient, ApiError
from mcp_server.tools import BY_NAME


def made(name: str, arguments: dict[str, Any], project: str | None = "sample") -> dict[str, Any]:
    return request_for(BY_NAME[name], arguments, project)


def test_start_run_sends_the_pipeline_adapters_and_choices_as_they_are() -> None:
    arguments = {
        "entity_id": "e1", "pipeline": "prop", "prompt": "a key",
        "adapters": {"image": "standin-image", "image-to-mesh": "standin-mesh"},
        "choices": {"style": "clay", "motif": "plain", "seed": 3, "candidates": 2},
    }  # fmt: skip
    request = made("start_run", arguments)
    assert request["method"] == "POST"
    assert request["path"] == "/projects/sample/entities/e1/jobs"
    assert request["body"] == {k: v for k, v in arguments.items() if k != "entity_id"}


def test_start_run_needs_only_a_record_a_pipeline_and_a_prompt() -> None:
    request = made("start_run", {"entity_id": "e1", "pipeline": "concept", "prompt": "a key"})
    assert request["body"] == {"pipeline": "concept", "prompt": "a key"}


def test_list_pipelines_can_be_narrowed_to_a_kind_of_record() -> None:
    request = made("list_pipelines", {"entity_kind": "prop"})
    assert request["query"] == {"entity_kind": "prop"} and request["body"] is None


def test_update_entity_sends_the_revision_it_was_given() -> None:
    request = made("update_entity", {"entity_id": "e1", "revision": 4, "data": {"name": "K"}})
    assert request["method"] == "PUT" and request["body"]["revision"] == 4


def test_filters_go_in_the_query_and_ids_in_the_path() -> None:
    request = made("list_entities", {"kind": "prop", "include_archived": True})
    assert request["query"] == {"kind": "prop", "include_archived": True}
    assert request["body"] is None
    assert made("get_trace", {"entity_id": "e", "run_id": "r", "attempt": "a"})["path"] == (
        "/projects/sample/entities/e/runs/r/trace"
    )


def test_a_project_tool_without_a_project_says_how_to_set_one() -> None:
    with pytest.raises(ToolError, match="--project"):
        made("list_kinds", {}, project=None)
    assert made("list_projects", {}, project=None)["path"] == "/projects"


def test_arguments_that_do_not_fit_are_refused_before_a_request() -> None:
    context = Context(ApiClient("http://127.0.0.1:9"), "sample")  # nothing listens there
    for name, arguments in (
        ("get_entity", {}),
        ("update_entity", {"entity_id": "e", "data": {}}),
        ("create_link", {"type": "belongs_to", "source": "a"}),
        ("list_links", {"entity_id": "e", "direction": "sideways"}),
        ("start_run", {"entity_id": "e", "pipeline": "prop", "prompt": ""}),
        ("start_run", {"entity_id": "e", "pipeline": "prop", "prompt": "x", "seed": 1}),
        ("start_run", {"entity_id": "e", "pipeline": "prop", "prompt": "x", "choices": {"width": 64}}),
        ("start_run", {"entity_id": "e", "pipeline": "prop", "prompt": "x", "choices": {"seed": "1"}}),
        ("start_run", {"entity_id": "e", "pipeline": "prop", "prompt": "x", "choices": {"style": "../x"}}),
        ("start_run", {"entity_id": "e", "pipeline": "prop", "prompt": "x", "adapters": {"image": "/bin/sh"}}),
        ("start_run", {"entity_id": "e", "pipeline": "prop", "prompt": "x", "adapters": {"shell": "sh"}}),
        ("no_such_tool", {}),
    ):  # fmt: skip
        with pytest.raises(ToolError):
            call(context, name, arguments)


class Recorder(BaseHTTPRequestHandler):
    seen: list[tuple[str, str, str | None, dict[str, Any] | None]] = []
    reply: tuple[int, Any] = (200, {"ok": True})

    def handle_any(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        Recorder.seen.append((self.command, self.path, self.headers.get("X-Studio-Request"), body))
        status, data = Recorder.reply
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = do_PUT = do_DELETE = handle_any

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def recorder() -> Any:
    Recorder.seen, Recorder.reply = [], (200, {"ok": True})
    server = HTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield ApiClient(f"http://127.0.0.1:{server.server_port}")
    server.shutdown()
    server.server_close()


def test_writes_carry_the_studio_header_and_reads_do_not(recorder: ApiClient) -> None:
    context = Context(recorder, "sample")
    call(context, "list_kinds", {})
    call(context, "create_entity", {"kind": "prop", "data": {"name": "K"}})
    call(context, "delete_link", {"link_id": "l1"})
    assert [(m, h) for m, _, h, _ in Recorder.seen] == [
        ("GET", None),
        ("POST", "1"),
        ("DELETE", "1"),
    ]
    assert Recorder.seen[1][3] == {"kind": "prop", "data": {"name": "K"}}


def test_error_answers_keep_the_apis_code_and_field(recorder: ApiClient) -> None:
    Recorder.reply = (
        409,
        {
            "error": {
                "status": 409,
                "code": "revision_conflict",
                "message": "stale",
                "field": "/revision",
            }
        },
    )
    with pytest.raises(ApiError) as caught:
        call(Context(recorder, "sample"), "get_entity", {"entity_id": "e"})
    assert (caught.value.status, caught.value.code, caught.value.field) == (
        409,
        "revision_conflict",
        "/revision",
    )
    assert "revision_conflict" in str(caught.value) and "/revision" in str(caught.value)


def test_an_unreachable_api_is_a_clear_error() -> None:
    with pytest.raises(ApiError) as caught:
        call(Context(ApiClient("http://127.0.0.1:9"), "sample"), "list_kinds", {})
    assert caught.value.code == "unreachable"


def test_list_projects_hides_folders(recorder: ApiClient) -> None:
    Recorder.reply = (
        200,
        {
            "projects": [
                {"slug": "s", "name": "S", "folder": "/work/s", "project_file": "/work/s/x.json"}
            ]
        },
    )
    assert call(Context(recorder, None), "list_projects", {}) == {
        "projects": [{"slug": "s", "name": "S"}]
    }


def test_the_api_address_must_be_plain_http() -> None:
    for bad in ("file:///etc/passwd", "ftp://x", "127.0.0.1:8780", ""):
        with pytest.raises(ValueError):
            ApiClient(bad)
