"""Model identity and the small hashing helpers (provenance.py). No model files are read."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provenance  # noqa: E402
from local_run import StepFailed  # noqa: E402


class ModelIdentityCacheTests(unittest.TestCase):
    """A stand-in weights folder and an injected hasher; the real weights are never read."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.weights = self.root / "weights"
        (self.weights / "sub").mkdir(parents=True)
        (self.weights / "a.bin").write_bytes(b"aaaa")
        (self.weights / "sub" / "b.bin").write_bytes(b"bb")
        self.cache = self.root / "identity.json"
        self.hashed = []

    def tearDown(self):
        self.temp.cleanup()

    def hasher(self, path):
        self.hashed.append(path.name)
        return "hash-of-" + path.name

    def identity(self):
        return provenance.cached_model_identity(self.weights, self.cache, self.hasher)

    def test_second_call_is_served_from_the_cache_file(self):
        first = self.identity()
        self.assertEqual(sorted(self.hashed), ["a.bin", "b.bin"])
        self.hashed.clear()
        self.assertEqual(self.identity(), first)
        self.assertEqual(self.hashed, [])
        self.assertTrue(self.cache.is_file())
        self.assertEqual(first, provenance.model_identity_uncached(self.weights, self.hasher))  # same value as before the cache

    def test_touching_a_file_or_changing_the_file_list_rehashes(self):
        self.identity()
        self.hashed.clear()
        (self.weights / "a.bin").write_bytes(b"aaaa")  # same size, new mtime
        os.utime(self.weights / "a.bin", ns=(1, 2))
        self.identity()
        self.assertEqual(sorted(self.hashed), ["a.bin", "b.bin"])
        self.hashed.clear()
        self.identity()
        self.assertEqual(self.hashed, [])
        (self.weights / "c.bin").write_bytes(b"c")
        self.identity()
        self.assertIn("c.bin", self.hashed)

    def test_other_folders_and_a_corrupt_cache_file_are_handled(self):
        self.cache.write_text("not json")
        self.identity()
        self.assertEqual(len(self.hashed), 2)
        other = self.root / "other"
        other.mkdir()
        (other / "x.bin").write_bytes(b"x")
        provenance.cached_model_identity(other, self.cache, self.hasher)
        self.hashed.clear()
        self.identity()
        self.assertEqual(self.hashed, [])
        with self.assertRaises(StepFailed):
            provenance.cached_model_identity(self.root / "empty-nonexistent", self.cache, self.hasher)


class HelperTests(unittest.TestCase):
    def test_digest_fingerprint_and_atomic_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "a.json"
            provenance.atomic_json(path, {"b": 1, "a": [2]})
            self.assertEqual(provenance.read_json(path, None), {"b": 1, "a": [2]})
            self.assertFalse(list(Path(temp).glob("*.tmp")))
            self.assertEqual(provenance.digest(path), __import__("hashlib").sha256(path.read_bytes()).hexdigest())
            self.assertEqual(provenance.fingerprint({"b": 1, "a": 2}), provenance.fingerprint({"a": 2, "b": 1}))
            self.assertEqual(provenance.read_json(Path(temp) / "missing.json", "fallback"), "fallback")
            path.write_text("not json")
            self.assertEqual(provenance.read_json(path, "fallback"), "fallback")

    def test_identity_cache_location_follows_the_environment(self):
        os.environ[provenance.IDENTITY_CACHE_ENV] = "/somewhere/else.json"
        try:
            self.assertEqual(provenance.identity_cache_path(), Path("/somewhere/else.json"))
        finally:
            del os.environ[provenance.IDENTITY_CACHE_ENV]


if __name__ == "__main__":
    unittest.main()
