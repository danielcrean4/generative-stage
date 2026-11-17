"""The stand-in adapter (adapters/standin/standin.py): no model, standard library only, the same output for the same
input, shaped like a real adapter's, and fast. The picture is a procedural drawing chosen by the prompt's words; the mesh
is raised from the picture's silhouette."""
import json
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "adapters" / "standin"))
import standin_solid  # noqa: E402

STANDIN = REPO / "adapters" / "standin" / "standin.py"


def standin(*args):
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-I", str(STANDIN), *map(str, args)], capture_output=True, text=True,
                            timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return time.monotonic() - started


class StandinTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def image(self, name, seed=1, size=(320, 192), prompt="a lamp"):
        out = self.dir / name / "image.png"
        seconds = standin("image", f"--prompt={prompt}", "--seed", seed, "--width", size[0], "--height", size[1],
                          "--output", out)
        self.assertLess(seconds, 20.0)
        return out

    def test_the_image_is_a_png_of_the_asked_size_and_the_same_for_the_same_input(self):
        first, again, other = self.image("a"), self.image("b"), self.image("c", seed=2)
        data = first.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (320, 192))
        self.assertEqual(data, again.read_bytes())
        self.assertNotEqual(data, other.read_bytes())
        self.assertEqual(json.loads((first.parent / "identity.json").read_text())["name"], "standin")

    def test_a_prompt_that_looks_like_an_option_is_still_the_prompt(self):
        self.image("dash", prompt="--output /etc/passwd")

    def test_the_prompt_chooses_the_family_and_each_family_is_its_own_picture(self):
        sys.path.insert(0, str(STANDIN.parent))
        try:
            import standin_subjects as subjects
        finally:
            sys.path.pop(0)
        cases = {"a driftwood fiddle with brass pegs": "instrument", "a brass signal lantern": "lantern",
                 "a swollen tide table notebook": "book", "the keeper of the lighthouse, a woman": "figure",
                 "a blue glazed vase": "vessel", "a mysterious thing": "gem", "": "gem"}
        for prompt, family in cases.items():
            self.assertEqual(subjects.family_for(prompt), family, prompt)
        pictures = {family: self.image(family, prompt=prompt).read_bytes() for prompt, family in cases.items()
                    if prompt}
        self.assertEqual(len(set(pictures.values())), len(pictures))

    def test_the_picture_is_a_subject_on_plain_white_and_not_a_disc(self):
        width, height, channels, rows = standin_solid.read_png(self.image("a", prompt="a fiddle").read_bytes())
        self.assertEqual((width, height, channels), (320, 192, 3))
        self.assertEqual(bytes(rows[0]), b"\xff" * width * 3)  # the border is plain white
        self.assertEqual(bytes(rows[-1]), b"\xff" * width * 3)
        subject = standin_solid.Subject(self.image("a", prompt="a fiddle").read_bytes())
        covered = sum(map(sum, subject.mask)) / (width * height)
        self.assertTrue(0.1 < covered < 0.6, covered)
        colours = {bytes(row[x:x + 3]) for row in rows for x in range(0, width * 3, 3)}
        self.assertGreater(len(colours), 500)  # shaded, not flat

    def test_the_seed_changes_the_drawing_but_not_the_family(self):
        a = self.image("a", seed=1, prompt="a lute").read_bytes()
        b = self.image("b", seed=2, prompt="a lute").read_bytes()
        self.assertNotEqual(a, b)

    def mesh(self, picture, name="mesh"):
        out = self.dir / name / "mesh.glb"
        self.assertLess(standin("mesh", "--image", picture, "--seed", 3, "--output", out), 10.0)
        data = out.read_bytes()
        magic, version, length = struct.unpack("<4sII", data[:12])
        self.assertEqual((magic, version, length), (b"glTF", 2, len(data)))
        size, kind = struct.unpack("<I4s", data[12:20])
        self.assertEqual(kind, b"JSON")
        document = json.loads(data[20:20 + size])
        offset = 20 + size + 8
        count = document["accessors"][0]["count"]
        points = struct.unpack(f"<{count * 3}f", data[offset:offset + count * 12])
        index = document["bufferViews"][3]
        triangles = struct.unpack(f"<{index['byteLength'] // 4}I",
                                  data[offset + index["byteOffset"]:offset + index["byteOffset"] + index["byteLength"]])
        return document, data, points, triangles

    def test_the_mesh_is_a_closed_solid_of_a_few_thousand_faces_coloured_from_the_image(self):
        picture = self.image("a", size=(512, 512), prompt="a driftwood fiddle")
        document, data, points, triangles = self.mesh(picture)
        faces = len(triangles) // 3
        self.assertTrue(2000 < faces < 9000, faces)
        self.assertLess(len(data), 600 * 1024)
        self.assertEqual(document["meshes"][0]["primitives"][0]["attributes"], {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2})
        # closed: every undirected edge is shared by exactly two faces, each time in opposite directions
        directed = {}
        for i in range(0, len(triangles), 3):
            a, b, c = triangles[i:i + 3]
            for edge in ((a, b), (b, c), (c, a)):
                directed[edge] = directed.get(edge, 0) + 1
        self.assertTrue(all(n == 1 and (e[1], e[0]) in directed for e, n in directed.items()))
        # outward: the signed volume is positive
        volume = 0.0
        for i in range(0, len(triangles), 3):
            p = [points[3 * t:3 * t + 3] for t in triangles[i:i + 3]]
            volume += sum(p[0][k] * (p[1][(k + 1) % 3] * p[2][(k + 2) % 3] - p[1][(k + 2) % 3] * p[2][(k + 1) % 3])
                          for k in range(3)) / 6
        self.assertGreater(volume, 0)

    def test_the_mesh_has_the_outline_of_the_picture_seen_from_the_front(self):
        picture = self.image("a", size=(512, 512), prompt="a brass lantern")
        subject = standin_solid.Subject(picture.read_bytes())
        _, _, points, _ = self.mesh(picture)
        xs, ys = points[0::3], points[1::3]
        inside = [(x, y) for y, row in enumerate(subject.mask) for x, v in enumerate(row) if v]
        left, right = min(p[0] for p in inside), max(p[0] for p in inside) + 1
        top, bottom = min(p[1] for p in inside), max(p[1] for p in inside) + 1
        scale = 2.0 / max(right - left, bottom - top)
        self.assertAlmostEqual(max(xs) - min(xs), (right - left) * scale, delta=0.03)
        self.assertAlmostEqual(max(ys) - min(ys), (bottom - top) * scale, delta=0.03)
        # the picture's top is the mesh's top (y up): the lantern's ring is on top, so the top is narrow
        self.assertGreater(max(ys), 0.9)
        self.assertGreater(max(points[2::3]), 0.1)  # it has depth, not a sheet

    def test_the_mesh_is_the_same_for_the_same_picture_and_differs_for_another(self):
        one, two = self.image("a", prompt="a lantern"), self.image("b", prompt="a notebook")
        self.assertEqual(self.mesh(one, "m1")[1], self.mesh(one, "m2")[1])
        self.assertNotEqual(self.mesh(one, "m3")[1], self.mesh(two, "m4")[1])

    def test_text_and_review_are_shaped_like_the_real_adapters(self):
        text, review = self.dir / "t" / "text.txt", self.dir / "r" / "review.json"
        standin("text", "--prompt=a lamp", "--seed", 4, "--output", text)
        self.assertIn("a lamp", text.read_text())
        standin("review", "--image", self.image("a"), "--prompt=is it round", "--seed", 4, "--output", review)
        verdict = json.loads(review.read_text())
        self.assertEqual(sorted(verdict), ["findings", "id", "score", "uncertainty"])
        self.assertIn(verdict["score"], range(1, 6))


if __name__ == "__main__":
    unittest.main()
