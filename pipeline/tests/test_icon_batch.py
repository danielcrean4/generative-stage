"""icon_batch.py without a model: the job checks, the background removal and the missing-setting errors. It runs under the
tools interpreter (it imports Pillow) like the tool itself."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import venv_tool  # noqa: E402

TOOL = HERE.parent / "icon_batch.py"
PREPARE_CODE = """
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, sys.argv[1])
import icon_batch
raw, out = Path(sys.argv[2]), Path(sys.argv[3])
image = Image.new("RGB", (300, 300), (255, 0, 255))
for x in range(100, 200):
    for y in range(80, 220):
        image.putpixel((x, y), (30, 160, 60))
image.save(raw)
icon_batch.prepare(raw, out)
result = Image.open(out)
print(result.size, result.mode, result.getpixel((0, 0))[3], result.getpixel((128, 128))[3])
"""


class IconBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)

    def run_tool(self, *args, env=None):
        return subprocess.run([str(venv_tool.interpreter()), "-I", str(TOOL), *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})}, timeout=120)

    def test_validate_only_lists_the_outputs_without_touching_a_model(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs = json.dumps([{"prompt": "a hand drill", "output": str(Path(temp) / "drill.png")}])
            result = self.run_tool("--validate-only", "--jobs-json", jobs)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["validated"], 1)

    def test_bad_jobs_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            for jobs in ([], [{"prompt": " ", "output": str(Path(temp) / "a.png")}], [{"prompt": "x", "output": "relative.png"}],
                         [{"prompt": "x", "output": str(Path(temp) / "a.png")}] * 2):
                with self.subTest(jobs=jobs):
                    self.assertNotEqual(self.run_tool("--validate-only", "--jobs-json", json.dumps(jobs)).returncode, 0)

    def test_a_run_without_machine_settings_names_the_missing_setting(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "machine.json"
            config.write_text("{}")
            jobs = json.dumps([{"prompt": "a hand drill", "output": str(Path(temp) / "drill.png")}])
            result = self.run_tool("--jobs-json", jobs, env={"GENSTAGE_MACHINE_CONFIG": str(config)})
            self.assertEqual(result.returncode, 2)
            self.assertIn("icon_dir", result.stderr)

    def test_the_magenta_key_is_removed_and_the_icon_is_fitted_to_a_transparent_square(self):
        with tempfile.TemporaryDirectory() as temp:
            result = venv_tool.run_code(PREPARE_CODE, HERE.parent, Path(temp) / "raw.png", Path(temp) / "icon.png")
            self.assertEqual(result.strip(), "(256, 256) RGBA 0 255")   # corner transparent, centre opaque


if __name__ == "__main__":
    unittest.main()
