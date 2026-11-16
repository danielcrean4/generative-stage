"""Pins what the mesh gate does today on known-bad meshes (docs/gate_v2.md).

Each fixture is mutated into every variant in gate_mutants.MUTANTS and sent through the real
`mesh_gates.py` CLI. tests/fixtures/gates/expected_v1.json says which verdict and which measures
decided each case. A case that passes the gate but should not is a "known_gap", still pinned, so
a stricter gate shows up as a table change. GATE_MUTANTS_REGENERATE=1 rewrites the table.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import venv_tool

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "gates"
EXPECTED = FIXTURES / "expected_v1.json"

CONTROL = "original"
# measure -> (threshold name, direction): the same four rules as mesh_gates.evaluate
RULES = {"largest_piece_share": ("min_largest_piece_share", "below"),
         "silhouette_iou": ("min_silhouette_iou", "below"),
         "thin_sheet_share": ("max_thin_sheet_share", "above"),
         "silhouette_excess": ("max_silhouette_excess", "above")}
LIST_CODE = """
import sys
sys.path.insert(0, sys.argv[1])
import gate_mutants
print("\\n".join(gate_mutants.MUTANTS))
"""
BUILD_CODE = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import gate_mutants
gate_mutants.write_all(Path(sys.argv[2]), Path(sys.argv[3]))
"""


def margins(report):
    """Distance from each threshold; negative means the measure broke it."""
    out = {}
    for name, (limit_name, direction) in RULES.items():
        value, limit = report["measures"][name], report["thresholds"][limit_name]
        out[name] = round(value - limit if direction == "below" else limit - value, 4)
    return out


def deciding(report):
    """The measures that failed, or the single "could not measure" marker."""
    if report["measures"] is None:
        return ["could not measure"]
    return sorted(name for name, margin in margins(report).items() if margin < 0)


class GateMutantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.fixtures = sorted(p.stem for p in FIXTURES.glob("*.glb"))
        cls.expected = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else {}
        cls.regenerate = bool(os.environ.get("GATE_MUTANTS_REGENERATE"))
        cls.mutants = venv_tool.run_code(LIST_CODE, HERE).split()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_gate(self, mesh, image, out):
        result = venv_tool.run_tool("mesh_gates.py", mesh, image, "--out", out)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return json.loads(out.read_text())

    def observe(self, fixture):
        """Run the gate on the fixture and every mutant of it; returns {name: report}."""
        folder = self.root / fixture
        venv_tool.run_code(BUILD_CODE, HERE, FIXTURES / f"{fixture}.glb", folder)
        image = FIXTURES / f"{fixture}.png"
        reports = {CONTROL: self.run_gate(FIXTURES / f"{fixture}.glb", image, folder / f"{CONTROL}.json")}
        for name in self.mutants:
            reports[name] = self.run_gate(folder / f"{name}.glb", image, folder / f"{name}.json")
        return reports

    @venv_tool.needs_gate_meshes
    def test_every_mutant_matches_the_table(self):
        self.assertTrue(self.fixtures, "no fixtures found")
        table, problems = {}, []
        for fixture in self.fixtures:
            reports = self.observe(fixture)
            table[fixture] = {}
            for name, report in reports.items():
                verdict = "pass" if report["passed"] else "fail"
                by = deciding(report)
                note = ""
                if report["measures"]:
                    note = " ".join(f"{m}={report['measures'][m]}({v:+.4f})" for m, v in margins(report).items())
                print(f"  {fixture:8} {name:11} {verdict} {','.join(by) or '-':32} {note}")
                entry = {"verdict": verdict, "decided_by": by}
                old = self.expected.get(fixture, {}).get(name, {})
                if name != CONTROL and verdict == "pass":
                    entry["known_gap"] = True
                    entry["reason"] = old.get("reason", "TODO: say why the gate cannot see this")
                table[fixture][name] = entry
                want = self.expected.get(fixture, {}).get(name)
                if not self.regenerate and (want is None or (want["verdict"], want["decided_by"]) != (verdict, by)):
                    problems.append(f"{fixture}/{name}: gate says {verdict} {by}, table says {want}")
        if self.regenerate:
            EXPECTED.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
            print(f"wrote {EXPECTED}")
        mutants = [(f, n) for f in table for n in table[f] if n != CONTROL]
        gaps = sum(1 for f, n in mutants if table[f][n].get("known_gap"))
        print(f"GATE_MUTANTS fixtures={len(table)} mutants={len(mutants)} caught={len(mutants) - gaps} known_gaps={gaps}")
        self.assertEqual(problems, [], "\n".join(problems))
        for fixture, cases in table.items():
            self.assertEqual(cases[CONTROL]["verdict"], "pass", f"{fixture}: the unmodified fixture must pass")


if __name__ == "__main__":
    unittest.main()
