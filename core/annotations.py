"""Where a kind schema says a value is a condition, a list of effects, a rule mode or a fact path.

A kind schema marks a property with the keyword `x-vocabulary` (docs/vocabulary.md):

    "when":    {"x-vocabulary": "condition", "anyOf": [...]}
    "effects": {"x-vocabulary": "effects", "type": "array", ...}

JSON Schema ignores keywords it does not know, so the schema validates as before. `sites` walks a
schema once (through properties, items, additionalProperties, local $refs and anyOf/oneOf/allOf) and
returns each marked place as a path pattern, where "*" is any key or index; `instances` finds the
values at those places in an entity's data, each with its JSON pointer.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

KEYWORD = "x-vocabulary"
ROLES = ("condition", "effects", "rule_mode", "fact")
ANY = "*"
BRANCHES = ("anyOf", "oneOf", "allOf")


@dataclass(frozen=True)
class Site:
    path: tuple[str, ...]  # property names, or ANY for any key or index
    role: str
    schema_pointer: str  # where the keyword sits in the schema, for messages


def _resolve(root: Mapping[str, Any], node: Any) -> Any:
    """Follow local `$ref`s (`#/$defs/x`); the kind loader has already checked they resolve."""
    seen = 0
    while isinstance(node, dict) and isinstance(node.get("$ref"), str) and seen < 32:
        target: Any = root
        for part in node["$ref"].lstrip("#").split("/")[1:]:
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
        seen += 1
    return node


def walk(
    root: Mapping[str, Any], keyword: str, inside: bool = False
) -> Iterator[tuple[tuple[str, ...], Any, str]]:
    """(instance path pattern, keyword value, schema pointer) for every schema node carrying `keyword`.
    Does not look inside a node that carries it unless `inside` (story nodes hold story nodes). A $ref
    already being followed on the way down is not followed again, so recursive schemas end."""
    yield from _walk(root, root, keyword, (), "", frozenset(), inside)


def _walk(
    root: Mapping[str, Any],
    node: Any,
    keyword: str,
    path: tuple[str, ...],
    at: str,
    refs: frozenset[str],
    inside: bool,
) -> Iterator[tuple[tuple[str, ...], Any, str]]:
    if not isinstance(node, dict):
        return
    if keyword in node:
        yield path, node[keyword], f"{at}/{keyword}"
        if not inside:
            return
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in refs:
            return
        yield from _walk(
            root, _resolve(root, node), keyword, path, ref.lstrip("#"), refs | {ref}, inside
        )
    for name, child in (node.get("properties") or {}).items():
        yield from _walk(
            root, child, keyword, (*path, name), f"{at}/properties/{name}", refs, inside
        )
    for key in ("items", "additionalProperties"):
        if isinstance(node.get(key), dict):
            yield from _walk(root, node[key], keyword, (*path, ANY), f"{at}/{key}", refs, inside)
    for key in BRANCHES:
        for i, child in enumerate(node.get(key) or []):
            yield from _walk(root, child, keyword, path, f"{at}/{key}/{i}", refs, inside)


def sites(schema: Mapping[str, Any]) -> tuple[Site, ...]:
    """Every place a kind schema marks with `x-vocabulary`, without repeats. A value that is not one
    of ROLES raises ValueError naming the schema pointer (the kind loader turns it into bad_schema)."""
    found: list[Site] = []
    for path, role, pointer in walk(schema, KEYWORD):
        if role not in ROLES:
            raise ValueError(f"{pointer}: {role!r} is not one of {', '.join(ROLES)}")
        if all(site.path != path for site in found):
            found.append(Site(path, role, pointer))
    return tuple(found)


def _escape(key: object) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def instances(data: Any, path: tuple[str, ...], pointer: str = "") -> Iterator[tuple[str, Any]]:
    """(JSON pointer, value) of every value in `data` at a path pattern. Missing keys yield nothing."""
    if not path:
        yield pointer, data
        return
    head, rest = path[0], path[1:]
    if head == ANY:
        if isinstance(data, dict):
            for key, value in data.items():
                yield from instances(value, rest, f"{pointer}/{_escape(key)}")
        elif isinstance(data, list):
            for i, value in enumerate(data):
                yield from instances(value, rest, f"{pointer}/{i}")
    elif isinstance(data, dict) and head in data:
        yield from instances(data[head], rest, f"{pointer}/{_escape(head)}")
