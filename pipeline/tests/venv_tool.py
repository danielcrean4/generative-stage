"""Helpers for tests that run a tool under the tools interpreter (numpy, scipy, trimesh, Pillow).

The interpreter is the one named by env GENSTAGE_TEST_TOOLS_PYTHON, else the machine setting tools_python, else the
interpreter running the tests (scripts/check.sh runs them under .venv-tools, which ./install.sh makes). No model is
involved; a missing package is a failure that says what to install, never a skip.
"""
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import machine


def interpreter():
    """The tools interpreter: numpy, scipy, trimesh, Pillow and fast-simplification (pipeline/requirements.txt)."""
    named = os.environ.get("GENSTAGE_TEST_TOOLS_PYTHON")
    return Path(named) if named else machine.tools_python()


_checked = {}


def require_venv(test):
    """Fail (never skip) when the tools interpreter is missing or lacks the packages of pipeline/requirements.txt."""
    python = interpreter()
    if python not in _checked:
        found = python.is_file() and subprocess.run(
            [str(python), "-I", "-c", "import numpy, scipy, trimesh, PIL, fast_simplification"],
            capture_output=True, timeout=120).returncode == 0
        _checked[python] = found
    if not _checked[python]:
        raise AssertionError(f"the tools interpreter {python} is missing or lacks pipeline/requirements.txt: run "
                             f"./install.sh, or set GENSTAGE_TEST_TOOLS_PYTHON or the machine setting tools_python")


def run_tool(script, *args):
    return subprocess.run([str(interpreter()), "-I", str(TOOLS / script), *map(str, args)],
                          capture_output=True, text=True, timeout=300)


def run_code(code, *args):
    """Run a snippet under the venv interpreter (sys.argv[1:] are args); returns its stdout."""
    result = subprocess.run([str(interpreter()), "-I", "-c", code, *map(str, args)],
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


DISC_CODE = """
import sys
from PIL import Image, ImageDraw
out, size, fill, *discs = sys.argv[1:]
size = int(size)
image = Image.new("RGB", (size, size), (255, 255, 255))
draw = ImageDraw.Draw(image)
for i in range(0, len(discs), 3):
    cx, cy, r = map(float, discs[i:i + 3])
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(int(fill),) * 3)
image.save(out)
"""


def write_discs(path, size, discs, fill=40):
    """White square image with dark discs given as (cx, cy, radius)."""
    run_code(DISC_CODE, path, size, fill, *[v for disc in discs for v in disc])


def needs_gate_meshes(test):
    """Kept as a marker for the tests that read tests/fixtures/gates/; the fixtures ship, so nothing is skipped."""
    return test
