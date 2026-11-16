"""The kit table: project data that maps subject values to parameter ranges (plain Python; docs/parametric.md owns it).

    {"version": 1, "kind": "lamp",
     "subject_fields": ["theme", "material"],            fields of the subject sheet the rules look at
     "rules": [{"about": text, "when": {field: value},    applies when every `when` field equals the subject's
               "builder": "value" | ["a", "b"],           which variants (the schema's selector) are allowed
               "ranges": {field: [low, high]},            numbers: a narrower range than the schema's
               "choices": {field: [values]},              enums and booleans: the allowed values
               "colours": {field: ["#rrggbb", ...]}}],    colours: the allowed picks
     "defaults": {field: value},                          used by a field no rule ranges (else the schema default)
     "forbidden": [{field: value, ...}]}                  combinations never made: any row matching one is dropped

Rules apply in file order; a later rule narrows the range or choice list of an earlier one (the intersection), and an
intersection that is empty is an error at the cell. `validate` reports every problem as a line `POINTER: message`.
`plan(model, kit, subject)` is the per-field sampling plan for one subject, the only thing the generator reads.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import parameters  # noqa: E402

RULE_KEYS = {"about", "when", "builder", "ranges", "choices", "colours"}
KIT_KEYS = {"version", "kind", "subject_fields", "rules", "defaults", "forbidden"}


class KitError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def _rule_types_ok(rule, at, problems):
    """Check the type of every rule field; add a line per wrong one. True when the rule can be read further."""
    ok = True
    if "about" in rule and not isinstance(rule["about"], str):
        problems.append(f"{at}/about: expected text")
        ok = False
    for key in ("when", "ranges", "choices", "colours"):
        if rule.get(key) is not None and not isinstance(rule[key], dict):
            problems.append(f"{at}/{key}: expected an object of field: value")
            ok = False
    builder = rule.get("builder")
    if "builder" in rule and not (isinstance(builder, str) or (isinstance(builder, list) and all(isinstance(b, str) for b in builder))):
        problems.append(f"{at}/builder: expected a variant name or a list of them")
        ok = False
    return ok


def validate(kit, schema_model, schema_properties):
    """Problems of KIT against the parameter model and the schema's property dict; [] when it is sound."""
    problems = []
    fields = {f["name"]: f for f in schema_model["fields"]}
    if not isinstance(kit, dict):
        return ["/: must be an object"]
    for key in kit:
        if key not in KIT_KEYS:
            problems.append(f"/{key}: not a known key (known: {', '.join(sorted(KIT_KEYS))})")
    if kit.get("version") != 1:
        problems.append("/version: must be 1")
    subject_fields = kit.get("subject_fields", [])
    if not isinstance(subject_fields, list) or not all(isinstance(x, str) for x in subject_fields):
        problems.append("/subject_fields: expected a list of field names")
        subject_fields = []
    for name in subject_fields:
        if name not in schema_properties:
            problems.append(f"/subject_fields: {name!r} is not a property of the kind")
    selector = schema_model["selector"]
    rules = kit.get("rules", [])
    if not isinstance(rules, list):
        problems.append("/rules: expected a list of rules")
        rules = []
    for index, rule in enumerate(rules):
        at = f"/rules/{index}"
        if not isinstance(rule, dict):
            problems.append(f"{at}: must be an object")
            continue
        if not _rule_types_ok(rule, at, problems):
            continue
        for key in rule:
            if key not in RULE_KEYS:
                problems.append(f"{at}/{key}: not a known key (known: {', '.join(sorted(RULE_KEYS))})")
        for name, value in (rule.get("when") or {}).items():
            if name not in subject_fields:
                problems.append(f"{at}/when/{name}: not in subject_fields")
            elif (prop := schema_properties.get(name, {})).get("enum") and value not in prop["enum"]:
                problems.append(f"{at}/when/{name}: {value!r} is not one of {prop['enum']}")
        if "builder" in rule:
            wanted = rule["builder"] if isinstance(rule["builder"], list) else [rule["builder"]]
            allowed = fields.get(selector, {}).get("values", []) if selector else []
            if not selector:
                problems.append(f"{at}/builder: this kind has no x-selector")
            for value in wanted:
                if value not in allowed:
                    problems.append(f"{at}/builder: {value!r} is not one of {allowed}")
        for key in ("ranges", "choices", "colours"):
            for name, value in (rule.get(key) or {}).items():
                field = fields.get(name)
                where = f"{at}/{key}/{name}"
                if field is None:
                    problems.append(f"{where}: not a parameter of the kind")
                elif key == "ranges":
                    if field["type"] not in ("number", "integer"):
                        problems.append(f"{where}: ranges are for numbers")
                    elif not (isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value)
                              and field["min"] <= value[0] <= value[1] <= field["max"]):
                        problems.append(f"{where}: expected [low, high] inside {field['min']} to {field['max']}")
                elif key == "choices":
                    if field["type"] not in ("enum", "boolean"):
                        problems.append(f"{where}: choices are for enums and switches")
                    elif not isinstance(value, list) or not value:
                        problems.append(f"{where}: expected a non-empty list")
                    else:
                        for item in value:
                            if parameters.value_problem(field, item):
                                problems.append(f"{where}: {item!r}: {parameters.value_problem(field, item)}")
                else:
                    if field["type"] != "colour":
                        problems.append(f"{where}: colours are for colour fields")
                    elif not isinstance(value, list) or not value or any(parameters.value_problem(field, v) for v in value):
                        problems.append(f"{where}: expected a non-empty list of #rrggbb colours")
    defaults = kit.get("defaults") or {}
    if not isinstance(defaults, dict):
        problems.append("/defaults: expected an object of field: value")
        defaults = {}
    forbidden = kit.get("forbidden", [])
    if not isinstance(forbidden, list):
        problems.append("/forbidden: expected a list of objects")
        forbidden = []
    for name, value in defaults.items():
        field = fields.get(name)
        if field is None:
            problems.append(f"/defaults/{name}: not a parameter of the kind")
        elif (why := parameters.value_problem(field, value)):
            problems.append(f"/defaults/{name}: {why}")
    for index, combo in enumerate(forbidden):
        if not isinstance(combo, dict) or not combo:
            problems.append(f"/forbidden/{index}: expected a non-empty object of field: value")
        else:
            for name in combo:
                if name not in schema_properties:
                    problems.append(f"/forbidden/{index}/{name}: not a property of the kind")
    return problems


