"""One open project: its kinds and link types, and the operations on its entities, links and
references to pipeline output. Every write is checked here before it reaches the store.

Rules kept here:
- An entity's data is checked against its kind's current schema on create, update and revert, and
  the values the schema marks with `x-vocabulary` against the project's vocabulary.
  Archive and restore change only the archived flag, so a later schema edit never strands one.
- An archived entity is read-only until restored. Its links are kept; listings hide links whose
  other end is archived unless asked for them, and restoring shows them again.
- Runs and candidates are opaque references into the run store; only their shape is checked
  here, plus an optional `run_exists` check passed in by the caller.
"""

import re
from collections.abc import Callable
from typing import Any

from core.errors import Conflict, Invalid, NotFound
from core.kinds import Catalogue, Kind
from core.project_file import ProjectFile
from core.store import WorldStore

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
SLOT = re.compile(r"[a-z][a-z0-9_]{0,63}")
DEFAULT_SLOT = "main"
MAX_NOTE = 500
MAX_CANDIDATE = 500
DIRECTIONS = ("out", "in", "both")


def _note(value: object, field: str = "/note") -> str:
    if not isinstance(value, str) or len(value) > MAX_NOTE:
        raise Invalid(f"{field}: expected text of at most {MAX_NOTE} characters", field=field)
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise Invalid(f"{field}: expected a non-empty string", field=field)
    return value


