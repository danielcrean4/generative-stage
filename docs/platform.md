# Platforms, install and the image

## What is supported

| Platform | Status |
|---|---|
| macOS (Apple Silicon) | tested: install, start, the checks and the browser specs |
| Linux | tested on arm64 in a container: the Linux checks pass and the image runs the demo; amd64 is what the CI workflow runs and has not been run yet |
| Windows | untested; use Docker (`docker compose up`) or WSL |

The install and the demo need no model, no GPU and no game. Every stage runs on the stand-in adapters
([adapters](adapters.md)). No model ships. An adapter you add for a model of your own says in its `requires` what it
needs (`apple_silicon`, `cuda`, ...); on a computer without that it is listed as not runnable and a stage that names it
stops with the reason.

## Install

`./install.sh` needs [uv](https://docs.astral.sh/uv/) and Node.js 22.22.3 or newer (or 24.15 and newer, or 26 and up).
Python 3.13 is the pinned version (`.python-version`); uv fetches it if the computer has none. The script:

1. checks those and says what to do when one is missing or too old;
2. makes the server environment from `server/uv.lock` (exact versions; `--dev` adds the test, lint and type tools);
3. makes the tools environment `.venv-tools` from `pipeline/requirements.txt` (exact versions of numpy, scipy,
   trimesh, Pillow and fast-simplification, which the deterministic image and mesh stages use);
4. installs the web app from `ui/package-lock.json` and builds it;
5. writes the default machine config, only if there is none, and lists the adapters it finds.

It is safe to run again. The machine config is the file named by `GENSTAGE_MACHINE_CONFIG`, else
`~/.config/generative-stage/machine.json` ([machine settings](machine_settings.md)). The script never changes a file
that is already there.

## Run

`./start.sh` starts three programs and stops them together on Ctrl-C:

| Program | Default port | Variable | What it is |
|---|---|---|---|
| web app | 4280 | `GENSTAGE_WEB_PORT` | the web app, and the two servers below behind one address (`authoring/web_gateway.py`) |
| API | 8780 | `GENSTAGE_API_PORT` | the world-model API ([API](api.md)); the MCP server talks to this |
| read-only server | 8781 | `GENSTAGE_READONLY_PORT` | what each pipeline run did, read from files |

Each binds the loopback address only, and each refuses a request that does not name its own address, so a web page
on another site cannot call them. If a port is taken, the start stops and says which. The defaults avoid 4200 and
8765 to 8776, which another copy of this tool may hold. Where the data lives is the server's machine
config ([configuration](../server/docs/configuration.md)): `data_dir`, by default `~/.local/share/generative-stage`.

To use a model of your own, edit the machine config (see [Integrating a model](adapters.md)): add an adapter entry and name it in
`defaults`, then rerun a pipeline. To drive it from an agent, see [MCP](mcp.md); give it the API port above.

`scripts/smoke.py <address>` checks a running install along the walkthrough: the page loads, both servers answer,
the adapters listed are the stand-ins, a copy of the example project loads under its own slug (`smoke-test`, unregistered at the end, so the example itself can still be loaded), a prop run on the stand-in
succeeds, its trace shows every stage, a concept image and a 3D model can be chosen, the statistics count the run and an
export bundle holds the model. With `--mcp-python server/.venv/bin/python` it also does the briefs, links, a run and the
trace through the MCP server.

## Docker

    docker compose up          # then open http://127.0.0.1:4280

One image, built in stages: the web app is built with Node, then a slim Python image holds the server, the tools
environment, the stand-in adapters and the built web app. The versions are pinned: base images by tag and digest, uv
by tag and digest, Python packages by `uv.lock` and `pipeline/requirements.txt`, web packages by the lock file. Blender
is not in the image. The page is published on this computer's loopback only; data is in the volume `data`
(`/data` in the container). The container runs as an ordinary user and needs no extra permissions.

The port inside must equal the port outside, because the servers check the address a request names. To change it:
`GENSTAGE_WEB_PORT=4390 docker compose up`. To use another machine config, mount your file over
`/etc/generative-stage/machine.json` (an example line is in `compose.yaml`).

The image is built for the architecture of the machine that builds it.

## Checks on Linux

The `test` stage of the same Dockerfile adds the test, lint and type tools:

    docker build --target test -t generative-stage-test .
    docker run --rm --security-opt seccomp=unconfined generative-stage-test

It runs the pipeline and server parts of `scripts/check.sh`. `seccomp=unconfined` is needed only here: Docker's default
profile blocks `unshare -rn`, which the host layer ([adapters](adapters.md), the `network_denied` requirement) uses on
Linux to deny a stage the network, and the tests that prove the denial need it. The demo does not need it, since the
stand-in adapters run with the network allowed.

## Continuous integration

`.github/workflows/ci.yml` runs the install, the checks, the scripted MCP walkthrough, the browser specs and a smoke
test on Linux and macOS. `.github/workflows/docker.yml` builds the image, runs the compose demo with the smoke test, and
runs the Linux checks in the image. Both are started by hand (`workflow_dispatch`); add `pull_request` or `push` to their `on:` blocks to run them on
every change.
