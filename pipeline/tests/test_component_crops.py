import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Pillow is required for component crops')
class ComponentCropsTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('component_crops', Path(__file__).resolve().parents[1] / 'component_crops.py')
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.png'
        Image.new('RGB', (20, 10), (20, 30, 40)).save(self.source)
        self.job = {'version': 1, 'source': str(self.source), 'components': [{'id': 'part', 'box': [.1, .2, .6, .8]}]}
        self.spec = self.root / 'job.json'

    def save(self):
        self.spec.write_text(json.dumps(self.job))

    def test_crop_has_recorded_bounds_and_hash(self):
        self.save()
        out = self.root / 'result'
        result = self.tool.prepare(self.spec, out)
        component = result['components'][0]
        self.assertEqual(component['pixel_box'], [2, 2, 12, 8])
        with Image.open(out / 'part.png') as image:
            self.assertEqual(image.size, (10, 6))
        self.assertEqual(component['sha256'], hashlib.sha256((out / 'part.png').read_bytes()).hexdigest())
        self.assertEqual(result['source_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            self.tool.prepare(self.spec, out)

    def test_invalid_boxes_and_duplicate_names_do_not_create_output(self):
        for components in ([{'id': 'part', 'box': [0, 0, 1.1, 1]}],
                           [{'id': '../bad', 'box': [0, 0, 1, 1]}],
                           [self.job['components'][0], self.job['components'][0]],
                           [{'id': 'part', 'box': [0, 0, 1, 1]}, {'id': 'Part', 'box': [0, 0, 1, 1]}]):
            self.job['components'] = components
            self.save()
            out = self.root / 'bad'
            with self.assertRaises(ValueError):
                self.tool.prepare(self.spec, out)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
