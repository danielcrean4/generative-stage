"""A project's condition vocabulary: the facts a condition may read, the operators, the id kinds,
the effects and the rule modes (docs/vocabulary.md). The file is data a game supplies; nothing here
knows any game.

    <schema_dir>/vocabulary.json    the file, in the format core/vocabulary.schema.json defines

It is optional. When present it is checked when the project's kinds load: against the format's JSON
Schema, then for names that must agree (a fact's type, an operator's types, an id kind a pattern or
an argument uses). The first problem raises BadProjectFiles naming the file and the JSON pointer.

A fact path is a pattern with every id kind filled in: `room(room).lamp` is read as `room(hall).lamp`.
"""

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from core.errors import BadProjectFiles, Invalid

VOCABULARY_FILE = "vocabulary.json"
FORMAT_SCHEMA_FILE = Path(__file__).with_name("vocabulary.schema.json")
DEFAULT_ID_FIELD = "key"
SEGMENT = re.compile(r"([a-z][a-z0-9_]*)(?:\(([^()]*)\))?")
ID_ARG = re.compile(r"[a-z0-9_][a-z0-9_ .:-]*")


@dataclass(frozen=True)
class Fact:
    pattern: str
    type: str
    doc: str
    shape: tuple[tuple[str, str | None], ...]  # (segment name, id kind or None)


@dataclass(frozen=True)
class FactRead:
    """One fact path a condition reads, matched to its pattern: `ids` are (id kind, id) in order."""

    path: str
    fact: Fact
    ids: tuple[tuple[str, str], ...]


def split_path(text: str) -> list[tuple[str, str | None]] | None:
    """`a(x).b` as [("a", "x"), ("b", None)], or None when the text is not a well-formed path."""
    parts: list[tuple[str, str | None]] = []
    for segment in _segments(text):
        match = SEGMENT.fullmatch(segment)
        if match is None:
            return None
        parts.append((match.group(1), match.group(2)))
    return parts or None


def _segments(text: str) -> Iterator[str]:
    """Split on dots outside parentheses (an id may hold dots)."""
    depth, start = 0, 0
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "." and depth == 0:
            yield text[start:i]
            start = i + 1
    yield text[start:]


@dataclass(frozen=True)
class Vocabulary:
    raw: Mapping[str, Any]  # the file as written, for the API
    types: Mapping[str, str]  # type name -> JSON type of a value
    facts: tuple[Fact, ...]
    operators: Mapping[str, Mapping[str, Any]]
    id_kinds: Mapping[str, Mapping[str, Any]]
    effect_key: str | None
    effects: Mapping[str, Mapping[str, Any]]
    rule_modes: Mapping[str, Mapping[str, Any]]
    shorthand: tuple[str, ...]

    def read(self, path: object) -> FactRead | None:
        """The fact a path reads, or None when no pattern matches it."""
        if not isinstance(path, str):
            return None
        parts = split_path(path)
        if parts is None:
            return None
        for fact in self.facts:
            if len(fact.shape) != len(parts):
                continue
            ids: list[tuple[str, str]] = []
            for (name, kind), (got, arg) in zip(fact.shape, parts, strict=True):
                if name != got or (kind is None) != (arg is None):
                    break
                if kind is not None and arg is not None:
                    if not ID_ARG.fullmatch(arg):
                        break
                    ids.append((kind, arg))
            else:
                return FactRead(path, fact, tuple(ids))
        return None

    def entity_kinds(self, id_kind: str) -> tuple[tuple[str, ...], str]:
        """The project kinds whose entities an id kind names, and the data field holding the id."""
        entry = self.id_kinds.get(id_kind, {})
        return tuple(entry.get("entity_kinds", ())), str(entry.get("field", DEFAULT_ID_FIELD))

    def describe(self) -> dict[str, Any]:
        return dict(self.raw)


def _fail(file: Path, pointer: str, problem: str) -> BadProjectFiles:
    return BadProjectFiles(f"{file}: {pointer or '/'}: {problem}", "bad_schema")