def plan(schema_model, kit, subject):
    """{"builders": [values] or None, "fields": {name: constraint}} for one SUBJECT (a dict of field values).
    A constraint is {"range": [lo, hi]}, {"choices": [...]} or {"fixed": value}; a field with none is open."""
    fields = {f["name"]: f for f in schema_model["fields"]}
    builders = None
    constraint = {}
    for rule in kit.get("rules", []):
        if any(subject.get(k) != v for k, v in (rule.get("when") or {}).items()):
            continue
        if "builder" in rule:
            wanted = rule["builder"] if isinstance(rule["builder"], list) else [rule["builder"]]
            builders = wanted if builders is None else [b for b in builders if b in wanted]
        for name, (low, high) in (rule.get("ranges") or {}).items():
            old = constraint.get(name, {}).get("range", [fields[name]["min"], fields[name]["max"]])
            constraint[name] = {"range": [max(old[0], low), min(old[1], high)]}
        for name, values in {**(rule.get("choices") or {}), **(rule.get("colours") or {})}.items():
            old = constraint.get(name, {}).get("choices")
            constraint[name] = {"choices": list(values) if old is None else [v for v in old if v in values]}
    if builders == []:
        raise KitError([f"subject {subject}: the rules leave no builder"])
    for name, spec in constraint.items():
        if ("range" in spec and spec["range"][0] > spec["range"][1]) or spec.get("choices") == []:
            raise KitError([f"subject {subject}: the rules leave no value for {name}"])
    for name, value in (kit.get("defaults") or {}).items():
        constraint.setdefault(name, {"fixed": value})
    return {"builders": builders, "fields": constraint}
