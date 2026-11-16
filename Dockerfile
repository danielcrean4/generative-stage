# Generative Stage: the demo image. Nothing in it needs a GPU or a model; every kind runs on the stand-in.
#   docker build -t generative-stage .                      the runtime image (default target)
#   docker build --target test -t generative-stage-test .   the same plus the test and lint tools (Linux checks);
#     run it with --security-opt seccomp=unconfined, as Docker's default profile blocks `unshare -rn`, which the
#     host layer's network denial and its tests use
# Base images are pinned by tag and digest. Blender is not in the image (the example project needs none).

# 1. The web app.
FROM node:24-trixie-slim@sha256:af02d57b57719b9657a45199a79264a9437940cd55b3c7b3fc99615654f124a0 AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npx ng build

# 2. Python with uv, the base of the next stages.
FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS python-base
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /usr/local/bin/uv
# procps: the GPU lock reads a process start time with `ps` (pipeline/gpu_lock.py); the slim image has none.
RUN apt-get update && apt-get install -y --no-install-recommends procps \
 && rm -rf /var/lib/apt/lists/*
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# 3. The server environment and the tools environment, pinned (server/uv.lock, pipeline/requirements.txt).
FROM python-base AS builder
COPY .python-version ./
COPY server/pyproject.toml server/uv.lock server/
RUN cd server && uv sync --locked --no-dev --no-install-project
COPY pipeline/requirements.txt pipeline/requirements.txt
RUN uv venv --python 3.13 .venv-tools \
 && uv pip install --python .venv-tools/bin/python -r pipeline/requirements.txt
COPY adapters adapters
COPY blender blender
COPY core core
COPY docs docs
COPY examples examples
COPY export export
COPY pipeline pipeline
COPY scripts scripts
COPY server server
RUN cd server && uv sync --locked --no-dev

# 4. The same with the test and lint tools, for the Linux checks.
FROM builder AS test
RUN cd server && uv sync --locked
ENV GENSTAGE_TEST_TOOLS_PYTHON=/app/.venv-tools/bin/python
CMD ["scripts/check.sh", "pipeline", "server"]

# 5. What runs: the environments, the code, the built web app, a default config, and a data volume.
FROM python-base AS runtime
RUN useradd --create-home --uid 1000 stage && mkdir /data /etc/generative-stage && chown stage /data
COPY --from=builder /app /app
COPY --from=ui /ui/dist/generative-stage-ui/browser /app/ui/dist/generative-stage-ui/browser
RUN printf '{"data_dir": "/data"}\n' > /etc/generative-stage/server.json \
 && /app/.venv-tools/bin/python /app/scripts/write_machine_config.py --file /etc/generative-stage/machine.json \
      --tools-python /app/.venv-tools/bin/python
ENV GENSTAGE_MACHINE_CONFIG=/etc/generative-stage/machine.json GENSTAGE_SERVER_CONFIG=/etc/generative-stage/server.json \
    GENSTAGE_WEB_PORT=4280
USER stage
VOLUME /data
EXPOSE 4280
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s \
  CMD ["/app/.venv-tools/bin/python", "-c", "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/v1/projects' % os.environ['GENSTAGE_WEB_PORT'], timeout=4)"]
CMD ["/app/server/.venv/bin/python", "/app/scripts/start.py", "--host", "0.0.0.0"]