class World:
    def __init__(
        self,
        project: ProjectFile,
        catalogue: Catalogue,
        store: WorldStore,
        run_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.project = project
        self.catalogue = catalogue
        self.store = store
        self._run_exists = run_exists

    # Views

    def _title(self, entity: dict[str, Any]) -> str | None:
        kind = self.catalogue.kinds.get(entity["kind"])
        value = entity["data"].get(kind.title_field) if kind else None
        return value if isinstance(value, str) else None

    def _view(self, entity: dict[str, Any]) -> dict[str, Any]:
        return {**entity, "title": self._title(entity)}

    def _summary(self, entity: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": entity["id"],
            "kind": entity["kind"],
            "title": self._title(entity),
            "archived": entity["archived"],
        }

    # Kinds and link types

    def kinds(self) -> list[dict[str, Any]]:
        return [kind.describe() for kind in self.catalogue.kinds.values()]

    def kind(self, kind_id: str) -> dict[str, Any]:
        return self.catalogue.kind(kind_id).describe()

    def link_types(self) -> list[dict[str, Any]]:
        return [link_type.describe() for link_type in self.catalogue.link_types.values()]

    # Entities

    def create_entity(self, kind_id: object, data: object, note: object = "") -> dict[str, Any]:
        kind = self._kind(_text(kind_id, "/kind"))
        clean = self._check(kind, data)
        return self._view(self.store.create_entity(kind.id, clean, _note(note) or "Created"))

    def get_entity(self, entity_id: str) -> dict[str, Any]:
        return self._view(self.store.get_entity(entity_id))

    def _active(self, entity_id: str) -> tuple[dict[str, Any], Kind]:
        entity = self.store.get_entity(entity_id)
        if entity["archived"]:
            raise Conflict(f"entity {entity_id!r} is archived; restore it first", "entity_archived")
        return entity, self._kind(entity["kind"])

    def _kind(self, kind_id: str) -> Kind:
        """The kind for a write; unknown is a problem with the data sent, so Invalid."""
        if kind_id not in self.catalogue.kinds:
            known = ", ".join(self.catalogue.kinds)
            raise Invalid(f"/kind: no kind {kind_id!r} (kinds: {known})", "unknown_kind", "/kind")
        return self.catalogue.kinds[kind_id]

    def _check(self, kind: Kind, data: object, pointer: str = "/data") -> dict[str, Any]:
        """The data if it fits the kind's schema and the vocabulary, else Invalid naming the field."""
        clean = kind.check(data, pointer)
        self.catalogue.check_vocabulary(kind, clean, pointer)
        return clean

    def update_entity(
        self, entity_id: str, revision: int, data: object, note: object = ""
    ) -> dict[str, Any]:
        _, kind = self._active(entity_id)
        clean = self._check(kind, data)
        written = self.store.write_entity(entity_id, revision, _note(note) or "Updated", clean)
        return self._view(written)

    def revert_entity(
        self, entity_id: str, revision: int, to: int, note: object = ""
    ) -> dict[str, Any]:
        """A new revision holding an earlier revision's data, checked against today's schema."""
        _, kind = self._active(entity_id)
        old = self.store.revision(entity_id, to)
        clean = self._check(kind, old["data"], f"/revisions/{to}/data")
        written = self.store.write_entity(
            entity_id, revision, _note(note) or f"Reverted to revision {to}", clean
        )
        return self._view(written)

    def archive_entity(self, entity_id: str, revision: int, note: object = "") -> dict[str, Any]:
        if self.store.get_entity(entity_id)["archived"]:
            raise Conflict(f"entity {entity_id!r} is already archived", "already_archived")
        written = self.store.write_entity(
            entity_id, revision, _note(note) or "Archived", archived=True
        )
        return self._view(written)

    def restore_entity(self, entity_id: str, revision: int, note: object = "") -> dict[str, Any]:
        if not self.store.get_entity(entity_id)["archived"]:
            raise Conflict(f"entity {entity_id!r} is not archived", "not_archived")
        written = self.store.write_entity(
            entity_id, revision, _note(note) or "Restored", archived=False
        )
        return self._view(written)

    def list_entities(
        self,
        kind: str | None = None,
        tag: str | None = None,
        text: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """Entities, most recently changed first. `tag` matches a tag exactly; `text` matches,
        ignoring case, anywhere in the title, the brief or a tag."""
        if kind is not None:
            self._kind(kind)
        needle = text.casefold() if text else None
        result = []
        for entity in self.store.list_entities(kind, include_archived):
            described = self.catalogue.kinds.get(entity["kind"])
            data = entity["data"]
            tags = data.get(described.tags_field, []) if described and described.tags_field else []
            if tag is not None and tag not in tags:
                continue
            if needle is not None:
                fields = [self._title(entity) or ""]
                if described and described.brief_field:
                    fields.append(str(data.get(described.brief_field, "")))
                if not any(needle in value.casefold() for value in [*fields, *tags]):
                    continue
            result.append(self._view(entity))
        return result

    def revisions(self, entity_id: str) -> list[dict[str, Any]]:
        return self.store.revisions(entity_id)

    def revision(self, entity_id: str, revision: int) -> dict[str, Any]:
        return self.store.revision(entity_id, revision)

    # Links

    def add_link(self, type_id: object, source: object, target: object) -> dict[str, Any]:
        type_id = _text(type_id, "/type")
        if type_id not in self.catalogue.link_types:
            known = ", ".join(self.catalogue.link_types) or "none"
            raise Invalid(
                f"/type: no link type {type_id!r} (link types: {known})",
                "unknown_link_type",
                "/type",
            )
        link_type = self.catalogue.link_types[type_id]
        return self.store.add_link(
            link_type.id,
            _text(source, "/source"),
            _text(target, "/target"),
            link_type.source_kinds,
            link_type.target_kinds,
        )

    def get_link(self, link_id: str) -> dict[str, Any]:
        return self.store.get_link(link_id)

    def delete_link(self, link_id: str) -> dict[str, Any]:
        return self.store.delete_link(link_id)

    def links(
        self, entity_id: str, direction: str = "both", include_archived: bool = False
    ) -> list[dict[str, Any]]:
        """The entity's links in one or both directions, each with the label read from that
        side (the link type's label going out, its inverse label coming in) and a summary of the
        entity at the other end."""
        if direction not in DIRECTIONS:
            raise Invalid(
                f"direction must be one of {', '.join(DIRECTIONS)}, not {direction!r}",
                field="/direction",
            )
        result = []
        for link, side, other in self.store.links_of(entity_id, direction):
            if other["archived"] and not include_archived:
                continue
            link_type = self.catalogue.link_types.get(link["type"])
            label = link["type"]
            if link_type:
                label = link_type.label if side == "out" else link_type.inverse_label
            result.append(
                {**link, "direction": side, "label": label, "other": self._summary(other)}
            )
        return result

    # References to pipeline output

    def _run_id(self, value: object) -> str:
        if not isinstance(value, str) or not RUN_ID.fullmatch(value):
            raise Invalid(
                "/run_id: expected a run id (letters, digits, '.', '_', '-'; at most 128)",
                field="/run_id",
            )
        if self._run_exists is not None and not self._run_exists(value):
            raise NotFound(f"no run {value!r} in the run store", "run_not_found", "/run_id")
        return value

    def runs(self, entity_id: str) -> list[dict[str, Any]]:
        return self.store.runs(entity_id)

    def attach_run(self, entity_id: str, run_id: object, note: object = "") -> dict[str, Any]:
        return self.store.attach_run(entity_id, self._run_id(run_id), _note(note))

    def detach_run(self, entity_id: str, run_id: str) -> None:
        self.store.detach_run(entity_id, run_id)

    def choose(
        self,
        entity_id: str,
        run_id: object,
        candidate: object,
        slot: object = DEFAULT_SLOT,
        note: object = "",
    ) -> dict[str, Any]:
        if not isinstance(slot, str) or not SLOT.fullmatch(slot):
            raise Invalid(
                "/slot: expected lowercase letters, digits and underscores", field="/slot"
            )
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or len(candidate) > MAX_CANDIDATE
            or any(ord(c) < 32 for c in candidate)
        ):
            raise Invalid(
                f"/candidate: expected a candidate reference of at most {MAX_CANDIDATE} "
                "characters with no control characters",
                field="/candidate",
            )
        return self.store.choose(entity_id, slot, self._run_id(run_id), candidate, _note(note))

    def chosen(self, entity_id: str) -> dict[str, dict[str, Any]]:
        return self.store.chosen(entity_id)

    def choices(self, entity_id: str) -> list[dict[str, Any]]:
        return self.store.choices(entity_id)