def _format_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(FORMAT_SCHEMA_FILE.read_text(encoding="utf-8")))


def _pointer(parts: Iterator[object] | list[object]) -> str:
    return "".join(f"/{str(p).replace('~', '~0').replace('/', '~1')}" for p in parts)


def parse(raw: object, file: Path) -> Vocabulary:
    """Check a parsed vocabulary file; BadProjectFiles names `file` and the JSON pointer."""
    error = best_match(_format_validator().iter_errors(raw))
    if error is not None:
        raise _fail(file, _pointer(list(error.absolute_path)), error.message)
    assert isinstance(raw, dict)
    types = {name: str(entry["json"]) for name, entry in raw["types"].items()}
    facts: list[Fact] = []
    id_kinds: dict[str, Any] = raw.get("id_kinds", {})
    used_kinds: list[tuple[str, str]] = []  # (pointer, id kind)
    for i, entry in enumerate(raw["facts"]):
        if entry["type"] not in types:
            raise _fail(file, f"/facts/{i}/type", f"{entry['type']!r} is not one of the types")
        shape = tuple((name, kind) for name, kind in split_path(entry["pattern"]) or [])
        if any(f.shape == shape for f in facts):
            raise _fail(file, f"/facts/{i}/pattern", f"{entry['pattern']!r} is listed twice")
        used_kinds += [(f"/facts/{i}/pattern", kind) for _, kind in shape if kind]
        facts.append(Fact(entry["pattern"], entry["type"], entry.get("doc", ""), shape))
    for name, operator in raw["operators"].items():
        for j, type_name in enumerate(operator["types"]):
            if type_name not in types:
                raise _fail(
                    file, f"/operators/{name}/types/{j}", f"{type_name!r} is not one of the types"
                )
    effects = raw.get("effects", {"kinds": {}})
    for name, effect in effects["kinds"].items():
        where = f"/effects/kinds/{name}"
        if effects["key"] in effect["args"]:
            raise _fail(file, f"{where}/args", f"an argument may not be named {effects['key']!r}")
        for arg in effect.get("required", []):
            if arg not in effect["args"]:
                raise _fail(file, f"{where}/required", f"{arg!r} is not one of its args")
        used_kinds += [
            (f"{where}/args/{a}", s["id_kind"]) for a, s in effect["args"].items() if "id_kind" in s
        ]
        ref = effect.get("ref")
        if ref is not None:
            used_kinds.append((f"{where}/ref", ref["id_kind"]))
            if ref["id"] not in effect["args"]:
                raise _fail(file, f"{where}/ref/id", f"{ref['id']!r} is not one of its args")
    if "id_kinds" in raw:
        for pointer, kind in used_kinds:
            if kind not in id_kinds:
                raise _fail(file, pointer, f"the id kind {kind!r} is not in id_kinds")
    return Vocabulary(
        raw=raw,
        types=types,
        facts=tuple(facts),
        operators=raw["operators"],
        id_kinds=id_kinds,
        effect_key=effects.get("key"),
        effects=effects["kinds"],
        rule_modes=raw.get("rule_modes", {}),
        shorthand=tuple(raw.get("shorthand", {}).get("keys", ())),
    )


def load_vocabulary(folder: Path) -> Vocabulary | None:
    """The vocabulary in a schema folder, or None when the folder has none."""
    file = folder / VOCABULARY_FILE
    if not file.is_file():
        return None
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _fail(file, "", f"not readable JSON ({error})") from error
    return parse(raw, file)


def write_vocabulary(folder: Path, raw: object) -> Vocabulary:
    """Check `raw` as a vocabulary file and, if it is one, write it into the schema folder.
    A problem is Invalid (the data sent is wrong), naming the JSON pointer in the body."""
    file = folder / VOCABULARY_FILE
    try:
        vocabulary = parse(raw, file)
    except BadProjectFiles as error:
        message = error.message.removeprefix(f"{file}: ")
        raise Invalid(message, "invalid", message.split(":", 1)[0]) from error
    temporary = file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(file)
    return vocabulary
