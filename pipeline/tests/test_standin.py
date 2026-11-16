"""The stand-in adapter (adapters/standin/standin.py): no model, standard library only, the same output for the same
input, shaped like a real adapter's, and fast."""
import json
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
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
        self.assertLess(seconds, 1.0)
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

    def test_the_mesh_is_a_valid_small_glb(self):
        out = self.dir / "mesh" / "mesh.glb"
        self.assertLess(standin("mesh", "--image", self.image("a"), "--seed", 3, "--output", out), 1.0)
        data = out.read_bytes()
        magic, version, length = struct.unpack("<4sII", data[:12])
        self.assertEqual((magic, version, length), (b"glTF", 2, len(data)))
        size, kind = struct.unpack("<I4s", data[12:20])
        document = json.loads(data[20:20 + size])
        self.assertEqual(kind, b"JSON")
        self.assertEqual(document["accessors"][3]["count"], 960 * 3)
        self.assertLess(len(data), 64 * 1024)

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
