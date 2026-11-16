#!/bin/sh
# Runs every check: the unit tests, then a headless build of the examples into a temp folder
# that must produce every .glb, build record and contact sheet, then the example motion clips
# (every one passing its checks) and their filmstrips. Prints OK at the end.
#
# No model and no GPU: every model stage runs on the stand-in adapters. The tests run under the tools
# environment (.venv-tools, made by ./install.sh; or set GENSTAGE_TEST_TOOLS_PYTHON) with a scratch machine config,
# so this computer's own machine config is not read. Needs Blender on PATH for the build steps.
set -eu
cd "$(dirname "$0")/.."
python="${GENSTAGE_TEST_TOOLS_PYTHON:-$PWD/.venv-tools/bin/python}"
[ -x "$python" ] || { echo "no tools environment at $python: run ./install.sh first" >&2; exit 1; }
scratch="$(mktemp -d)"
printf '{"tools_python": "%s"}\n' "$python" > "$scratch/machine.json"
GENSTAGE_MACHINE_CONFIG="$scratch/machine.json" GENSTAGE_TEST_TOOLS_PYTHON="$python" \
  "$python" -m unittest discover -s pipeline/tests -q
rm -rf "$scratch"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
blender --background --factory-startup --python blender/build.py -- \
    --families blender/examples/families --manifest blender/examples/manifest.json \
    --palette blender/palettes/garden.json --out "$out" > "$out/log.txt" 2>&1 \
    || { cat "$out/log.txt"; exit 1; }
python3 - "$out" blender/examples/manifest.json <<'PY'
import json, sys
from pathlib import Path
out, manifest = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
for family, entry in manifest.items():
    glbs = sorted((out / family).glob("*.glb"))
    assert len(glbs) == entry["variants"], f"{family}: {len(glbs)} of {entry['variants']} .glb files"
    assert (out / family / "build.json").exists(), f"{family}: no build.json"
    assert (out / "previews" / f"{family}.png").exists(), f"{family}: no contact sheet"
PY
python3 blender/build_motions.py --motions blender/motions --manifest blender/examples/motion_manifest.json \
    --out "$out/motions" > "$out/motions.log" 2>&1 || { cat "$out/motions.log"; exit 1; }
blender --background --factory-startup --python blender/filmstrip_motions.py -- \
    --clips "$out/motions" --manifest blender/examples/motion_manifest.json --out "$out/filmstrips" \
    >> "$out/log.txt" 2>&1 || { cat "$out/log.txt"; exit 1; }
python3 - "$out" blender/examples/motion_manifest.json <<'PY'
import json, sys
from pathlib import Path
out, manifest = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
for rig in manifest["rigs"]:
    assert (out / "filmstrips" / f"{rig}.png").exists(), f"{rig}: no filmstrip"
PY
if grep -E "Traceback|Error" "$out/log.txt"; then exit 1; fi
echo OK
