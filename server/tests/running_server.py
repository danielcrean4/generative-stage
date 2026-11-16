"""A real HTTP server over a temp workspace and a dispatcher the test drives by hand (no thread runs jobs)."""

import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from studio_test_support import stand_in_config
from test_api_v1 import Api

from authoring.jobs import Dispatcher
from authoring.server import handler
from core.registry import RegistryFile
from core.workspace import Workspace


class Running:
    """An HTTP server over a temp workspace with a dispatcher the test drives by hand."""

    def __init__(self, tmp_path: Path) -> None:
        self.config = stand_in_config(tmp_path)
        workspace = Workspace(
            RegistryFile(tmp_path / "registry.json"),
            run_exists=lambda run_id: (self.config.runs_root / run_id).is_dir(),
        )
        self.dispatcher = Dispatcher(self.config)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(self.config, workspace, self.dispatcher)
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api = Api(self.server.server_port, tmp_path)
        self.api.ok(
            "POST",
            "/api/v1/projects",
            {"folder": str(tmp_path / "sample"), "slug": "sample", "name": "Sample"},
            201,
        )
        self.project = "/api/v1/projects/sample"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def start_dispatcher(self) -> None:
        """Let a worker thread run queued jobs, as the real server does."""
        self.dispatcher.start()
