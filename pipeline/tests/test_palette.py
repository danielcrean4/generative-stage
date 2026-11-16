"""Palette loading and checks. Plain Python: python3 -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER = ROOT.parent / "blender"
sys.path.insert(0, str(BLENDER))

import palette  # noqa: E402


class PaletteTest(unittest.TestCase):
    def write(self, data: object) -> Path:
        path = Path(tempfile.mkstemp(suffix=".json")[1])
        path.write_text(json.dumps(data))
        self.addCleanup(path.unlink)
        return path

    def test_every_shipped_palette_loads(self) -> None:
        for path in (BLENDER / "palettes").glob("*.json"):
            with self.subTest(path.name):
                self.assertTrue(palette.load(path).colours)

    def test_reads_slots_and_defaults(self) -> None:
        pal = palette.load(self.write({"colours": {"metal": [[0.5, 0.5, 0.5]]}, "metallic": {"metal": 0.8}}))
        self.assertEqual(pal.colour("metal"), (0.5, 0.5, 0.5))
        self.assertEqual(pal.metallic["metal"], 0.8)
        self.assertEqual(pal.mended, 0.0)
        self.assertEqual(len(pal.sha256), 64)

    def test_rejects_bad_files(self) -> None:
        bad = [
            {},
            {"colours": {"a": []}},
            {"colours": {"a": [[1.2, 0, 0]]}},
            {"colours": {"a": [[0, 0]]}},
            {"colours": {"a": [[0, 0, 0]]}, "roughness": {"b": 0.5}},
            {"colours": {"a": [[0, 0, 0]]}, "mended": 2},
        ]
        for data in bad:
            with self.subTest(data), self.assertRaises(ValueError):
                palette.load(self.write(data))

    def test_to_linear_matches_srgb_curve(self) -> None:
        self.assertEqual(palette.to_linear((0.0, 1.0, 0.04045)), (0.0, 1.0, 0.04045 / 12.92))
        self.assertAlmostEqual(palette.to_linear((0.5, 0.5, 0.5))[0], 0.21404, places=4)


if __name__ == "__main__":
    unittest.main()
