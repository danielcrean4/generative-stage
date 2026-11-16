"""Smoke test of a running install: the same steps against a native start, a container or CI.

    python3 scripts/smoke.py http://127.0.0.1:4280 --folder /data/smoke

The address is the web gateway's. `--folder` is where the test project is made, as the server sees it (it must be
missing or empty); the default is a new temporary folder, right for a server on this computer. Checks, in order:
the web page loads, the API and the read-only server answer, the adapters listed are the stand-ins; then the README
walkthrough on a copy of the example project under its own slug (SMOKE_SLUG, so the example itself can still be loaded
afterwards; the copy is unregistered at the end, pass or fail, and its folder is left as it is): load it, a prop run on the stand-in with a concept image and a mesh, its trace,
choosing both, the statistics, and an export bundle. With `--mcp-python PY` it also walks briefs, links, a run and the
trace through the MCP server. Standard library only (the MCP part runs in the server environment). Exit 0 when all pass.
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_example  # noqa: E402

STANDINS = {"standin-image", "standin-mesh", "standin-text", "standin-review"}
SMOKE_SLUG = "smoke-test"


class Smoke:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.passed = 0

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "X-Studio-Request": "1"}
        request = urllib.request.Request(self.base + path, data, headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as answer:
                return answer.status, answer.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def json(self, method: str, path: str, body: Any = None, want: int = 200) -> Any:
        status, data = self.call(method, path, body)
        if status != want:
            raise SystemExit(f"FAIL {method} {path}: {status} {data[:300]!r}")
        return json.loads(data)

    def ok(self, what: str) -> None:
        self.passed += 1
        print(f"ok   {what}", flush=True)


def wait_until_ready(smoke: Smoke, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if smoke.call("GET", "/api/v1/projects")[0] == 200:
                return
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f"FAIL {smoke.base}: no answer from /api/v1/projects after {seconds}s")
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("base", help="the web gateway's address, such as http://127.0.0.1:4280")
    parser.add_argument("--folder", help="where to make the test project (default: a temporary folder)")
    parser.add_argument("--wait", type=int, default=60, help="seconds to wait for the server to answer")
    parser.add_argument("--mcp-python", help="the server environment's python (server/.venv/bin/python): also walks steps 3 to 5 through the MCP server")
    args = parser.parse_args()
    smoke = Smoke(args.base)
    wait_until_ready(smoke, args.wait)
    smoke.ok("API answers: GET /api/v1/projects")

    status, page = smoke.call("GET", "/")
    if status != 200 or b"<app-root" not in page:
        raise SystemExit(f"FAIL web page: {status}, no <app-root> in the page")
    smoke.ok("web page loads")
    status, page = smoke.call("GET", "/projects")
    if status != 200 or b"<app-root" not in page:
        raise SystemExit("FAIL web app route /projects does not fall back to the page")
    smoke.ok("web app route loads")

    health = smoke.json("GET", "/api/ro/health")
    if health.get("ok") is not True:
        raise SystemExit(f"FAIL read-only server health: {health}")
    smoke.ok("read-only server answers: GET /api/ro/health")

    adapters = smoke.json("GET", "/api/v1/adapters")["adapters"]
    ids = {a["id"] for a in adapters}
    defaults = {a["id"] for a in adapters if a["default"]}
    if not STANDINS <= ids or not {"standin-image", "standin-mesh"} <= defaults:
        raise SystemExit(f"FAIL adapters: expected the stand-ins as defaults, got {sorted(ids)} / {sorted(defaults)}")
    if not all(a["runnable"] for a in adapters if a["id"] in STANDINS):
        raise SystemExit("FAIL adapters: a stand-in is not runnable on this computer")
    smoke.ok(f"adapters listed: {', '.join(sorted(ids))}; stand-ins are the defaults and runnable")

    folder = Path(args.folder) if args.folder else Path(tempfile.mkdtemp(prefix="gs-smoke-")) / SMOKE_SLUG
    made: list[str] = []
    try:
        walkthrough(smoke, args, folder, made)
    finally:
        for slug in made:  # unregister what the smoke made; the folders stay, as with any removed project
            smoke.call("DELETE", f"/api/v1/projects/{slug}")
    print(f"smoke: {smoke.passed} checks passed")
    return 0


def walkthrough(smoke: Smoke, args: argparse.Namespace, folder: Path, made: list[str]) -> None:
    """The README walkthrough on a copy of the example; each project registered is added to MADE."""
    if any(p["slug"] == SMOKE_SLUG for p in smoke.json("GET", "/api/v1/projects")["projects"]):
        smoke.call("DELETE", f"/api/v1/projects/{SMOKE_SLUG}")  # left by a run that was killed
    slug, said = load_example.load(smoke.base, folder, SMOKE_SLUG, "Smoke test (copy of the example)")
    made.append(slug)
    project = f"/api/v1/projects/{slug}"
    records = smoke.json("GET", f"{project}/entities")["entities"]
    by_name = {r["data"]["name"]: r for r in records}
    if {r["kind"] for r in records} != {"setting", "character", "prop", "script"} or "Brass Signal Lantern" not in by_name:
        raise SystemExit(f"FAIL example project: unexpected records {sorted(by_name)}")
    lantern = by_name["Brass Signal Lantern"]
    links = smoke.json("GET", f"{project}/entities/{lantern['id']}/links")["links"]
    if sorted(link["type"] for link in links) != ["belongs_to", "found_in"]:
        raise SystemExit(f"FAIL example project: the lantern's links are {links}")
    smoke.ok(f"example project: {len(records)} records, the lantern linked to its keeper and its place ({said.split(':')[0]})")

    job = smoke.json(
        "POST", f"{project}/entities/{lantern['id']}/jobs",
        {"pipeline": "prop", "prompt": lantern["data"]["brief"], "adapters": {"image": "standin-image", "image-to-mesh": "standin-mesh"},
         "choices": {"seed": 7}},
        202,
    )  # fmt: skip
    job_id = job["job"]["id"]
    deadline = time.monotonic() + 180
    while True:
        done = smoke.json("GET", f"{project}/jobs/{job_id}")
        status = done["runs"][0]["status"]
        if status in ("succeeded", "failed"):
            break
        if time.monotonic() > deadline:
            raise SystemExit("FAIL prop run did not finish in 180s")
        time.sleep(0.5)
    if status != "succeeded":
        raise SystemExit(f"FAIL prop run {status}: {done['runs'][0]['log_tail']}")
    names = [c["candidate"] for c in done["candidates"]]
    concept = next((n for n in names if n.endswith("concept/image.png")), None)
    mesh = next((n for n in names if n.startswith("final/")), None)
    if not concept or not mesh:
        raise SystemExit(f"FAIL prop run candidates: {names}")
    smoke.ok("prop run on the stand-in succeeded: concept image and mesh made")

    trace = smoke.json("GET", f"{project}/entities/{lantern['id']}/runs/{job_id}/trace")
    stages = {s["id"]: s["status"] for s in trace["stages"]}
    if stages.get("concept") != "completed" or stages.get("mesh") != "completed":
        raise SystemExit(f"FAIL trace stages: {stages}")
    smoke.ok(f"trace shows every stage ({', '.join(stages)}) with its status")

    entity = f"{project}/entities/{lantern['id']}"
    smoke.json("POST", f"{entity}/chosen", {"run_id": job_id, "candidate": concept}, 201)
    smoke.json("POST", f"{entity}/chosen", {"run_id": job_id, "candidate": mesh, "slot": "mesh"}, 201)
    if set(smoke.json("GET", f"{entity}/chosen")["chosen"]) != {"main", "mesh"}:
        raise SystemExit("FAIL choosing: the image and the 3D model are not both chosen")
    smoke.ok("a concept image and a 3D model chosen for the lantern")

    stats = smoke.json("GET", f"{project}/statistics")
    if stats["runs"]["completed"] < 1 or stats["runs"]["errored"] != 0 or stats["assets"]["chosen_slots"] < 2 or not stats["by_stage"]:
        raise SystemExit(f"FAIL statistics: {stats}")
    smoke.ok(f"statistics: {stats['runs']['completed']} completed, {stats['runs']['errored']} errored, {stats['assets']['candidates']} candidates, by day and by stage")

    exported = smoke.json("POST", f"{project}/exports", {}, 201)
    if exported["entities"] != len(records) or exported["links"] != 5 or exported["assets"] != 2:
        raise SystemExit(f"FAIL export: {exported}")
    status, archive = smoke.call("GET", f"{project}/exports/{exported['id']}/bundle.zip")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        members = bundle.namelist()
        manifest = json.loads(bundle.read("manifest.json"))
    if status != 200 or manifest["format"] not in ("generative-stage-bundle", "dramatis-fabrica-bundle") or not any(m.endswith(".glb") for m in members):
        raise SystemExit(f"FAIL export bundle: {status} {members}")
    smoke.ok(f"export bundle {exported['id']}: manifest and {sum(m.endswith('.glb') for m in members)} glTF model, {exported['links']} links")

    if args.mcp_python:
        throwaway = "smoke-mcp-" + str(int(time.time()))
        smoke.json("POST", "/api/v1/projects", {"folder": str(folder.parent / throwaway), "slug": throwaway, "name": "Smoke MCP"}, 201)
        made.append(throwaway)
        # abspath, not resolve(): a venv's python is a symlink to the base interpreter, which has no `mcp`
        result = subprocess.run(
            [os.path.abspath(args.mcp_python), str(Path(__file__).with_name("smoke_mcp.py")), smoke.base, throwaway],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1] / "server", timeout=300,
        )  # fmt: skip
        if result.returncode != 0:
            raise SystemExit(f"FAIL MCP walkthrough:\n{result.stdout}\n{result.stderr}")
        for line in result.stdout.splitlines():
            smoke.ok(line)


if __name__ == "__main__":
    sys.exit(main())
