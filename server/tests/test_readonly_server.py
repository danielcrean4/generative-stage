"""The read-only server's routes, through a real server on a free port."""

import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.client import HTTPConnection, HTTPResponse
from http.server import ThreadingHTTPServer

import pytest
from run_fixture import (
    BIG_LOG_BYTES,
    NEW_ATTEMPT,
    OLD_ATTEMPT,
    RUN_ICON,
    RUN_JOB,
    RUN_LINK,
    SECRET,
    make_runs_root,
)
from studio_test_support import default_config

from authoring.readonly_server import handler
from authoring.run_view import LOG_TAIL_BYTES

ATTEMPT_URL = f"/api/ro/runs/{RUN_JOB}/attempts/{NEW_ATTEMPT}"


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def request(
        self, method: str, path: str, headers: dict[str, str] | None = None
    ) -> tuple[HTTPResponse, bytes]:
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    def get(
        self, path: str, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, object]]:
        response, body = self.request("GET", path, headers)
        assert response.getheader("Content-Type", "").startswith("application/json")
        assert response.getheader("X-Content-Type-Options") == "nosniff"
        return response.status, json.loads(body)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Client]:
    """One read-only server for the module; no route writes, so tests can share it."""
    base = tmp_path_factory.mktemp("ro")
    config = replace(default_config(), runs_root=make_runs_root(base))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(config))
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield Client(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_health(client: Client) -> None:
    status, body = client.get("/api/ro/health")
    assert status == 200 and body["ok"] is True
    assert str(body["runs_root"]).endswith("/runs")


def test_runs_list_and_limit(client: Client) -> None:
    status, body = client.get("/api/ro/runs?limit=1")
    assert status == 200 and len(body["runs"]) == 1  # type: ignore[arg-type]
    status, body = client.get("/api/ro/runs")
    assert {r["run_id"] for r in body["runs"]} == {RUN_JOB, RUN_ICON}  # type: ignore[attr-defined]
    for bad in ("limit=0", "limit=abc", "limit=-1", "limit=9999"):
        status, body = client.get(f"/api/ro/runs?{bad}")
        assert status == 400 and "limit" in str(body["error"])


def test_run_and_attempt_views(client: Client) -> None:
    status, run = client.get(f"/api/ro/runs/{RUN_JOB}")
    assert status == 200
    assert [a["attempt_id"] for a in run["attempts"]] == [NEW_ATTEMPT, OLD_ATTEMPT]  # type: ignore[attr-defined]
    status, view = client.get(ATTEMPT_URL)
    assert status == 200
    assert [s["stage"] for s in view["stages"]] == ["concept", "matte", "mesh"]  # type: ignore[attr-defined]


def test_every_listed_url_serves_its_file(client: Client) -> None:
    _, view = client.get(ATTEMPT_URL)
    _, run = client.get(f"/api/ro/runs/{RUN_JOB}")
    urls = [f["url"] for s in view["stages"] for f in s["files"]]  # type: ignore[attr-defined]
    urls += [f["url"] for f in run["root_files"]]  # type: ignore[attr-defined]
    assert len(urls) >= 10
    for url in urls:
        response, body = client.request("GET", url)
        assert response.status == 200, url
        assert response.getheader("Content-Length") == str(len(body))


def test_file_content_types_and_log_tail(client: Client) -> None:
    response, body = client.request("GET", f"{ATTEMPT_URL}/files/mesh/try-1/mesh.glb")
    assert response.getheader("Content-Type") == "model/gltf-binary" and body == b"glTF"
    response, body = client.request("GET", f"{ATTEMPT_URL}/files/concept/image.png")
    assert response.getheader("Content-Type") == "image/png"
    response, body = client.request("GET", f"{ATTEMPT_URL}/files/concept/big.log")
    assert len(body) == LOG_TAIL_BYTES and body.endswith(b"TAIL!")
    assert response.getheader("X-Total-Size") == str(BIG_LOG_BYTES)
    assert "last" in (response.getheader("X-Truncated") or "")
    response, _ = client.request("GET", f"{ATTEMPT_URL}/files/concept/step.log")
    assert response.getheader("X-Truncated") is None


def test_root_files_served_both_ways(client: Client) -> None:
    for url in (
        f"/api/ro/runs/{RUN_ICON}/files/_root/icon.png",
        f"/api/ro/runs/{RUN_JOB}/files/_root/bust_raw.png",
        f"{ATTEMPT_URL}/files/_root/bust_raw.png",
    ):
        response, _ = client.request("GET", url)
        assert response.status == 200, url


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def test_other_methods_are_405(client: Client, method: str) -> None:
    response, _ = client.request(method, "/api/ro/health")
    assert response.status == 405 and response.getheader("Allow") == "GET"


def test_host_and_origin_guards(client: Client) -> None:
    status, _ = client.get("/api/ro/health", {"Host": "evil.example"})
    assert status == 403
    status, _ = client.get("/api/ro/health", {"Origin": "http://evil.example"})
    assert status == 403
    status, _ = client.get("/api/ro/health", {"Origin": f"http://localhost:{client.port}"})
    assert status == 200


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/ro",
        "/api/ro/nothing",
        "/api/ro/runs/",
        "/api/ro/runs/nope",
        f"/api/ro/runs/{RUN_JOB}/attempts",
        f"/api/ro/runs/{RUN_JOB}/attempts/nope",
        f"/api/ro/runs/{RUN_JOB}/cache",
        f"{ATTEMPT_URL}/files",
        f"{ATTEMPT_URL}/files/concept",
        f"{ATTEMPT_URL}/files/concept/missing.png",
        f"{ATTEMPT_URL}/files/concept/tool.exe",
        f"{ATTEMPT_URL}/files/concept/../../attempt.json",
        f"{ATTEMPT_URL}/files/concept/%2e%2e/%2e%2e/attempt.json",
        f"{ATTEMPT_URL}/files/concept/%2e%2e%2f%2e%2e%2fattempt.json",
        f"{ATTEMPT_URL}/files/%2e%2e/concept/image.png",
        f"{ATTEMPT_URL}/files/concept//etc/passwd",
        f"{ATTEMPT_URL}/files/concept/%2Fetc%2Fpasswd",
        f"{ATTEMPT_URL}/files/concept/evil.png",  # planted symlink to a file outside the root
        f"/api/ro/runs/{RUN_JOB}/files/_root/leak.png",  # planted symlink at the run root
        f"/api/ro/runs/{RUN_JOB}/files/_root/latest.json",
        f"/api/ro/runs/{RUN_LINK}",  # a run folder that is a symlink outside the root
        f"/api/ro/runs/{RUN_LINK}/attempts/x",
        f"/api/ro/runs/{RUN_LINK}/files/_root/secret.txt",
        "/api/ro/runs/..",
        "/api/ro/runs/%2e%2e",
        f"/api/ro/runs/{RUN_JOB}/attempts/%2e%2e",
    ],
)
def test_traversal_and_unknown_routes_are_json_404(client: Client, path: str) -> None:
    response, body = client.request("GET", path)
    assert response.status == 404, path
    assert response.getheader("Content-Type", "").startswith("application/json")
    assert SECRET.encode() not in body
    assert "error" in json.loads(body)
