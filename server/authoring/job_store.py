"""A project's generation jobs: what was asked for an entity, each run of it and what each run made.

One SQLite file per project (`jobs.sqlite3` in the project folder), beside the world store. A job
is a recipe (prompt, adapters, choices; see run_request.py) plus a snapshot of the entity's
revision it was made for. A run is one execution of a job by the dispatcher (jobs.py); a candidate
is a file a run made. The job's id names its run folder under the runs root, so the run view and
the world model's run references use the same id.

Entities are referred to by id only: this store never reads the world store, and the world store
never reads this one. The HTTP layer (api_v1.py) joins them.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.errors import NotFound

FILE_NAME = "jobs.sqlite3"
STATUSES = ("queued", "running", "succeeded", "failed")


# `component` is a column an earlier version wrote; a job made now leaves it empty.
SQL_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, entity_revision INTEGER NOT NULL,
    pipeline TEXT NOT NULL, component TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_by_entity ON jobs(entity_id);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), output_ref TEXT NOT NULL,
    note TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), status TEXT NOT NULL,
    log_tail TEXT NOT NULL DEFAULT '', candidate_id TEXT REFERENCES candidates(id),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connect() as db:
            db.executescript(SQL_SCHEMA)

    @classmethod
    def for_project(cls, root: Path) -> "JobStore":
        return cls(root / FILE_NAME)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_job(
        self, entity: dict[str, Any], pipeline: str, recipe: dict[str, Any]
    ) -> dict[str, Any]:
        """A new job for the entity's current revision. The entity must be live (the caller
        checks it through the world model) and the recipe checked (authoring/run_request.py)."""
        payload = {**recipe}
        payload["content_snapshot"] = {
            key: entity[key] for key in ("id", "kind", "revision", "data")
        }
        job_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
                (
                    job_id,
                    entity["id"],
                    entity["revision"],
                    pipeline,
                    None,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    _now(),
                ),
            )
        return self.job(job_id)

    @staticmethod
    def _job(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "entity_id": row["entity_id"],
            "entity_revision": row["entity_revision"],
            "pipeline": row["pipeline"],
            "component": row["component"],
            "created_at": row["created_at"],
            "recipe": json.loads(row["payload"]),
        }

    def job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFound(f"no job {job_id!r}", "job_not_found")
        return self._job(row)

    def jobs_of(self, entity_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE entity_id=? ORDER BY created_at DESC, id", (entity_id,)
            ).fetchall()
        return [self._job(row) for row in rows]

    def add_candidate(self, job_id: str, output_ref: str, note: str) -> dict[str, Any]:
        self.job(job_id)
        candidate = {
            "id": str(uuid4()),
            "job_id": job_id,
            "output_ref": output_ref.strip(),
            "note": note,
            "created_at": _now(),
        }
        with self.connect() as db:
            db.execute("INSERT INTO candidates VALUES(?,?,?,?,?)", tuple(candidate.values()))
        return candidate

    def candidates(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM candidates WHERE job_id=? ORDER BY created_at, id", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def create_run(self, job_id: str) -> dict[str, Any]:
        self.job(job_id)
        now = _now()
        run_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                (run_id, job_id, "queued", "", None, now, now),
            )
        return self.get_run(run_id)

    def update_run(
        self,
        run_id: str,
        status: str | None = None,
        log_tail: str | None = None,
        candidate_id: str | None = None,
    ) -> None:
        if status is not None and status not in STATUSES:
            raise ValueError(f"unknown run status {status!r}")
        sets, params = [], []
        for column, value in (
            ("status", status),
            ("log_tail", log_tail),
            ("candidate_id", candidate_id),
        ):
            if value is not None:
                sets.append(f"{column}=?")
                params.append(value)
        sets.append("updated_at=?")
        params += [_now(), run_id]
        with self.connect() as db:
            db.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", params)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise NotFound(f"no run {run_id!r}", "run_not_found")
        return dict(row)

    def runs_of(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM runs WHERE job_id=? ORDER BY created_at DESC, id", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def fail_orphaned_runs(self) -> int:
        """At server start: a queued or running run has no worker any more; mark it failed so
        nothing waits on it forever. Returns how many were marked."""
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status='failed', "
                "log_tail='orphaned: no worker was running when the server restarted', "
                "updated_at=? WHERE status IN ('queued','running')",
                (_now(),),
            )
            return cursor.rowcount
