"""The world-model API (/api/v1) through HTTP, on a temporary project and registry."""

import io
import json
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from studio_test_support import default_config, stand_in_config
from trace_fixture import FIRST, RUN, SECOND, make_run

from authoring import jobs as dispatching
from authoring.job_store import JobStore
from authoring.jobs import Dispatcher
from authoring.machine_config import MachineConfig
from authoring.server import handler
from core.registry import RegistryFile
from core.workspace import Workspace

WRITE = {"Content-Type": "application/json", "X-Studio-Request": "1"}


class Api:
    def __init__(self, port: int, root: Path) -> None:
        self.port = port
        self.root = root

    def call(
        self,
        method: str,
        path: str,
        body: object = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        client = HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = None if body is None else json.dumps(body)
            sent = dict(WRITE if method != "GET" else {}) if headers is None else headers
            client.request(method, path, payload, sent)
            response = client.getresponse()
            raw = response.read()
            kind = response.getheader("Content-Type", "")
            return response.status, json.loads(raw) if "json" in kind else raw.decode()
        finally:
            client.close()

    def ok(self, method: str, path: str, body: object = None, status: int = 200) -> Any:
        got, data = self.call(method, path, body)
        assert got == status, data
        return data

    def fails(
        self, method: str, path: str, body: object, status: int, code: str, field: str | None = None
    ) -> dict[str, Any]:
        got, data = self.call(method, path, body)
        assert got == status, data
        error: dict[str, Any] = data["error"]
        assert (error["status"], error["code"]) == (status, code), error
        if field is not None:
            assert error["field"] == field, error
        assert error["message"]
        return error


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    runs = tmp_path / "runs"
    (runs / "run-1").mkdir(parents=True)
    (runs / "run-2").mkdir()
    workspace = Workspace(
        RegistryFile(tmp_path / "data" / "registry.json"),
        run_exists=lambda run_id: (runs / run_id).is_dir(),
    )
    config = replace(default_config(), runs_root=runs)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler(config, workspace),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Api(server.server_port, tmp_path)
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def project(api: Api) -> str:
    folder = str(api.root / "sample")
    api.ok("POST", "/api/v1/projects", {"folder": folder, "slug": "sample", "name": "Sample"}, 201)
    return "/api/v1/projects/sample"


def entity(api: Api, project: str, kind: str, name: str, **fields: Any) -> dict[str, Any]:
    body = {"kind": kind, "data": {"name": name, **fields}}
    created: dict[str, Any] = api.ok("POST", f"{project}/entities", body, 201)
    return created


def test_projects_create_list_open_remove(api: Api, project: str) -> None:
    listed = api.ok("GET", "/api/v1/projects")["projects"]
    assert [(p["slug"], p["name"], p["problem"]) for p in listed] == [("sample", "Sample", None)]
    detail = api.ok("GET", project)
    assert detail["folder"] == str((api.root / "sample").resolve())
    removed = api.ok("DELETE", project)
    assert removed["removed"] is True
    assert (api.root / "sample" / "studio.project.json").is_file()  # the folder is kept
    api.fails("GET", project, None, 404, "not_found")
    reopened = api.ok("POST", "/api/v1/projects", {"project_file": detail["project_file"]}, 201)
    assert reopened["slug"] == "sample"
    api.fails("POST", "/api/v1/projects", {"project_file": "relative.json"}, 422, "invalid")
    both = {"project_file": detail["project_file"], "slug": "x"}
    api.fails("POST", "/api/v1/projects", both, 422, "invalid", "/project_file")
    # A project may be called "open" (or anything else) without hiding a route.
    folder = str(api.root / "open")
    api.ok("POST", "/api/v1/projects", {"folder": folder, "slug": "open", "name": "Open"}, 201)
    assert api.ok("GET", "/api/v1/projects/open")["name"] == "Open"
    folder = str(api.root / "other")
    api.fails(
        "POST",
        "/api/v1/projects",
        {"folder": folder, "slug": "sample", "name": "X"},
        409,
        "slug_taken",
        "/slug",
    )


def test_kinds_and_link_types(api: Api, project: str) -> None:
    kinds = api.ok("GET", f"{project}/kinds")["kinds"]
    assert [k["id"] for k in kinds] == ["setting", "character", "prop", "script"]
    assert [(k["family"], k["form"]) for k in kinds] == [
        ("setting", None),
        ("character", None),
        ("prop", None),
        ("script", "linear"),
    ]
    prop = api.ok("GET", f"{project}/kinds/prop")
    assert prop["title_field"] == "name" and prop["schema"]["properties"]["brief"]
    api.fails("GET", f"{project}/kinds/vehicle", None, 404, "unknown_kind")
    types = api.ok("GET", f"{project}/link-types")["link_types"]
    assert {
        "id": "belongs_to",
        "label": "belongs to",
        "inverse_label": "owns",
        "source_kinds": ["prop"],
        "target_kinds": ["character"],
    } in types


def test_a_bad_schema_is_reported_with_its_file(api: Api, project: str) -> None:
    schema_file = api.root / "sample" / "kinds" / "setting.schema.json"
    schema_file.write_text(json.dumps({"type": "object", "properties": {"name": {"type": 5}}}))
    error = api.fails("GET", f"{project}/kinds", None, 422, "bad_schema")
    assert error["message"].startswith(f"{schema_file.resolve()}: /properties/name/type:")
    api.fails("GET", f"{project}/entities", None, 422, "bad_schema")


def test_entity_lifecycle(api: Api, project: str) -> None:
    key = entity(api, project, "prop", "Key", brief="Opens the storage room.", tags=["hall"])
    path = f"{project}/entities/{key['id']}"
    assert api.ok("GET", path) == key
    updated = api.ok(
        "PUT",
        path,
        {"revision": 1, "data": {**key["data"], "material": "steel"}, "note": "Steel, not iron"},
    )
    assert updated["revision"] == 2
    revisions = api.ok("GET", f"{path}/revisions")["revisions"]
    assert [r["note"] for r in revisions] == ["Steel, not iron", "Created"]
    assert api.ok("GET", f"{path}/revisions/1")["data"] == key["data"]
    api.fails("GET", f"{path}/revisions/x", None, 404, "revision_not_found")
    archived = api.ok("POST", f"{path}/archive", {"revision": 2})
    assert archived["archived"] is True
    assert api.ok("GET", f"{project}/entities")["entities"] == []
    assert len(api.ok("GET", f"{project}/entities?include_archived=true")["entities"]) == 1
    api.ok("POST", f"{path}/restore", {"revision": 3})
    reverted = api.ok("POST", f"{path}/revert", {"revision": 4, "to": 1})
    assert reverted["data"] == key["data"] and reverted["revision"] == 5


def test_listing_filters(api: Api, project: str) -> None:
    entity(api, project, "setting", "Hall", tags=["outdoor"])
    entity(api, project, "character", "Guide", brief="Knows the town.", tags=["outdoor"])
    entity(api, project, "prop", "Key")

    def titles(query: str) -> list[str]:
        return sorted(e["title"] for e in api.ok("GET", f"{project}/entities?{query}")["entities"])

    assert titles("kind=character") == ["Guide"]
    assert titles("tag=outdoor") == ["Guide", "Hall"]
    assert titles("q=town") == ["Guide"]
    assert titles("q=key") == ["Key"]
    api.fails("GET", f"{project}/entities?include_archived=maybe", None, 422, "invalid")
    api.fails("GET", f"{project}/entities?kind=vehicle", None, 422, "unknown_kind")


def test_invalid_entities_name_the_field(api: Api, project: str) -> None:
    url = f"{project}/entities"
    api.fails(
        "POST", url, {"kind": "prop", "data": {"brief": "x"}}, 422, "invalid_entity", "/data/name"
    )
    api.fails(
        "POST",
        url,
        {"kind": "prop", "data": {"name": "Key", "size": 3}},
        422,
        "invalid_entity",
        "/data/size",
    )
    api.fails(
        "POST", url, {"kind": "vehicle", "data": {"name": "Cart"}}, 422, "unknown_kind", "/kind"
    )
    api.fails("POST", url, {"data": {"name": "Cart"}}, 422, "invalid", "/kind")
    key = entity(api, project, "prop", "Key")
    api.fails("PUT", f"{url}/{key['id']}", {"data": {"name": "Key"}}, 422, "invalid", "/revision")
    api.fails(
        "PUT",
        f"{url}/{key['id']}",
        {"revision": 1, "data": {"name": 7}},
        422,
        "invalid_entity",
        "/data/name",
    )
    api.fails("GET", f"{url}/missing", None, 404, "entity_not_found")


def test_concurrent_updates_of_one_entity(api: Api, project: str) -> None:
    key = entity(api, project, "prop", "Key")
    path = f"{project}/entities/{key['id']}"
    statuses: list[int] = []
    failures: list[OSError] = []
    # Four writers: the standard library server's listen backlog is five, so more connections
    # can be refused under load before they reach the code under test.
    barrier = threading.Barrier(4)

    def write(n: int) -> None:
        barrier.wait()
        try:
            status, _ = api.call("PUT", path, {"revision": 1, "data": {"name": f"Key {n}"}})
            statuses.append(status)
        except OSError as exc:
            failures.append(exc)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    assert sorted(statuses) == [200] + [409] * 3
    error = api.fails(
        "PUT",
        path,
        {"revision": 1, "data": {"name": "Late"}},
        409,
        "revision_conflict",
        "/revision",
    )
    assert "revision 2" in error["message"]


def test_links(api: Api, project: str) -> None:
    hall = entity(api, project, "setting", "Hall")
    guide = entity(api, project, "character", "Guide")
    key = entity(api, project, "prop", "Key")
    links = f"{project}/links"
    lives = api.ok(
        "POST",
        links,
        {"type": "lives_in", "source": guide["id"], "target": hall["id"]},
        201,
    )
    api.ok("POST", links, {"type": "belongs_to", "source": key["id"], "target": guide["id"]}, 201)
    both = api.ok("GET", f"{project}/entities/{guide['id']}/links")["links"]
    assert sorted((link["direction"], link["label"], link["other"]["title"]) for link in both) == [
        ("in", "owns", "Key"),
        ("out", "lives in", "Hall"),
    ]
    inbound = api.ok("GET", f"{project}/entities/{hall['id']}/links?direction=in")["links"]
    assert [link["label"] for link in inbound] == ["home of"]
    assert api.ok("GET", f"{links}/{lives['id']}")["type"] == "lives_in"
    # Failure cases.
    api.fails(
        "POST",
        links,
        {"type": "lives_in", "source": guide["id"], "target": "missing"},
        404,
        "entity_not_found",
        "/target",
    )
    api.fails(
        "POST",
        links,
        {"type": "lives_in", "source": key["id"], "target": hall["id"]},
        422,
        "link_kinds",
        "/source",
    )
    api.fails(
        "POST",
        links,
        {"type": "lives_in", "source": guide["id"], "target": hall["id"]},
        409,
        "duplicate_link",
    )
    api.fails(
        "POST",
        links,
        {"type": "sails_to", "source": guide["id"], "target": hall["id"]},
        422,
        "unknown_link_type",
        "/type",
    )
    api.fails("GET", f"{project}/entities/{guide['id']}/links?direction=up", None, 422, "invalid")
    # Archiving one end hides the link until it is restored.
    api.ok("POST", f"{project}/entities/{hall['id']}/archive", {"revision": 1})
    assert len(api.ok("GET", f"{project}/entities/{guide['id']}/links")["links"]) == 1
    with_archived = f"{project}/entities/{guide['id']}/links?include_archived=true"
    assert len(api.ok("GET", with_archived)["links"]) == 2
    api.ok("DELETE", f"{links}/{lives['id']}")
    api.fails("DELETE", f"{links}/{lives['id']}", None, 404, "link_not_found")


def test_runs_and_chosen(api: Api, project: str) -> None:
    key = entity(api, project, "prop", "Key")
    base = f"{project}/entities/{key['id']}"
    api.ok("POST", f"{base}/runs", {"run_id": "run-1", "note": "first"}, 201)
    api.fails("POST", f"{base}/runs", {"run_id": "run-9"}, 404, "run_not_found", "/run_id")
    api.fails("POST", f"{base}/runs", {"run_id": "run-1"}, 409, "already_attached")
    choice = api.ok(
        "POST", f"{base}/chosen", {"run_id": "run-2", "candidate": "concept/2.png"}, 201
    )
    assert choice["slot"] == "main" and choice["entity_revision"] == 1
    assert api.ok("GET", f"{base}/chosen")["chosen"]["main"]["candidate"] == "concept/2.png"
    assert [r["run_id"] for r in api.ok("GET", f"{base}/runs")["runs"]] in (
        ["run-1", "run-2"],
        ["run-2", "run-1"],
    )
    assert len(api.ok("GET", f"{base}/choices")["choices"]) == 1
    api.fails("DELETE", f"{base}/runs/run-2", None, 409, "run_has_choice")
    api.ok("DELETE", f"{base}/runs/run-1")


def test_guards_and_malformed_requests(api: Api, project: str) -> None:
    url = f"{project}/entities"
    body = {"kind": "prop", "data": {"name": "Key"}}
    status, data = api.call("POST", url, body, {"Content-Type": "application/json"})
    assert status == 403 and data["error"]["code"] == "forbidden"
    status, data = api.call("GET", url, None, {"Host": "evil.example"})
    assert status == 403 and data["error"]["code"] == "forbidden"
    port = api.port
    status, data = api.call(
        "GET", url, None, {"Host": f"127.0.0.1:{port}", "Origin": "http://evil.example"}
    )
    assert status == 403 and data["error"]["code"] == "forbidden"
    client = HTTPConnection("127.0.0.1", port, timeout=10)
    client.request("POST", url, "{not json", WRITE)
    response = client.getresponse()
    assert response.status == 400 and json.loads(response.read())["error"]["code"] == "bad_json"
    client.close()
    api.fails("GET", "/api/v1/nothing", None, 404, "route_not_found")
    api.fails("PUT", f"{project}/kinds", {}, 405, "method_not_allowed")
    api.fails("GET", "/api/v1/projects/nobody/entities", None, 404, "not_found")


def test_a_server_without_the_world_model(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(default_config(), None))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api = Api(server.server_port, tmp_path)
        api.fails("GET", "/api/v1/projects", None, 503, "not_configured")
        status, data = api.call("GET", "/api/v1/projects", None, {"Host": "evil.example"})
        assert status == 403 and data["error"]["code"] == "forbidden"  # the guard comes first
    finally:
        server.shutdown()
        server.server_close()


def test_routes_outside_v1_are_not_found(api: Api) -> None:
    api.fails("GET", "/api/records", None, 404, "route_not_found")
    api.fails("GET", "/", None, 404, "route_not_found")


def test_exports(api: Api, project: str) -> None:
    hall = entity(api, project, "setting", "Hall", tags=["outdoor"])
    key = entity(api, project, "prop", "Key", tags=["outdoor"])
    entity(api, project, "character", "Guide")
    api.ok(
        "POST",
        f"{project}/links",
        {"type": "found_in", "source": key["id"], "target": hall["id"]},
        201,
    )
    (api.root / "runs" / "run-1" / "key.glb").write_bytes(b"glTF-key")
    api.ok(
        "POST",
        f"{project}/entities/{key['id']}/chosen",
        {"run_id": "run-1", "candidate": "key.glb"},
        201,
    )
    assert api.ok("GET", f"{project}/exports")["exports"] == []

    made = api.ok("POST", f"{project}/exports", {"tags": ["outdoor"]}, 201)
    assert (made["entities"], made["links"], made["assets"]) == (2, 1, 1)
    again = api.ok("POST", f"{project}/exports", {"tags": ["outdoor"]}, 201)
    assert again["id"] == made["id"]  # the same state and selection: the same bundle
    assert [e["id"] for e in api.ok("GET", f"{project}/exports")["exports"]] == [made["id"]]

    manifest = api.ok("GET", f"{project}/exports/{made['id']}")
    assert sorted(e["title"] for e in manifest["entities"]) == ["Hall", "Key"]
    client = HTTPConnection("127.0.0.1", api.port, timeout=10)
    client.request("GET", f"{project}/exports/{made['id']}/bundle.zip")
    response = client.getresponse()
    assert response.getheader("Content-Type") == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
        names = archive.namelist()
        assert archive.read(f"assets/prop/{key['id']}/main.glb") == b"glTF-key"
    client.close()
    assert "manifest.json" in names

    api.ok("POST", f"{project}/entities/{hall['id']}/archive", {"revision": 1})
    later = api.ok("POST", f"{project}/exports", {"since": made["id"]}, 201)
    assert later["removed"] == [hall["id"]]
    assert later["entities"] == 1  # the guide, new since the outdoor-only bundle

    api.fails("POST", f"{project}/exports", {"kinds": ["vehicle"]}, 422, "unknown_kind", "/kinds")
    api.fails("POST", f"{project}/exports", {"tags": "outdoor"}, 422, "invalid", "/tags")
    api.fails("POST", f"{project}/exports", {"colour": "red"}, 422, "invalid", "/colour")
    api.fails("POST", f"{project}/exports", {"since": "0123456789abcdef"}, 404, "export_not_found")
    api.fails("GET", f"{project}/exports/../../etc", None, 404, "route_not_found")
    api.fails("GET", f"{project}/exports/zzzz", None, 404, "export_not_found")
    api.fails("DELETE", f"{project}/exports/{made['id']}", None, 405, "method_not_allowed")


def test_starting_a_job_without_a_dispatcher_is_refused(api: Api, project: str) -> None:
    key = entity(api, project, "prop", "Key")
    jobs = f"{project}/entities/{key['id']}/jobs"
    assert api.ok("GET", jobs)["jobs"] == []
    request = {"pipeline": "concept", "prompt": "a key"}
    api.fails("POST", jobs, request, 503, "not_configured")


INSTANT = "concept"


def instant_pipeline(
    store: JobStore, job: dict[str, Any], run_id: str, job_id: str, config: MachineConfig
) -> None:
    made = config.runs_root / job_id / "concept.png"
    made.parent.mkdir(parents=True)
    made.write_bytes(b"png")
    candidate = store.add_candidate(job_id, str(made), "instant")
    store.update_run(run_id, status="succeeded", candidate_id=candidate["id"])


def test_a_job_runs_and_its_run_is_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatching, "run_pipeline_job", instant_pipeline)
    config = stand_in_config(tmp_path)
    workspace = Workspace(
        RegistryFile(tmp_path / "registry.json"),
        run_exists=lambda run_id: (config.runs_root / run_id).is_dir(),
    )
    dispatcher = Dispatcher(config)  # not started: the test runs the queue by hand
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(config, workspace, dispatcher))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api = Api(server.server_port, tmp_path)
        folder = str(tmp_path / "sample")
        api.ok(
            "POST",
            "/api/v1/projects",
            {"folder": folder, "slug": "sample", "name": "Sample"},
            201,
        )
        project = "/api/v1/projects/sample"
        key = entity(api, project, "prop", "Key")
        jobs = f"{project}/entities/{key['id']}/jobs"
        request = {"pipeline": INSTANT, "prompt": "a key", "choices": {"seed": 3}}
        started = api.ok("POST", jobs, request, 202)
        job_id = started["job"]["id"]
        assert started["job"]["entity_id"] == key["id"]
        assert [r["status"] for r in started["runs"]] == ["queued"]
        api.fails(
            "POST",
            jobs,
            {"pipeline": INSTANT, "prompt": "x", "choices": {"seed": "one"}},
            422,
            "invalid",
            "/choices/seed",
        )

        assert dispatcher.run_next(timeout=0)

        done = api.ok("GET", f"{project}/jobs/{job_id}")
        assert [r["status"] for r in done["runs"]] == ["succeeded"]
        assert [c["candidate"] for c in done["candidates"]] == ["concept.png"]
        runs = api.ok("GET", f"{project}/entities/{key['id']}/runs")["runs"]
        assert [r["run_id"] for r in runs] == [job_id]
        api.ok(
            "POST",
            f"{project}/entities/{key['id']}/chosen",
            {"run_id": job_id, "candidate": "concept.png"},
            201,
        )
        api.fails("GET", f"{project}/jobs/missing", None, 404, "job_not_found")
    finally:
        server.shutdown()
        server.server_close()


