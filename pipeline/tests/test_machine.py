"""Machine settings (machine.py): where models, interpreters and the GPU lock live. Nothing is guessed."""
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gpu_lock  # noqa: E402
import machine  # noqa: E402
import old_names  # noqa: E402

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

    def test_the_file_used_before_the_rename_is_read_while_the_new_one_is_missing(self):
        old = self.home / ".config" / old_names.OLD_FOLDERS[0]
        old.mkdir(parents=True)
        (old / "machine.json").write_text(json.dumps({"gpu_lock": "~/old-lock"}))
        new = self.home / ".config/generative-stage"
        new.mkdir(parents=True)
        (new / "server.json").write_text("{}")  # another file has moved; this one has not: it is still found
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(machine.path("gpu_lock", {}, self.home), self.home / "old-lock")
        self.assertIn("migrate_home.py", err.getvalue())
        (new / "machine.json").write_text("{}")  # once the new file exists, only it is read
        self.assertEqual(machine.config_file({}, self.home), new / "machine.json")

    def test_the_variable_used_before_the_rename_is_read_with_a_note(self):
        file = self.write({"gpu_lock": "/lock"})
        old_variable = old_names.OLD_PREFIX + machine.CONFIG_NAME
        old_names._noted.clear()  # the note is printed once per process
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(machine.config_file({old_variable: str(file)}, self.home), file)
        self.assertIn(machine.CONFIG_ENV, err.getvalue())
        other = self.write({}, "other.json")  # the new name wins over the old one
        self.assertEqual(machine.config_file({old_variable: str(file), machine.CONFIG_ENV: str(other)}, self.home), other)

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
