"""Tests of the z-buffer renderer (pipeline/mesh_render.py) on synthetic meshes with known answers.

The code under test needs numpy and trimesh, so every probe runs under the tools interpreter
(tests/venv_tool.py). The style dict is the test's own; the renderer has no look defaults.
"""
import json
import unittest
from pathlib import Path

import venv_tool

TOOLS = str(Path(__file__).resolve().parents[1])
HEADER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import numpy as np, trimesh
import mesh_render as R

STYLE = {"size": 128, "supersample": 1, "margin": 0.1, "shading": "smooth", "background": [250, 250, 250],
         "surface": [120, 120, 120], "ambient": 0.3, "light": [0, 0, 1]}

def depth_of(mesh, view="front", style=STYLE):
    size = style["size"] * style["supersample"]
    centre, scale = R.fit(mesh.vertices, style["size"], style["margin"])
    return R.rasterise(mesh.vertices, mesh.faces, R.view_axes(view, "+y", "+z"), centre, scale * style["supersample"], size)
"""


def probe(body):
    """Run BODY after HEADER under the venv interpreter; BODY sets `result` to a JSON value."""
    return json.loads(venv_tool.run_code(HEADER + body + "\nprint(json.dumps(result))", TOOLS))


class RenderTests(unittest.TestCase):
    def setUp(self):
        venv_tool.require_venv(self)

    def test_sphere_is_radially_symmetric_and_the_right_size(self):
        result = probe("""
mesh = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
depth, face = depth_of(mesh)
size = depth.shape[0]
covered = face >= 0
radius = size * (1 - 2 * STYLE["margin"]) / 2
area_error = abs(covered.sum() - np.pi * radius ** 2) / (np.pi * radius ** 2)
# depth of a unit sphere is sqrt(r^2 - d^2) in pixels: compare with it, and with the 90-degree rotated image
yy, xx = np.mgrid[0:size, 0:size]
d = np.hypot(xx + 0.5 - size / 2, yy + 0.5 - size / 2)
inner = d < radius * 0.9
expected = np.sqrt(radius ** 2 - d[inner] ** 2)
sphere_error = float(np.abs(depth[inner] - expected).max() / radius)
turned = float(np.abs(np.where(covered, depth, 0) - np.rot90(np.where(covered, depth, 0))).max() / radius)
result = {"area_error": area_error, "depth_error": sphere_error, "rot90_difference": turned}
""")
        self.assertLess(result["area_error"], 0.02)
        self.assertLess(result["depth_error"], 0.02)      # polygonal sphere: well inside the facet sag
        self.assertLess(result["rot90_difference"], 0.03)

    def test_torus_shows_the_far_surface_through_the_hole_not_the_hidden_one(self):
        # A torus lying with its axis along the view direction: the hole shows the background, and a
        # brute-force per-pixel ray cast (nearest triangle by exact ray-triangle tests) must agree everywhere.
        result = probe("""
mesh = trimesh.creation.torus(major_radius=1.0, minor_radius=0.35, major_sections=24, minor_sections=12)
mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(60), [1, 0, 0]))  # tilted: parts overlap in depth
small = {**STYLE, "size": 48}
depth, face = depth_of(mesh, style=small)
size = 48
centre, scale = R.fit(mesh.vertices, size, small["margin"])
axes = R.view_axes("front", "+y", "+z")
local = (mesh.vertices - centre) @ axes.T
local[:, :2] *= scale
local[:, 0] += size / 2
local[:, 1] = size / 2 - local[:, 1]
local[:, 2] *= scale
tri = local[mesh.faces]
best = np.full((size, size), -np.inf)
for r in range(size):
    for c in range(size):
        p = np.array([c + 0.5, r + 0.5])
        a, b, d = tri[:, 0, :2], tri[:, 1, :2], tri[:, 2, :2]
        den = (b[:, 0]-a[:, 0])*(d[:, 1]-a[:, 1]) - (d[:, 0]-a[:, 0])*(b[:, 1]-a[:, 1])
        ok = np.abs(den) > 1e-12
        u = np.where(ok, ((p[0]-a[:, 0])*(d[:, 1]-a[:, 1]) - (d[:, 0]-a[:, 0])*(p[1]-a[:, 1])) / np.where(ok, den, 1), -1)
        v = np.where(ok, ((b[:, 0]-a[:, 0])*(p[1]-a[:, 1]) - (p[0]-a[:, 0])*(b[:, 1]-a[:, 1])) / np.where(ok, den, 1), -1)
        hit = ok & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
        if hit.any():
            z = (1-u-v)[hit] * tri[hit, 0, 2] + u[hit] * tri[hit, 1, 2] + v[hit] * tri[hit, 2, 2]
            best[r, c] = z.max()
