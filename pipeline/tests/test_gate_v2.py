"""Unit tests of the v2 mesh gate (pipeline/gate_v2.py, gate_v2_config.py, mesh_gates.py --profile v2).

Meshes are synthetic boxes whose right answers are known by construction. The code under test
needs numpy and trimesh, so every probe runs under the tools interpreter (tests/venv_tool.py).
"""
import json
import tempfile
import unittest
from pathlib import Path

import venv_tool

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "pipelines" / "examples"
TOOLS = str(ROOT)
HEADER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import numpy as np, trimesh
import gate_v2, gate_v2_config

def raw_config(**gate):
    base = {"profile": "v2", "thin": False, "min_silhouette_iou": 0.6, "max_deficit": 0.15, "max_excess": 0.15,
            "max_aspect_error": 0.15, "min_depth_ratio": 0.25, "max_thin_sheet_share": 0.2, "max_pieces": 1,
            "review_margin": 0.05, "orientation_margin": 0.1, "search_seconds": 10}
    return {"gate": {**base, **gate}, "capture": {"view": {"camera": {"yaw": [0, 0, 1], "elevation": [0, 0, 1]}}},
            "frame": {"drop_axis": 2, "transpose": False, "flip_x": False, "flip_y": True}, "face_budget": 100}

def config(**gate):
    return gate_v2_config.parse(raw_config(**gate), "test.json")

def rect(width, height, pad=20):
    mask = np.zeros((height + 2 * pad, width + 2 * pad), bool)
    mask[pad:pad + height, pad:pad + width] = True
    return mask

def box(extents, at=(0, 0, 0)):
    return trimesh.creation.box(extents=extents, transform=trimesh.transformations.translation_matrix(at))

def measures(mesh, subject, **gate):
    return gate_v2.measure(mesh, subject, config(**gate))["measures"]
"""
GOOD = """
good = {"silhouette_iou": 0.9, "aspect_error": 0.0, "deficit": 0.0, "excess": 0.0, "depth_ratio": 1.0,
        "thin_sheet_share": 0.0, "pieces": 1, "faces": 50, "orientation_gain": -0.5}
"""


def probe(body, *args):
    """Run BODY after HEADER under the venv interpreter; BODY must set `result` to a JSON value."""
    return json.loads(venv_tool.run_code(HEADER + body + "\nprint(json.dumps(result))", TOOLS, *args))


class VenvTestCase(unittest.TestCase):
    def setUp(self):
        venv_tool.require_venv(self)


class MeasureTests(VenvTestCase):
    def test_box_against_matching_rectangle(self):
        m = probe("result = measures(box((2, 3, 1)), rect(200, 300))")
        self.assertGreater(m["silhouette_iou"], 0.95)
        self.assertLess(m["deficit"], 0.03)
        self.assertLess(m["excess"], 0.03)
        self.assertLess(m["aspect_error"], 0.02)
        self.assertAlmostEqual(m["depth_ratio"], 0.5, places=3)  # depth 1 over the smaller of 2 and 3, by hand
        self.assertEqual((m["pieces"], m["faces"]), (1, 12))

    def test_top_third_removed_shows_as_deficit_and_aspect_error(self):
        # the 2x3 subject against a mesh 2 wide and 2 tall (its top third missing) standing on the same floor
        m = probe("result = measures(box((2, 2, 1), at=(0, -0.5, 0)), rect(200, 300))")
        self.assertAlmostEqual(m["deficit"], 1 / 3, delta=0.03)
        self.assertLess(m["excess"], 0.03)
        # mesh 2:2 = 1.0 against subject 2:3 = 0.6667: |1 - 0.6667| / 0.6667 = 0.5
        self.assertAlmostEqual(m["aspect_error"], 0.5, delta=0.02)

    def test_thin_plate_has_low_depth_ratio(self):
        m = probe("result = measures(box((3, 3, 0.3)), rect(300, 300))")
        self.assertAlmostEqual(m["depth_ratio"], 0.1, places=3)

    def test_two_separate_boxes_are_two_pieces(self):
        m = probe("result = measures(trimesh.util.concatenate([box((1, 1, 1), (-2, 0, 0)), box((1, 1, 1), (2, 0, 0))]),"
                  " rect(500, 100))")
        self.assertEqual(m["pieces"], 2)

    def test_positive_elevation_raises_the_camera(self):
        # the top of an upright mesh turns toward the viewer (third column) when the camera rises
        top = probe("result = gate_v2.project([[0, 1, 0]], config()['frame'], 0, 30)[0].tolist()")
        self.assertAlmostEqual(top[1], 0.866, places=3)
        self.assertAlmostEqual(top[2], 0.5, places=3)

    def test_camera_range_of_zero_is_the_single_conventional_view(self):
        out = probe("""
