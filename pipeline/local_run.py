"""Run one local command offline: the host's network sandbox, the offline environment and a step log.

`execute(command, log, timeout, network="allow", env=None, cwd=None)` is how every pipeline stage starts a program.
A model stage passes the network mode of its adapter entry ("deny" or "loopback"); host.py wraps the command and the
run fails closed when the host cannot apply it. A CPU stage runs with the offline environment only.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host  # noqa: E402

OFFLINE = {"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
           "TRANSFORMERS_OFFLINE": "1", "WANDB_DISABLED": "true"}


class StepFailed(Exception):
    """A step could not run or did not finish (a lock that could not be taken, a missing model)."""


def execute(command, log, timeout, network="allow", env=None, cwd=None):
    """Run COMMAND, appending the command line and its output to LOG; RuntimeError on a nonzero exit. NETWORK is the
    sandbox mode (host.sandboxed; HostError, a RuntimeError, when the host cannot apply it). ENV adds variables to
    the child's environment; CWD is its working folder."""
    command = host.sandboxed(command, network)
    with Path(log).open("a") as stream:
        stream.write(json.dumps(command) + "\n")
        stream.flush()
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, cwd=cwd,
                                env={**os.environ, **OFFLINE, **(env or {})}, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"stage exited {result.returncode}; see {log}")
