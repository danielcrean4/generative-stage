"""Rebuild tests/fixtures/gates/: the meshes and pictures the shape-gate tests use (tools interpreter: numpy, trimesh, PIL).

    python make_gate_fixtures.py shapes OUT_DIR

`shapes` writes `cabinet` (a boxy prop with a neck and two side lugs), `tool` (a thin handle and blade) and `head` (a bust:
an ellipsoid skull, a jaw and chin, a nose, two ears and a neck cylinder), all made here from formulas, no model and no random
numbers, so the same files come out every time. Each is one closed surface of 7,752 faces, centred, its longest extent 1.9, y up,
drawn from the front (+z) by `mesh_render.py` on white. The picture is what the mesh looks like from the front, so the gate's
silhouette measures start near 1. The head's picture is painted too (skin, a darker hair cap, eyes, mouth) so the colouring tests
have colours to count; the mesh files carry geometry only.

After it, rewrite the expected tables (see the module docstrings of the gate tests):
    GATE_MUTANTS_REGENERATE=1 python -m unittest tests.test_gate_mutants tests.test_gate_mutants_v2 tests.test_mesh_finish
"""
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_render

IMAGE_SIZE = 256
SLICES, RINGS = 76, 53  # 2 * SLICES * (RINGS - 2) = 7,752 faces
LONGEST = 1.9
STYLE = {"size": IMAGE_SIZE, "supersample": 3, "margin": 0.06, "shading": "smooth", "background": [255, 255, 255],
         "ambient": 0.4, "light": [-0.4, 0.5, 0.75]}