mesh, subject = box((2, 3, 1)), rect(200, 300)
cfg = config()
found = gate_v2.measure(mesh, subject, cfg)["camera"]
target, _ = gate_v2.subject_outline(subject)
direct = gate_v2.register(target, gate_v2.outline(mesh.vertices, mesh.faces, cfg["frame"], 0, 0)[0])["iou"]
result = {"camera": found, "direct": direct, "values": gate_v2.range_values([-30, 30, 15]), "zero": gate_v2.range_values([0, 0, 1])}
""")
        camera = out["camera"]
        self.assertEqual((camera["yaw"], camera["elevation"], camera["tried"], camera["total"]), (0, 0, 1, 1))
        self.assertAlmostEqual(camera["score"], out["direct"], places=9)
        self.assertEqual(out["values"], [-30, -15, 0, 15, 30])
        self.assertEqual(out["zero"], [0])

    def test_search_stops_at_the_time_limit_with_the_conventional_pose_first(self):
        out = probe("""
ticks = iter(range(100))
raw = raw_config()
raw["capture"]["view"]["camera"] = {"yaw": [-30, 30, 15], "elevation": [-30, 0, 10]}
cfg = gate_v2_config.parse(raw, "t.json")
target, _ = gate_v2.subject_outline(rect(200, 300))
mesh = box((2, 3, 1))
result = gate_v2.search_camera(mesh.vertices, mesh.faces, target, cfg["frame"], cfg["camera"], 2.5, lambda: next(ticks))
""")
        self.assertFalse(out["complete"])
        self.assertLess(out["tried"], out["total"])
        self.assertEqual((out["yaw"], out["elevation"]), (0, 0))


class VerdictTests(VenvTestCase):
    def test_every_ratio_measure_at_and_around_its_margin(self):
        out = probe(GOOD + """
gate = config()["gate"]
result = {}
for limit_key, (name, kind) in gate_v2_config.RATIO_LIMITS.items():
    limit, band = gate[limit_key], gate["review_margin"]
    sign = 1 if kind == "min" else -1  # inside the limit is above a min and below a max
    def at(inside):
        return gate_v2.verdict({**good, name: round(limit + sign * inside, 6)}, gate)[0]
    result[name] = [at(band + 0.001), at(band), at(0.0), at(-band), at(-band - 0.001)]
""")
        self.assertEqual(len(out), 6)
        for name, got in out.items():
            self.assertEqual(got, ["pass", "review", "review", "review", "fail"], name)

    def test_counts_and_orientation(self):
        out = probe(GOOD + """
gate = config()["gate"]
def v(**change):
    return gate_v2.verdict({**good, **change}, gate)
result = {"at_budget": v(faces=100)[0], "over_budget": v(faces=101)[0], "one_piece": v(pieces=1)[0],
          "two_pieces": v(pieces=2)[0], "orientation_at": v(orientation_gain=0.1)[0],
          "orientation_over": v(orientation_gain=0.1001)[0], "fail_beats_review": v(pieces=2, faces=101)[0],
          "reasons": v(pieces=2, faces=101)[1]}
""")
        self.assertEqual((out["at_budget"], out["over_budget"]), ("pass", "fail"))
        self.assertEqual((out["one_piece"], out["two_pieces"]), ("pass", "review"))
        self.assertEqual((out["orientation_at"], out["orientation_over"]), ("pass", "review"))
        self.assertEqual(out["fail_beats_review"], "fail")
        self.assertEqual(len(out["reasons"]), 2)

    def test_depth_ratio_is_review_only_for_thin_kinds(self):
        out = probe(GOOD + """
good["depth_ratio"] = 0.01
result = [gate_v2.verdict(good, config(thin=thin)["gate"])[0] for thin in (False, True)]
""")
        self.assertEqual(out, ["fail", "review"])


class ConfigTests(VenvTestCase):
    def error(self, edit):
        """The ConfigError message after running EDIT (python statements on `raw`) on a valid config."""
        return probe(f"""
raw = raw_config()
{edit}
try:
    gate_v2_config.parse(raw, "my.json")
    result = None
except gate_v2_config.ConfigError as exc:
    result = str(exc)
