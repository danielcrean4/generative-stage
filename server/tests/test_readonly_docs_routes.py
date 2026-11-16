"""The read-only server's docs routes, through a real server on a free port."""

import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from docs_project_fixture import SECRET, make_project
from run_fixture import make_runs_root
from studio_test_support import default_config

from authoring.readonly_server import handler, registry_for
from core.project_file import PROJECT_FILE_NAME, ProjectFileError, load_project_file
from core.registry import ProjectRegistry, RegistryFile

SECOND = Path(__file__).parent / "fixtures/docs_fixture"


class Client:
    def __init__(self, port: int, root: Path) -> None:
        self.port, self.root = port, root

    def raw(
        self, method: str, path: str, headers: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, body

    def get(self, path: str) -> tuple[int, dict[str, object]]:
        status, body = self.raw("GET", path)
        data = json.loads(body)
        assert SECRET not in body.decode()
        assert str(self.root) not in body.decode()
        return status, data


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Client]:
    base = tmp_path_factory.mktemp("docs")
    project = make_project(base)
    registry = ProjectRegistry([project, load_project_file(SECOND / PROJECT_FILE_NAME)])
    config = replace(default_config(), runs_root=make_runs_root(base))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(config, registry))
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    ).start()
    try:
        yield Client(server.server_port, base)
    finally:
        server.shutdown()
        server.server_close()


def test_projects_list(client: Client) -> None:
    status, data = client.get("/api/ro/projects")
    assert status == 200
    assert data["projects"] == [
        {"slug": "tmp-game", "name": "Tmp Game", "doc_count": 4},
        {"slug": "docs-fixture", "name": "Docs Fixture", "doc_count": 1},
    ]


def test_tree_file_source_and_search(client: Client) -> None:
    status, tree = client.get("/api/ro/projects/tmp-game/docs")
    assert status == 200 and tree["count"] == 4
    status, doc = client.get("/api/ro/projects/tmp-game/docs/file?path=docs/index.md")
    assert status == 200 and doc["title"] == "Tmp Game" and doc["links"]
    status, doc = client.get("/api/ro/projects/tmp-game/docs/file?path=README.md")
    assert status == 200
    status, src = client.get("/api/ro/projects/tmp-game/source?path=src/main.gd&line=100&window=11")
    assert (status, src["start"], src["end"], src["total_lines"]) == (200, 95, 105, 300)
    status, found = client.get("/api/ro/projects/tmp-game/docs/search?q=ratchet&limit=2")
    assert status == 200 and len(found["hits"]) == 2 and found["truncated"] is True
    status, everywhere = client.get("/api/ro/docs/search?q=tiny&whole_word=1")
    assert status == 200 and {h["project"] for h in everywhere["hits"]} == {"docs-fixture"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/ro/projects/tmp-game/docs/file?path=../outside/secret.md",
        "/api/ro/projects/tmp-game/docs/file?path=%2e%2e%2foutside%2fsecret.md",
        "/api/ro/projects/tmp-game/docs/file?path=%252e%252e%252foutside%252fsecret.md",
        "/api/ro/projects/tmp-game/docs/file?path=/etc/passwd",
        "/api/ro/projects/tmp-game/docs/file?path=docs/evil.md",
        "/api/ro/projects/tmp-game/docs/file?path=docs/outlink/secret.md",
        "/api/ro/projects/tmp-game/docs/file?path=.git/config",
        "/api/ro/projects/tmp-game/docs/file?path=docs/index.md%00.png",
        "/api/ro/projects/tmp-game/docs/file?path=src/main.gd",
        "/api/ro/projects/docs-fixture/docs/file?path=docs/index.md",  # another project's doc
        "/api/ro/projects/tmp-game/source?path=secret_src/key.txt",
        "/api/ro/projects/tmp-game/source?path=src/evil.gd",
        "/api/ro/projects/tmp-game/source?path=.git/config",
        "/api/ro/projects/tmp-game/source?path=../outside/secret.txt",
        "/api/ro/projects/tmp-game/source?path=%2Fetc%2Fpasswd",
        "/api/ro/projects/tmp-game/source?path=src/../secret_src/key.txt",
        "/api/ro/projects/..%2F..%2Fx/docs",
        "/api/ro/projects/nope/docs",
        "/api/ro/projects/tmp-game/docs/..%2f..%2fsecret",
        "/api/ro/projects/tmp-game/nothing",
        "/api/ro/projects/tmp-game/docs/file/extra",
    ],
)
def test_traversal_and_unknowns_are_json_404(client: Client, path: str) -> None:
    status, data = client.get(path)
    assert status == 404 and list(data) == ["error"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/ro/projects/tmp-game/docs/file",
        "/api/ro/projects/tmp-game/source",
        "/api/ro/projects/tmp-game/source?path=src/main.gd&line=abc",
        "/api/ro/projects/tmp-game/source?path=src/main.gd&line=0",
        "/api/ro/projects/tmp-game/source?path=src/main.gd&window=99999",
        "/api/ro/projects/tmp-game/source?path=src/blob.bin",
        "/api/ro/projects/tmp-game/docs/search",
        "/api/ro/projects/tmp-game/docs/search?q=",
        "/api/ro/projects/tmp-game/docs/search?q=a&limit=0",
        "/api/ro/docs/search?q=a&limit=x",
    ],
)
def test_bad_arguments_are_json_400(client: Client, path: str) -> None:
    status, data = client.get(path)
    assert status == 400 and list(data) == ["error"]


def test_same_guards_and_get_only(client: Client) -> None:
    status, _ = client.raw("GET", "/api/ro/projects", {"Host": "evil.example"})
    assert status == 403
    status, _ = client.raw("GET", "/api/ro/projects", {"Origin": "http://evil.example"})
    assert status == 403
    for method in ("POST", "PUT", "DELETE"):
        assert client.raw(method, "/api/ro/projects")[0] == 405


def test_no_projects_registered_is_an_empty_list(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), handler(replace(default_config(), runs_root=tmp_path))
    )
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    ).start()
    try:
        status, body = Client(server.server_port, tmp_path).raw("GET", "/api/ro/projects")
        assert (status, json.loads(body)) == (200, {"projects": []})
    finally:
        server.shutdown()
        server.server_close()


def test_project_option_adds_files_and_dedupes(tmp_path: Path) -> None:
    config = default_config()
    second = SECOND / PROJECT_FILE_NAME
    registry = registry_for(
        config, [second, second, SECOND / ".." / "docs_fixture" / PROJECT_FILE_NAME]
    )
    assert [p.slug for p in registry.projects] == ["docs-fixture"]
    bad = tmp_path / PROJECT_FILE_NAME
    bad.write_text("{}")
    with pytest.raises(ProjectFileError, match="slug|missing"):
        registry_for(config, [bad])


def test_registry_file_projects_are_listed(tmp_path: Path) -> None:
    registry_file = RegistryFile(tmp_path / "registry.json")
    registry_file.add(SECOND / PROJECT_FILE_NAME)
    (tmp_path / "gone").mkdir()
    broken = tmp_path / "gone" / PROJECT_FILE_NAME
    broken.write_text(json.dumps({"slug": "gone", "name": "Gone"}))
    registry_file.add(broken)
    broken.unlink()  # a moved project stays in the registry with a problem; it is left out here
    config = replace(default_config(), registry_file=tmp_path / "registry.json")
    assert [p.slug for p in registry_for(config, []).projects] == ["docs-fixture"]
