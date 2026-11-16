"""Entity kinds and link types, read from a project's schema folder. The only module that uses the
JSON Schema validator.

    <schema_dir>/kinds.json         {"kinds": [descriptor, ...]}
    <schema_dir>/<kind>.schema.json one JSON Schema (draft 2020-12) per kind, named by its descriptor
    <schema_dir>/link_types.json    {"link_types": [link type, ...]}   (optional)

A kind descriptor: `id`, `label`, `plural_label`, `schema` (file name in the folder),
`title_field`, `icon` (a name), optional `brief_field` (a string property holding a short
description; leave it out for a kind with none), optional `tags_field` (default `tags`), optional
`family` (one of FAMILIES: how the app groups the kind; none means "Other") and, for a `script`
kind only, optional `form` (one of FORMS: whether its lines run in order or branch).
A link type: `id`, `label`, `inverse_label`, `source_kinds`, `target_kinds`.

A kind schema may mark properties with `x-vocabulary` (core/annotations.py); such a kind needs the
folder's optional condition vocabulary, `vocabulary.json` (core/vocabulary.py), which is loaded
with the kinds and checks the marked values on every write (core/conditions.py). It may also mark
story nodes, edges and references with `x-story` (core/story_marks.py), which the story graph reads
(core/story.py).

Everything is checked when loaded; the first problem raises BadProjectFiles naming the file and
the key or JSON pointer. Only local `$ref` (starting with `#`) is allowed, so validation never
reaches the network or another file. This module and core/vocabulary.py are the only users of the
JSON Schema validator.
"""

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError, best_match
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from core import conditions, parameters
from core.annotations import Site, instances, sites
from core.errors import BadProjectFiles, Invalid, NotFound
from core.ids import NAME_ID
from core.story_marks import Mark, marks
from core.vocabulary import VOCABULARY_FILE, Vocabulary, load_vocabulary

KINDS_FILE = "kinds.json"
LINK_TYPES_FILE = "link_types.json"
DEFAULT_TAGS_FIELD = "tags"
KIND_KEYS = ("id", "label", "plural_label", "schema", "title_field", "icon")
OPTIONAL_KIND_KEYS = ("brief_field", "tags_field", "family", "form")
FAMILIES = ("prop", "character", "setting", "script", "stage")
FORMS = ("linear", "branching")
SELF = "urn:kind-schema"  # the base a schema's local references resolve against
LINK_TYPE_KEYS = ("id", "label", "inverse_label", "source_kinds", "target_kinds")


@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    plural_label: str
    icon: str
    title_field: str
    brief_field: str | None  # None when the kind has no short description
    tags_field: str | None  # None when the schema has no tags property
    schema_file: Path
    schema: Mapping[str, Any]
    sites: tuple[Site, ...] = ()  # the values the schema marks with x-vocabulary
    story: tuple[Mark, ...] = ()  # the values the schema marks with x-story
    family: str | None = None  # one of FAMILIES, or None for "Other"
    form: str | None = None  # one of FORMS, for a script kind only

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "plural_label": self.plural_label,
            "icon": self.icon,
            "title_field": self.title_field,
            "brief_field": self.brief_field,
            "tags_field": self.tags_field,
            "family": self.family,
            "form": self.form,
            "schema_file": self.schema_file.name,
            "schema": self.schema,
            "parameters": self._parameters(),
        }

    def _parameters(self) -> dict[str, Any] | None:
        """The parameter model (core/parameters.py) when this kind is parametric, else None."""
        found = parameters.model(dict(self.schema))
        return found if parameters.is_parametric(found) else None

    def check(self, data: object, pointer: str = "/data") -> dict[str, Any]:
        """Return `data` if it fits this kind's schema, else raise Invalid naming the field."""
        if not isinstance(data, dict):
            raise Invalid(f"{pointer} must be an object", "invalid_entity", pointer)
        validator = Draft202012Validator(dict(self.schema), registry=Registry())
        try:
            error = best_match(validator.iter_errors(data))
        except Unresolvable as exc:  # checked at load; reaching here means the file is wrong
            raise BadProjectFiles(
                f"{self.schema_file}: a reference does not resolve ({exc})", "bad_schema"
            ) from exc
        if error is not None:
            field = pointer + _pointer(_field_path(error))
            raise Invalid(f"{field}: {error.message}", "invalid_entity", field)
        return data


@dataclass(frozen=True)
class LinkType:
    id: str
    label: str
    inverse_label: str
    source_kinds: tuple[str, ...]
    target_kinds: tuple[str, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "inverse_label": self.inverse_label,
            "source_kinds": list(self.source_kinds),
            "target_kinds": list(self.target_kinds),
        }


