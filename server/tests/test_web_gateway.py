"""The web gateway: files of the web app, the two servers behind it, and the local-only check."""

import http.client
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from authoring.web_gateway import GatewayServer, file_for, handler, upstream_for


def echo(name: str) -> type[BaseHTTPRequestHandler]:
    """A stand-in for one of the servers: answers with what it was sent."""

    class Echo(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            seen = {
                "who": name,
                "method": self.command,
                "path": self.path,
                "host": self.headers.get("Host"),
                "origin": self.headers.get("Origin"),
                "marker": self.headers.get("X-Studio-Request"),
                "body": self.rfile.read(length).decode(),
            }
            body = json.dumps(seen).encode()
            self.send_response(201 if self.command == "POST" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = answer  # noqa: N815

    return Echo


def serve(
    handler_class: type[BaseHTTPRequestHandler], server_class: Any = ThreadingHTTPServer
) -> Any:
    server = server_class(("127.0.0.1", 0), handler_class)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Gateway:
    def __init__(self, ui: Path, api: Any, readonly: Any) -> None:
        self.api, self.readonly = api, readonly
        self.server = serve(
            handler(
                ui,
                f"http://127.0.0.1:{api.server_port}",
                f"http://127.0.0.1:{readonly.server_port}",
            ),
            GatewayServer,
        )
        self.port = self.server.server_port

    def ask(
        self, method: str, path: str, body: str | None = None, **headers: str
    ) -> tuple[int, bytes]:
        sent = {
            "Host": f"127.0.0.1:{self.port}",
            **{k.replace("_", "-"): v for k, v in headers.items()},
        }
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.request(method, path, body=body, headers=sent)
        answer = connection.getresponse()
        data = answer.read()
        connection.close()
        return answer.status, data


@pytest.fixture
def gateway(tmp_path: Path) -> Iterator[Gateway]:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<html>app</html>")
    (ui / "assets" / "main.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside")
    api, readonly = serve(echo("api")), serve(echo("readonly"))
    found = Gateway(ui, api, readonly)
    yield found
    for server in (found.server, api, readonly):
        server.shutdown()
        server.server_close()


def test_routes_go_to_the_right_place() -> None:
    assert upstream_for("/api/ro/runs", "A", "R") == "R"
    assert upstream_for("/api/v1/projects", "A", "R") == "A"
    assert upstream_for("/api/rox", "A", "R") == "A"
    assert upstream_for("/projects/x", "A", "R") is None


def test_files_stay_inside_the_app_folder(tmp_path: Path) -> None:
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("x")
    (tmp_path / "secret.txt").write_text("y")
    assert file_for(ui, "/../secret.txt") == ui / "index.html"
    assert file_for(ui, "/no/such/route") == ui / "index.html"


def test_serves_files_and_falls_back_to_the_index(gateway: Gateway) -> None:
    assert gateway.ask("GET", "/") == (200, b"<html>app</html>")
    assert gateway.ask("GET", "/assets/main.js") == (200, b"console.log(1)")
    assert gateway.ask("GET", "/projects/sample/entities") == (200, b"<html>app</html>")
    assert gateway.ask("GET", "/..%2fsecret.txt")[1] == b"<html>app</html>"


def test_api_calls_reach_the_servers_as_their_own_local_address(gateway: Gateway) -> None:
    status, data = gateway.ask(
        "POST", "/api/v1/projects?a=1", '{"x": 1}',
        Origin=f"http://127.0.0.1:{gateway.port}", X_Studio_Request="1", Content_Type="application/json",
    )  # fmt: skip
    seen = json.loads(data)
    assert status == 201 and seen["who"] == "api" and seen["path"] == "/api/v1/projects?a=1"
    assert seen["host"] == f"127.0.0.1:{gateway.api.server_port}"
    assert seen["origin"] == f"http://127.0.0.1:{gateway.api.server_port}"
    assert seen["marker"] == "1" and seen["body"] == '{"x": 1}'
    seen = json.loads(gateway.ask("GET", "/api/ro/runs")[1])
    assert seen["who"] == "readonly" and seen["host"] == f"127.0.0.1:{gateway.readonly.server_port}"


def test_other_sites_and_hosts_are_refused(gateway: Gateway) -> None:
    assert gateway.ask("GET", "/api/v1/projects", Origin="http://evil.example")[0] == 403
    assert gateway.ask("GET", "/", Host="evil.example")[0] == 403
    assert gateway.ask("GET", "/", Host=f"127.0.0.1:{gateway.port + 1}")[0] == 403


def test_a_dead_server_is_a_502(gateway: Gateway) -> None:
    gateway.api.shutdown()
    gateway.api.server_close()
    status, data = gateway.ask("GET", "/api/v1/projects")
    assert status == 502 and b"did not answer" in data
