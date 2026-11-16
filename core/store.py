"""A project's SQLite store: entities with every revision, links, and references to runs.

Storage only. It knows nothing of kinds or schemas: the caller (core.world) validates data first.
Each write runs in one `BEGIN IMMEDIATE` transaction, so two writers can never both win: an
update names the revision it was based on and a stale one raises Conflict. Rows are returned as
plain dicts with JSON data already decoded.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.errors import BadProjectFiles, Conflict, Invalid, NotFound
from core.ids import new_id

FORMAT = "world-store-1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, revision INTEGER NOT NULL,
    archived INTEGER NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS entities_kind ON entities(kind);
CREATE TABLE IF NOT EXISTS entity_revisions (
    entity_id TEXT NOT NULL REFERENCES entities(id), revision INTEGER NOT NULL,
    data TEXT NOT NULL, archived INTEGER NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(entity_id, revision));
CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY, type TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES entities(id),
    target_id TEXT NOT NULL REFERENCES entities(id), created_at TEXT NOT NULL,
    UNIQUE(type, source_id, target_id));
CREATE INDEX IF NOT EXISTS links_target ON links(target_id);
CREATE TABLE IF NOT EXISTS entity_runs (
    entity_id TEXT NOT NULL REFERENCES entities(id), run_id TEXT NOT NULL,
    entity_revision INTEGER NOT NULL, note TEXT NOT NULL, attached_at TEXT NOT NULL,
    PRIMARY KEY(entity_id, run_id));
CREATE TABLE IF NOT EXISTS entity_choices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id TEXT NOT NULL REFERENCES entities(id),
    slot TEXT NOT NULL, run_id TEXT NOT NULL, candidate TEXT NOT NULL,
    entity_revision INTEGER NOT NULL, note TEXT NOT NULL, chosen_at TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _entity(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "revision": row["revision"],
        "archived": bool(row["archived"]),
        "data": json.loads(row["data"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _revision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "entity_id": row["entity_id"],
        "revision": row["revision"],
        "archived": bool(row["archived"]),
        "data": json.loads(row["data"]),
        "note": row["note"],
        "created_at": row["created_at"],
    }


class WorldStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        with self._transaction() as db:
            row = db.execute("SELECT value FROM meta WHERE key='format'").fetchone()
            if row is None:
                db.execute("INSERT INTO meta VALUES('format', ?)", (FORMAT,))
            elif row["value"] != FORMAT:
                raise BadProjectFiles(f"{path}: store format {row['value']!r}, expected {FORMAT!r}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """One write transaction, taken with the write lock up front."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    @staticmethod
    def _row(db: sqlite3.Connection, entity_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = db.execute(
            "SELECT * FROM entities WHERE id=?", (entity_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no entity {entity_id!r}", "entity_not_found")
        return row

    # Entities and revisions

    def create_entity(self, kind: str, data: dict[str, Any], note: str) -> dict[str, Any]:
        entity_id, now, payload = new_id(), _now(), _dump(data)
        with self._transaction() as db:
            db.execute(
                "INSERT INTO entities VALUES(?,?,?,?,?,?,?)",
                (entity_id, kind, 1, 0, payload, now, now),
            )
            db.execute(
                "INSERT INTO entity_revisions VALUES(?,?,?,?,?,?)",
                (entity_id, 1, payload, 0, note, now),
            )
            return _entity(self._row(db, entity_id))

    def get_entity(self, entity_id: str) -> dict[str, Any]:
        with self._connect() as db:
            return _entity(self._row(db, entity_id))

    def write_entity(
        self,
        entity_id: str,
        expected: int,
        note: str,
        data: dict[str, Any] | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        """Append a revision that changes the data, the archived flag or both. `expected` is the
        revision the caller read; anything else means someone wrote in between."""
        with self._transaction() as db:
            row = self._row(db, entity_id)
            if row["revision"] != expected:
                raise Conflict(
                    f"entity {entity_id!r} is at revision {row['revision']}, not {expected}; "
                    "reload it and apply the change again",
                    "revision_conflict",
                    "/revision",
                )
            payload = row["data"] if data is None else _dump(data)
            flag = bool(row["archived"]) if archived is None else archived
            revision, now = expected + 1, _now()
            db.execute(
                "UPDATE entities SET revision=?, archived=?, data=?, updated_at=? WHERE id=?",
                (revision, int(flag), payload, now, entity_id),
            )
            db.execute(
                "INSERT INTO entity_revisions VALUES(?,?,?,?,?,?)",
                (entity_id, revision, payload, int(flag), note, now),
            )
            return _entity(self._row(db, entity_id))

    def list_entities(self, kind: str | None, include_archived: bool) -> list[dict[str, Any]]:
        query = "SELECT * FROM entities WHERE (? IS NULL OR kind=?) AND (archived=0 OR ?)"
        with self._connect() as db:
            rows = db.execute(
                query + " ORDER BY updated_at DESC, id", (kind, kind, int(include_archived))
            )
            return [_entity(row) for row in rows]

    def revisions(self, entity_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            self._row(db, entity_id)
            rows = db.execute(
                "SELECT * FROM entity_revisions WHERE entity_id=? ORDER BY revision DESC",
                (entity_id,),
            )
            return [_revision(row) for row in rows]

    def revision(self, entity_id: str, revision: int) -> dict[str, Any]:
        with self._connect() as db:
            self._row(db, entity_id)
            row = db.execute(
                "SELECT * FROM entity_revisions WHERE entity_id=? AND revision=?",
                (entity_id, revision),
            ).fetchone()
        if row is None:
            raise NotFound(f"entity {entity_id!r} has no revision {revision}", "revision_not_found")
        return _revision(row)

    # Links

    def add_link(
        self,
        type_id: str,
        source_id: str,
        target_id: str,
        source_kinds: tuple[str, ...],
        target_kinds: tuple[str, ...],
    ) -> dict[str, Any]:
        """Create one link. Both ends must exist, be active and be of an allowed kind; the checks
        and the insert share one transaction."""
        if source_id == target_id:
            raise Invalid("a link cannot point at its own source", "self_link", "/target")
        with self._transaction() as db:
            for end, entity_id, allowed in (
                ("source", source_id, source_kinds),
                ("target", target_id, target_kinds),
            ):
                try:
                    row = self._row(db, entity_id)
                except NotFound as error:
                    raise NotFound(error.message, "entity_not_found", f"/{end}") from error
                if row["archived"]:
                    raise Conflict(
                        f"the {end} {entity_id!r} is archived; restore it first",
                        "entity_archived",
                        f"/{end}",
                    )
                if row["kind"] not in allowed:
                    raise Invalid(
                        f"link type {type_id!r} needs a {end} of kind {' or '.join(allowed)}, "
                        f"not {row['kind']!r}",
                        "link_kinds",
                        f"/{end}",
                    )
            if db.execute(
                "SELECT 1 FROM links WHERE type=? AND source_id=? AND target_id=?",
                (type_id, source_id, target_id),
            ).fetchone():
                raise Conflict(
                    f"a {type_id!r} link from {source_id!r} to {target_id!r} already exists",
                    "duplicate_link",
                )
            link_id = new_id()
            db.execute(
                "INSERT INTO links VALUES(?,?,?,?,?)",
                (link_id, type_id, source_id, target_id, _now()),
            )
        return self.get_link(link_id)

    def get_link(self, link_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM links WHERE id=?", (link_id,)).fetchone()
        if row is None:
            raise NotFound(f"no link {link_id!r}", "link_not_found")
        return self._link(row)

    @staticmethod
    def _link(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "source": row["source_id"],
            "target": row["target_id"],
            "created_at": row["created_at"],
        }

    def delete_link(self, link_id: str) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute("SELECT * FROM links WHERE id=?", (link_id,)).fetchone()
            if row is None:
                raise NotFound(f"no link {link_id!r}", "link_not_found")
            db.execute("DELETE FROM links WHERE id=?", (link_id,))
            return self._link(row)

    def links_of(
        self, entity_id: str, direction: str
    ) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
        """Each link touching the entity as (link, "out" or "in", the entity at the other end)."""
        result = []
        with self._connect() as db:
            self._row(db, entity_id)
            for wanted, own, other in (
                ("out", "source_id", "target_id"),
                ("in", "target_id", "source_id"),
            ):
                if direction not in (wanted, "both"):
                    continue
                rows = db.execute(
                    f"SELECT l.*, e.id AS e_id FROM links l JOIN entities e ON e.id=l.{other} "
                    f"WHERE l.{own}=? ORDER BY l.created_at, l.id",
                    (entity_id,),
                ).fetchall()
                for row in rows:
                    result.append((self._link(row), wanted, _entity(self._row(db, row["e_id"]))))
        return result

    # References to pipeline output

    def _writable(self, db: sqlite3.Connection, entity_id: str) -> sqlite3.Row:
        row = self._row(db, entity_id)
        if row["archived"]:
            raise Conflict(f"entity {entity_id!r} is archived; restore it first", "entity_archived")
        return row

    def attach_run(self, entity_id: str, run_id: str, note: str) -> dict[str, Any]:
        with self._transaction() as db:
            row = self._writable(db, entity_id)
            if db.execute(
                "SELECT 1 FROM entity_runs WHERE entity_id=? AND run_id=?", (entity_id, run_id)
            ).fetchone():
                raise Conflict(
                    f"run {run_id!r} is already attached to {entity_id!r}",
                    "already_attached",
                    "/run_id",
                )
            db.execute(
                "INSERT INTO entity_runs VALUES(?,?,?,?,?)",
                (entity_id, run_id, row["revision"], note, _now()),
            )
        return next(r for r in self.runs(entity_id) if r["run_id"] == run_id)

    def detach_run(self, entity_id: str, run_id: str) -> None:
        with self._transaction() as db:
            self._writable(db, entity_id)
            if db.execute(
                "SELECT 1 FROM entity_choices WHERE entity_id=? AND run_id=?", (entity_id, run_id)
            ).fetchone():
                raise Conflict(
                    f"a candidate from run {run_id!r} has been chosen for {entity_id!r}; the "
                    "choice history keeps the run attached",
                    "run_has_choice",
                    "/run_id",
                )
            cursor = db.execute(
                "DELETE FROM entity_runs WHERE entity_id=? AND run_id=?", (entity_id, run_id)
            )
            if cursor.rowcount == 0:
                raise NotFound(
                    f"run {run_id!r} is not attached to {entity_id!r}", "run_not_attached"
                )

    def runs(self, entity_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            self._row(db, entity_id)
            rows = db.execute(
                "SELECT * FROM entity_runs WHERE entity_id=? ORDER BY attached_at DESC, run_id",
                (entity_id,),
            )
            return [dict(row) for row in rows]

    def choose(
        self, entity_id: str, slot: str, run_id: str, candidate: str, note: str
    ) -> dict[str, Any]:
        """Record a choice (append-only). The run is attached too if it was not yet."""
        with self._transaction() as db:
            row = self._writable(db, entity_id)
            now = _now()
            db.execute(
                "INSERT OR IGNORE INTO entity_runs VALUES(?,?,?,?,?)",
                (entity_id, run_id, row["revision"], "", now),
            )
            db.execute(
                "INSERT INTO entity_choices(entity_id, slot, run_id, candidate, entity_revision, "
                "note, chosen_at) VALUES(?,?,?,?,?,?,?)",
                (entity_id, slot, run_id, candidate, row["revision"], note, now),
            )
        return self.chosen(entity_id)[slot]

    def choices(self, entity_id: str) -> list[dict[str, Any]]:
        """Every choice ever made for the entity, newest first."""
        with self._connect() as db:
            self._row(db, entity_id)
            rows = db.execute(
                "SELECT entity_id, slot, run_id, candidate, entity_revision, note, chosen_at "
                "FROM entity_choices WHERE entity_id=? ORDER BY id DESC",
                (entity_id,),
            )
            return [dict(row) for row in rows]

    def chosen(self, entity_id: str) -> dict[str, dict[str, Any]]:
        """The current choice per slot: the latest one recorded."""
        current: dict[str, dict[str, Any]] = {}
        for choice in self.choices(entity_id):
            current.setdefault(choice["slot"], choice)
        return current
