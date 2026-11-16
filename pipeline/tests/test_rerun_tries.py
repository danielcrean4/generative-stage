"""pipeline/rerun_tries.py: saved tries through the finishing chain, tabulated (docs/gate_v2.md, "Real tries, first run").

One synthetic try (the cabinet fixture saved in the layout of a recorded attempt) is run end to end; the
face budget in the mapping must reach the scratch config, results.json/results.csv/contact page must exist,
and a bad mapping or index is a usage error naming the file and key. Probes run under the tools interpreter.
"""
import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import venv_tool

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "pipelines" / "examples"
FIXTURES = ROOT / "tests" / "fixtures" / "gates"


class RerunTriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        folder = self.root / "runs" / "run-a" / "attempts" / "attempt-b" / "mesh" / "try-0"
        folder.mkdir(parents=True)
        shutil.copy(FIXTURES / "cabinet.glb", folder / "mesh.glb")
        shutil.copy(FIXTURES / "cabinet.png", folder / "mesh.input.png")
        (folder / "mesh-validation.json").write_text(json.dumps({"passed": True, "reasons": []}))
        self.index = self.root / "index.json"
        self.index.write_text(json.dumps([[0, str(folder / "mesh-validation.json"), True]]))
        self.mapping = {"configs": {"prop": str(EXAMPLES / "finish.prop.json")}, "face_budget": 5000, "tries": {"0": "prop"},
                        "contact": {"per_page": 8, "columns": 2, "scale": 0.5}}
        self.out = self.root / "out"

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, mapping=None):
        path = self.root / "mapping.json"
        path.write_text(json.dumps(mapping or self.mapping))
        return venv_tool.run_tool("rerun_tries.py", self.index, path, self.out)

    @venv_tool.needs_gate_meshes
    def test_one_try_end_to_end(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads((self.out / "results.json").read_text())
        self.assertEqual([r["n"] for r in rows], [0])
        row = rows[0]
        self.assertEqual((row["run"], row["attempt"], row["try"], row["kind"]), ("run-a", "attempt-b", "try-0", "prop"))
        self.assertTrue(row["v1_passed"])
        self.assertIn(row["v2_verdict"], ("pass", "review", "fail"))
        self.assertLessEqual(row["after"]["faces"], 5000, "the mapping's face_budget must reach the chain")
        scratch = json.loads((self.out / "configs" / "finish.prop.json").read_text())
        self.assertEqual(scratch["contract"]["face_budget"], 5000)
        self.assertTrue((self.out / "00" / "gate" / "review-sheet.png").is_file())
        self.assertTrue((self.out / "contact_00.png").is_file())
        with open(self.out / "results.csv", newline="") as handle:
            line = next(csv.DictReader(handle))
        self.assertEqual(line["n"], "0")
        self.assertIn("aspect_error", line)
        self.assertIn("aspect_error_margin", line)

    @venv_tool.needs_gate_meshes
    def test_bad_mapping_is_a_usage_error_naming_the_key(self):
        broken = {**self.mapping, "tries": {"0": "shoe"}}
        result = self.run_tool(broken)
        self.assertEqual(result.returncode, 2)
        self.assertIn("tries.0", result.stderr)
        self.assertFalse((self.out / "results.json").exists())

    @venv_tool.needs_gate_meshes
    def test_index_with_a_gap_is_a_usage_error(self):
        self.index.write_text(json.dumps([[1, "x/attempts/a/mesh/try-0/mesh-validation.json", True]]))
        result = self.run_tool()
        self.assertEqual(result.returncode, 2)
        self.assertIn("index.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
