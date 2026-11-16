import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'apply_material.py'
spec = importlib.util.spec_from_file_location('apply_material', MODULE)
mat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mat)


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def png(path, width=2, height=2, color=(120, 100, 80)):
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    pixels = b''.join(b'\0' + bytes(color) * width for _ in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def glb(path, extra=None):
    positions = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack('<3H', 0, 1, 2) + b'\0\0'
    binary = positions + indices
    data = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
            'buffers': [{'byteLength': len(binary)}],
            'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(positions)},
                            {'buffer': 0, 'byteOffset': len(positions), 'byteLength': 6}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]},
                          {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}]}
    if extra:
        data.update(extra)
    payload = json.dumps(data, separators=(',', ':')).encode()
    payload += b' ' * ((-len(payload)) % 4)
    total = 12 + 8 + len(payload) + 8 + len(binary)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, total) + struct.pack('<I4s', len(payload), b'JSON') + payload
                     + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.mesh = self.root / 'mesh.glb'
        glb(self.mesh)
        self.maps = self.root / 'maps'
        self.maps.mkdir()
        for name in mat.MAPS:
            png(self.maps / (name + '.png'))
        self.out = self.root / 'out'

    def tearDown(self):
        self.temp.cleanup()

    def test_inputs_and_overwrite_are_checked_before_output(self):
        with self.assertRaises(ValueError):
            mat.run(str(self.mesh), str(self.maps), str(self.out), False)
        self.assertFalse(self.out.exists())
        self.out.mkdir()
        sentinel = self.out / 'sentinel'
        sentinel.write_text('keep')
        with self.assertRaises(ValueError):
            mat.run(str(self.mesh), str(self.maps), str(self.out), True)
        self.assertEqual(sentinel.read_text(), 'keep')
        with self.assertRaises(ValueError):
            mat.validate('relative.glb', str(self.maps), str(self.root / 'new'), True)

    def test_invalid_or_mismatched_maps_are_rejected_without_output(self):
        png(self.maps / 'normal.png', width=4)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            mat.run(str(self.mesh), str(self.maps), str(self.out), True)
        png(self.maps / 'normal.png')
        path = self.maps / 'normal.png'
        path.write_bytes(path.read_bytes()[:-8])
        with self.assertRaises(ValueError):
            mat.run(str(self.mesh), str(self.maps), str(self.out), True)
        self.assertFalse(self.out.exists())

    def test_rejects_valid_crc_truncated_scanlines_and_illegal_ihdr(self):
        path = self.maps / 'normal.png'
        header = struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0)
        one_row = b'\0' + bytes((10, 20, 30)) * 2
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(one_row)) + chunk(b'IEND', b''))
        with self.assertRaises(ValueError):
            mat.run(str(self.mesh), str(self.maps), str(self.out), True)
        self.assertFalse(self.out.exists())
        illegal_header = struct.pack('>IIBBBBB', 2, 2, 4, 2, 0, 0, 0)
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', illegal_header) + chunk(b'IDAT', zlib.compress(one_row)) + chunk(b'IEND', b''))
        with self.assertRaises(ValueError):
            mat.run(str(self.mesh), str(self.maps), str(self.out), True)
        self.assertFalse(self.out.exists())

    def test_accepts_adam7_interlaced_scanlines(self):
        header = struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 1)
        pixel = bytes((10, 20, 30))
        # For 2x2, nonempty Adam7 passes are (0,0), (1,0), and row (0,1),(1,1).
        raw = b'\0' + pixel + b'\0' + pixel + b'\0' + pixel * 2
        path = self.root / 'adam7.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        self.assertEqual(mat.png_size(path), [2, 2])

    def test_skinned_or_external_resources_are_rejected(self):
        for extra in ({'skins': [{'joints': [0]}]}, {'animations': [{'channels': [], 'samplers': []}]},
                      {'images': [{'uri': '../private.png'}]}):
            glb(self.mesh, extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                mat.validate(str(self.mesh), str(self.maps), str(self.out), True)
        self.assertFalse(self.out.exists())

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('blender'), 'macOS and Blender are required for network-isolated integration')
    def test_real_blender_export_embeds_maps_and_keeps_inputs(self):
        before = hashlib.sha256(self.mesh.read_bytes()).hexdigest()
        record = mat.run(str(self.mesh), str(self.maps), str(self.out), True)
        self.assertEqual(record['status'], 'candidate')
        self.assertEqual(record['recipe']['mesh']['sha256'], before)
        self.assertEqual(hashlib.sha256(self.mesh.read_bytes()).hexdigest(), before)
        self.assertGreaterEqual(record['output_validation']['embedded_images'], 2)
        self.assertIn('blender_smart_project', next(iter(record['evidence']['uv_by_object'].values())))
        self.assertFalse(record['evidence']['game_ready'])
        old_hash = record['recipe']['maps']['basecolor']['sha256']
        png(self.maps / 'basecolor.png', color=(10, 80, 200))
        changed = mat.run(str(self.mesh), str(self.maps), str(self.root / 'second'), True)
        self.assertNotEqual(old_hash, changed['recipe']['maps']['basecolor']['sha256'])
        self.assertNotEqual(record['output_sha256'], changed['output_sha256'])


if __name__ == '__main__':
    unittest.main()
