"""Parameters of a kind, read from its JSON Schema (standard library only, so tools and the server share it).

A property of a kind's schema is a parameter when it is one of:
    number / integer with `minimum` and `maximum` (optional `multipleOf` step, `x-unit` hint, `default`)
    string with `enum`                              a select
    boolean                                         a switch
    string with `"format": "color"`                 a colour, written "#rrggbb"
A kind is parametric when at least one property is a number with both bounds.

Two optional schema features make the parameter set vary with the row:
    `"x-selector": "<property>"` at the top of the schema names an enum property that picks a variant. The
        variant's own properties sit in `allOf: [{"if": {"properties": {sel: {"const": v}}}, "then":
        {"properties": {...}}}]` branches (draft 2020-12; use `unevaluatedProperties: false` to close the schema).
    `"x-when": "<boolean property>"` on a property: it applies only while that switch is true.

`model(schema)` lists every field once, with the variants it belongs to (`builders`, None for all) and its switch
(`when`). `active(model, row)` is the fields that apply to one row: the others are hidden in the form and left out by
the rules stage. Nothing here knows what a game calls its fields.
"""
import math
import re
from typing import Any

COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
DEFAULT_COLOUR = "#808080"


def _field(name: str, prop: dict[str, Any], builders: list[str] | None) -> dict[str, Any] | None:
    kind = prop.get("type")
    spec: dict[str, Any] | None = None
    if kind in ("number", "integer") and "minimum" in prop and "maximum" in prop:
        low, high = prop["minimum"], prop["maximum"]
        step = prop.get("multipleOf") or (1 if kind == "integer" else None)
        spec = {"type": kind, "min": low, "max": high, "step": step, "unit": prop.get("x-unit"), "default": 0}
        spec["default"] = prop["default"] if "default" in prop else snap(spec, (low + high) / 2)
    elif kind == "string" and isinstance(prop.get("enum"), list) and prop["enum"]:
        spec = {"type": "enum", "values": list(prop["enum"]), "default": prop.get("default", prop["enum"][0])}
    elif kind == "boolean":
        spec = {"type": "boolean", "default": prop.get("default", False)}
    elif kind == "string" and prop.get("format") == "color":
        spec = {"type": "colour", "default": prop.get("default", DEFAULT_COLOUR)}
    if spec is None:
        return None
    return {"name": name, "label": prop.get("title", name), "about": prop.get("description", ""), **spec,
            "builders": builders, "when": prop.get("x-when")}


def _sub(node: Any, key: str) -> dict[str, Any]:
    """NODE[key] when both are objects, else {} (a boolean subschema carries no parameter information)."""
    found = node.get(key) if isinstance(node, dict) else None
    return found if isinstance(found, dict) else {}


def model(schema: dict[str, Any]) -> dict[str, Any]:
    """{"selector": name or None, "fields": [field, ...]} for SCHEMA; fields are in schema order, branch fields after."""
    selector = schema.get("x-selector")
    # a subschema may be `true` or `false` in JSON Schema: that says nothing about a parameter, so it is skipped
    fields = [
        f for n, p in schema.get("properties", {}).items() if isinstance(p, dict) and (f := _field(n, p, None))
    ]
    seen = {f["name"] for f in fields}
    for branch in schema.get("allOf", []):
        if not isinstance(branch, dict):
            continue
        values = _sub(_sub(_sub(branch, "if"), "properties"), selector) if selector else {}
        match = [values["const"]] if "const" in values else list(values.get("enum", []))
        for name, prop in _sub(_sub(branch, "then"), "properties").items():
            if not isinstance(prop, dict):
                continue
            field = _field(name, prop, match)
            if field and name not in seen:
                fields.append(field)
            elif field:  # the same name in two variants: one field, offered to both
                next(f for f in fields if f["name"] == name)["builders"] = None
    return {"selector": selector, "fields": fields}


def is_parametric(parameter_model: dict[str, Any]) -> bool:
    return any(f["type"] in ("number", "integer") for f in parameter_model["fields"])


def active(parameter_model: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    """The fields that apply to ROW: those of its variant, whose switch (if any) is on."""
    selector = parameter_model["selector"]
    variant = row.get(selector) if selector else None
    chosen = [f for f in parameter_model["fields"] if f["builders"] is None or variant in f["builders"]]
    names = {f["name"] for f in chosen}
    return [f for f in chosen if f["when"] is None or (f["when"] in names and row.get(f["when"]) is True)]


def snap(field: dict[str, Any], value: float) -> float:
    """VALUE moved onto the field's step grid (from its minimum), clamped, rounded to hide float noise."""
    step = field["step"]
    if step:
        value = field["min"] + round((value - field["min"]) / step) * step
    value = min(max(value, field["min"]), field["max"])
    return int(round(value)) if field["type"] == "integer" else round(value, 6)


def value_problem(field: dict[str, Any], value: Any) -> str | None:
    """Why VALUE does not fit FIELD, or None."""
    kind = field["type"]
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"expected a {kind}"
        if kind == "integer" and int(value) != value:
            return f"expected a {kind}"
        if not field["min"] <= value <= field["max"]:
            return f"{value} is outside {field['min']} to {field['max']}"
        step = field["step"]
        if step and abs((value - field["min"]) / step - round((value - field["min"]) / step)) > 1e-6:
            return f"{value} is not a multiple of {step} from {field['min']}"
        return None
    if kind == "enum":
        return None if value in field["values"] else f"{value!r} is not one of {field['values']}"
    if kind == "boolean":
        return None if isinstance(value, bool) else "expected true or false"
    return None if isinstance(value, str) and COLOUR.fullmatch(value) else "expected a colour like #aabbcc"


def row_problems(parameter_model: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """Problems of ROW's parameters: an active field missing or out of range, an inactive field present."""
    problems = []
    fields = active(parameter_model, row)
    names = {f["name"] for f in fields}
    for f in fields:
        if f["name"] not in row:
            problems.append(f"{f['name']}: missing")
        elif (why := value_problem(f, row[f["name"]])):
            problems.append(f"{f['name']}: {why}")
    for f in parameter_model["fields"]:
        if f["name"] in row and f["name"] not in names:
            problems.append(f"{f['name']}: does not apply to this row")
    return problems
