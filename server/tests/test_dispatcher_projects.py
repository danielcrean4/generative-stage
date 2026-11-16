"""A run belongs to the project that asked for it: the dispatcher updates that project's job
store, and the start-up sweep fails orphaned runs in every registered project. No model or GPU:
two job stores and a trivial in-process pipeline, driven through the dispatcher's run_next()."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from studio_test_support import stand_in_config

from authoring import jobs
from authoring.job_store import FILE_NAME, JobStore
from authoring.jobs import Dispatcher
from authoring.machine_config import MachineConfig
from authoring.server import fail_orphaned_runs
from core.registry import RegistryFile
from core.workspace import Workspace

PIPELINE = "concept"
ENTITY = {"id": "e1", "kind": "prop", "revision": 1, "data": {"name": "Key"}}
RECIPE = {"prompt": "a key", "adapters": {}, "choices": {"seed": 1, "candidates": 1}}


def instant_pipeline(
    store: JobStore, job: dict[str, Any], run_id: str, job_id: str, config: MachineConfig
) -> None:
    candidate = store.add_candidate(job_id, "/local/instant.png", f"run {run_id}")
    store.update_run(run_id, status="succeeded", candidate_id=candidate["id"])


@pytest.fixture
def dispatcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Dispatcher]:
    monkeypatch.setattr(jobs, "run_pipeline_job", instant_pipeline)
    yield Dispatcher(stand_in_config(tmp_path))


def test_run_is_updated_in_the_project_that_requested_it(
    tmp_path: Path, dispatcher: Dispatcher
) -> None:
    first = JobStore(tmp_path / "first.sqlite3")
    second = JobStore(tmp_path / "second.sqlite3")
    job = second.create_job(ENTITY, PIPELINE, RECIPE)
    run = second.create_run(job["id"])
    called = []
    dispatcher.enqueue(second, run["id"], job["id"], lambda status: called.append(job["id"]))

    assert dispatcher.run_next(timeout=0)

    finished = second.get_run(run["id"])
    assert finished["status"] == "succeeded", finished["log_tail"]
    assert second.candidates(job["id"])[0]["id"] == finished["candidate_id"]
    assert called == [job["id"]]
    with first.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_a_failing_success_callback_is_written_to_the_run(
    tmp_path: Path, dispatcher: Dispatcher
) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job(ENTITY, PIPELINE, RECIPE)
    run = store.create_run(job["id"])

    def broken(status: str) -> None:
        raise RuntimeError("the entity was archived")

    dispatcher.enqueue(store, run["id"], job["id"], broken)
    assert dispatcher.run_next(timeout=0)
    finished = store.get_run(run["id"])
    assert finished["status"] == "succeeded"
    assert "could not be attached to its entity: the entity was archived" in finished["log_tail"]


def test_start_sweep_fails_orphaned_runs_in_every_project(tmp_path: Path) -> None:
    workspace = Workspace(RegistryFile(tmp_path / "registry.json"))
    runs = {}
    for slug in ("first", "second"):
        workspace.create(str(tmp_path / slug), slug, slug.title())
        store = JobStore.for_project(tmp_path / slug)
        runs[slug] = store.create_run(store.create_job(ENTITY, PIPELINE, RECIPE)["id"])
    workspace.create(str(tmp_path / "idle"), "idle", "Idle")  # no job store: left alone

    assert fail_orphaned_runs(workspace) == 2
    for slug, run in runs.items():
        assert JobStore.for_project(tmp_path / slug).get_run(run["id"])["status"] == "failed"
    assert not (tmp_path / "idle" / FILE_NAME).exists()
