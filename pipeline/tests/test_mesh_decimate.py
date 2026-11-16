"""The collapse guard of mesh_decimate.py on shapes with a known topology (tools interpreter: numpy, scipy, trimesh)."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import venv_tool  # noqa: E402

CODE = """
import json, sys
import numpy as np, trimesh
sys.path.insert(0, sys.argv[1])
import mesh_decimate as md
shape, budget = sys.argv[2], int(sys.argv[3])
if shape == "torus":
    mesh = trimesh.creation.torus(1.0, 0.3, major_sections=80, minor_sections=40)
elif shape == "two_spheres":
    a = trimesh.creation.icosphere(subdivisions=4)
    b = trimesh.creation.icosphere(subdivisions=4)
    b.apply_translation([2.0005, 0, 0])   # nearly touching, never sharing a vertex
    mesh = trimesh.util.concatenate([a, b])
elif shape == "open_dome":
    mesh = trimesh.creation.icosphere(subdivisions=4)
    keep = mesh.triangles_center[:, 1] > -0.2
    mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
elif shape in ("cabinet", "head"):
    mesh = trimesh.load(sys.argv[4] + "/" + shape + ".glb", force="mesh", process=False)
elif shape == "coloured_torus":
    mesh = trimesh.creation.torus(1.0, 0.3, major_sections=80, minor_sections=40)
v, f = np.asarray(mesh.vertices, float), np.asarray(mesh.faces)
colours = None
if shape == "coloured_torus":
    colours = np.zeros((len(v), 4), np.uint8)
    colours[:, 3] = 255
    colours[v[:, 2] > 0, 0] = 200
    colours[v[:, 2] <= 0, 2] = 200
ov, of, oc = md.decimate(v, f, budget, True, colours)
edges = np.sort(np.concatenate([of[:, [0, 1]], of[:, [1, 2]], of[:, [2, 0]]]), axis=1)
_, uses = np.unique(edges, axis=0, return_counts=True)
before_edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
_, before_uses = np.unique(before_edges, axis=0, return_counts=True)
out = {"faces_in": len(f), "faces_out": len(of), "before": md.topology(v, f), "after": md.topology(ov, of),
       "border_in": int((before_uses == 1).sum()), "border_out": int((uses == 1).sum())}
if oc is not None:
    out["colour_groups"] = sorted({tuple(c) for c in oc.tolist()})
    out["colour_rows"] = len(oc) == len(ov)
print(json.dumps(out))
"""


def decimate(shape, budget):
    return json.loads(venv_tool.run_code(CODE, HERE.parent, shape, budget, HERE / "fixtures" / "gates"))


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)

    def test_a_torus_keeps_its_handle(self):
        result = decimate("torus", 1000)
        self.assertEqual(result["before"]["euler"], 0)
        self.assertEqual(result["after"], result["before"])
        self.assertLessEqual(result["faces_out"], 1000)
        self.assertGreater(result["faces_out"], 900)

    def test_two_nearly_touching_pieces_stay_two(self):
        result = decimate("two_spheres", 1200)
        self.assertEqual(result["before"]["pieces"], 2)
        self.assertEqual(result["after"], result["before"])
        self.assertLessEqual(result["faces_out"], 1200)

    def test_an_open_boundary_stays_open(self):
        result = decimate("open_dome", 600)
        self.assertGreater(result["border_in"], 0)
        self.assertEqual(result["border_out"], result["border_in"])
        self.assertEqual(result["after"], result["before"])
        self.assertLessEqual(result["faces_out"], 600)

    @venv_tool.needs_gate_meshes
    def test_the_detailed_fixtures_keep_their_handles_and_pieces(self):
        # the topology guard keeps the Euler number and the non-manifold edge count of detailed meshes
        for shape in ("cabinet", "head"):
            with self.subTest(shape=shape):
                result = decimate(shape, 4000)
                self.assertEqual(result["after"], result["before"])
                self.assertLessEqual(result["faces_out"], 4000)
                self.assertGreater(result["faces_out"], 3600)

    def test_colours_follow_the_vertices(self):
        result = decimate("coloured_torus", 1000)
        self.assertTrue(result["colour_rows"])
        self.assertEqual(len(result["colour_groups"]), 2)   # flat colours stay flat: no blended third colour
        self.assertEqual(result["after"], result["before"])


if __name__ == "__main__":
    unittest.main()
