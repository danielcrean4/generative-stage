#!/usr/bin/env bash
# One-command install for macOS and Linux. Safe to run again.
#   ./install.sh            server, tools environment, web app, default machine config
#   ./install.sh --dev      also the test, lint and type-check tools of the server
set -euo pipefail
cd "$(dirname "$0")"
DEV=""
for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done
PYTHON_VERSION="$(cat .python-version)"
fail() { echo "ERROR: $*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) fail "Only macOS and Linux are supported (this is $(uname -s))." ;;
esac

# Prerequisites, each with what to do about it.
command -v uv >/dev/null || fail "uv is not installed. Install it (https://docs.astral.sh/uv/getting-started/installation/), then run this again."
command -v node >/dev/null || fail "Node.js is not installed. Install Node 22.22.3 or newer (24.15 or newer, or 26+, also work), then run this again."
command -v npm >/dev/null || fail "npm is not installed (it comes with Node.js)."
node -e '
  const [a, b, c] = process.versions.node.split(".").map(Number);
  const ok = a >= 26 || (a === 24 && (b > 15 || (b === 15 && c >= 0))) || (a === 22 && (b > 22 || (b === 22 && c >= 3)));
  process.exit(ok ? 0 : 1);' || fail "Node $(node -v) is too old. The web app needs 22.22.3 or newer, 24.15 or newer, or 26+."
echo "Using uv $(uv --version | cut -d' ' -f2), node $(node -v), Python $PYTHON_VERSION (uv fetches it if this computer has none)."

echo "== Server environment"
SYNC=(uv sync --locked --python "$PYTHON_VERSION")
[ -n "$DEV" ] || SYNC+=(--no-dev)
(cd server && "${SYNC[@]}")

echo "== Tools environment (the deterministic image and mesh stages, pinned in pipeline/requirements.txt)"
uv venv --quiet --allow-existing --python "$PYTHON_VERSION" .venv-tools
uv pip install --quiet --python .venv-tools/bin/python -r pipeline/requirements.txt
.venv-tools/bin/python -I -c "import numpy, scipy, trimesh, PIL, fast_simplification" \
  || fail "The tools environment (.venv-tools) is missing a package after install."

echo "== Web app"
(cd ui && npm ci --no-audit --no-fund && npx ng build)

echo "== Machine config"
.venv-tools/bin/python scripts/write_machine_config.py --tools-python .venv-tools/bin/python
.venv-tools/bin/python -I pipeline/adapter_config.py check

cat <<DONE

Installed. Start it with:

    ./start.sh

then open http://127.0.0.1:${GENSTAGE_WEB_PORT:-4280}  (API ${GENSTAGE_API_PORT:-8780}, read-only ${GENSTAGE_READONLY_PORT:-8781}).
DONE
