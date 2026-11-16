"""The v2 column of the mutant table (docs/gate_v2.md, docs/gate_v2.md "Acceptance" item 1).

Same mechanism as test_gate_mutants.py: each fixture and each of its mutants goes through the real
`mesh_gates.py --profile v2` command (no normaliser runs first in this slice), and
tests/fixtures/gates/expected_v2.json says which verdict and which measures decided it. Any
difference fails the test. GATE_MUTANTS_REGENERATE=1 rewrites the table. Each fixture uses the
example config for its kind (FIXTURE_CONFIG). The spec's required outcomes are printed beside the
result as information; they are not asserted, because the normalisers that repair some mutants
are not part of this slice.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import venv_tool
from test_gate_mutants import BUILD_CODE, CONTROL, LIST_CODE

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "gates"
EXAMPLES = HERE.parent / "pipelines" / "examples"
EXPECTED = FIXTURES / "expected_v2.json"
FIXTURE_CONFIG = {"cabinet": "gate_v2.prop.json", "head": "gate_v2.head.json", "tool": "gate_v2.thin.json"}
EXIT_BY_VERDICT = {"pass": 0, "fail": 1, "review": 3}
# docs/gate_v2.md Acceptance item 1: what each mutant should end as once the normalisers have run
REQUIRED = {"box": {"fail"}, "cut_33": {"fail"}, "cut_20": {"fail", "review"}, "on_side": {"fail", "review"},
            "relief_15": {"fail"}, "scatter": {"pass"}, "scaled_3x": {"pass"}, "subdivided": {"pass"}, CONTROL: {"pass"}}
REQUIRED_THIN = {"relief_15": {"fail", "review"}}


def deciding(report):
    """Names of the measures (and markers) that stopped the verdict being a plain pass."""
    if report["measures"] is None:
        return ["could not measure"]
    names = [name for name, m in report["measures"].items() if m["outcome"] != "pass"]
    if not report["camera"]["complete"]:
        names.append("camera_search")
    return sorted(names)


class GateMutantV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.fixtures = sorted(p.stem for p in FIXTURES.glob("*.glb"))
        cls.expected = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else {}
        cls.regenerate = bool(os.environ.get("GATE_MUTANTS_REGENERATE"))
        cls.mutants = venv_tool.run_code(LIST_CODE, HERE).split()
        cls.slowest = (0.0, "")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_gate(self, label, mesh, image, config, out):
        start = time.monotonic()
        result = venv_tool.run_tool("mesh_gates.py", mesh, image, "--out", out, "--profile", "v2", "--gate", config)
        seconds = time.monotonic() - start
        self.slowest = max(self.slowest, (seconds, label))
        report = json.loads(out.read_text())
        self.assertEqual(result.returncode, EXIT_BY_VERDICT[report["verdict"]], result.stderr)
        return report

    def observe(self, fixture):
        folder = self.root / fixture
        venv_tool.run_code(BUILD_CODE, HERE, FIXTURES / f"{fixture}.glb", folder)
        image, config = FIXTURES / f"{fixture}.png", EXAMPLES / FIXTURE_CONFIG[fixture]
        reports = {CONTROL: self.run_gate(f"{fixture}/{CONTROL}", FIXTURES / f"{fixture}.glb", image, config,
                                          folder / f"{CONTROL}.json")}
        for name in self.mutants:
            reports[name] = self.run_gate(f"{fixture}/{name}", folder / f"{name}.glb", image, config, folder / f"{name}.json")
        return reports

    @venv_tool.needs_gate_meshes
    def test_every_mutant_matches_the_table(self):
        self.assertTrue(self.fixtures, "no fixtures found")
        self.assertEqual(set(self.fixtures), set(FIXTURE_CONFIG), "every fixture needs an example config")
        table, problems, unmet = {}, [], []
        for fixture in self.fixtures:
            table[fixture] = {}
            for name, report in self.observe(fixture).items():
                verdict, by = report["verdict"], deciding(report)
                note = ""
                if report["measures"]:
                    note = " ".join(f"{m}={v['value']}({v['margin']:+.4f})" for m, v in report["measures"].items()
                                    if m in ("silhouette_iou", "aspect_error", "deficit", "excess", "depth_ratio",
                                             "orientation_gain"))
                print(f"  {fixture:8} {name:11} {verdict:6} {','.join(by) or '-':30} {note}")
                entry = {"verdict": verdict, "decided_by": by}
                old = self.expected.get(fixture, {}).get(name, {})
                if verdict == "pass" and name != CONTROL:
                    entry["known_gap"] = True
                    entry["reason"] = old.get("reason", "TODO: say why the gate cannot see this")
                table[fixture][name] = entry
                want = self.expected.get(fixture, {}).get(name)
                if not self.regenerate and (want is None or (want["verdict"], want["decided_by"]) != (verdict, by)):
                    problems.append(f"{fixture}/{name}: gate says {verdict} {by}, table says {want}")
                required = (REQUIRED_THIN if fixture == "tool" else {}).get(name, REQUIRED.get(name))
                if required and verdict not in required:
                    unmet.append(f"{fixture}/{name}={verdict} (spec wants {'/'.join(sorted(required))})")
        if self.regenerate:
            EXPECTED.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
            print(f"wrote {EXPECTED}")
        counts = {v: sum(1 for f in table.values() for e in f.values() if e["verdict"] == v) for v in EXIT_BY_VERDICT}
        print(f"GATE_V2 fixtures={len(table)} cases={sum(counts.values())} pass={counts['pass']} "
              f"review={counts['review']} fail={counts['fail']}")
        print(f"GATE_V2_TIME slowest={self.slowest[1]} seconds={self.slowest[0]:.1f} (acceptance item 3: under 20)")
        print("GATE_V2_ACCEPTANCE_UNMET " + ("; ".join(unmet) or "none"))
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertLess(self.slowest[0], 20, "acceptance item 3: under 20 seconds per mesh")
        for fixture, cases in table.items():
            self.assertNotEqual(cases[CONTROL]["verdict"], "fail", f"{fixture}: the unmodified fixture must not fail")


if __name__ == "__main__":
    unittest.main()
