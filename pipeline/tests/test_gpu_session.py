"""The foreign-job scan and the session that holds the GPU lock once (gpu_session.py). No GPU, no real lock."""
import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gpu_session  # noqa: E402
import machine  # noqa: E402
from local_run import StepFailed  # noqa: E402


class ForeignJobTests(unittest.TestCase):
    def test_the_markers_are_the_scripts_or_programs_of_gpu_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            for name in ("make-image", "venv-python", "mesh_runner.py", "cpu-tool"):
                (folder / name).write_text("")
            base = {"sandbox": {"network": "deny"}, "licence": "MIT (a test entry)"}
            config = folder / "machine.json"
            config.write_text(json.dumps({"adapters": [
                {**base, "id": "img", "kind": "image", "gpu": True, "argv": [str(folder / "make-image"), "{prompt}"]},
                {**base, "id": "mesh", "kind": "image-to-mesh", "gpu": True,
                 "argv": [str(folder / "venv-python"), str(folder / "mesh_runner.py"), "{image}", "{output}"]},
                {**base, "id": "cpu", "kind": "text", "argv": [str(folder / "cpu-tool"), "{prompt}"]}]}))
            with patch.dict("os.environ", {machine.CONFIG_ENV: str(config)}):
                markers = gpu_session.gpu_markers()
            self.assertEqual(markers, {str(folder / "make-image"), str(folder / "mesh_runner.py")})  # stand-ins: none
            found = gpu_session._is_foreign_gpu_generator
            self.assertTrue(found(f"{folder}/make-image --prompt cat", markers))
            self.assertTrue(found(f"{folder}/venv-python {folder}/mesh_runner.py in.png out.glb", markers))
            self.assertFalse(found(f"{folder}/venv-python /tmp/ordinary_script.py", markers))
            self.assertFalse(found(f"{folder}/cpu-tool hello", markers))
            self.assertFalse(found(f'python /tmp/custom.py --prompt "{folder}/make-image"x', markers))

    def test_process_inspection_denied_prevents_gpu_work(self):
        with patch.object(gpu_session, "_ancestors", side_effect=PermissionError("sandbox")):
            with self.assertRaises(StepFailed):
                gpu_session.foreign_gpu_jobs()

    def test_a_lock_that_cannot_be_placed_is_a_failed_step_naming_the_key(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "machine.json"
            config.write_text(json.dumps({}))
            with patch.dict("os.environ", {machine.CONFIG_ENV: str(config)}):
                with self.assertRaisesRegex(StepFailed, "gpu_lock"):
                    with gpu_session.gpu_lock(lambda message: None, max_wait_s=1):
                        pass


class SessionTests(unittest.TestCase):
    def test_the_lock_is_taken_once_held_across_calls_and_released_on_close(self):
        events = []

        @contextlib.contextmanager
        def acquire(log, max_wait_s):
            events.append(("acquire", max_wait_s))
            try:
                yield
            finally:
                events.append(("release",))

        with gpu_session.GpuSession(print, 77, acquire) as session:
            self.assertFalse(session.held)
            session.hold()
            session.hold()
            self.assertTrue(session.held)
        self.assertEqual(events, [("acquire", 77), ("release",)])
        self.assertFalse(session.held)

    def test_a_session_that_never_holds_never_touches_the_lock(self):
        with patch.object(gpu_session, "gpu_lock", side_effect=AssertionError("must not be taken")):
            with gpu_session.GpuSession(print, 1):
                pass


if __name__ == "__main__":
    unittest.main()