PNG = b"\x89PNG\r\n\x1a\nstand-in"


def fetch(api: Api, path: str) -> tuple[int, str, dict[str, str], bytes]:
    """A raw GET: status, content type, headers and body bytes (the Api helper decodes text)."""
    client = HTTPConnection("127.0.0.1", api.port, timeout=10)
    try:
        client.request("GET", path)
        response = client.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        return response.status, headers.get("content-type", ""), headers, response.read()
    finally:
        client.close()


def test_candidate_files_are_served_from_inside_the_run(api: Api, project: str) -> None:
    run = api.root / "runs" / "run-1"
    stage = run / "attempts" / "a1" / "concept"
    stage.mkdir(parents=True)
    (stage / "final.png").write_bytes(PNG)
    (stage / "image-validation.json").write_text(json.dumps({"passed": True}))
    (run / "key.glb").write_bytes(b"glTF-key")
    (run / "notes.exe").write_bytes(b"x")
    outside = api.root / "secret.png"
    outside.write_bytes(b"secret")
    (run / "leak.png").symlink_to(outside)
    key = entity(api, project, "prop", "Key")
    base = f"{project}/entities/{key['id']}"
    ref = "attempts/a1/concept/final.png"
    api.ok("POST", f"{base}/runs", {"run_id": "run-1"}, 201)
    api.ok("POST", f"{base}/chosen", {"run_id": "run-1", "candidate": ref}, 201)
    api.ok(
        "POST", f"{base}/chosen", {"run_id": "run-1", "candidate": "key.glb", "slot": "mesh"}, 201
    )

    status, kind, headers, body = fetch(api, f"{base}/chosen/main/file")
    assert (status, kind, body) == (200, "image/png", PNG)
    assert headers["content-disposition"].startswith("inline;")
    assert headers["x-content-type-options"] == "nosniff"
    status, kind, headers, body = fetch(api, f"{base}/chosen/mesh/file")
    assert (status, kind, body) == (200, "model/gltf-binary", b"glTF-key")
    assert headers["content-disposition"].startswith("attachment;")
    status, kind, _, body = fetch(api, f"{base}/runs/run-1/files/{ref}")
    assert (status, kind, body) == (200, "image/png", PNG)

    def refused(path: str, code: str, status: int = 404) -> None:
        got, kind, _, body = fetch(api, path)
        assert got == status and "json" in kind, body
        assert json.loads(body)["error"]["code"] == code

    refused(f"{base}/chosen/icon/file", "no_choice")
    refused(f"{base}/chosen/Main%2F..%2Ffile/file", "no_choice")
    refused(f"{base}/runs/run-1/files/attempts/a1/../../../../secret.png", "candidate_not_found")
    refused(f"{base}/runs/run-1/files/%2e%2e/secret.png", "candidate_not_found")
    refused(f"{base}/runs/run-1/files/attempts%2Fa1%2F..%2F..%2Fkey.glb", "candidate_not_found")
    refused(f"{base}/runs/run-1/files/leak.png", "candidate_not_found")  # symlink leaves the run
    refused(f"{base}/runs/run-1/files/notes.exe", "candidate_not_found")  # a type not sent
    refused(f"{base}/runs/run-1/files/missing.png", "candidate_not_found")
    refused(f"{base}/runs/run-2/files/key.glb", "run_not_attached")
    refused(f"{base}/runs/..%2F..%2Fdata/files/key.glb", "run_not_attached")
    refused(f"{project}/entities/nobody/runs/run-1/files/key.glb", "entity_not_found")
    api.fails("POST", f"{base}/chosen/main/file", {}, 405, "method_not_allowed")
    api.fails("POST", f"{base}/runs/run-1/files/key.glb", {}, 405, "method_not_allowed")


