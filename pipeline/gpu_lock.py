"""The machine-wide GPU lock: one owner-recorded lock that every GPU job on this computer takes.

    python3 pipeline/gpu_lock.py status [--path P]
    python3 pipeline/gpu_lock.py run [--path P] [--timeout S] [--label TEXT] -- COMMAND [ARGS...]

On a 16 GB machine the lock guards memory: two models loaded at once make the machine swap or
kill a job. Docs: docs/gpu_lock.md. Any path works for `run --path`; only the default path is special.

The path (ONE function, `default_lock_path`, which asks host.gpu_lock_path): the `gpu_lock` key of the machine config
(machine.py: the file named by env GENSTAGE_MACHINE_CONFIG, else ~/.config/generative-stage/machine.json). There is no
fallback: a missing key is an error that names the key and the file.

Lock file (version 1): a small JSON file at the lock path with the owner's pid, its process start
time, a label (what it is running) and the time it was taken. Pid plus start time is the identity:
the file lives in the home folder and survives a reboot, after which the old pid can belong to an
unrelated process. The start time is the text of `ps -o lstart=` (run with TZ=UTC and LC_ALL=C so
a different timezone cannot make a live owner look different). Why ps and not ctypes
`proc_pidinfo`: no struct layout to get wrong across macOS versions, no new dependency, and one
second is plenty because a recycled pid also needs a new start time at least a boot away.

Sequence of one attempt (`try_acquire`):
 1. Write our own complete lock text to a temp file next to the lock path.
 2. `os.link(temp, lock)`. This is atomic and fails if the lock exists, and the lock appears
    with its content already in it, so a kill at any moment cannot leave an owner-less new lock.
    Success: we hold it.
 3. The lock exists, so look at it. A lock is STALE when its pid has no process, or the pid is
    alive but its start time differs from the recorded one (a recycled pid). A start time we
    cannot read for a live pid counts as live. A lock held by a live owner is never removed,
    whatever its age.
 4. Stale: take the takeover mutex (`flock` on `<lock>.takeover`; the OS drops it when its
    holder dies, so it cannot itself go stale), look again (someone else may have won
    meanwhile), and if still stale `os.rename(temp, lock)`. That one rename replaces the stale
    lock atomically: the lock path never disappears, and because the look-again and the rename
    happen under the mutex, two contenders cannot both win (the second sees the first's live
    lock and waits).
 5. Release: delete the lock only if it still holds our pid and start time.

Legacy locks (the old `mkdir` folder at the same path), respected until every caller has moved:
  - folder with an `owner` file naming a live process: blocks.
  - folder with an `owner` file naming a dead process: taken over (folder renamed aside under the
    mutex, then step 2).
  - folder with NO owner file: cannot be proved stale (a live holder is indistinguishable from a
    crashed one, and a holder may be milliseconds between `mkdir` and writing its owner file), so
    it blocks until the caller's timeout and the error says how to clear it by hand. Wrongly
    removing a live lock lets two models load at once; wrongly waiting costs a message.
  - the legacy owner file has a pid but no start time, so a live recycled pid blocks until the
    timeout; the error gives the same hand-clear instructions.

Released on normal exit, on an exception, on SIGINT (KeyboardInterrupt) and on SIGTERM (turned
into SystemExit by `held`, when the caller has not installed its own handler). After SIGKILL
nothing runs; the next taker finds the dead pid and takes over.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host  # noqa: E402
import machine  # noqa: E402

POLL_S = 5.0
LOG_EVERY_S = 300.0
LOCK_VERSION = 1


class LockError(RuntimeError):
    """The lock could not be taken or the path could not be resolved; the message says why."""


class LockTimeout(LockError):
    """The wait ran out. The message names the owner (pid, command, since when)."""


# ---------------------------------------------------------------- path

def default_lock_path(environ=None, home=None) -> Path:
    """The one place the lock path is decided (see the module docstring)."""
    try:
        return host.gpu_lock_path(environ, home)
    except machine.MachineError as error:
        raise LockError(str(error)) from error


# ---------------------------------------------------------------- process identity

def process_start_time(pid: int):
    """Start time of a process as an opaque text token, or None when it cannot be read."""
    env = {**os.environ, "TZ": "UTC", "LC_ALL": "C"}
    try:
        result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                                text=True, env=env, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    text = " ".join(result.stdout.split())
    return text if result.returncode == 0 and text else None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------- reading a lock

def _since() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _clear_hint(path: Path) -> str:
    return (f"If nothing is running, clear it by hand with `rm -r {path}` "
            f"(check first: `python3 pipeline/gpu_lock.py status --path {path}`)")


def _inspect(path: Path, start_time_of, alive):
    """What is at `path`: ("free",), ("stale", text), ("live", text) or ("unprovable", text)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return ("free",)
    if os.path.isdir(path) and not os.path.islink(path):
        owner = path / "owner"
        try:
            text = owner.read_text(errors="replace").strip()
        except OSError:
            text = ""
        if not text:
            return ("unprovable", f"legacy lock folder {path} has no owner file, so it cannot be proved stale. "
                                  + _clear_hint(path))
        match = re.search(r"\bpid\s+(\d+)", text) or re.fullmatch(r"(\d+)", text)
        if not match:
            return ("unprovable", f"legacy lock folder {path} has an owner file I cannot read ({text[:80]!r}). "
                                  + _clear_hint(path))
        pid = int(match.group(1))
        what = f"legacy owner pid {pid} ({text[:80]})"
        return ("live", what) if alive(pid) else ("stale", what)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        pid, start = int(record["pid"]), record.get("start")
    except FileNotFoundError:
        return ("free",)
    except (OSError, ValueError, KeyError, TypeError):
        return ("unprovable", f"lock {path} is not a lock file I wrote and cannot be read. " + _clear_hint(path))
    what = f"pid {pid}, command {record.get('label', '?')!r}, since {record.get('since', '?')}"
    if not alive(pid):
        return ("stale", what)
    current = start_time_of(pid)
    if start is not None and current is not None and current != start:
        return ("stale", what + f" (pid reused: started {current!r}, lock says {start!r})")
    return ("live", what)