""")

    def test_missing_keys_name_the_file_and_key(self):
        for edit, key in (("del raw['gate']['max_deficit']", "gate.max_deficit"),
                          ("del raw['gate']['review_margin']", "gate.review_margin"),
                          ("del raw['face_budget']", "config.face_budget"),
                          ("del raw['frame']['flip_y']", "frame.flip_y"),
                          ("del raw['capture']['view']['camera']['yaw']", "capture.view.camera.yaw"),
                          ("del raw['capture']", "config.capture")):
            message = self.error(edit)
            self.assertIn("my.json", message)
            self.assertIn(f"missing key {key}", message)

    def test_unknown_and_invalid_values_are_errors(self):
        self.assertIn("unknown key gate.max_boxfill", self.error("raw['gate']['max_boxfill'] = 0.1"))
        self.assertIn("gate.profile", self.error("raw['gate']['profile'] = 'v1'"))
        self.assertIn("gate.max_excess", self.error("raw['gate']['max_excess'] = 1.5"))
        self.assertIn("gate.max_pieces", self.error("raw['gate']['max_pieces'] = 0"))
        self.assertIn("gate.thin", self.error("raw['gate']['thin'] = 'yes'"))
        self.assertIn("step", self.error("raw['capture']['view']['camera']['yaw'] = [0, 0, 0]"))
        self.assertIn("camera.elevation", self.error("raw['capture']['view']['camera']['elevation'] = [10, -10, 5]"))
        self.assertIn("frame.drop_axis", self.error("raw['frame']['drop_axis'] = 3"))
        self.assertIn("face_budget", self.error("raw['face_budget'] = 0"))

    def test_unreadable_file_names_the_file(self):
        out = probe("""
try:
    gate_v2_config.load("/nonexistent/gate.json")
except gate_v2_config.ConfigError as exc:
    result = str(exc)
""")
        self.assertIn("/nonexistent/gate.json", out)

    def test_shipped_examples_are_valid(self):
        for name in ("prop", "head", "thin"):
            path = EXAMPLES / f"gate_v2.{name}.json"
            self.assertEqual(probe("result = gate_v2_config.load(sys.argv[2])['gate']['profile']", path), "v2", name)


class CliTests(VenvTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "rect.png"
        venv_tool.run_code("import sys\nfrom PIL import Image, ImageDraw\nim = Image.new('RGB', (300, 400), (255, 255, 255))\n"
                           "ImageDraw.Draw(im).rectangle([50, 50, 249, 349], fill=(40, 40, 40))\nim.save(sys.argv[1])", self.image)
        self.config = self.root / "gate.json"
        self.config.write_text(json.dumps(probe("result = raw_config()")))

    def tearDown(self):
        self.temp.cleanup()

    def mesh(self, name, code):
        path = self.root / f"{name}.glb"
        probe(f"({code}).export(sys.argv[2])\nresult = 0", path)
        return path

    def gate(self, mesh, *extra):
        out = self.root / "report.json"
        out.unlink(missing_ok=True)
        result = venv_tool.run_tool("mesh_gates.py", mesh, self.image, "--out", out, *extra)
        return result, (json.loads(out.read_text()) if out.exists() else None)

    def test_exit_codes_and_report_shape(self):
        args = ("--profile", "v2", "--gate", self.config)
        passing, report = self.gate(self.mesh("good", "box((2, 3, 1))"), *args)
        self.assertEqual(passing.returncode, 0, passing.stderr)
        self.assertEqual((report["profile"], report["verdict"]), ("v2", "pass"))
        self.assertEqual(set(report["measures"]["deficit"]), {"value", "limit", "limit_key", "margin", "outcome"})
        self.assertIn("yaw", report["camera"])
        two = "trimesh.util.concatenate([box((2, 3, 1)), box((0.1, 0.1, 0.1), (0, 0, 1))])"
        reviewing, report = self.gate(self.mesh("two", two), *args)
        self.assertEqual((reviewing.returncode, report["verdict"]), (3, "review"), reviewing.stderr)
        failing, report = self.gate(self.mesh("cut", "box((2, 2, 1), at=(0, -0.5, 0))"), *args)
        self.assertEqual((failing.returncode, report["verdict"]), (1, "fail"))
        self.assertIn("deficit", " ".join(report["reasons"]))

    def test_usage_errors(self):
        mesh = self.mesh("good", "box((2, 3, 1))")
        self.assertEqual(self.gate(mesh, "--profile", "v2")[0].returncode, 2)
        self.assertEqual(self.gate(mesh, "--gate", self.config)[0].returncode, 2)
        broken = self.root / "broken.json"
        broken.write_text(json.dumps({"gate": {}}))
        result, report = self.gate(mesh, "--profile", "v2", "--gate", broken)
        self.assertEqual(result.returncode, 2)
        self.assertIn("broken.json", result.stderr)
        self.assertIn("missing key", result.stderr)
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
