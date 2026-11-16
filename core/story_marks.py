"""Where a kind schema says a value is a step in a story: a node, an edge between nodes, or a reference
to another entity (docs/story_graph.md).

A kind schema marks an object schema with the keyword `x-story`:

    {"x-story": {"node": "step", "text": "note", "sequence": true}}           a node
    {"x-story": {"edge": "reply", "text": "say", "to": "goto", "target": "/lines/{}"}}
                                                                              an edge to a node in
                                                                              the same entity
    {"x-story": {"ref": {"id_kind": "errand", "id": "id", "at": "/steps/{step}"}}}
                                                                              a reference to another
                                                                              entity's node

JSON Schema ignores the keyword, so the schema validates as before. `marks` walks a schema once
(core/annotations.py, looking inside marked nodes too, since nodes hold nodes) and checks each mark's
shape; a bad one raises ValueError naming the schema pointer (the kind loader turns it into
bad_schema).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.annotations import walk

KEYWORD = "x-story"
NODE_KEYS = {"node", "text", "sequence"}
EDGE_KEYS = {"edge", "text", "to", "target"}
REF_KEYS = {"id_kind", "id", "at"}
SLOT = "{}"


@dataclass(frozen=True)
class Mark:
    path: tuple[str, ...]  # property names, or annotations.ANY for any key or index
    role: str  # "node", "edge" or "ref"
    label: str = ""  # a node's or edge's name, such as "step" or "reply"
    text: str | None = None  # the field holding the words people read
    sequence: bool = False  # sibling nodes follow one another in key order
    to: str = ""  # an edge's field naming the next node; empty or null ends the story there
    target: str = ""  # an edge's pointer to that node, with {} for the field's value
    ref: Mapping[str, str] = field(default_factory=dict)  # id_kind, id and optional at


def _string(value: object, pointer: str, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{pointer}: {key} must be a non-empty string")
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], pointer: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError(
            f"{pointer}: unknown keys {', '.join(extra)} (known: {', '.join(sorted(allowed))})"
        )


def _mark(path: tuple[str, ...], value: object, pointer: str) -> Mark:
    if not isinstance(value, dict):
        raise ValueError(f"{pointer}: expected an object with node, edge or ref")
    roles = [role for role in ("node", "edge", "ref") if role in value]
    if len(roles) != 1:
        raise ValueError(f"{pointer}: give exactly one of node, edge or ref")
    if "node" in value:
        _keys(value, NODE_KEYS, pointer)
        if not isinstance(value.get("sequence", False), bool):
            raise ValueError(f"{pointer}: sequence must be true or false")
        text = _string(value["text"], pointer, "text") if "text" in value else None
        return Mark(
            path,
            "node",
            _string(value["node"], pointer, "node"),
            text,
            value.get("sequence", False),
        )
    if "edge" in value:
        _keys(value, EDGE_KEYS, pointer)
        target = _string(value.get("target"), pointer, "target")
        if not target.startswith("/") or SLOT not in target:
            raise ValueError(f"{pointer}: target must be a JSON pointer holding {SLOT}")
        text = _string(value["text"], pointer, "text") if "text" in value else None
        label = _string(value["edge"], pointer, "edge")
        return Mark(
            path, "edge", label, text, to=_string(value.get("to"), pointer, "to"), target=target
        )
    _keys(value, {"ref"}, pointer)
    ref = value["ref"]
    if not isinstance(ref, dict):
        raise ValueError(f"{pointer}: ref must be an object with id_kind, id and optional at")
    _keys(ref, REF_KEYS, pointer)
    clean = {key: _string(ref.get(key), pointer, f"ref.{key}") for key in ("id_kind", "id")}
    if "at" in ref:
        clean["at"] = _string(ref["at"], pointer, "ref.at")
    return Mark(path, "ref", ref=clean)


def marks(schema: Mapping[str, Any]) -> tuple[Mark, ...]:
    """Every place a kind schema marks with `x-story`, without repeats."""
    found: list[Mark] = []
    for path, value, pointer in walk(schema, KEYWORD, inside=True):
        mark = _mark(path, value, pointer)
        if all(m.path != path for m in found):
            found.append(mark)
    return tuple(found)
