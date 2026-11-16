"""Runs a project's generation jobs (authoring/job_store.py) one at a time.

Every job is a pipeline from authoring/offered.json run by `pipeline/pipeline_run.py` as a subprocess
(authoring/pipeline_job.py): its output is tailed into the run's log, and it reports through the job store's
add_candidate and update_run. A job's id names its run folder under the runs root. A job row made by an earlier version
of this tool (pipeline `asset_job`, `icon_job` or `heads_bodies_job`) is still listed with its candidates and runs, but
it is not offered and cannot be run again.
"""

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from authoring.job_store import JobStore
from authoring.machine_config import MachineConfig
from authoring.offered import offers
from authoring.pipeline_job import describe_pipeline_steps, run_pipeline_job
from authoring.steps import StepInfo


def describe_steps(
    job: dict[str, Any], run: dict[str, Any] | None, config: MachineConfig
) -> list[StepInfo]:
    """The job's steps for the run routes; none for a job whose pipeline is no longer offered."""
    return describe_pipeline_steps(job, run, config) if job["pipeline"] in offers() else []


@dataclass(frozen=True)
class RunRef:
    """A queued run and the project job store that owns it. The store travels with the run, so a
    run is always updated in the project that requested it. `finished` is called with the run's
    status once the run has ended, succeeded or failed (the API attaches the run to its entity
    there, so a failed run's trace can be opened); its own failure is logged in the run, never
    raised."""

    store: JobStore
    run_id: str
    job_id: str
    finished: Callable[[str], None] | None = None


class Dispatcher:
    """One daemon worker thread per server process, consuming an in-process queue - matches
    the project's stated 'no broker, this is the whole envelope' constraint. It holds no store
    of its own: each queued RunRef names the store its run lives in."""

    def __init__(self, config: MachineConfig) -> None:
        self.queue: queue.Queue[RunRef] = queue.Queue()
        self.config = config

    def start(self) -> None:
        threading.Thread(target=self._worker, daemon=True).start()

    def enqueue(
        self,
        store: JobStore,
        run_id: str,
        job_id: str,
        finished: Callable[[str], None] | None = None,
    ) -> None:
        self.queue.put(RunRef(store, run_id, job_id, finished))

    def run_next(self, timeout: float | None = None) -> bool:
        """Take one queued run and execute it on the calling thread. Blocks up to `timeout`
        seconds (forever if None); returns False if nothing arrived. The worker loop is just
        this in a loop, and checks use it with timeout=0 to drain the queue without a thread."""
        try:
            ref = self.queue.get(timeout=timeout)
        except queue.Empty:
            return False
        self._run_one(ref)
        return True

    def _worker(self) -> None:
        while True:
            self.run_next()

    def _run_one(self, ref: RunRef) -> None:
        store = ref.store
        store.update_run(ref.run_id, status="running")
        try:
            job = store.job(ref.job_id)
            if job["pipeline"] not in offers():
                store.update_run(
                    ref.run_id,
                    status="failed",
                    log_tail=f"Unknown pipeline: {job['pipeline']!r} (it is not offered by this version)",
                )
                return
            run_pipeline_job(store, job, ref.run_id, ref.job_id, self.config)
        except Exception as exc:  # noqa: BLE001 - always surface to the UI, never die silently
            store.update_run(ref.run_id, status="failed", log_tail=str(exc))
        status = store.get_run(ref.run_id)["status"]
        if ref.finished is not None and status in ("succeeded", "failed"):
            try:
                ref.finished(status)
            except Exception as exc:  # noqa: BLE001 - the run stands; say why the link is missing
                run = store.get_run(ref.run_id)
                note = f"{status}, but it could not be attached to its entity: {exc}"
                store.update_run(ref.run_id, log_tail=f"{run['log_tail']}\n{note}".strip())
