"""Gates for parametric rows: data that turns measured numbers into pass, review or fail (docs/parametric.md).

    {"version": 1, "kind": "lamp", "gates": [
        {"id": "not_empty", "about": text, "measure": "ink_ratio", "min": 0.06, "max": 0.35 (either or both),
         "verdict": "fail" | "review",
         "mutant": {"about": text, "row": {...}}}]}          a row that must fail this gate

Every gate names the measured number it reads, and ships a mutant row the gate must reject, so a gate that can never
fail is caught by `check_mutants` (the tests run it with the stand-in; a game runs it with its own measure adapter).
`evaluate(gates, numbers)` is [{"id", "verdict": "pass" | "review" | "fail", "value", "about"}] and `overall` is the
worst of them.
"""
GATE_KEYS = {"id", "about", "measure", "min", "max", "verdict", "mutant"}
ORDER = {"pass": 0, "review": 1, "fail": 2}


class GateError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def validate(raw):
    """The gates list of RAW, or GateError with one line per problem."""
    problems = []
    if not isinstance(raw, dict) or not isinstance(raw.get("gates"), list):
        raise GateError(["/gates: expected a list"])
    seen = set()
    for index, gate in enumerate(raw["gates"]):
        at = f"/gates/{index}"
        if not isinstance(gate, dict):
            problems.append(f"{at}: must be an object")
            continue
        for key in gate:
            if key not in GATE_KEYS:
                problems.append(f"{at}/{key}: not a known key")
        if not isinstance(gate.get("id"), str) or gate["id"] in seen:
            problems.append(f"{at}/id: expected a unique text id")
        seen.add(gate.get("id"))
        if not isinstance(gate.get("measure"), str):
            problems.append(f"{at}/measure: expected the name of a measured number")
        if not any(isinstance(gate.get(k), (int, float)) for k in ("min", "max")):
            problems.append(f"{at}: give min, max or both")
        if gate.get("verdict") not in ("fail", "review"):
            problems.append(f"{at}/verdict: expected fail or review")
        if not isinstance((gate.get("mutant") or {}).get("row"), dict):
            problems.append(f"{at}/mutant/row: every gate ships a mutant row it must fail")
    if problems:
        raise GateError(problems)
    return raw["gates"]


def evaluate(gates, numbers):
    results = []
    for gate in gates:
        value = numbers.get(gate["measure"])
        bad = value is None or ("min" in gate and value < gate["min"]) or ("max" in gate and value > gate["max"])
        results.append({"id": gate["id"], "about": gate.get("about", ""), "measure": gate["measure"], "value": value,
                        "verdict": gate["verdict"] if bad else "pass"})
    return results


def overall(results):
    return max((r["verdict"] for r in results), key=ORDER.__getitem__, default="pass")


def check_mutants(gates, measure_row):
    """Problems: a gate its own mutant does not fail. MEASURE_ROW(row) returns the measured numbers of one row."""
    problems = []
    for gate in gates:
        numbers = measure_row(gate["mutant"]["row"])
        outcome = next(r for r in evaluate([gate], numbers))
        if outcome["verdict"] == "pass":
            problems.append(f"gate {gate['id']}: its mutant row passes ({gate['measure']} = {numbers.get(gate['measure'])})")
    return problems
