"""Conditions and effects checked, shown and read against a project's vocabulary (core/vocabulary.py).

A condition is one of
    {"all": [C, ...]}   every one holds          {"any": [C, ...]}   at least one holds
    {"not": C}          C does not hold           {"fact": <path>, <operator>: <value>}   a leaf
or, when the vocabulary lists shorthand keys, an object made only of those keys (accepted as written;
the tool shows it key by key and cannot say what it reads).

`problems` returns (JSON pointer, message) pairs, never raising, so an editor can show every problem
at once; `text` is one line for people; `reads` lists the fact paths a condition reads. Effects are a
list of objects whose effect key names a kind from the vocabulary; `effect_problems` checks each
argument against its small schema.
"""

import re
from typing import Any

from core.vocabulary import FactRead, Vocabulary

GROUPS = ("all", "any", "not")
LEAF = "fact"
Problem = tuple[str, str]
JSON_TYPES: dict[str, tuple[type, ...]] = {
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "string": (str,),
}
TEXT_LIMIT = 60  # longest value shown in full in a condition's text


def _escape(key: object) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def _is(value: object, json_type: str) -> bool:
    """Whether `value` is of a JSON type ("array" is a list of strings); a bool is never a number."""
    if json_type == "array":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if isinstance(value, bool) and json_type != "boolean":
        return False
    return isinstance(value, JSON_TYPES[json_type])


def _article(name: str) -> str:
    return f"{'an' if name[:1] in 'aeiou' else 'a'} {name}"


def _nearest(word: str, options: list[str]) -> str:
    close = [o for o in options if o.startswith(word[:3])] or options
    return f" (known: {', '.join(sorted(close)[:8])})" if close else ""


def problems(vocabulary: Vocabulary, value: object, pointer: str = "") -> list[Problem]:
    """Every problem with a condition, each with the JSON pointer of the value at fault."""
    if not isinstance(value, dict) or not value:
        return [(pointer, "a condition is a non-empty object")]
    keys = set(value)
    if keys & set(GROUPS) or LEAF in keys:
        return _shaped(vocabulary, value, pointer)
    unknown = sorted(keys - set(vocabulary.shorthand))
    if unknown:
        known = [*GROUPS, LEAF, *vocabulary.shorthand]
        return [
            (f"{pointer}/{_escape(k)}", f"{k!r} is not a condition key{_nearest(k, known)}")
            for k in unknown
        ]
    return []


def _shaped(vocabulary: Vocabulary, value: dict[str, Any], pointer: str) -> list[Problem]:
    if len(value) != 1 and LEAF not in value:
        return [
            (
                pointer,
                f"a group holds exactly one of {', '.join(GROUPS)}, got {', '.join(sorted(value))}",
            )
        ]
    if LEAF in value:
        return _leaf(vocabulary, value, pointer)
    ((group, inner),) = value.items()
    if group == "not":
        return problems(vocabulary, inner, f"{pointer}/not")
    if not isinstance(inner, list) or not inner:
        return [(f"{pointer}/{group}", f"{group} takes a non-empty list of conditions")]
    found: list[Problem] = []
    for i, child in enumerate(inner):
        found += problems(vocabulary, child, f"{pointer}/{group}/{i}")
    return found


def _leaf(vocabulary: Vocabulary, value: dict[str, Any], pointer: str) -> list[Problem]:
    ops = [k for k in value if k != LEAF]
    if len(ops) != 1:
        return [
            (
                pointer,
                f"a leaf holds 'fact' and exactly one operator ({', '.join(vocabulary.operators)})",
            )
        ]
    op = ops[0]
    read = vocabulary.read(value[LEAF])
    if read is None:
        patterns = [f.pattern for f in vocabulary.facts]
        return [
            (
                f"{pointer}/fact",
                f"{value[LEAF]!r} is not a fact the vocabulary lists{_nearest(str(value[LEAF]), patterns)}",
            )
        ]
    if op not in vocabulary.operators:
        return [
            (
                f"{pointer}/{_escape(op)}",
                f"{op!r} is not an operator{_nearest(op, list(vocabulary.operators))}",
            )
        ]
    operator = vocabulary.operators[op]
    fact_type = read.fact.type
    if fact_type not in operator["types"]:
        return [
            (
                f"{pointer}/{_escape(op)}",
                f"{op} does not apply to {read.fact.pattern} ({fact_type}; {op} takes {', '.join(operator['types'])})",
            )
        ]
    json_type = vocabulary.types[fact_type]
    operand, given = operator["operand"], value[op]
    where = f"{pointer}/{_escape(op)}"
    if operand == "member" and not isinstance(given, str):
        return [(where, f"{op} takes one id")]
    if operand == "list":
        if not isinstance(given, list) or not given:
            return [(where, f"{op} takes a non-empty list")]
        return [
            (f"{where}/{i}", f"expected {_article(fact_type)}")
            for i, v in enumerate(given)
            if not _is(v, json_type)
        ]
    if operand == "same" and not _is(given, json_type):
        return [
            (
                where,
                f"{read.fact.pattern} is {_article(fact_type)}, so the value must be a JSON {json_type}",
            )
        ]
    return []


def _show(value: object) -> str:
    if isinstance(value, list):
        text = ", ".join(_show(v) for v in value)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, dict):
        text = ", ".join(f"{k} {_show(v)}" for k, v in value.items())
    else:
        text = str(value)
    return text if len(text) <= TEXT_LIMIT else text[: TEXT_LIMIT - 1] + "…"


