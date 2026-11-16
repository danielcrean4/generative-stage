"""The read-only Studio server (port 8781): what each pipeline run did, from files on disk.

    uv run python -m authoring.readonly_server --port 8781

GET only, JSON (or the file itself), the same Host and Origin guards as the main server. Routing
only: the reading is in authoring/run_view.py (runs) and authoring/docs_view.py (project docs and
source). See docs/run_view.md and docs/docs_view.md for every route.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlparse

from authoring import run_view
from authoring.docs_view import DEFAULT_LIMIT as SEARCH_LIMIT
from authoring.docs_view import DEFAULT_WINDOW, DocsView
from authoring.machine_config import MachineConfig, load_machine_config
from authoring.request_guard import local_request_problem
from authoring.run_view import LOG_TAIL_BYTES, ROOT_STAGE, NotFound
from core.ids import SLUG
from core.project_file import ProjectFile, ProjectFileError, load_project_file
from core.registry import ProjectRegistry, RegistryFile, unique_files

DEFAULT_PORT = 8781
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
CHUNK = 1 << 20


def registry_for(config: MachineConfig, extra: list[Path]) -> ProjectRegistry[ProjectFile]:
    """The projects whose docs this server shows: every project in the registry file that loads,
    plus the --project files, each file once."""
    listed = [entry.file for entry in RegistryFile(config.registry_file).entries() if entry.project]
    return ProjectRegistry([load_project_file(f) for f in unique_files([*listed, *extra])])


def handler(
    config: MachineConfig, registry: ProjectRegistry[ProjectFile] | None = None
) -> type[BaseHTTPRequestHandler]:
    runs_root = config.runs_root
    projects = registry or ProjectRegistry[ProjectFile]([])
    docs = DocsView()

    class Handler(BaseHTTPRequestHandler):
        def common_headers(self, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")

        def send(self, status: int, data: Any, extra: dict[str, str] | None = None) -> None:
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.common_headers("application/json; charset=utf-8", len(body))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, served: run_view.ServedFile) -> None:
            start = served.size - LOG_TAIL_BYTES if served.truncated else 0
            self.send_response(200)
            self.common_headers(served.media_type, served.size - start)
            self.send_header("X-Total-Size", str(served.size))
            if served.truncated:
                self.send_header("X-Truncated", f"last {LOG_TAIL_BYTES} bytes of {served.size}")
            self.end_headers()
            with open(served.path, "rb") as file:
                file.seek(start)
                while chunk := file.read(CHUNK):
                    self.wfile.write(chunk)

        def do_GET(self) -> None:
            self.dispatch("GET")

        def do_POST(self) -> None:
            self.dispatch("POST")

        def do_PUT(self) -> None:
            self.dispatch("PUT")

        def do_DELETE(self) -> None:
            self.dispatch("DELETE")

        def do_PATCH(self) -> None:
            self.dispatch("PATCH")

        def do_HEAD(self) -> None:
            self.dispatch("HEAD")

        def do_OPTIONS(self) -> None:
            self.dispatch("OPTIONS")

        def dispatch(self, method: str) -> None:
            port = cast(ThreadingHTTPServer, self.server).server_port
            problem = local_request_problem(self.headers, port)
            if problem:
                self.send(403, {"error": problem})
            elif method != "GET":
                self.send(405, {"error": "Read-only server: GET only"}, {"Allow": "GET"})
            else:
                try:
                    self.route(urlparse(self.path))
                except NotFound as exc:
                    self.send(404, {"error": str(exc)})
                except ValueError as exc:
                    self.send(400, {"error": str(exc)})
                except run_view.BadData as exc:
                    self.send(500, {"error": str(exc)})

        def route(self, url: Any) -> None:
            parts = [unquote(p) for p in url.path.split("/")]
            if parts[:3] != ["", "api", "ro"]:
                raise NotFound("no such route")
            tail = parts[3:]
            if tail == ["health"]:
                self.send(200, {"ok": True, "runs_root": str(runs_root)})
            elif tail == ["runs"]:
                self.send(200, run_view.list_runs(runs_root, self.limit(url.query)))
            elif len(tail) == 2 and tail[0] == "runs":
                self.send(200, run_view.get_run(runs_root, tail[1]))
            elif len(tail) == 4 and tail[0] == "runs" and tail[2] == "attempts":
                self.send(200, run_view.get_attempt(runs_root, tail[1], tail[3]))
            elif (
                len(tail) >= 5
                and tail[0] == "runs"
                and tail[2] == "attempts"
                and tail[4] == "files"
            ):
                if len(tail) < 7:
                    raise NotFound("no such route")
                self.send_file(
                    run_view.find_file(runs_root, tail[1], tail[3], tail[5], "/".join(tail[6:]))
                )
            elif (
                len(tail) == 5
                and tail[0] == "runs"
                and tail[2] == "files"
                and tail[3] == ROOT_STAGE
            ):
                self.send_file(run_view.find_root_file(runs_root, tail[1], tail[4]))
            elif tail[:1] == ["projects"] or tail[:2] == ["docs", "search"]:
                self.route_docs(tail, url.query)
            else:
                raise NotFound("no such route")

        def route_docs(self, tail: list[str], query: str) -> None:
            params = parse_qs(query)
            if tail == ["docs", "search"]:
                self.send(200, docs.search(projects.projects, *self.search_args(params)))
            elif tail == ["projects"]:
                self.send(200, {"projects": [self.summary(p) for p in projects.projects]})
            elif len(tail) >= 3 and tail[2] == "docs" and SLUG.fullmatch(tail[1]):
                project = self.project(tail[1])
                if len(tail) == 3:
                    self.send(200, docs.list_docs(project))
                elif tail[3:] == ["file"]:
                    self.send(200, docs.read_doc(project, self.required(params, "path")))
                elif tail[3:] == ["search"]:
                    self.send(200, docs.search([project], *self.search_args(params)))
                else:
                    raise NotFound("no such route")
            elif len(tail) == 3 and tail[2] == "source" and SLUG.fullmatch(tail[1]):
                line = params.get("line", [None])[0]
                window = params.get("window", [str(DEFAULT_WINDOW)])[0]
                self.send(
                    200,
                    docs.read_source(
                        self.project(tail[1]),
                        self.required(params, "path"),
                        None if line is None else self.whole(line, "line"),
                        self.whole(window, "window"),
                    ),
                )
            else:
                raise NotFound("no such route")

        def project(self, slug: str) -> ProjectFile:
            try:
                return projects.get(slug)
            except ProjectFileError:
                raise NotFound("no such project") from None

        def summary(self, project: ProjectFile) -> dict[str, Any]:
            return {
                "slug": project.slug,
                "name": project.name,
                "doc_count": docs.doc_count(project),
            }

        @staticmethod
        def required(params: dict[str, list[str]], name: str) -> str:
            if name not in params:
                raise ValueError(f"{name} is required")
            return params[name][0]

        @staticmethod
        def whole(raw: str, name: str) -> int:
            if not raw.isdigit():
                raise ValueError(f"{name} must be a whole number")
            return int(raw)

        def search_args(self, params: dict[str, list[str]]) -> tuple[str, bool, int]:
            word = params.get("whole_word", ["0"])[0] in {"1", "true"}
            limit = self.whole(params.get("limit", [str(SEARCH_LIMIT)])[0], "limit")
            return self.required(params, "q"), word, limit

        def limit(self, query: str) -> int:
            raw = parse_qs(query).get("limit", [str(DEFAULT_LIMIT)])[0]
            if not raw.isdigit() or not 1 <= int(raw) <= MAX_LIMIT:
                raise ValueError(f"limit must be a whole number from 1 to {MAX_LIMIT}")
            return int(raw)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only view of pipeline runs")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--project",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help="a studio.project.json whose docs to show as well (repeatable)",
    )
    args = parser.parse_args()
    config = load_machine_config()
    try:
        registry = registry_for(config, args.project)
    except ProjectFileError as error:
        raise SystemExit(str(error)) from error
    if not config.runs_root.is_dir():
        raise SystemExit(f"{config.source}: key 'runs_root': {config.runs_root} is not a folder")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(config, registry))
    print(f"Read-only run view: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
