import json
import tempfile
import unittest
from pathlib import Path

import venv_tool

SIZE = 256
RADIUS = 1.0
CARD_HALF = 1.6      # the card reaches well past the sphere
CARD_THICKNESS = 0.04
BLOB_OFFSET = 4.0    # distance between the two separate blobs


MESH_CODE = """
import sys
import trimesh
out, kind, radius, card_half, thickness, offset = sys.argv[1:]
radius, card_half, thickness, offset = map(float, (radius, card_half, thickness, offset))
ball = trimesh.creation.icosphere(subdivisions=3, radius=radius)
if kind == "ball":
    mesh = ball
elif kind == "carded":
    mesh = trimesh.util.concatenate([ball, trimesh.creation.box(extents=[2 * card_half, 2 * card_half, thickness])])
elif kind == "pair":
    other = ball.copy()
    other.apply_translation([offset, 0, 0])
    mesh = trimesh.util.concatenate([ball, other])
elif kind == "open":
    mesh = trimesh.Trimesh(ball.vertices, ball.faces[1:], process=False)
mesh.export(out)
"""


class MeshGateTests(unittest.TestCase):
    def setUp(self):
        venv_tool.require_venv(self)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "disc.png"
        venv_tool.write_discs(self.image, SIZE, [(SIZE // 2, SIZE // 2, SIZE // 4)])

    def tearDown(self):
        self.temp.cleanup()

    def write_mesh(self, name, kind):
        path = self.root / f"{name}.glb"
        venv_tool.run_code(MESH_CODE, path, kind, RADIUS, CARD_HALF, CARD_THICKNESS, BLOB_OFFSET)
        return path

    def gate(self, mesh, *extra):
        out = self.root / "mesh-validation.json"
        result = venv_tool.run_tool("mesh_gates.py", mesh, self.image, "--out", out, *extra)
        return result, json.loads(out.read_text())

    def test_sphere_matching_disc_passes(self):
        result, report = self.gate(self.write_mesh("ball", "ball"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["passed"])
        self.assertGreater(report["measures"]["silhouette_iou"], 0.9)

    def test_card_through_sphere_fails(self):
        result, report = self.gate(self.write_mesh("carded", "carded"))
        self.assertEqual(result.returncode, 1)
        self.assertFalse(report["passed"])
        text = " ".join(report["reasons"])
        self.assertTrue("thin_sheet_share" in text or "silhouette_excess" in text, text)

    def test_separate_blobs_fail_on_largest_piece(self):
        result, report = self.gate(self.write_mesh("pair", "pair"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("largest_piece_share", " ".join(report["reasons"]))
        self.assertEqual(report["measures"]["pieces"], 2)

    def test_threshold_override_and_bad_checks(self):
        pair = self.write_mesh("pair", "pair")
        result, report = self.gate(pair, "--checks", json.dumps({"min_largest_piece_share": 0.4,
                                                                "min_silhouette_iou": 0.0,
                                                                "max_silhouette_excess": 1.0}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["thresholds"]["min_largest_piece_share"], 0.4)
        bad = venv_tool.run_tool("mesh_gates.py", pair, self.image, "--out", self.root / "x.json", "--checks", '{"nope": 1}')
        self.assertEqual(bad.returncode, 2)

    def test_require_watertight_gates(self):
        path = self.write_mesh("open", "open")
        result, report = self.gate(path)
        self.assertFalse(report["measures"]["watertight"])
        self.assertEqual(result.returncode, 0, result.stderr)
        result, report = self.gate(path, "--checks", '{"require_watertight": true}')
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
