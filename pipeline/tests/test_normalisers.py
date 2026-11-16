"""Fixture tests for the three normalisers (docs/normalisers.md), run as real CLIs under the venv.

Each case is a named check; the run ends with one line `NORMALISERS cases=<n> ok=<n>`. Geometry and
pixel comparisons use tolerances, never byte equality (the exporter is not byte-stable).
"""
import json
import tempfile
import unittest
from pathlib import Path

import venv_tool

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "gates"
GEOMETRY_TOLERANCE = 1e-4   # of the target size; float32 glb positions, scale ~1 on a rerun
# Fixtures whose subject has a near-white edge on the white background (the head's white beard). A flat picture has no alpha
# to remember where that edge was, so normalising a flat output again moves it: the white-on-white limit that
# docs/normalisers.md describes (a chroma-key background is the way round it). The RGBA output is still checked.
PALE_EDGE = {"head"}
PIXEL_TOLERANCE = 0         # a rerun of normalize_image (rgba) on its own output must not change a pixel
# Flat output has no alpha, so a rerun re-detects the background by colour: a near-white pixel that
# the first run kept (enclosed by the subject) can turn into background. Such a pixel is by definition
# within 255 - background_tolerance of the background, so that bounds the change.
FLAT_PIXEL_TOLERANCE = 255 - 236
TARGET_SIZE = 2.0
FACE_BUDGET = 4000
BUDGET_SLACK = 0            # decimation must land at or under the budget
EXTENT_MATCH = 0.03         # upright mutant vs original, per axis, as a share of the target size
SMALL_PIECE_SHARE = 0.01

IMAGE_CONFIG = {"background_tolerance": 236, "canvas_size": 512, "margin": 32, "output_mode": "rgba",
                "background_color": [255, 255, 255]}
MESH_CONFIG = {"orientation": None, "up_axis": "+y", "front_axis": "-z", "weld_distance_share": 0.00001,
               "small_piece_area_share": SMALL_PIECE_SHARE, "target_size": TARGET_SIZE, "scale_axis": "largest"}
DECIMATE_CONFIG = {"face_budget": FACE_BUDGET, "preserve_topology": True}

BUILD_MUTANTS = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import gate_mutants
gate_mutants.write_all(Path(sys.argv[2]), Path(sys.argv[3]))
"""
COLOURISE = """
import sys
import numpy as np, trimesh
mesh = trimesh.load(sys.argv[1], force="mesh", process=False)
v = mesh.vertices
rgb = ((v - v.min(axis=0)) / (np.ptp(v, axis=0) + 1e-9) * 255).astype(np.uint8)
mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=np.column_stack([rgb, np.full(len(v), 255, np.uint8)]))
mesh.export(sys.argv[2])
"""
INSPECT = """
import json, sys
import numpy as np, trimesh
mesh = trimesh.load(sys.argv[1], force="mesh", process=False)
colors = mesh.visual.vertex_colors if mesh.visual.kind == "vertex" else None
print(json.dumps({"kind": mesh.visual.kind, "faces": len(mesh.faces),
                  "distinct_colors": None if colors is None else len(np.unique(colors[:, :3], axis=0))}))
"""
COMPARE_MESH = """
import json, sys
import numpy as np, trimesh
a = trimesh.load(sys.argv[1], force="mesh", process=False)
b = trimesh.load(sys.argv[2], force="mesh", process=False)
same = len(a.vertices) == len(b.vertices) and len(a.faces) == len(b.faces)
print(json.dumps({"same_counts": same, "faces_equal": bool(same and (a.faces == b.faces).all()),
                  "max_vertex_diff": float(np.abs(a.vertices - b.vertices).max()) if same else None}))
"""
COMPARE_IMAGE = """
import json, sys
import numpy as np
from PIL import Image
a = np.asarray(Image.open(sys.argv[1])).astype(int)
b = np.asarray(Image.open(sys.argv[2])).astype(int)
print(json.dumps({"same_shape": a.shape == b.shape, "max_diff": int(np.abs(a - b).max()) if a.shape == b.shape else None}))
"""
IMAGE_STATS = """
import json, sys
import numpy as np
from PIL import Image
image = Image.open(sys.argv[1])
alpha = np.asarray(image)[:, :, 3] if image.mode == "RGBA" else None
print(json.dumps({"mode": image.mode, "size": list(image.size),
                  "alpha_values": None if alpha is None else sorted(int(v) for v in np.unique(alpha))}))
