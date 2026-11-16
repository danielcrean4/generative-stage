"""Run one adapter entry for one stage (plain Python; docs/adapters.md "Running").

`run(entry, data, folder, gpu)`: checks what the entry requires against the host (a clear refusal when something is
missing), renders its command with the run's data values (adapter_config.command), takes the GPU lock through the
job's session when the entry asks for it, runs the command offline in the entry's network sandbox with its env, cwd
and timeout, and returns the seconds it took. A nonzero exit or a timeout is `Failed`, naming the adapter and the log. The adapter may write `identity.json` beside its outputs (the model
identity it reports); `reported(folder)` reads it, and the runner keeps it out of the stage's output hashes.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapter_config  # noqa: E402
import host  # noqa: E402
import local_run  # noqa: E402

REPORTED = "identity.json"
MAX_REPORTED_BYTES = 64 * 1024


class Refused(RuntimeError):
    """The adapter cannot run here or now; the message says why (a requirement, the GPU lock, a value)."""


class Failed(RuntimeError):
    """The adapter ran and did not finish: it exited nonzero or ran past its timeout (and was stopped)."""


def check_host(entry):
    """Refused with one sentence per unmet requirement of ENTRY."""
    problems = host.unmet(entry.needs())
    if problems:
        raise Refused(f"adapter '{entry.id}' cannot run on this computer: " + "; ".join(problems)
                      + f" (its entry: {entry.origin})")


def run(entry, data, folder, gpu=None, log_name="step.log"):
    """Run ENTRY with DATA into FOLDER; the seconds it took. GPU is the job's GpuSession (gpu_session.py)."""
    check_host(entry)
    try:
        argv, env, cwd = adapter_config.command(entry, data)
    except adapter_config.AdapterError as error:
        raise Refused(str(error)) from error
    if entry.gpu:
        if gpu is None:
            raise Refused(f"adapter '{entry.id}' holds the GPU lock, but no GPU session was given")
        try:
            gpu.hold()
        except local_run.StepFailed as error:
            raise Refused(str(error)) from error
    started = time.monotonic()
    log = Path(folder) / log_name
    try:
        local_run.execute(argv, log, entry.timeout_seconds, network=entry.sandbox, env=env, cwd=cwd)
    except host.HostError as error:
        raise Refused(f"adapter '{entry.id}': {error}") from error
    except subprocess.TimeoutExpired as error:
        raise Failed(f"adapter '{entry.id}' ran past its timeout of {entry.timeout_seconds}s and was stopped; "
                     f"see {log}") from error
    except RuntimeError as error:  # local_run: a nonzero exit
        raise Failed(f"adapter '{entry.id}': {error}") from error
    return round(time.monotonic() - started, 2)


def reported(folder):
    """The identity the adapter reported in FOLDER/identity.json (a JSON object), or None."""
    path = Path(folder) / REPORTED
    if not path.is_file() or path.stat().st_size > MAX_REPORTED_BYTES:
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None