def smooth(x, low, high):
    """0 below LOW, 1 above HIGH, a smooth rise between."""
    t = np.clip((x - low) / (high - low), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def sgnpow(x, power):
    return np.sign(x) * np.abs(x) ** power


def revolve(axis, profile, ends=6.0, sides=0.3):
    """A closed surface around the AXIS (0, 1 or 2): at position s in [-1, 1] along the axis the cross-section is a
    rounded rectangle whose half-sizes and offsets come from PROFILE(s) -> (half_a, half_b, offset_a, offset_b), a and b
    being the other two axes in order. ENDS (how flat the ends are) and SIDES (how square the section is) are exponents
    of the superellipse: 2 is round, larger is boxier for ENDS, smaller for SIDES."""
    eta = np.linspace(-np.pi / 2, np.pi / 2, RINGS)
    omega = np.linspace(0, 2 * np.pi, SLICES, endpoint=False)
    along = np.sin(eta)  # rings are packed towards the ends, where the surface turns
    ring = (1 - np.abs(along) ** ends) ** (1 / ends)  # the cross-section shrinks to nothing at the ends; a large ENDS is boxy
    spine = []
    for index, (s, scale) in enumerate(zip(along, ring)):
        half_a, half_b, off_a, off_b = profile(s)
        if index in (0, RINGS - 1):
            spine.append([(s, off_a, off_b)])
            continue
        a = off_a + half_a * scale * sgnpow(np.cos(omega), sides)
        b = off_b + half_b * scale * sgnpow(np.sin(omega), sides)
        spine.append(list(zip(np.full(SLICES, s), a, b)))
    order = [(axis + 1) % 3, (axis + 2) % 3]
    vertices = []
    for row in spine:
        for s, a, b in row:
            p = [0.0, 0.0, 0.0]
            p[axis], p[order[0]], p[order[1]] = s, a, b
            vertices.append(p)
    vertices = np.array(vertices)
    faces = []
    first = lambda r: 0 if r == 0 else 1 + (r - 1) * SLICES  # noqa: E731
    for k in range(SLICES):
        faces.append((0, first(1) + (k + 1) % SLICES, first(1) + k))
        faces.append((len(vertices) - 1, first(RINGS - 2) + k, first(RINGS - 2) + (k + 1) % SLICES))
    for r in range(1, RINGS - 2):
        for k in range(SLICES):
            a0, a1 = first(r) + k, first(r) + (k + 1) % SLICES
            b0, b1 = first(r + 1) + k, first(r + 1) + (k + 1) % SLICES
            faces += [(a0, a1, b0), (a1, b1, b0)]
    faces = np.array(faces)
    if trimesh.Trimesh(vertices, faces, process=False).volume < 0:
        faces = faces[:, ::-1]  # wound outwards
    return vertices, faces


def cabinet():
    """Axis y. A body 1.0 wide and 0.7 deep, a narrow neck on top leaning to +x, and a thin lug through each side."""
    def profile(s):
        neck = smooth(s, 0.62, 0.74)
        lugs = smooth(s, -0.16, -0.1) * (1 - smooth(s, 0.1, 0.16))
        half_x = 0.5 + 0.45 * lugs - 0.3 * neck
        half_z = 0.36 - 0.24 * lugs - 0.14 * neck
        return half_z, half_x, 0.0, 0.1 * neck  # the cross-section's axes are z, then x
    vertices, faces = revolve(1, profile, ends=8.0, sides=0.32)
    vertices[:, 1] *= 0.85  # height 1.7
    return vertices, faces


def tool():
    """Axis x. A thin round handle on the left, a flat broad blade on the right, both 0.2 deep at most."""
    def profile(s):
        blade = smooth(s, -0.2, 0.05)
        half_y = 0.12 + 0.25 * blade
        half_z = 0.07 + 0.03 * blade
        return half_y, half_z, 0.0, 0.0
    vertices, faces = revolve(0, profile, ends=4.0, sides=0.55)
    vertices[:, 0] *= 0.95
    return vertices, faces


def head():
    """Axis y, the face toward +z. A neck cylinder, a jaw that widens into an ellipsoid skull, then a nose, a chin and two ears
    pushed out of that one surface, so the bust stays a single closed mesh."""
    def profile(s):
        dome = np.sqrt(max(0.0, 1 - (max(s - 0.28, 0.0) / 0.72) ** 2))
        half_x = (0.27 + 0.23 * smooth(s, -0.55, 0.0)) * dome
        half_z = (0.26 + 0.26 * smooth(s, -0.52, 0.05)) * dome
        back = -0.12 * (1 - smooth(s, -0.55, -0.1))  # the neck sits behind the face
        return half_z, half_x, back, 0.0  # the cross-section's axes are z, then x
    vertices, faces = revolve(1, profile, ends=8.0, sides=1.0)
    x, y, z = vertices[:, 0], vertices[:, 1], vertices[:, 2]
    front = z > 0.1
    vertices[:, 2] += front * (0.16 * np.exp(-((x / 0.09) ** 2 + ((y + 0.05) / 0.16) ** 2))  # nose
                               + 0.08 * np.exp(-((x / 0.2) ** 2 + ((y + 0.5) / 0.12) ** 2))  # chin
                               + 0.04 * np.exp(-(((y - 0.25) / 0.08) ** 2)))  # brow
    vertices[:, 0] += np.sign(x) * (np.abs(x) > 0.25) * 0.12 * np.exp(-(((y - 0.1) / 0.17) ** 2 + ((z + 0.03) / 0.13) ** 2))  # ears
    return vertices, faces


def head_colours(vertices):
    """Per-vertex colours for the head's picture: skin that warms toward the cheeks, a dark hair cap, white eyes with dark
    irises, a mouth. Positions are those of head() before it is centred."""
    x, y, z = vertices[:, 0], vertices[:, 1], vertices[:, 2]
    colours = np.zeros((len(vertices), 3))
    colours[:] = (222, 170, 138)
    colours += np.outer(np.cos(6 * x) * np.cos(4 * y), (10, 5, 4))
    hair = (y > 0.45) | ((z < -0.12) & (y > -0.25))
    colours[hair] = (74, 48, 30)
    for side in (-1, 1):
        eye = np.hypot(x - side * 0.2, y - 0.12) < 0.1
        iris = np.hypot(x - side * 0.2, y - 0.12) < 0.05
        colours[(z > 0.2) & eye] = (240, 240, 236)
        colours[(z > 0.2) & iris] = (52, 36, 30)
    colours[(z > 0.2) & (np.abs(x) < 0.14) & (np.abs(y + 0.28) < 0.03)] = (170, 84, 84)
    return np.clip(colours, 0, 255).astype(np.uint8)


def centred(vertices):
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    return (vertices - (low + high) / 2) * (LONGEST / float((high - low).max()))


def write_pair(out_dir, name, vertices, faces, surface, colours=None):
    colours_raw = None if colours is None else colours(vertices)
    vertices = centred(vertices)
    trimesh.Trimesh(vertices, faces, process=False).export(out_dir / f"{name}.glb")
    picture, _ = mesh_render.render(vertices, faces, "front", "+y", "+z", {**STYLE, "surface": surface}, colors=colours_raw)
    Image.fromarray(picture).save(out_dir / f"{name}.png", optimize=True)
    print(f"{name}: wrote {name}.glb ({len(faces)} faces) and {name}.png")


def shapes(out_dir):
    write_pair(out_dir, "cabinet", *cabinet(), surface=[190, 140, 84])
    write_pair(out_dir, "tool", *tool(), surface=[112, 128, 156])
    write_pair(out_dir, "head", *head(), surface=[222, 170, 138], colours=head_colours)


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "shapes":
        sys.exit(__doc__)
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    shapes(out_dir)


if __name__ == "__main__":
    main()