@dataclass(frozen=True)
class Catalogue:
    """A project's kinds and link types, in the order their files list them."""

    kinds: Mapping[str, Kind]
    link_types: Mapping[str, LinkType]
    vocabulary: Vocabulary | None = None

    def check_vocabulary(self, kind: Kind, data: dict[str, Any], pointer: str = "/data") -> None:
        """Raise Invalid at the first marked value (a condition, effects, a rule mode, a fact path)
        that the vocabulary refuses. Absent or null values are not checked."""
        if self.vocabulary is None:
            return
        for site in kind.sites:
            for at, value in instances(data, site.path, pointer):
                if value is None:
                    continue
                found = CHECKS[site.role](self.vocabulary, value, at)
                if found:
                    field, message = found[0]
                    raise Invalid(f"{field}: {message}", "invalid_entity", field)

    def kind(self, kind_id: str) -> Kind:
        if kind_id not in self.kinds:
            known = ", ".join(self.kinds) or "none"
            raise NotFound(f"no kind {kind_id!r} (kinds: {known})", "unknown_kind", "/kind")
        return self.kinds[kind_id]


CHECKS = {
    "condition": conditions.problems,
    "effects": conditions.effect_problems,
    "rule_mode": conditions.rule_mode_problems,
    "fact": conditions.fact_problems,
}


