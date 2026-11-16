"""The rules stage: seeded candidate rows from a kit table, no model, no network (docs/parametric.md).

    python3 -I rules_generate.py --schema KIND.schema.json --kit KIT.json --subject SUBJECT.json --seed N --count N --output rows.json

SUBJECT.json is {"subject": {field: value}, "cross": {field: [values]}}: the fixed subject values, and up to two fields
whose values are crossed (a cell for each combination). Each cell makes COUNT rows from seeds derived from SEED, the
cell and the row number, so the same inputs give the same file. A row holds the subject values, the selector, and every
parameter that applies to it (core/parameters.py), and passes the schema's own limits. Output:
{"rows": [{"id": "v001", "cell": {...}, "seed": n, "row": {...}}], "dropped": n}.
"""
import argparse
import itertools
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_table  # noqa: E402
from core import parameters  # noqa: E402

MAX_CROSS = 2
MAX_ROWS = 500
TRIES = 50


def _draw(field, constraint, rng):
    if "fixed" in constraint:
        return constraint["fixed"]
    kind = field["type"]
    if kind in ("number", "integer"):
        low, high = constraint.get("range", [field["min"], field["max"]])
        value = parameters.snap(field, rng.uniform(low, high))
        return min(max(value, low), high) if not field["step"] else (value if low <= value <= high else parameters.snap(field, (low + high) / 2))
    pool = constraint.get("choices") or (field["values"] if kind == "enum" else [False, True] if kind == "boolean" else None)
    if pool is None:  # a colour with no list: three random channels
        return "#" + "".join(f"{rng.randrange(256):02x}" for _ in range(3))
    return rng.choice(pool)


def _row(parameter_model, plan, subject, rng, properties):
    """One row for SUBJECT: the selector first, then each field that applies to the row so far."""
    fields = {f["name"]: f for f in parameter_model["fields"]}
    row = {k: v for k, v in subject.items() if k in properties}
    selector = parameter_model["selector"]
    if selector and selector not in row:
        pool = plan["builders"] or plan["fields"].get(selector, {}).get("choices") or fields[selector]["values"]
        row[selector] = rng.choice(pool)
    for _ in range(len(fields) + 1):  # a switch decides which later fields apply; settle in a few passes
        wanted = parameters.active(parameter_model, row)
        missing = [f for f in wanted if f["name"] not in row]
        if not missing:
            break
        for field in missing:
            row[field["name"]] = _draw(field, plan["fields"].get(field["name"], {}), rng)
    names = {f["name"] for f in parameters.active(parameter_model, row)}
    return {k: v for k, v in row.items() if k in names or k not in fields}


def _forbidden(kit, row):
    return any(all(row.get(k) == v for k, v in combo.items()) for combo in kit.get("forbidden", []))


def generate(schema, kit, subject_sheet, seed, count):
    properties = schema.get("properties", {})
    parameter_model = parameters.model(schema)
    problems = kit_table.validate(kit, parameter_model, properties)
    if problems:
        raise kit_table.KitError(problems)
    fixed, cross = subject_sheet.get("subject", {}), subject_sheet.get("cross", {})
    if len(cross) > MAX_CROSS:
        raise ValueError(f"cross takes at most {MAX_CROSS} fields, got {len(cross)}")
    if not 1 <= count <= MAX_ROWS:
        raise ValueError(f"count must be 1 to {MAX_ROWS}")
    names = list(cross)
    cells = [dict(zip(names, combo)) for combo in itertools.product(*(cross[n] for n in names))] or [{}]
    if len(cells) * count > MAX_ROWS:
        raise ValueError(f"{len(cells)} cells of {count} rows is more than {MAX_ROWS}")
    rows, dropped = [], 0
    for cell in cells:
        subject = {**fixed, **cell}
        plan = kit_table.plan(parameter_model, kit, subject)
        for number in range(count):
            for attempt in range(TRIES):
                row_seed = seed * 1_000_003 + len(rows) * 101 + attempt
                row = _row(parameter_model, plan, subject, random.Random(f"{row_seed}:{sorted(subject.items())}"), properties)
                if not _forbidden(kit, row):
                    break
                dropped += 1
            else:
                raise kit_table.KitError([f"subject {subject}: every try hit a forbidden combination"])
            if "name" in properties and "name" not in row:
                row["name"] = " ".join([*(str(v) for v in cell.values()), f"{len(rows) + 1:03d}"])
            if (why := parameters.row_problems(parameter_model, row)):
                raise kit_table.KitError([f"made a bad row {row}: {'; '.join(why)}"])
            rows.append({"id": f"v{len(rows) + 1:03d}", "cell": cell, "seed": row_seed, "row": row})
    return {"rows": rows, "dropped": dropped}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("schema", "kit", "subject", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = generate(*(json.loads(p.read_text()) for p in (args.schema, args.kit, args.subject)), args.seed, args.count)
    except (kit_table.KitError, ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(result, indent=1) + "\n")
    (args.output.parent / "identity.json").write_text(json.dumps({"name": "rules-kit", "version": 1}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