def text(vocabulary: Vocabulary, value: object) -> str:
    """One line for people: `a(x).b at least 2 and (c is d or not e has f)`."""
    return _text(vocabulary, value, top=True)


def _text(vocabulary: Vocabulary, value: object, top: bool = False) -> str:
    if not isinstance(value, dict) or not value:
        return "(not a condition)"
    if LEAF in value:
        ops = [k for k in value if k != LEAF]
        if len(ops) != 1:
            return "(not a condition)"
        words = vocabulary.operators.get(ops[0], {}).get("text", ops[0])
        return f"{value[LEAF]} {words} {_show(value[ops[0]])}"
    if len(value) == 1 and next(iter(value)) in GROUPS:
        ((group, inner),) = value.items()
        if group == "not":
            return f"not ({_text(vocabulary, inner)})"
        if not isinstance(inner, list):
            return "(not a condition)"
        joined = f" {'and' if group == 'all' else 'or'} ".join(_text(vocabulary, c) for c in inner)
        return joined if top or len(inner) < 2 else f"({joined})"
    return "; ".join(f"{k}: {_show(v)}" for k, v in value.items())


def reads(vocabulary: Vocabulary, value: object) -> list[FactRead]:
    """The facts a condition reads, in order of first appearance, without repeats."""
    found: list[FactRead] = []
    _reads(vocabulary, value, found)
    return found


def _reads(vocabulary: Vocabulary, value: object, found: list[FactRead]) -> None:
    if not isinstance(value, dict):
        return
    if LEAF in value:
        read = vocabulary.read(value[LEAF])
        if read is not None and all(r.path != read.path for r in found):
            found.append(read)
        return
    for group in GROUPS:
        inner = value.get(group)
        for child in inner if isinstance(inner, list) else [inner] if inner is not None else []:
            _reads(vocabulary, child, found)


def is_shorthand(vocabulary: Vocabulary, value: object) -> bool:
    """Whether a condition is written in shorthand keys, whose reads the tool cannot know."""
    return isinstance(value, dict) and bool(value) and set(value) <= set(vocabulary.shorthand)


def read_view(read: FactRead) -> dict[str, Any]:
    return {
        "path": read.path,
        "pattern": read.fact.pattern,
        "type": read.fact.type,
        "doc": read.fact.doc,
        "ids": [{"id_kind": kind, "id": arg} for kind, arg in read.ids],
    }


# Effects


def effect_problems(vocabulary: Vocabulary, value: object, pointer: str = "") -> list[Problem]:
    """Every problem with a list of effects."""
    key = vocabulary.effect_key
    if key is None:
        return [(pointer, "the vocabulary lists no effects")]
    if not isinstance(value, list):
        return [(pointer, "effects are a list")]
    found: list[Problem] = []
    for i, effect in enumerate(value):
        found += _effect(vocabulary, key, effect, f"{pointer}/{i}")
    return found


def _effect(vocabulary: Vocabulary, key: str, effect: object, pointer: str) -> list[Problem]:
    if not isinstance(effect, dict) or not isinstance(effect.get(key), str):
        return [(pointer, f"an effect is an object whose {key!r} names its kind")]
    kind = effect[key]
    if kind not in vocabulary.effects:
        return [
            (
                f"{pointer}/{key}",
                f"{kind!r} is not an effect{_nearest(kind, list(vocabulary.effects))}",
            )
        ]
    spec = vocabulary.effects[kind]
    args: dict[str, Any] = spec["args"]
    found: list[Problem] = []
    for name in effect:
        if name != key and name not in args:
            found.append(
                (
                    f"{pointer}/{_escape(name)}",
                    f"{kind} takes no {name!r} (it takes: {', '.join(args) or 'nothing'})",
                )
            )
    for name in spec.get("required", []):
        if name not in effect:
            found.append((pointer, f"{kind} needs {name!r}"))
    for name, schema in args.items():
        if name in effect:
            problem = _argument(effect[name], schema)
            if problem:
                found.append((f"{pointer}/{_escape(name)}", problem))
    return found


def _argument(value: object, schema: dict[str, Any]) -> str | None:
    json_type = schema["type"]
    if not _is(value, json_type):
        return f"expected a JSON {json_type}"
    if "enum" in schema and value not in schema["enum"]:
        return f"expected one of {', '.join(map(str, schema['enum']))}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"at least {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"at most {schema['maximum']}"
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return f"at least {schema['minLength']} characters"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"at most {schema['maxLength']} characters"
        if "pattern" in schema and not re.search(schema["pattern"], value):
            return f"does not match {schema['pattern']}"
    return None


def effect_text(vocabulary: Vocabulary, effect: object) -> str:
    """One line for people: `kind arg value, arg value`."""
    key = vocabulary.effect_key or ""
    if not isinstance(effect, dict) or key not in effect:
        return "(not an effect)"
    rest = ", ".join(f"{k} {_show(v)}" for k, v in effect.items() if k != key)
    return f"{effect[key]} {rest}".strip()


def rule_mode_problems(vocabulary: Vocabulary, value: object, pointer: str = "") -> list[Problem]:
    if value in vocabulary.rule_modes:
        return []
    return [
        (pointer, f"expected a rule mode ({', '.join(vocabulary.rule_modes) or 'none listed'})")
    ]


def fact_problems(vocabulary: Vocabulary, value: object, pointer: str = "") -> list[Problem]:
    if vocabulary.read(value) is not None:
        return []
    patterns = [f.pattern for f in vocabulary.facts]
    return [
        (pointer, f"{value!r} is not a fact the vocabulary lists{_nearest(str(value), patterns)}")
    ]
