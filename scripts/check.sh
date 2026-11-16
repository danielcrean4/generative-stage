#!/usr/bin/env bash
# The checks, one part per argument (default: all but e2e). CI, the container and a developer run the same lines.
#   scripts/check.sh [pipeline] [server] [ui] [e2e] [all]
# Needs ./install.sh --dev first. The pipeline part uses a scratch machine config naming the tools environment. The server part uses the tools environment so the stand-in walkthroughs run
# rather than skip. The e2e part needs a browser: npx playwright install chromium.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
export GENSTAGE_TEST_TOOLS_PYTHON="${GENSTAGE_TEST_TOOLS_PYTHON:-$ROOT/.venv-tools/bin/python}"
parts=("$@"); [ ${#parts[@]} -gt 0 ] || parts=(pipeline server ui)
[ "${parts[0]}" != all ] || parts=(pipeline server ui e2e)
for part in "${parts[@]}"; do
  echo "=== $part"
  case "$part" in
    pipeline)
      # The pipeline tests run under the tools environment and read a scratch machine config naming it (stand-ins
      # only, no model), so this computer's own machine config is not used.
      scratch="$(mktemp -d)"
      printf '{"tools_python": "%s"}\n' "$ROOT/.venv-tools/bin/python" > "$scratch/machine.json"
      GENSTAGE_MACHINE_CONFIG="$scratch/machine.json" "$ROOT/.venv-tools/bin/python" -m unittest discover -s pipeline/tests
      rm -rf "$scratch" ;;
    server)
      cd "$ROOT/server"
      uv run --no-sync ruff check . ../core ../export
      uv run --no-sync mypy
      uv run --no-sync pytest -q -rs ;;
    ui)
      cd "$ROOT/ui"
      npx ng test --watch=false
      npx ng build
      npm run test:node ;;
    e2e) cd "$ROOT/ui" && npm run e2e:world ;;
    *) echo "Unknown part: $part" >&2; exit 2 ;;
  esac
  cd "$ROOT"
done