def test_a_choice_whose_file_is_gone_is_not_found(api: Api, project: str) -> None:
    key = entity(api, project, "prop", "Key")
    base = f"{project}/entities/{key['id']}"
    api.ok("POST", f"{base}/chosen", {"run_id": "run-1", "candidate": "gone.png"}, 201)
    api.fails("GET", f"{base}/chosen/main/file", None, 404, "candidate_not_found")


def test_a_runs_trace_and_the_project_statistics(api: Api, project: str) -> None:
    make_run(api.root / "runs")
    key = entity(api, project, "prop", "Key")
    base = f"{project}/entities/{key['id']}"
    api.fails("GET", f"{base}/runs/{RUN}/trace", None, 404, "run_not_attached")
    api.ok("POST", f"{base}/runs", {"run_id": RUN}, 201)
    ref = f"attempts/{FIRST}/concept/image.png"
    api.ok("POST", f"{base}/chosen", {"run_id": RUN, "candidate": ref}, 201)

    trace = api.ok("GET", f"{base}/runs/{RUN}/trace")
    assert trace["attempt_id"] == SECOND and trace["entity"]["title"] == "Key"
    assert trace["stages"][2]["status"] == "errored"
    assert trace["chosen"]["main"]["candidate"] == ref
    first = api.ok("GET", f"{base}/runs/{RUN}/trace?attempt={FIRST}")
    image = next(f for f in first["stages"][0]["files"] if f["name"] == "image.png")
    assert image["url"] == f"{base}/runs/{RUN}/files/{ref}"
    status, kind, _, body = fetch(api, image["url"])  # the URL it gives is served
    assert (status, kind) == (200, "image/png") and body.startswith(b"\x89PNG")
    api.fails("GET", f"{base}/runs/{RUN}/trace?attempt=nope", None, 404, "trace_not_found")
    api.fails("POST", f"{base}/runs/{RUN}/trace", {}, 405, "method_not_allowed")

    figures = api.ok("GET", f"{project}/statistics")
    assert figures["runs"]["total"] == 2 and figures["runs"]["errored"] == 1
    assert figures["assets"]["entities"] == 1 and figures["assets"]["chosen_slots"] == 1
    assert {s["stage"] for s in figures["by_stage"]} == {"concept", "tidy", "shape"}
    api.fails("POST", f"{project}/statistics", {}, 405, "method_not_allowed")