result = {"covered_equal": bool(((depth > -np.inf) == (best > -np.inf)).all()),
          "max_depth_difference": float(np.abs(np.where(best > -np.inf, depth - best, 0)).max()),
          "hole_pixels": int(((best == -np.inf) & (np.hypot(np.arange(size)[None, :] + .5 - size/2, np.arange(size)[:, None] + .5 - size/2) < 3)).sum()),
          "covered": int((depth > -np.inf).sum())}
""")
        self.assertTrue(result["covered_equal"])
        self.assertLess(result["max_depth_difference"], 1e-6)
        self.assertGreater(result["hole_pixels"], 0, "the torus hole must show the background")

    def test_notched_box_shows_the_far_wall_through_the_gap(self):
        # A slab with a square notch cut through it, in front of a taller, farther slab: through the notch
        # the far slab's colour shows, never the near slab's hidden side.
        result = probe("""
far = trimesh.creation.box(extents=[2, 2, 0.2], transform=trimesh.transformations.translation_matrix([0, 0, -1]))
near = trimesh.creation.box(extents=[2, 2, 0.2], transform=trimesh.transformations.translation_matrix([0, 0, 1]))
hole = trimesh.creation.box(extents=[0.6, 0.6, 1])
# build the near wall as four slabs around a gap in the middle
parts = [trimesh.creation.box(extents=e, transform=trimesh.transformations.translation_matrix(t))
         for e, t in (([2, 0.7, 0.2], [0, 0.65, 1]), ([2, 0.7, 0.2], [0, -0.65, 1]),
                      ([0.7, 0.6, 0.2], [0.65, 0, 1]), ([0.7, 0.6, 0.2], [-0.65, 0, 1]))]
scene = trimesh.util.concatenate([far] + parts)
colours = np.zeros((len(scene.vertices), 4), np.uint8)
colours[:, 3] = 255
colours[:len(far.vertices)] = [0, 200, 0, 255]
colours[len(far.vertices):] = [200, 0, 0, 255]
flat = {**STYLE, "shading": "flat", "ambient": 1.0}
centre, scale = R.fit(scene.vertices, 128, 0.1)
image, depth = R.render(scene.vertices, scene.faces, "front", "+y", "+z", flat, colours)
mid = image[64, 64]
corner = image[40, 40]   # on the near wall's frame
result = {"gap_centre": mid.tolist(), "frame": corner.tolist()}
""")
        self.assertEqual(result["gap_centre"], [0, 200, 0])
        self.assertEqual(result["frame"], [200, 0, 0])

    def test_vertex_colours_are_kept_and_neutral_colour_otherwise(self):
        result = probe("""
mesh = trimesh.creation.box(extents=[1, 1, 1])
colours = np.tile(np.array([[10, 200, 30, 255]], np.uint8), (len(mesh.vertices), 1))
flat = {**STYLE, "shading": "flat", "ambient": 1.0}
coloured, _ = R.render(mesh.vertices, mesh.faces, "front", "+y", "+z", flat, colours)
plain, _ = R.render(mesh.vertices, mesh.faces, "front", "+y", "+z", flat)
result = {"coloured": coloured[64, 64].tolist(), "plain": plain[64, 64].tolist(), "background": coloured[2, 2].tolist()}
""")
        self.assertEqual(result["coloured"], [10, 200, 30])
        self.assertEqual(result["plain"], [120, 120, 120])
        self.assertEqual(result["background"], [250, 250, 250])

    def test_views_are_named_from_the_contract_axes(self):
        # A red knob on the subject's front (+z) and a blue one on its right as seen from the front (+x):
        # the front view shows red in the middle and blue on the right; the back view shows neither red
        # nor blue in the middle, and blue on its LEFT; the side view shows red on its right (front points right);
        # the top view shows red at the bottom.
        result = probe("""
