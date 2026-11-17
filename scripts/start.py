"""Start the API, the read-only server and the web app together; stop them together.

    cd server && uv run python ../scripts/start.py [--host 127.0.0.1] [--api-port 8780] [--readonly-port 8781]
                                                    [--web-port 4280] [--ui DIR]

Ports come from the options, else GENSTAGE_API_PORT, GENSTAGE_READONLY_PORT, GENSTAGE_WEB_PORT else 8780, 8781, 4280. Run through ./start.sh, which does the `cd` and the environment. Each server binds
the loopback only; `--host` (for the container) is the web app's address alone. A port that is taken stops the start
with a message before anything runs.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "server"
UI = REPO / "ui" / "dist" / "generative-stage-ui" / "browser"
RESERVED = {4200, 8765, 8766, 8775, 8776}  # a live install may hold these; never default to them


def port_problem(port: int) -> str | None:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            return f"port {port} is not free ({error.strerror})"
    return None


def wait_for(url: str, process: subprocess.Popen[bytes], seconds: int = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"{url}: the server exited with code {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"{url}: no answer after {seconds}s")


def env_port(name: str, default: int) -> int:
    return int(os.environ.get(f"GENSTAGE_{name}") or default)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1", help="the web app's address (0.0.0.0 in a container)")
    parser.add_argument("--api-port", type=int, default=env_port("API_PORT", 8780))
    parser.add_argument("--readonly-port", type=int, default=env_port("READONLY_PORT", 8781))
    parser.add_argument("--web-port", type=int, default=env_port("WEB_PORT", 4280))
    parser.add_argument("--ui", type=Path, default=UI, help="the built web app")
    args = parser.parse_args()
    ports = [args.api_port, args.readonly_port, args.web_port]
    if len(set(ports)) != 3:
        raise SystemExit("The API, read-only and web ports must be three different ports")
    for port in ports:
        problem = port_problem(port)
        if problem:
            raise SystemExit(f"{problem}. Pick another with --api-port, --readonly-port or --web-port.")
    if not (args.ui / "index.html").is_file():
        raise SystemExit(f"The web app is not built ({args.ui}). Run ./install.sh first.")

    sys.path.insert(0, str(SERVER))
    from authoring.machine_config import ConfigError, load_machine_config

    try:
        runs_root = load_machine_config().runs_root
    except ConfigError as error:
        raise SystemExit(str(error)) from error
    runs_root.mkdir(parents=True, exist_ok=True)  # the read-only server refuses to start without it

    api = f"http://127.0.0.1:{args.api_port}"
    readonly = f"http://127.0.0.1:{args.readonly_port}"
    modules = [
        ("API", ["-m", "authoring.server", "--port", str(args.api_port)]),
        ("read-only server", ["-m", "authoring.readonly_server", "--port", str(args.readonly_port)]),
        ("web app", ["-m", "authoring.web_gateway", "--ui", str(args.ui), "--api", api,
                     "--readonly", readonly, "--host", args.host, "--port", str(args.web_port)]),
    ]  # fmt: skip
    children: list[subprocess.Popen[bytes]] = []

    def stop(*_: object) -> None:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()

    signal.signal(signal.SIGTERM, lambda *_: (stop(), sys.exit(0)))
    try:
        for name, arguments in modules:
            children.append(subprocess.Popen([sys.executable, *arguments], cwd=SERVER))
            probe = {
                "API": f"{api}/api/v1/projects",
                "read-only server": f"{readonly}/api/ro/health",
                "web app": f"http://127.0.0.1:{args.web_port}/",
            }[name]
            wait_for(probe, children[-1])
        print(f"\nGenerative Stage is running.\n  Open http://127.0.0.1:{args.web_port}\n"
              f"  API http://127.0.0.1:{args.api_port}/api/v1   read-only http://127.0.0.1:{args.readonly_port}/api/ro\n"
              "  Press Ctrl-C to stop.", flush=True)  # fmt: skip
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        print("A server stopped; stopping the others.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        stop()


if __name__ == "__main__":
    sys.exit(main())