def status(path, start_time_of=process_start_time, alive=pid_alive):
    """("free",) | ("live", who) | ("stale", who) | ("unprovable", why), for the CLI and tests."""
    return _inspect(Path(path), start_time_of, alive)


# ---------------------------------------------------------------- taking and releasing

class Blocked(Exception):
    """try_acquire could not take the lock; .why names the owner."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


class Lease:
    """A lock we hold. Release it with .release() (held() does)."""

    def __init__(self, path, text):
        self.path, self._text = Path(path), text

    def release(self) -> None:
        try:
            if self.path.read_text(encoding="utf-8") == self._text:
                self.path.unlink()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            pass


def try_acquire(path, owner_label, *, start_time_of=process_start_time, alive=pid_alive) -> Lease:
    """One attempt, no waiting. Returns a Lease or raises Blocked. See the module docstring."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    text = json.dumps({"v": LOCK_VERSION, "pid": pid, "start": start_time_of(pid),
                       "label": owner_label, "since": _since()}) + "\n"
    temp = path.with_name(f"{path.name}.{pid}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(text, encoding="utf-8")
    try:
        for _ in range(5):  # a lock that vanishes between our look and our move is simply retried
            try:
                os.link(temp, path)
                return Lease(path, text)
            except FileExistsError:
                pass
            state = _inspect(path, start_time_of, alive)
            if state[0] == "free":
                continue
            if state[0] != "stale":
                raise Blocked(state[1])
            if _take_over(path, temp, start_time_of, alive):
                return Lease(path, text)
            # lost the takeover (or it went live meanwhile): look again
        raise Blocked("lock keeps changing under me; will retry")
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()


def _take_over(path: Path, temp: Path, start_time_of, alive) -> bool:
    with open(path.with_name(path.name + ".takeover"), "a") as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        state = _inspect(path, start_time_of, alive)  # someone may have won while we waited
        if state[0] != "stale":
            return False
        if os.path.isdir(path) and not os.path.islink(path):
            aside = path.with_name(f"{path.name}.legacy-{os.getpid()}-{uuid.uuid4().hex[:6]}")
            os.rename(path, aside)
            shutil.rmtree(aside, ignore_errors=True)
            try:
                os.link(temp, path)  # a fresh creator may have slipped in: then we lost
            except FileExistsError:
                return False
            return True
        os.rename(temp, path)  # THE atomic takeover
        return True


@contextlib.contextmanager
def _sigterm_releases():
    """Turn SIGTERM into SystemExit so `finally` runs, unless the caller has its own handler."""
    if threading.current_thread() is not threading.main_thread() or signal.getsignal(signal.SIGTERM) != signal.SIG_DFL:
        yield
        return

    def handler(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)


@contextlib.contextmanager
def held(path, owner_label, timeout_s, log=print, *, poll_s=POLL_S, start_time_of=process_start_time,
         alive=pid_alive, wait_while=None):
    """Hold the lock at `path` for the block. Waits up to timeout_s (0 = one try), then raises
    LockTimeout naming the owner. `wait_while`, if given, is called before each try and again
    after we win; a non-empty text it returns is a reason to wait (we release and keep waiting)."""
    deadline = time.monotonic() + timeout_s
    next_log = 0.0
    with _sigterm_releases():
        while True:
            reason, lease = None, None
            if wait_while is not None:
                reason = wait_while()
            if not reason:
                try:
                    lease = try_acquire(path, owner_label, start_time_of=start_time_of, alive=alive)
                    reason = wait_while() if wait_while is not None else None
                    if reason:
                        lease.release()
                        lease = None
                except Blocked as blocked:
                    reason = blocked.why
            if lease is not None:
                break
            if time.monotonic() >= deadline:
                raise LockTimeout(f"GPU lock {path} not free after {timeout_s:g} s: {reason}")
            if time.monotonic() >= next_log:
                log(f"waiting for GPU lock {path}: {reason}")
                next_log = time.monotonic() + LOG_EVERY_S
            time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))
        try:
            yield lease
        finally:
            lease.release()


