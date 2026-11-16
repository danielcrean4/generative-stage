"""The local HTTP server: the world-model API under /api/v1 (api_v1.py) and nothing else.

    uv run python -m authoring.server [--port 8780]

Binds 127.0.0.1 only. The machine config (machine_config.py) names the registry of projects, the
runs root and the forge; the dispatcher that runs jobs always starts. A job that needs the forge fails
when it runs if the forge is not there, and says which setting to fix.
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from authoring import api_v1
from authoring.job_store import FILE_NAME as JOBS_FILE
from authoring.job_store import JobStore
from authoring.jobs import Dispatcher
from authoring.machine_config import ConfigError, MachineConfig, load_machine_config
from authoring.replies import FileBody
from authoring.run_view import run_exists
from core.registry import RegistryFile
from core.workspace import Workspace


class ApiServer(ThreadingHTTPServer):
    """A page opens a dozen requests at once; the default queue of 5 resets some of them."""

    request_queue_size = 128


def handler(
    config: MachineConfig,
    world: Workspace | None,
    dispatcher: Dispatcher | None = None,
) -> type[BaseHTTPRequestHandler]:
    """The request handler: every request goes to api_v1; anything outside /api/v1 is a 404."""
    services = api_v1.Services(world, config, dispatcher) if world is not None else None

    class Handler(BaseHTTPRequestHandler):
        def send(self, status: int, data: Any) -> None:
            if isinstance(data, FileBody):
                body, content_type = data.data, data.media_type
            else:
                body = json.dumps(data, ensure_ascii=False).encode()
                content_type = "application/json; charset=utf-8"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if isinstance(data, FileBody):
                how = "inline" if data.inline else "attachment"
                self.send_header("Content-Disposition", f'{how}; filename="{data.filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self.dispatch("GET")

        def do_POST(self) -> None:
            self.dispatch("POST")

        def do_PUT(self) -> None:
            self.dispatch("PUT")

        def do_PATCH(self) -> None:
            self.dispatch("PATCH")

        def do_DELETE(self) -> None:
            self.dispatch("DELETE")

        def dispatch(self, method: str) -> None:
            if not api_v1.is_v1(urlparse(self.path).path):
                self.send(*api_v1.error(404, "route_not_found", "no such route"))
                return
            port = cast(ThreadingHTTPServer, self.server).server_port
            self.send(
                *api_v1.handle(services, method, self.path, self.headers, self.rfile.read, port)
            )

    return Handler


def fail_orphaned_runs(workspace: Workspace) -> int:
    """At start: runs a dead server left queued or running, in every registered project that
    has a job store, are marked failed. Returns how many."""
    marked = 0
    for project in workspace.projects():
        if project["problem"] is None and (Path(project["folder"]) / JOBS_FILE).is_file():
            marked += JobStore.for_project(Path(project["folder"])).fail_orphaned_runs()
    return marked


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the world-model API on 127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()
    try:
        config = load_machine_config()
    except ConfigError as error:
        raise SystemExit(str(error)) from error
    for note in config.notes:
        print(note, file=sys.stderr, flush=True)
    runs_root = config.runs_root
    world = Workspace(
        RegistryFile(config.registry_file), run_exists=lambda run_id: run_exists(runs_root, run_id)
    )
    orphaned = fail_orphaned_runs(world)
    if orphaned:
        print(f"Marked {orphaned} orphaned run(s) from a previous server as failed", flush=True)
    dispatcher = Dispatcher(config)
    dispatcher.start()
    server = ApiServer(("127.0.0.1", args.port), handler(config, world, dispatcher))
    print(f"Serving http://127.0.0.1:{server.server_port}/api/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
