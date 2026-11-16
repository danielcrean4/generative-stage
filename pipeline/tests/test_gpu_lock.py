"""Tests for pipeline/gpu_lock.py. Stand-in children only (sleep, tiny Python); every lock lives in a
temp folder, never at the real lock path. Prints GPU_LOCK cases=<n> ok=<n>."""
import functools
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import gpu_lock as gl  # noqa: E402

TALLY = {"cases": 0, "ok": 0}
CHILD_HOLDER = ("import sys,time; sys.path.insert(0,%r); import gpu_lock as g; "
                "g.try_acquire(sys.argv[1], 'child holder'); print('held', flush=True); time.sleep(60)") % str(TOOLS)
CHILD_RACER = ("import sys,time,os; sys.path.insert(0,%r); import gpu_lock as g\n"
               "go=sys.argv[2]\n"
               "while not os.path.exists(go): pass\n"
               "try:\n g.try_acquire(sys.argv[1], 'racer'); print('WON', flush=True)\n"
               "except g.Blocked: print('LOST', flush=True)\n"
               "time.sleep(60)\n") % str(TOOLS)


def case(function):
    @functools.wraps(function)
    def wrapper(self):
        TALLY["cases"] += 1
        function(self)
        TALLY["ok"] += 1
    return wrapper


def tearDownModule():
    print(f"GPU_LOCK cases={TALLY['cases']} ok={TALLY['ok']}")


def dead_pid():
    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


def write_lock(path, pid, start, label="old holder"):
    Path(path).write_text(json.dumps({"v": 1, "pid": pid, "start": start, "label": label,
                                      "since": "2026-01-01 00:00:00 UTC"}) + "\n")


class GpuLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.lock = self.dir / "gpu-lock"
        self.children = []

    def tearDown(self):
        for child in self.children:  # only processes this test started, by handle
            if child.poll() is None:
                child.kill()
            child.wait()
            for stream in (child.stdout, child.stdin):
                if stream:
                    stream.close()
        self.temp.cleanup()

    def spawn(self, *args, **kwargs):
        child = subprocess.Popen(list(args), stdout=subprocess.PIPE, text=True, **kwargs)
        self.children.append(child)
        return child

    def wait_for(self, predicate, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("timed out waiting")

    @case
    def test_take_and_release(self):
        with gl.held(self.lock, "me", 1, log=lambda m: None):
            record = json.loads(self.lock.read_text())
            self.assertEqual(record["pid"], os.getpid())
            self.assertEqual(record["label"], "me")
            self.assertEqual(gl.status(self.lock)[0], "live")
        self.assertFalse(self.lock.exists())
        self.assertEqual(gl.status(self.lock), ("free",))

    @case
    def test_released_on_exception(self):
        with self.assertRaises(ValueError), gl.held(self.lock, "me", 1, log=lambda m: None):
            raise ValueError("boom")
        self.assertFalse(self.lock.exists())

    @case
    def test_second_taker_waits_then_gets_it(self):
        order = []

        def first():
            with gl.held(self.lock, "first", 5, log=lambda m: None):
                order.append("first in")
                time.sleep(0.6)
                order.append("first out")
        thread = threading.Thread(target=first)
        thread.start()
        self.wait_for(self.lock.exists)
        start = time.monotonic()
        with gl.held(self.lock, "second", 10, log=lambda m: None, poll_s=0.05):
            order.append("second in")
        thread.join()
        self.assertEqual(order, ["first in", "first out", "second in"])
        self.assertGreaterEqual(time.monotonic() - start, 0.3)

    @case
    def test_timeout_error_names_owner(self):
        holder = self.spawn(sys.executable, "-c", CHILD_HOLDER, str(self.lock))
        self.assertEqual(holder.stdout.readline().strip(), "held")
        with self.assertRaises(gl.LockTimeout) as caught:
            with gl.held(self.lock, "waiter", 0.3, log=lambda m: None, poll_s=0.05):
                pass
        message = str(caught.exception)
        self.assertIn(f"pid {holder.pid}", message)
        self.assertIn("child holder", message)
        self.assertIn("since", message)
        self.assertEqual(json.loads(self.lock.read_text())["pid"], holder.pid)  # a live lock is never removed

    @case
    def test_holder_killed_with_sigkill_is_taken_over(self):
        holder = self.spawn(sys.executable, "-c", CHILD_HOLDER, str(self.lock))
        self.assertEqual(holder.stdout.readline().strip(), "held")
        os.kill(holder.pid, signal.SIGKILL)
        holder.wait()
        with gl.held(self.lock, "next", 5, log=lambda m: None, poll_s=0.05):
            self.assertEqual(json.loads(self.lock.read_text())["pid"], os.getpid())
        self.assertFalse(self.lock.exists())

    @case
    def test_recycled_pid_with_different_start_time_is_taken_over(self):
        write_lock(self.lock, os.getpid(), "start A")  # a live pid, so only the start time can tell
        same = lambda pid: "start A"
        different = lambda pid: "start B"
        self.assertEqual(gl.status(self.lock, start_time_of=same)[0], "live")
        self.assertEqual(gl.status(self.lock, start_time_of=different)[0], "stale")
        with self.assertRaises(gl.LockTimeout):  # same start: the same process still owns it
            with gl.held(self.lock, "x", 0, log=lambda m: None, start_time_of=same):
                pass
        with gl.held(self.lock, "x", 0, log=lambda m: None, start_time_of=different):
            record = json.loads(self.lock.read_text())
            self.assertEqual(record["label"], "x")
            self.assertEqual(record["start"], "start B")

    @case
    def test_real_start_time_of_this_process_is_readable_and_stable(self):
        first = gl.process_start_time(os.getpid())
        self.assertTrue(first)
        self.assertEqual(first, gl.process_start_time(os.getpid()))
        self.assertIsNone(gl.process_start_time(dead_pid()))

    @case
    def test_two_contenders_for_a_stale_lock_exactly_one_wins(self):
        for round_number in range(60):
            lock = self.dir / f"race-{round_number}"
            go = self.dir / f"go-{round_number}"
            write_lock(lock, dead_pid(), "whenever")
            racers = [self.spawn(sys.executable, "-c", CHILD_RACER, str(lock), str(go)) for _ in range(2)]
            time.sleep(0.25)  # both are spinning on the go file
            go.write_text("go")
            results = sorted(racer.stdout.readline().strip() for racer in racers)
            self.assertEqual(results, ["LOST", "WON"], f"round {round_number}")
            winner = json.loads(lock.read_text())["pid"]
            self.assertIn(winner, [racer.pid for racer in racers])
            for racer in racers:
                racer.kill()
                racer.wait()
                racer.stdout.close()
            self.children = [c for c in self.children if c not in racers]

    @case
    def test_legacy_folder_with_live_owner_blocks(self):
        self.lock.mkdir()
        (self.lock / "owner").write_text(f"legacy_tool.py pid {os.getpid()} since 10:00:00\n")
        with self.assertRaises(gl.LockTimeout) as caught:
            with gl.held(self.lock, "x", 0.2, log=lambda m: None, poll_s=0.05):
                pass
        self.assertIn(str(os.getpid()), str(caught.exception))
        self.assertTrue(self.lock.is_dir())

    @case
    def test_legacy_folder_with_dead_owner_is_taken_over(self):
        self.lock.mkdir()
        (self.lock / "owner").write_text(f"legacy_tool.py pid {dead_pid()} since 10:00:00\n")
        with gl.held(self.lock, "x", 2, log=lambda m: None, poll_s=0.05):
            self.assertTrue(self.lock.is_file())
        self.assertFalse(self.lock.exists())
        self.assertEqual([p.name for p in self.dir.glob("gpu-lock.legacy-*")], [])

    @case
    def test_legacy_folder_with_no_owner_file_blocks_with_hand_clear_message(self):
        self.lock.mkdir()
        with self.assertRaises(gl.LockTimeout) as caught:
            with gl.held(self.lock, "x", 0.2, log=lambda m: None, poll_s=0.05):
                pass
        self.assertIn(f"rm -r {self.lock}", str(caught.exception))
        self.assertIn("no owner file", str(caught.exception))
        self.assertTrue(self.lock.is_dir())

    @case
    def test_run_releases_on_sigterm_and_stops_its_child(self):
        wrapper = self.spawn(sys.executable, str(TOOLS / "gpu_lock.py"), "run", "--path", str(self.lock),
                             "--timeout", "5", "--", "sleep", "30")
        self.wait_for(self.lock.exists)
        self.assertEqual(json.loads(self.lock.read_text())["pid"], wrapper.pid)
        self.wait_for(lambda: subprocess.run(["pgrep", "-P", str(wrapper.pid)], capture_output=True).returncode == 0)
        child_pid = int(subprocess.run(["pgrep", "-P", str(wrapper.pid)], capture_output=True, text=True).stdout.split()[0])
        os.kill(wrapper.pid, signal.SIGTERM)
        wrapper.wait(timeout=15)
        self.assertFalse(self.lock.exists())
        self.assertFalse(gl.pid_alive(child_pid) and subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)],
                         capture_output=True, text=True).stdout.strip() not in ("", "Z"))

    @case
    def test_run_passes_exit_code_and_status_command(self):
        done = subprocess.run([sys.executable, str(TOOLS / "gpu_lock.py"), "run", "--path", str(self.lock), "--",
                               sys.executable, "-c", "import sys; sys.exit(7)"])
        self.assertEqual(done.returncode, 7)
        self.assertFalse(self.lock.exists())
        status = subprocess.run([sys.executable, str(TOOLS / "gpu_lock.py"), "status", "--path", str(self.lock)],
                                capture_output=True, text=True)
        self.assertEqual(status.returncode, 0)
        self.assertIn("free", status.stdout)


if __name__ == "__main__":
    unittest.main()
