"""Taking the machine GPU lock: `gpu_lock(log)` around one command, `GpuSession` for a whole job (plain Python;
docs/gpu_lock.md).

`gpu_lock(log, max_wait_s)` is the lock of gpu_lock.py plus a wait while some other program's model runs: a process,
not started by this job, running the program or a script of an adapter entry that holds the GPU lock (`"gpu": true`
in the machine config; `gpu_markers`). A tool that runs one model command takes it around that
command. A pipeline job takes it once: it creates ONE GpuSession at its entry point and passes it to the stage
runners. A runner calls `hold()` before a neural command; the first call takes the lock, later calls do nothing, and
the lock is released when the session closes (end of the job, an exception, SIGINT or SIGTERM). So the lock is held
across stages and seeds without being taken twice by the same process, which would wait on itself, and a run that
never reaches a neural stage (reused stages, or a run started from saved files) never touches the lock at all.

Nothing below the entry point takes the lock for this job: `pipeline_run`'s runners only call `hold()`.
"""
import contextlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

import adapter_config
import gpu_lock as gpu_lock_module
from local_run import StepFailed

LOCK_POLL_S = 20


def _ancestors() -> set[int]:
    pids, pid = set(), os.getpid()
    while pid > 1:
        pids.add(pid)
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        pid = int(out) if out else 0
    return pids


def gpu_markers(adapters=None) -> set[str]:
    """The paths that mark another program's model run: for each configured entry that holds the GPU lock, its fixed
    script arguments (absolute files in argv[1:] with no data placeholder), else its program. The interpreter running
    this pipeline is never a marker, so the stand-ins and the tools are not taken for a model."""
    try:
        adapters = adapters or adapter_config.from_machine()
    except adapter_config.AdapterError as error:
        raise StepFailed(f"Cannot read the adapters to check for other GPU jobs: {error}") from error
    markers: set[str] = set()
    for entry in adapters.entries.values():
        if not entry.gpu:
            continue
        rendered = []
        for part in entry.argv[1:]:
            if set(adapter_config.placeholders(part)) - set(adapter_config.SYSTEM):
                continue
            path = Path(adapter_config.render(part, adapter_config.system_values())).expanduser()
            if path.is_absolute() and path.is_file():
                rendered.append(str(path))
        program = str(adapter_config.program(entry))
        markers.update(rendered or ([program] if program != sys.executable else []))
    return markers


def _is_foreign_gpu_generator(command: str, markers: set[str]) -> bool:
    """Whether COMMAND (a `ps` command line) runs one of MARKERS as its program or as an argument."""
    try:
        args = shlex.split(command)
    except ValueError:
        args = command.split()  # ps can print unquoted argument contents
    return any(arg in markers for arg in args)


def foreign_gpu_jobs() -> list[str]:
    try:
        mine = _ancestors()
        result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True)
    except PermissionError:
        raise StepFailed("Process inspection is blocked; cannot safely check for other GPU jobs")
    if result.returncode:
        raise StepFailed("Cannot inspect GPU jobs: " + result.stderr.strip())
    markers = gpu_markers()
    jobs = []
    for line in result.stdout.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if int(pid) in mine:
            continue
        if _is_foreign_gpu_generator(cmd, markers):
            jobs.append(f"{pid} {cmd[:120]}")
    return jobs


@contextlib.contextmanager
def gpu_lock(log, max_wait_s=1800):
    """The shared GPU lock (gpu_lock.py), plus a wait while another program's model runs."""
    def foreign_reason():
        jobs = foreign_gpu_jobs()
        return f"foreign job {jobs[0]}" if jobs else None
    try:
        with gpu_lock_module.held(gpu_lock_module.default_lock_path(), "pipeline", max_wait_s, log,
                                  poll_s=LOCK_POLL_S, wait_while=foreign_reason):
            yield
    except gpu_lock_module.LockError as error:
        raise StepFailed(str(error)) from error


class GpuSession:
    """Lazily takes the shared GPU lock once and keeps it until the session closes.

    `acquire(log, max_wait_s=...)` is a context manager that holds the lock (default: gpu_lock() above, which
    also waits while some other program's model runs); tests inject a stand-in (principle 2)."""

    def __init__(self, log, max_wait_s, acquire=None):
        self._log, self._max_wait_s, self._acquire = log, max_wait_s, acquire
        self._stack = contextlib.ExitStack()
        self._held = False

    @property
    def held(self):
        return self._held

    def hold(self):
        """Take the lock if this session does not hold it yet (waits up to max_wait_s, then raises)."""
        if self._held:
            return
        acquire = self._acquire or gpu_lock
        self._stack.enter_context(acquire(self._log, max_wait_s=self._max_wait_s))
        self._held = True

    def close(self):
        self._stack.close()
        self._held = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
