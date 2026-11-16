import json
import tempfile
import unittest
from pathlib import Path

import venv_tool

SIZE = 128


class MatteTests(unittest.TestCase):
    def setUp(self):
        venv_tool.require_venv(self)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def matte(self, discs, *extra, name="out"):
        image = self.root / f"{name}.png"
        venv_tool.write_discs(image, SIZE, discs)
        result = venv_tool.run_tool("matte.py", image, "--out", self.root / name, *extra)
        return result, json.loads((self.root / name / "matte.json").read_text())

    def test_single_disc_passes(self):
        result, report = self.matte([(64, 64, 30)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report["passed"])
        self.assertEqual(report["component_count"], 1)
        self.assertEqual(report["border_contact"], [])
        self.assertEqual(report["image_size"], [SIZE, SIZE])

    def test_two_far_discs_fail_on_largest_component(self):
        result, report = self.matte([(30, 30, 18), (98, 98, 18)])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["component_count"], 2)
        self.assertIn("largest subject component", result.stderr)

    def test_border_contact_needs_allow_border(self):
        result, report = self.matte([(10, 64, 30)])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["border_contact"], ["left"])
        self.assertIn("border", result.stderr)
        allowed, report = self.matte([(10, 64, 30)], "--allow-border", name="allowed")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertTrue(report["passed"])

    def test_output_is_byte_identical_across_runs(self):
        first = self.root / "first"
        second = self.root / "second"
        image = self.root / "same.png"
        venv_tool.write_discs(image, SIZE, [(64, 64, 30)])
        for out in (first, second):
            venv_tool.run_tool("matte.py", image, "--out", out)
        for name in ("matte.png", "matte.json"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())

    def test_a_transparent_background_with_black_under_it_is_not_subject(self):
        """The tidied image (normalize_image, rgba) has alpha 0 and black outside the subject; the matte must read the alpha."""
        image = self.root / "rgba.png"
        venv_tool.run_code(
            "import sys; from PIL import Image, ImageDraw; im = Image.new('RGBA', (128, 128), (0, 0, 0, 0)); "
            "ImageDraw.Draw(im).ellipse([34, 34, 94, 94], fill=(200, 60, 40, 255)); im.save(sys.argv[1])", image)
        result = venv_tool.run_tool("matte.py", image, "--out", self.root / "rgba")
        report = json.loads((self.root / "rgba" / "matte.json").read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(report["subject_share"], 0.3)
        self.assertEqual(report["border_contact"], [])

    def test_alpha_marks_the_subject(self):
        self.matte([(64, 64, 30)])
        corner_and_centre = venv_tool.run_code(
            "import sys; from PIL import Image; a = Image.open(sys.argv[1]).getchannel('A'); "
            "print(a.getpixel((2, 2)), a.getpixel((64, 64)))", self.root / "out/matte.png")
        self.assertEqual(corner_and_centre.split(), ["0", "255"])


if __name__ == "__main__":
    unittest.main()