body = trimesh.creation.box(extents=[2, 2, 2])
red = trimesh.creation.box(extents=[0.4, 0.4, 0.6], transform=trimesh.transformations.translation_matrix([0, 0, 1.2]))
blue = trimesh.creation.box(extents=[0.6, 0.4, 0.4], transform=trimesh.transformations.translation_matrix([1.2, 0, 0]))
scene = trimesh.util.concatenate([body, red, blue])
n = [len(body.vertices), len(red.vertices), len(blue.vertices)]
colours = np.full((len(scene.vertices), 4), 128, np.uint8)
colours[n[0]:n[0] + n[1]] = [255, 0, 0, 255]
colours[n[0] + n[1]:] = [0, 0, 255, 255]
flat = {**STYLE, "shading": "flat", "ambient": 1.0}
def where(view, colour):
    image, _ = R.render(scene.vertices, scene.faces, view, "+y", "+z", flat, colours)
    hits = np.argwhere((image == colour).all(axis=2))
    return None if not len(hits) else hits.mean(axis=0).tolist()   # (row, col)
result = {v: {"red": where(v, [255, 0, 0]), "blue": where(v, [0, 0, 255]), "body": where(v, [128, 128, 128])} for v in R.VIEWS}
""")
        front, back, side, top = (result[v] for v in ("front", "back", "side", "top"))
        def right_of(view, colour):   # columns right of the grey body's centre
            return view[colour][1] - view["body"][1]
        self.assertAlmostEqual(right_of(front, "red"), 0, delta=3)         # red faces the camera, in the middle
        self.assertGreater(right_of(front, "blue"), 15)                    # blue on the right
        self.assertIsNone(back["red"])                                      # hidden behind the body
        self.assertLess(right_of(back, "blue"), -15)                       # seen from behind, right is left
        self.assertGreater(right_of(side, "red"), 15)                      # the front points to the screen's right
        self.assertGreater(top["red"][0] - top["body"][0], 15)             # the front is at the bottom of the top view

    def test_the_same_input_renders_identically(self):
        result = probe("""
mesh = trimesh.creation.icosphere(subdivisions=3)
a, da = R.render(mesh.vertices, mesh.faces, "side", "+y", "+z", STYLE)
b, db = R.render(mesh.vertices, mesh.faces, "side", "+y", "+z", STYLE)
result = {"image": bool((a == b).all()), "depth": bool((da == db).all())}
""")
        self.assertTrue(result["image"] and result["depth"])

    def test_speed_on_an_8000_face_mesh(self):
        result = probe("""
import time
mesh = trimesh.creation.icosphere(subdivisions=5)
big = {**STYLE, "size": 256, "supersample": 1}
start = time.monotonic()
for view in R.VIEWS:
    R.render(mesh.vertices, mesh.faces, view, "+y", "+z", big)
result = {"faces": len(mesh.faces), "seconds_per_view": (time.monotonic() - start) / 4}
""")
        self.assertGreater(result["faces"], 8000)
        self.assertLess(result["seconds_per_view"], 1.0)

    def test_style_errors_name_the_key(self):
        result = probe("""
errors = []
for broken in ({k: v for k, v in STYLE.items() if k != "light"}, {**STYLE, "shading": "gouraud"}, {**STYLE, "extra": 1},
               {**STYLE, "light": [0, 0, 0]}):
    try:
        R.check_style(broken)
        errors.append(None)
    except ValueError as exc:
        errors.append(str(exc))
result = errors
""")
        self.assertIn("missing key light", result[0])
        self.assertIn("shading", result[1])
        self.assertIn("unknown key extra", result[2])
        self.assertIn("light", result[3])


if __name__ == "__main__":
    unittest.main()