# ---------------------------------------------------------------- CLI

def _run(args) -> int:
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("gpu_lock.py run: give a command after --", file=sys.stderr)
        return 2
    label = args.label or " ".join(command)[:200]
    path = Path(args.path) if args.path else default_lock_path()
    with held(path, label, args.timeout, lambda m: print(m, file=sys.stderr, flush=True)):
        child = subprocess.Popen(command)

        def forward(signum, frame):
            with contextlib.suppress(ProcessLookupError):
                child.send_signal(signum)
        previous = {s: signal.signal(s, forward) for s in (signal.SIGTERM, signal.SIGINT)}
        try:
            code = child.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return 128 - code if code < 0 else code  # death by signal N -> 128 + N


def _status(args) -> int:
    path = Path(args.path) if args.path else default_lock_path()
    state = status(path)
    print(f"{path}: " + (" ".join(str(x) for x in state)))
    return {"free": 0, "live": 1, "stale": 2, "unprovable": 1}[state[0]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="print who holds the lock (exit 0 free, 1 held, 2 stale)")
    st.add_argument("--path")
    run = sub.add_parser("run", help="hold the lock while COMMAND runs")
    run.add_argument("--path")
    run.add_argument("--timeout", type=float, default=1800.0, help="seconds to wait for the lock")
    run.add_argument("--label")
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        return _run(args) if args.cmd == "run" else _status(args)
    except LockError as error:
        print(f"gpu_lock.py: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
