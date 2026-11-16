"""The finishing chain on the gate fixtures (docs/gate_v2.md "Finishing chain", docs/gate_v2.md).

Every fixture and each of its nine mutants goes through the real `mesh_finish.py` command
(normalize_mesh, decimate_mesh, then the v2 gate) with the example config for its kind, and
tests/fixtures/gates/expected_finish.json says what came out: verdict, the measures that decided it
with their margins, and pieces and faces before and after. Counts and verdicts must match exactly;
margins within MARGIN_TOLERANCE (they are floats from a camera search). GATE_MUTANTS_REGENERATE=1
rewrites the table. The spec's required outcomes (Acceptance item 1) are printed, not asserted.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import venv_tool
from test_gate_mutants import BUILD_CODE, CONTROL, LIST_CODE
from test_gate_mutants_v2 import EXIT_BY_VERDICT, REQUIRED, REQUIRED_THIN, deciding

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "gates"
EXAMPLES = HERE.parent / "pipelines" / "examples"
EXPECTED = FIXTURES / "expected_finish.json"
FIXTURE_CONFIG = {"cabinet": "finish.prop.json", "head": "finish.head.json", "tool": "finish.thin.json"}
MARGIN_TOLERANCE = 0.005   # margins are floats from a camera search; counts and verdicts are exact
REPAIRED = ("scatter", "scaled_3x", "subdivided")   # must come out with the original's measures
MEASURE_TOLERANCE = 0.03   # how far a repaired mutant's ratio measures may sit from the original's
RATIOS = ("silhouette_iou", "aspect_error", "deficit", "excess", "depth_ratio", "thin_sheet_share")


class MeshFinishTests(unittest.TestCase):
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

    def finish(self, label, mesh, image, config, out):
        start = time.monotonic()
        result = venv_tool.run_tool("mesh_finish.py", mesh, image, out, "--config", config)
        self.slowest = max(self.slowest, (time.monotonic() - start, label))
        finished = json.loads((out / "finish.json").read_text())
        self.assertEqual(result.returncode, EXIT_BY_VERDICT[finished["verdict"]], result.stderr)
        return finished, json.loads((out / "gate" / "mesh-validation.json").read_text())

    def observe(self, fixture):
        folder = self.root / fixture
        venv_tool.run_code(BUILD_CODE, HERE, FIXTURES / f"{fixture}.glb", folder)
        image, config = FIXTURES / f"{fixture}.png", EXAMPLES / FIXTURE_CONFIG[fixture]
        runs = {CONTROL: self.finish(f"{fixture}/{CONTROL}", FIXTURES / f"{fixture}.glb", image, config,
                                     folder / "out" / CONTROL)}
        for name in self.mutants:
            runs[name] = self.finish(f"{fixture}/{name}", folder / f"{name}.glb", image, config, folder / "out" / name)
        return runs

    @venv_tool.needs_gate_meshes
    def test_every_case_matches_the_table(self):
        self.assertEqual(set(self.fixtures), set(FIXTURE_CONFIG), "every fixture needs an example config")
        table, problems, unmet, differences = {}, [], [], []
        for fixture in self.fixtures:
            table[fixture], originals = {}, None
            for name, (finished, report) in self.observe(fixture).items():
                measures = report["measures"]
                by = deciding(report)
                entry = {"verdict": finished["verdict"], "decided_by": by,
                         "margins": {m: measures[m]["margin"] for m in by if m in (measures or {})},
                         "pieces": [finished["before"]["pieces"], finished["after"]["pieces"]],
                         "faces": [finished["before"]["faces"], finished["after"]["faces"]]}
                table[fixture][name] = entry
                values = {m: v["value"] for m, v in (measures or {}).items()}
                if name == CONTROL:
                    originals = values
                print(f"  {fixture:8} {name:11} {entry['verdict']:6} {','.join(by) or '-':32} "
                      f"pieces {entry['pieces'][0]}->{entry['pieces'][1]} faces {entry['faces'][0]}->{entry['faces'][1]} "
                      + " ".join(f"{m}={values[m]}" for m in RATIOS if m in values))
                want = self.expected.get(fixture, {}).get(name)
                if not self.regenerate:
                    if want is None:
                        problems.append(f"{fixture}/{name}: not in the table")
                    else:
                        for key in ("verdict", "decided_by", "pieces", "faces"):
                            if want[key] != entry[key]:
                                problems.append(f"{fixture}/{name}: {key} is {entry[key]}, table says {want[key]}")
                        for m, margin in entry["margins"].items():
                            if abs(margin - want["margins"].get(m, 99)) > MARGIN_TOLERANCE:
                                problems.append(f"{fixture}/{name}: {m} margin {margin}, table says {want['margins'].get(m)}")
                required = (REQUIRED_THIN if fixture == "tool" else {}).get(name, REQUIRED.get(name))
                if required and entry["verdict"] not in required:
                    unmet.append(f"{fixture}/{name}={entry['verdict']} (spec wants {'/'.join(sorted(required))})")
                if name in REPAIRED and originals and values:
                    gaps = {m: round(values[m] - originals[m], 4) for m in RATIOS}
                    off = {m: g for m, g in gaps.items() if abs(g) > MEASURE_TOLERANCE}
                    differences.append(f"{fixture}/{name} max|diff|={max(abs(g) for g in gaps.values()):.4f}")
                    if off:
                        unmet.append(f"{fixture}/{name} measures differ from the original by more than "
                                     f"{MEASURE_TOLERANCE}: {off}")
        if self.regenerate:
            EXPECTED.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
            print(f"wrote {EXPECTED}")
        counts = {v: sum(1 for f in table.values() for e in f.values() if e["verdict"] == v) for v in EXIT_BY_VERDICT}
        print("MESH_FINISH_REPAIRED " + "; ".join(differences))
        print(f"MESH_FINISH fixtures={len(table)} cases={sum(counts.values())} pass={counts['pass']} "
              f"review={counts['review']} fail={counts['fail']} spec_unmet={len(unmet)}")
        print(f"MESH_FINISH_TIME slowest={self.slowest[1]} seconds={self.slowest[0]:.1f}")
        print("MESH_FINISH_UNMET " + ("; ".join(unmet) or "none"))
        self.assertEqual(problems, [], "\n".join(problems))


class MeshFinishConfigTests(unittest.TestCase):
    """Usage and config errors exit 2, write nothing, and name the file and key."""

    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.good = json.loads((EXAMPLES / "finish.prop.json").read_text())

    def tearDown(self):
        self.temp.cleanup()

    def run_with(self, config):
        path = self.root / "finish.json.in"
        path.write_text(json.dumps(config))
        out = self.root / "out"
        result = venv_tool.run_tool("mesh_finish.py", FIXTURES / "cabinet.glb", FIXTURES / "cabinet.png", out,
                                    "--config", path)
        self.assertFalse(out.exists(), "a config error must write nothing")
        return result

    def test_missing_unknown_and_invalid_keys_name_the_file_and_key(self):
        cases = []
        for where, key in (("contract", "face_budget"), ("contract", "target_size"), ("clean_mesh", "orientation"),
                           ("clean_mesh", "small_piece_area_share"), ("decimate", "preserve_topology"),
                           ("gate", "max_deficit"), ("capture", "background")):
            broken = json.loads(json.dumps(self.good))
            del broken[where][key]
            cases.append((broken, f"missing key {where}.{key}"))
        broken = json.loads(json.dumps(self.good))
        broken["gate"]["face_budget"] = 5
        cases.append((broken, "unknown key gate.face_budget"))
        broken = json.loads(json.dumps(self.good))
        broken["contract"]["face_budget"] = 0
        cases.append((broken, "contract.face_budget"))
        broken = json.loads(json.dumps(self.good))
        broken["contract"]["front_axis"] = "-z"
        cases.append((broken, "disagree with clean_mesh.orientation"))
        broken = json.loads(json.dumps(self.good))
        del broken["gate"]
        cases.append((broken, "missing key config.gate"))
        for config, message in cases:
            result = self.run_with(config)
            self.assertEqual(result.returncode, 2, message)
            self.assertIn("finish.json.in", result.stderr)
            self.assertIn(message, result.stderr)

    def test_missing_input_is_a_usage_error(self):
        path = self.root / "ok.json"
        path.write_text(json.dumps(self.good))
        result = venv_tool.run_tool("mesh_finish.py", self.root / "none.glb", FIXTURES / "cabinet.png",
                                    self.root / "out", "--config", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("none.glb", result.stderr)


if __name__ == "__main__":
    unittest.main()