"""
WRITE_IMAGE = """
import sys
from PIL import Image
Image.new(sys.argv[2], (64, 64), (255, 255, 255) if sys.argv[2] == "RGB" else 255).save(sys.argv[1])
"""


def write_json(path, data):
    path.write_text(json.dumps(data))
    return path


class NormaliserTests(unittest.TestCase):
    cases = 0
    passed = 0

    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.fixtures = sorted(p.stem for p in FIXTURES.glob("*.glb"))
        cls.image_config = write_json(cls.root / "image.json", IMAGE_CONFIG)
        cls.mesh_config = write_json(cls.root / "mesh.json", MESH_CONFIG)
        cls.decimate_config = write_json(cls.root / "decimate.json", DECIMATE_CONFIG)
        cls.mutants = {}
        for fixture in cls.fixtures:
            folder = cls.root / "mutants" / fixture
            venv_tool.run_code(BUILD_MUTANTS, HERE, FIXTURES / f"{fixture}.glb", folder)
            cls.mutants[fixture] = folder

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        print(f"NORMALISERS cases={NormaliserTests.cases} ok={NormaliserTests.passed}")

    def case(self, label, body):
        """Run one named check; count it, and re-raise so the test fails with the label."""
        NormaliserTests.cases += 1
        try:
            body()
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}") from exc
        NormaliserTests.passed += 1

    def tool(self, script, source, name, config, expect=0, report=None):
        """Run a normaliser CLI; returns (output path, report dict or None, result)."""
        out = self.root / name
        report = report or self.root / (name + ".report.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        result = venv_tool.run_tool(script, source, out, "--config", config, "--report", report)
        self.assertEqual(result.returncode, expect, f"{script} {name}: {result.stderr}")
        return out, (json.loads(report.read_text()) if report.exists() else None), result

    def json_code(self, code, *args):
        return json.loads(venv_tool.run_code(code, *args))

    def config_without(self, name, base, key):
        return write_json(self.root / f"{name}.json", {k: v for k, v in base.items() if k != key})

    def assert_mesh_same(self, first, second):
        diff = self.json_code(COMPARE_MESH, first, second)
        self.assertTrue(diff["same_counts"] and diff["faces_equal"], diff)
        self.assertLessEqual(diff["max_vertex_diff"], GEOMETRY_TOLERANCE * TARGET_SIZE, diff)

    def assert_fails_naming(self, script, source, name, config, key):
        _, _, result = self.tool(script, source, name, config, expect=2)
        self.assertIn(f"'{key}'", result.stderr)
        self.assertIn(str(config), result.stderr)

    # ---- normalize_image ----

    def test_image_happy_path_and_idempotence(self):
        for fixture in self.fixtures:
            source = FIXTURES / f"{fixture}.png"
            out, report, _ = self.tool("normalize_image.py", source, f"img/{fixture}.png", self.image_config)

            def happy():
                stats = self.json_code(IMAGE_STATS, out)
                self.assertEqual((stats["mode"], stats["size"]), ("RGBA", [512, 512]))
                self.assertEqual(stats["alpha_values"], [0, 255])
                box = report["placed_bbox"]
                self.assertEqual(max(box["right"] - box["left"], box["bottom"] - box["top"]), 512 - 2 * 32)
                self.assertLessEqual(abs(box["left"] - (512 - box["right"])), 1)
                self.assertLessEqual(abs(box["top"] - (512 - box["bottom"])), 1)
                self.assertFalse(report["touched_border"])
                self.assertEqual(len(report["config_sha256"]), 64)
            self.case(f"image happy {fixture}", happy)

            def idempotent():
                again, again_report, _ = self.tool("normalize_image.py", out, f"img/{fixture}.again.png", self.image_config)
                self.assertEqual(again_report["scale"], 1.0)
                self.assertLessEqual(self.json_code(COMPARE_IMAGE, out, again)["max_diff"], PIXEL_TOLERANCE)
            self.case(f"image idempotent rgba {fixture}", idempotent)

            def flat():
                if fixture in PALE_EDGE:
                    return  # see PALE_EDGE
                flat_config = write_json(self.root / "flat.json", {**IMAGE_CONFIG, "output_mode": "flat"})
                flat_out, _, _ = self.tool("normalize_image.py", source, f"img/{fixture}.flat.png", flat_config)
                self.assertEqual(self.json_code(IMAGE_STATS, flat_out)["mode"], "RGB")
                again, again_report, _ = self.tool("normalize_image.py", flat_out, f"img/{fixture}.flat2.png", flat_config)
                self.assertEqual(again_report["scale"], 1.0)
                self.assertLessEqual(self.json_code(COMPARE_IMAGE, flat_out, again)["max_diff"], FLAT_PIXEL_TOLERANCE)
            self.case(f"image flat and idempotent {fixture}", flat)

    def test_image_missing_key_and_bad_input(self):
        source = FIXTURES / "head.png"
        for key in IMAGE_CONFIG:
            config = self.config_without(f"image_no_{key}", IMAGE_CONFIG, key)
            self.case(f"image missing {key}",
                      lambda: self.assert_fails_naming("normalize_image.py", source, "img/x.png", config, key))
        blank, gray = self.root / "blank.png", self.root / "gray.png"
        venv_tool.run_code(WRITE_IMAGE, blank, "RGB")
        venv_tool.run_code(WRITE_IMAGE, gray, "L")
        for label, bad in (("no such file", self.root / "nope.png"), ("blank image", blank), ("grayscale", gray),
                           ("not an image", self.mesh_config)):
            self.case(f"image bad input: {label}", lambda: self.tool("normalize_image.py", bad, "img/x.png", self.image_config, expect=2))
        wide = write_json(self.root / "wide.json", {**IMAGE_CONFIG, "margin": 256})
        self.case("image margin too large", lambda: self.tool("normalize_image.py", source, "img/x.png", wide, expect=2))
        wrong = write_json(self.root / "wrong.json", {**IMAGE_CONFIG, "output_mode": "sepia"})
        self.case("image bad value names key", lambda: self.assertIn(
            "'output_mode'", self.tool("normalize_image.py", source, "img/x.png", wrong, expect=2)[2].stderr))

    # ---- normalize_mesh ----

    def test_mesh_happy_path_and_idempotence(self):
        for fixture in self.fixtures:
            source = FIXTURES / f"{fixture}.glb"
            out, report, _ = self.tool("normalize_mesh.py", source, f"mesh/{fixture}.glb", self.mesh_config)

            def happy():
                after = report["after"]
                lo, hi = after["bounds"]["min"], after["bounds"]["max"]
                extents = [h - l for l, h in zip(lo, hi)]
                self.assertAlmostEqual(max(extents), TARGET_SIZE, places=4)
                self.assertAlmostEqual(lo[1], 0.0, places=5)          # base on the floor, up is +y
                self.assertAlmostEqual(lo[0] + hi[0], 0.0, places=4)  # base centred
                self.assertAlmostEqual(lo[2] + hi[2], 0.0, places=4)
                self.assertEqual(after["pieces"], 1)
                self.assertIn("before", report)
                self.assertEqual(len(report["config_sha256"]), 64)
            self.case(f"mesh happy {fixture}", happy)

            def idempotent():
                again, again_report, _ = self.tool("normalize_mesh.py", out, f"mesh/{fixture}.again.glb", self.mesh_config)
                self.assertEqual(again_report["pieces_dropped"], 0)
                self.assert_mesh_same(out, again)
            self.case(f"mesh idempotent {fixture}", idempotent)

    @venv_tool.needs_gate_meshes
    def test_mesh_keeps_vertex_colours(self):
        coloured = self.root / "coloured.glb"
        venv_tool.run_code(COLOURISE, FIXTURES / "head.glb", coloured)
        out, report, _ = self.tool("normalize_mesh.py", coloured, "mesh/coloured.glb", self.mesh_config)

        def kept():
            self.assertEqual(report["vertex_colors"], {"present": True, "kept": True})
            info = self.json_code(INSPECT, out)
            self.assertEqual(info["kind"], "vertex")
            self.assertGreater(info["distinct_colors"], 100)
        self.case("mesh keeps vertex colours", kept)

    def test_mesh_missing_key_and_bad_input(self):
        source = FIXTURES / "head.glb"
        for key in MESH_CONFIG:
            config = self.config_without(f"mesh_no_{key}", MESH_CONFIG, key)
            self.case(f"mesh missing {key}",
                      lambda: self.assert_fails_naming("normalize_mesh.py", source, "mesh/x.glb", config, key))
        garbage = self.root / "garbage.glb"
        garbage.write_text("not a mesh")
        for label, bad in (("no such file", self.root / "nope.glb"), ("garbage file", garbage)):
            self.case(f"mesh bad input: {label}", lambda: self.tool("normalize_mesh.py", bad, "mesh/x.glb", self.mesh_config, expect=2))
        mirror = write_json(self.root / "mirror.json", {**MESH_CONFIG, "orientation": {"matrix": [[-1, 0, 0], [0, 1, 0], [0, 0, 1]]}})
        same_axis = write_json(self.root / "same_axis.json", {**MESH_CONFIG, "front_axis": "+y"})
        for label, config in (("mirror matrix", mirror), ("up and front on one axis", same_axis)):
            self.case(f"mesh bad config: {label}", lambda: self.tool("normalize_mesh.py", source, "mesh/x.glb", config, expect=2))

    def gate(self, mesh, fixture, name):
        report = self.root / f"{name}.gate.json"
        result = venv_tool.run_tool("mesh_gates.py", mesh, FIXTURES / f"{fixture}.png", "--out", report)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return json.loads(report.read_text())

    def test_on_side_mutant_comes_back_upright(self):
        for fixture in self.fixtures:
            tilted = self.mutants[fixture] / "on_side.glb"
            view = self.gate(tilted, fixture, f"{fixture}.on_side")["measures"]["view"]
            config = write_json(self.root / f"{fixture}.view.json", {**MESH_CONFIG, "orientation": {"view": view}})
            _, original, _ = self.tool("normalize_mesh.py", FIXTURES / f"{fixture}.glb", f"mesh/{fixture}.orig.glb", self.mesh_config)
            out, fixed, _ = self.tool("normalize_mesh.py", tilted, f"mesh/{fixture}.on_side.glb", config)

            def upright():
                self.assertTrue(fixed["orientation"]["applied"])
                self.assertEqual(fixed["after"]["pieces"], 1)
                for axis in range(3):
                    want = original["after"]["bounds"]
                    got = fixed["after"]["bounds"]
                    extent = lambda b: b["max"][axis] - b["min"][axis]
                    self.assertLessEqual(abs(extent(got) - extent(want)), EXTENT_MATCH * TARGET_SIZE,
                                         f"axis {axis}: {extent(got)} vs {extent(want)}")
            self.case(f"on_side upright {fixture}", upright)

            def once_only():
                again, again_report, _ = self.tool("normalize_mesh.py", out, f"mesh/{fixture}.on_side2.glb", config)
                self.assertFalse(again_report["orientation"]["applied"])
                self.assert_mesh_same(out, again)
            self.case(f"on_side idempotent {fixture}", once_only)

    def test_scatter_mutant_loses_its_pieces_and_passes_the_gate(self):
        for fixture in self.fixtures:
            scattered = self.mutants[fixture] / "scatter.glb"
            self.assertEqual(self.gate(scattered, fixture, f"{fixture}.scatter")["passed"], False)
            out, report, _ = self.tool("normalize_mesh.py", scattered, f"mesh/{fixture}.scatter.glb", self.mesh_config)

            def cleaned():
                self.assertEqual(report["after"]["pieces"], 1)
                self.assertGreaterEqual(report["pieces_dropped"], 30)
                self.assertGreater(report["dropped_area_share"], 0.02)
                gate = self.gate(out, fixture, f"{fixture}.scatter.after")
                self.assertTrue(gate["passed"], gate["reasons"])
            self.case(f"scatter cleaned and gate passes {fixture}", cleaned)

    # ---- decimate_mesh ----

    def test_decimate_happy_path_and_idempotence(self):
        for fixture in self.fixtures:
            out, report, _ = self.tool("decimate_mesh.py", FIXTURES / f"{fixture}.glb", f"dec/{fixture}.glb", self.decimate_config)

            def happy():
                self.assertTrue(report["changed"])
                self.assertLessEqual(report["after"]["faces"], FACE_BUDGET + BUDGET_SLACK)
                self.assertGreater(report["after"]["faces"], FACE_BUDGET * 0.9)
                self.assertEqual(len(report["config_sha256"]), 64)
            self.case(f"decimate happy {fixture}", happy)

            def idempotent():
                again, again_report, _ = self.tool("decimate_mesh.py", out, f"dec/{fixture}.again.glb", self.decimate_config)
                self.assertFalse(again_report["changed"])
                self.assertIn("within the face budget", again_report["note"])
                self.assertEqual(out.read_bytes(), again.read_bytes())
            self.case(f"decimate idempotent {fixture}", idempotent)

    @venv_tool.needs_gate_meshes
    def test_decimate_under_budget_is_copied(self):
        roomy = write_json(self.root / "roomy.json", {**DECIMATE_CONFIG, "face_budget": 100000})
        source = FIXTURES / "tool.glb"
        out, report, _ = self.tool("decimate_mesh.py", source, "dec/roomy.glb", roomy)
        self.case("decimate under budget copies", lambda: (
            self.assertFalse(report["changed"]), self.assertEqual(out.read_bytes(), source.read_bytes())))

    @venv_tool.needs_gate_meshes
    def test_decimate_keeps_vertex_colours(self):
        coloured = self.root / "coloured_dec.glb"
        venv_tool.run_code(COLOURISE, FIXTURES / "head.glb", coloured)
        out, report, _ = self.tool("decimate_mesh.py", coloured, "dec/coloured.glb", self.decimate_config)

        def kept():
            self.assertEqual(report["vertex_colors"], {"present": True, "preserved": True})
            info = self.json_code(INSPECT, out)
            self.assertEqual(info["kind"], "vertex")
            self.assertGreater(info["distinct_colors"], 100)
        self.case("decimate keeps vertex colours", kept)

    def test_decimate_subdivided_mutant_returns_to_budget(self):
        for fixture in self.fixtures:
            out, report, _ = self.tool("decimate_mesh.py", self.mutants[fixture] / "subdivided.glb",
                                       f"dec/{fixture}.subdivided.glb", self.decimate_config)

            def back():
                self.assertGreater(report["before"]["faces"], 16 * 7000)
                self.assertLessEqual(report["after"]["faces"], FACE_BUDGET + BUDGET_SLACK)
                self.assertGreater(report["after"]["faces"], FACE_BUDGET * 0.9)
            self.case(f"subdivided back to budget {fixture}", back)

    def test_decimate_missing_key_and_bad_input(self):
        source = FIXTURES / "head.glb"
        for key in DECIMATE_CONFIG:
            config = self.config_without(f"decimate_no_{key}", DECIMATE_CONFIG, key)
            self.case(f"decimate missing {key}",
                      lambda: self.assert_fails_naming("decimate_mesh.py", source, "dec/x.glb", config, key))
        garbage = self.root / "garbage_dec.glb"
        garbage.write_text("not a mesh")
        for label, bad in (("no such file", self.root / "nope.glb"), ("garbage file", garbage)):
            self.case(f"decimate bad input: {label}", lambda: self.tool("decimate_mesh.py", bad, "dec/x.glb", self.decimate_config, expect=2))
        zero = write_json(self.root / "zero.json", {**DECIMATE_CONFIG, "face_budget": 0})
        self.case("decimate zero budget", lambda: self.tool("decimate_mesh.py", source, "dec/x.glb", zero, expect=2))


if __name__ == "__main__":
    unittest.main()
