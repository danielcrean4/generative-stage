"""The step list shape the run routes return, and the one rule for telling this run's attempt from an older one.

Used by authoring/pipeline_job.py, which describes the steps of a pipeline job.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict

StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]


class StepInfo(TypedDict):
    id: str
    label: str
    file: str  # what does this step's work: a repo-relative script, or the pipeline file and tool
    status: StepStatus


def attempt_is_current(attempt: Path, run_created_at: str) -> bool:
    """A retry reuses the same job id and run folder, so a stale attempt from the *previous* run
    must never be reported as this run's progress. Attempt directory
    names are a timestamp prefix (YYYYMMDDTHHMMSSZ-hex, see pipeline_run.py's run_job()), compared
    directly against the run's created_at rather than filesystem mtime, which a cache copytree
    could disturb."""
    try:
        stamp = attempt.name.split("-")[0]
        attempt_time = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return True  # unexpected name shape - don't block progress on a parsing edge case
    # An attempt's name has whole seconds only, and a fast job starts its attempt in the second its run was created.
    run_time = datetime.fromisoformat(run_created_at).replace(tzinfo=None, microsecond=0)
    return attempt_time >= run_time
