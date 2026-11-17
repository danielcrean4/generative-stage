"""Machine settings (machine.py): where models, interpreters and the GPU lock live. Nothing is guessed."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gpu_lock  # noqa: E402
import machine  # noqa: E402

PIPELINE = Path(__file__).resolve().parents[1]


class MachineConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.home = self.dir / "home"
        self.home.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, value, name="machine.json"):
        file = self.dir / name
        file.write_text(json.dumps(value))
        return file

    def test_value_forms(self):
        file = self.write({"gpu_lock": "~/locks/gpu", "tools_python": "/abs/python", "icon_dir": "icons"})
        env = {machine.CONFIG_ENV: str(file)}
        self.assertEqual(machine.path("gpu_lock", env, self.home), self.home / "locks/gpu")
        self.assertEqual(machine.path("tools_python", env, self.home), Path("/abs/python"))
        self.assertEqual(machine.path("icon_dir", env, self.home), self.dir / "icons")  # relative: from the file's folder

    def test_default_file_is_under_the_home_folder(self):
        (self.home / ".config/generative-stage").mkdir(parents=True)
        (self.home / ".config/generative-stage/machine.json").write_text(json.dumps({"gpu_lock": "~/lock"}))
        self.assertEqual(machine.path("gpu_lock", {}, self.home), self.home / "lock")

    def test_a_missing_key_names_the_key_and_the_file(self):
        file = self.write({})
        with self.assertRaises(machine.MachineError) as raised:
            machine.path("tools_python", {machine.CONFIG_ENV: str(file)}, self.home)
        self.assertIn("tools_python", str(raised.exception))
        self.assertIn(str(file), str(raised.exception))

    def test_no_file_at_all_is_a_missing_key_not_a_guess(self):
        with self.assertRaisesRegex(machine.MachineError, "icon_dir"):
            machine.path("icon_dir", {}, self.home)

    def test_bad_files_and_values_are_errors(self):
        for content, pattern in (("not json", "JSON"), ("[]", "JSON object"), ('{"nonsense": "x"}', "unknown key"), ('{"icon_dir": ""}', "non-empty")):
            file = self.dir / "bad.json"
            file.write_text(content)
            with self.subTest(content=content), self.assertRaisesRegex(machine.MachineError, pattern):
                machine.path("icon_dir", {machine.CONFIG_ENV: str(file)}, self.home)
        with self.assertRaisesRegex(machine.MachineError, "not a file"):
            machine.path("icon_dir", {machine.CONFIG_ENV: str(self.dir / "missing.json")}, self.home)

    def test_the_gpu_lock_path_comes_only_from_the_config(self):
        file = self.write({"gpu_lock": "rel/lock"})
        self.assertEqual(gpu_lock.default_lock_path({machine.CONFIG_ENV: str(file)}, self.home), self.dir / "rel/lock")
        with self.assertRaisesRegex(gpu_lock.LockError, "gpu_lock"):
            gpu_lock.default_lock_path({machine.CONFIG_ENV: str(self.write({}, "empty.json"))}, self.home)


class NoMachinePathsInTheSourceTests(unittest.TestCase):
    """The pipeline's own code names no computer: no home-folder paths, no checkout of someone's models."""

    def test_no_hard_coded_machine_paths(self):
        pattern = re.compile(r"Developer/|spikes|/Users/|Path\.home\(\) */ *['\"]")
        found = []
        for source in sorted(PIPELINE.glob("*.py")) + sorted((PIPELINE.parent / "adapters").rglob("*.py")):
            for number, line in enumerate(source.read_text().splitlines(), 1):
                if pattern.search(line):
                    found.append(f"{source.name}:{number}: {line.strip()}")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