def _pointer(parts: Iterable[object]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _field_path(error: ValidationError) -> list[object]:
    """Where the error is. A missing required property is reported at that property."""
    path: list[object] = list(error.absolute_path)
    wanted = error.validator_value
    if (
        error.validator == "required"
        and isinstance(error.instance, dict)
        and isinstance(wanted, list)
    ):
        missing = [k for k in wanted if k not in error.instance]
        if missing:
            path.append(missing[0])
    return path


def _fail(file: Path, where: str, problem: str) -> BadProjectFiles:
    return BadProjectFiles(f"{file}: {where}: {problem}", "bad_schema")


def _read_object(file: Path) -> dict[str, Any]:
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BadProjectFiles(f"{file}: missing", "bad_schema") from error
    except OSError as error:
        raise BadProjectFiles(f"{file}: cannot read ({error})", "bad_schema") from error
    except ValueError as error:
        raise BadProjectFiles(f"{file}: not valid JSON ({error})", "bad_schema") from error
    if not isinstance(raw, dict):
        raise BadProjectFiles(f"{file}: the file must hold a JSON object", "bad_schema")
    return raw


def _list(file: Path, raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entries = raw.get(key)
    if set(raw) != {key} or not isinstance(entries, list):
        raise _fail(file, f"key '{key}'", f"expected an object with one key '{key}' holding a list")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _fail(file, f"key '{key}[{i}]'", "expected an object")
    return entries


def _string(file: Path, where: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(file, where, f"expected a non-empty string, got {value!r}")
    return value


def _name_id(file: Path, where: str, value: object, seen: Mapping[str, object]) -> str:
    text = _string(file, where, value)
    if not NAME_ID.fullmatch(text):
        raise _fail(file, where, f"{text!r} must be lowercase letters, digits and underscores")
    if text in seen:
        raise _fail(file, where, f"{text!r} is listed twice")
    return text


def _keys(
    file: Path,
    where: str,
    entry: dict[str, Any],
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> None:
    for key in entry:
        if key not in (*required, *optional):
            raise _fail(
                file,
                f"{where}.{key}",
                f"unknown key (known keys: {', '.join((*required, *optional))})",
            )
    for key in required:
        if key not in entry:
            raise _fail(file, f"{where}.{key}", "missing")


def _refs(node: object, pointer: str = "") -> Iterator[tuple[str, object]]:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{pointer}/{key}"
            if key in ("$ref", "$dynamicRef"):
                yield here, value
            yield from _refs(value, here)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _refs(value, f"{pointer}/{i}")


def _property(file: Path, schema: dict[str, Any], key: str, name: str) -> dict[str, Any] | None:
    properties = schema.get("properties")
    value = properties.get(name) if isinstance(properties, dict) else None
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _fail(file, f"/properties/{name}", f"must be a schema object (named by {key})")
    return value


def _load_schema(
    file: Path, kinds_file: Path, descriptor: dict[str, Any], where: str
) -> tuple[dict[str, Any], str | None]:
    """Read and check one kind schema against its descriptor; return it and its tags field."""
    schema = _read_object(file)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        pointer = _pointer(list(error.absolute_path)) or "/"
        raise _fail(
            file, pointer, f"not a valid JSON Schema (draft 2020-12): {error.message}"
        ) from error
    resolver = Registry().with_resource(SELF, DRAFT202012.create_resource(schema)).resolver(SELF)
    for pointer, value in _refs(schema):
        if not isinstance(value, str) or not value.startswith("#"):
            raise _fail(
                file,
                pointer,
                f"only local references (starting with '#') are allowed, got {value!r}",
            )
        try:
            resolver.lookup(value)
        except Unresolvable as error:
            raise _fail(file, pointer, f"the reference {value!r} does not resolve") from error
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise _fail(file, "/type", 'a kind schema must be "type": "object" with "properties"')
    required = schema.get("required", [])
    for key in ("title_field", "brief_field"):
        if key not in descriptor:
            continue  # only brief_field is optional; _keys has already required title_field
        name = _string(kinds_file, f"{where}.{key}", descriptor[key])
        prop = _property(file, schema, key, name)
        if prop is None or prop.get("type") != "string":
            raise _fail(file, f"/properties/{name}", f"{key} {name!r} must be a string property")
    if descriptor["title_field"] not in required:
        raise _fail(
            file, "/required", f"the title field {descriptor['title_field']!r} must be required"
        )
    tags = descriptor.get("tags_field", DEFAULT_TAGS_FIELD)
    named = "tags_field" in descriptor
    tags = _string(kinds_file, f"{where}.tags_field", tags)
    prop = _property(file, schema, "tags_field", tags)
    if prop is None:
        if named:
            raise _fail(file, f"/properties/{tags}", f"tags_field {tags!r} is not a property")
        return schema, None
    items = prop.get("items")
    if prop.get("type") != "array" or not isinstance(items, dict) or items.get("type") != "string":
        raise _fail(file, f"/properties/{tags}", "the tags field must be an array of strings")
    return schema, tags


def _choice(file: Path, where: str, value: object, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise _fail(file, where, f"expected one of {', '.join(allowed)}, got {value!r}")
    return str(value)


def _family_and_form(
    file: Path, where: str, entry: dict[str, Any]
) -> tuple[str | None, str | None]:
    """The kind's family and form, both optional; a form belongs to a script kind only."""
    family = (
        _choice(file, f"{where}.family", entry["family"], FAMILIES) if "family" in entry else None
    )
    if "form" not in entry:
        return family, None
    if family != "script":
        raise _fail(file, f"{where}.form", 'only a kind with "family": "script" has a form')
    return family, _choice(file, f"{where}.form", entry["form"], FORMS)


def _load_kinds(folder: Path) -> dict[str, Kind]:
    file = folder / KINDS_FILE
    kinds: dict[str, Kind] = {}
    for i, entry in enumerate(_list(file, _read_object(file), "kinds")):
        where = f"key 'kinds[{i}]'"
        _keys(file, where, entry, KIND_KEYS, OPTIONAL_KIND_KEYS)
        kind_id = _name_id(file, f"{where}.id", entry["id"], kinds)
        family, form = _family_and_form(file, where, entry)
        name = _string(file, f"{where}.schema", entry["schema"])
        schema_file = (folder / name).resolve()
        if schema_file.parent != folder.resolve():
            raise _fail(
                file, f"{where}.schema", f"{name!r} must be a file name in the schema folder"
            )
        schema, tags_field = _load_schema(schema_file, file, entry, where)
        try:
            marked = sites(schema)
            story = marks(schema)
        except ValueError as error:
            pointer, problem = str(error).split(": ", 1)
            raise _fail(schema_file, pointer, problem) from error
        kinds[kind_id] = Kind(
            id=kind_id,
            label=_string(file, f"{where}.label", entry["label"]),
            plural_label=_string(file, f"{where}.plural_label", entry["plural_label"]),
            icon=_string(file, f"{where}.icon", entry["icon"]),
            title_field=entry["title_field"],
            brief_field=entry.get("brief_field"),
            tags_field=tags_field,
            schema_file=schema_file,
            schema=schema,
            sites=marked,
            story=story,
            family=family,
            form=form,
        )
    if not kinds:
        raise _fail(file, "key 'kinds'", "list at least one kind")
    return kinds


def _kind_list(file: Path, where: str, value: object, kinds: Mapping[str, Kind]) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _fail(file, where, "expected a non-empty list of kind ids")
    for i, kind_id in enumerate(value):
        if kind_id not in kinds:
            raise _fail(
                file, f"{where}[{i}]", f"{kind_id!r} is not a kind (kinds: {', '.join(kinds)})"
            )
    return tuple(value)


def _load_link_types(folder: Path, kinds: Mapping[str, Kind]) -> dict[str, LinkType]:
    file = folder / LINK_TYPES_FILE
    if not file.exists():
        return {}
    types: dict[str, LinkType] = {}
    for i, entry in enumerate(_list(file, _read_object(file), "link_types")):
        where = f"key 'link_types[{i}]'"
        _keys(file, where, entry, LINK_TYPE_KEYS)
        type_id = _name_id(file, f"{where}.id", entry["id"], types)
        types[type_id] = LinkType(
            id=type_id,
            label=_string(file, f"{where}.label", entry["label"]),
            inverse_label=_string(file, f"{where}.inverse_label", entry["inverse_label"]),
            source_kinds=_kind_list(file, f"{where}.source_kinds", entry["source_kinds"], kinds),
            target_kinds=_kind_list(file, f"{where}.target_kinds", entry["target_kinds"], kinds),
        )
    return types


def load_catalogue(folder: Path) -> Catalogue:
    """Read and check every kind and link type in a schema folder."""
    if not folder.is_dir():
        raise BadProjectFiles(f"{folder}: the schema folder does not exist", "bad_schema")
    kinds = _load_kinds(folder)
    vocabulary = load_vocabulary(folder)
    if vocabulary is None:
        for kind in kinds.values():
            if kind.sites:
                raise _fail(
                    kind.schema_file,
                    kind.sites[0].schema_pointer,
                    f"marks a {kind.sites[0].role} but the folder has no {VOCABULARY_FILE}",
                )
    return Catalogue(kinds=kinds, link_types=_load_link_types(folder, kinds), vocabulary=vocabulary)
