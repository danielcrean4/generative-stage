"""The review sheet (pipeline/review_sheet.py) and its place in the finishing chain (docs/gate_v2.md "Review sheet").

mesh_finish.py writes gate/review-sheet.png for every verdict and lists it in finish.json; review_sheet.py
rebuilds it from a finish folder; the `review_sheet` config block is validated in one place and a missing,
unknown or invalid key is an error naming the file and key. Probes run under the tools interpreter.
"""
import json
import tempfile
import unittest
from pathlib import Path

import venv_tool

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "pipelines" / "examples"
FIXTURES = ROOT / "tests" / "fixtures" / "gates"
PIXEL_CODE = """
import sys
from PIL import Image
image = Image.open(sys.argv[1])
print(image.width, image.height)
"""
EARLY_STOP_CODE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import review_sheet
config, axes = review_sheet.load_config(sys.argv[2])
finish = {"verdict": "fail", "passed": False, "reasons": ["could not finish: bad mesh"], "before": None, "after": None, "outputs": {}}
sheet = review_sheet.build(sys.argv[3], None, finish, None, axes, config)
sheet.save(sys.argv[4])
"""


class ReviewSheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.out = cls.root / "out"
        cls.result = venv_tool.run_tool("mesh_finish.py", FIXTURES / "cabinet.glb", FIXTURES / "cabinet.png", cls.out,
                                        "--config", EXAMPLES / "finish.prop.json")
        cls.config = json.loads((EXAMPLES / "finish.prop.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @venv_tool.needs_gate_meshes
    def test_chain_writes_the_sheet_and_lists_it(self):
        finished = json.loads((self.out / "finish.json").read_text())
        self.assertEqual(finished["outputs"]["review_sheet"], "gate/review-sheet.png")
        sheet = self.out / finished["outputs"]["review_sheet"]
        self.assertTrue(sheet.is_file())
        render = self.config["review_sheet"]["render"]
        width, height = map(int, venv_tool.run_code(PIXEL_CODE, sheet).split())
        pad, gap = self.config["review_sheet"]["padding"], self.config["review_sheet"]["gap"]
        self.assertEqual(width, 2 * pad + 5 * render["size"] + 4 * gap)     # concept + four views
        self.assertGreater(height, pad + render["size"])                   # with text underneath

    @venv_tool.needs_gate_meshes
    def test_cli_rebuilds_the_sheet_from_the_finish_folder(self):
        target = self.root / "again.png"
        result = venv_tool.run_tool("review_sheet.py", self.out, FIXTURES / "cabinet.png", target,
                                    "--config", EXAMPLES / "finish.prop.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes(), (self.out / "gate" / "review-sheet.png").read_bytes(),
                         "the same inputs must give the same sheet")

    @venv_tool.needs_gate_meshes
    def test_a_chain_that_stopped_early_still_gets_a_sheet(self):
        target = self.root / "early.png"
        venv_tool.run_code(EARLY_STOP_CODE, ROOT, EXAMPLES / "finish.prop.json", FIXTURES / "cabinet.png", target)
        self.assertTrue(target.is_file())

    def test_config_errors_name_the_file_and_key(self):
        cases = []
        for key in ("gap", "font_size", "verdict_colours", "render"):
            broken = json.loads(json.dumps(self.config))
            del broken["review_sheet"][key]
            cases.append((broken, f"missing key review_sheet.{key}"))
        broken = json.loads(json.dumps(self.config))
        del broken["review_sheet"]["render"]["light"]
        cases.append((broken, "review_sheet.render missing key light"))
        broken = json.loads(json.dumps(self.config))
        broken["review_sheet"]["colour"] = [1, 2, 3]
        cases.append((broken, "unknown key review_sheet.colour"))
        broken = json.loads(json.dumps(self.config))
        broken["review_sheet"]["text"] = [1, 2]
        cases.append((broken, "review_sheet.text"))
        broken = json.loads(json.dumps(self.config))
        del broken["review_sheet"]
        cases.append((broken, "missing key config.review_sheet"))
        for config, message in cases:
            path = self.root / "bad.json"
            path.write_text(json.dumps(config))
            out = self.root / "bad_out"
            result = venv_tool.run_tool("mesh_finish.py", FIXTURES / "cabinet.glb", FIXTURES / "cabinet.png", out,
                                        "--config", path)
            self.assertEqual(result.returncode, 2, message)
            self.assertIn("bad.json", result.stderr)
            self.assertIn(message, result.stderr)
            self.assertFalse(out.exists(), "a config error must write nothing")


if __name__ == "__main__":
    unittest.main()
