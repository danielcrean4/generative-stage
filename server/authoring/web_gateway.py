"""The web gateway: the built web app, and the two servers behind one address.

    uv run python -m authoring.web_gateway --ui ../ui/dist/generative-stage-ui/browser \
        --api http://127.0.0.1:8780 --readonly http://127.0.0.1:8781 [--host 127.0.0.1] [--port 4280]

It serves the web app's files (any path without a file gets index.html, so the app's own routes work), sends
`/api/ro/...` to the read-only server and `/api/...` to the API. Both servers check that a request names their own
address, so the gateway sends them exactly that and nothing from the browser's Host or Origin. The same check is
applied here, to the gateway's own port: a request must name 127.0.0.1 or localhost with this port, so a web page
on another site still cannot call it. With `--host 0.0.0.0` (the container) only the published port is reachable,
and the container publishes it on the host's loopback.
"""

import argparse
import http.client
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from authoring.request_guard import local_request_problem

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade", "host", "origin", "content-length",
}  # fmt: skip
READONLY_PREFIX = "/api/ro/"
API_PREFIX = "/api/"
TEXT = {"Content-Type": "text/plain; charset=utf-8"}


class GatewayServer(ThreadingHTTPServer):
    """A page opens a dozen requests at once; the default queue of 5 resets some of them."""

    request_queue_size = 128


def upstream_for(path: str, api: str, readonly: str) -> str | None:
    """The base address a path goes to, or None when it is a file of the web app."""
    if path == "/api/ro" or path.startswith(READONLY_PREFIX):
        return readonly
    if path == "/api" or path.startswith(API_PREFIX):
        return api
    return None


def file_for(root: Path, request_path: str) -> Path:
    """The file to serve for a path: the file itself when it exists inside `root`, else index.html."""
    relative = request_path.lstrip("/")
    candidate = (root / relative).resolve()
    if relative and candidate.is_file() and candidate.is_relative_to(root.resolve()):
        return candidate
    return root / "index.html"


def handler(root: Path, api: str, readonly: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # the servers behind keep their own logs

        def do_GET(self) -> None:
            self.serve("GET")

        def do_HEAD(self) -> None:
            self.serve("HEAD")

        def do_POST(self) -> None:
            self.serve("POST")

        def do_PUT(self) -> None:
            self.serve("PUT")

        def do_PATCH(self) -> None:
            self.serve("PATCH")

        def do_DELETE(self) -> None:
            self.serve("DELETE")

        def reply(self, status: int, headers: dict[str, str], body: bytes, method: str) -> None:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(body)

        def serve(self, method: str) -> None:
            port = cast(ThreadingHTTPServer, self.server).server_port
            problem = local_request_problem(self.headers, port)
            body_length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(body_length) if body_length else b""
            if problem is not None:
                self.reply(403, TEXT, problem.encode(), method)
                return
            path = urlparse(self.path).path
            target = upstream_for(path, api, readonly)
            if target is None:
                self.static(path, method)
            else:
                self.forward(method, target, body)

        def static(self, path: str, method: str) -> None:
            if method not in ("GET", "HEAD"):
                self.reply(405, TEXT, b"Method not allowed", method)
                return
            file = file_for(root, path)
            if not file.is_file():
                self.reply(404, TEXT, b"Web app not built", method)
                return
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            headers = {"Content-Type": kind, "X-Content-Type-Options": "nosniff"}
            self.reply(200, headers, file.read_bytes(), method)

        def forward(self, method: str, target: str, body: bytes) -> None:
            address = urlparse(target)
            sent = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            sent["Host"] = address.netloc
            sent["Origin"] = f"{address.scheme}://{address.netloc}"
            connection = http.client.HTTPConnection(
                address.hostname or "127.0.0.1", address.port, timeout=600
            )
            try:
                connection.request(method, self.path, body=body or None, headers=sent)
                answer = connection.getresponse()
                data = answer.read()
                headers = {k: v for k, v in answer.getheaders() if k.lower() not in HOP_BY_HOP}
                self.reply(answer.status, headers, data, method)
            except OSError as error:
                message = f"The server behind the gateway ({target}) did not answer: {error}"
                self.reply(502, TEXT, message.encode(), method)
            finally:
                connection.close()

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the web app and the servers behind one address"
    )
    parser.add_argument("--ui", type=Path, required=True, help="the built web app (has index.html)")
    parser.add_argument(
        "--api", required=True, help="the API's address, such as http://127.0.0.1:8780"
    )
    parser.add_argument("--readonly", required=True, help="the read-only server's address")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4280)
    args = parser.parse_args()
    if not (args.ui / "index.html").is_file():
        raise SystemExit(
            f"{args.ui}: no index.html here; build the web app first (cd ui && npx ng build)"
        )
    server = GatewayServer((args.host, args.port), handler(args.ui, args.api, args.readonly))
    print(f"Web app: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
