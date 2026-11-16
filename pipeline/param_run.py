"""Run the parametric stages through adapters: rules, then render and measure for each row (docs/parametric.md).

Every command comes from the machine config (adapter_config); this module only fills data values and reads the files an
adapter wrote. Folder layout of a batch (`<folder>/`):
    inputs/{schema,kit,subject}.json   what the rules stage read
    rows.json                          its output
    tiles/<row id>/{row.json, still.png, still-*.png (other views), measure.json}
    parametric.json                    the whole batch: settings, tiles with numbers and gate results, timings
`render_one` is the same render and measure for a single row (the slider preview and a saved candidate).
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapter_config  # noqa: E402
import adapter_run  # noqa: E402
import param_gates  # noqa: E402

WORKERS = 4
MAX_BYTES = 8 * 1024 * 1024


def _pick(adapters, chosen, kind):
    return adapters.pick(chosen.get(kind) if chosen else None, kind)


def run_rules(adapters, chosen, schema_file, kit_file, subject, seed, count, folder):
    """Rows from the rules stage: [{"id", "cell", "seed", "row"}] and the number the kit dropped."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    subject_file = folder / "subject.json"
    subject_file.write_text(json.dumps(subject))
    adapter_run.run(_pick(adapters, chosen, "rules"),
                    {"schema": schema_file, "kit": kit_file, "subject": subject_file, "seed": seed, "count": count,
                     "output": folder / "rows.json", "out_dir": folder}, folder, log_name="rules.log")
    found = json.loads((folder / "rows.json").read_text())
    return found["rows"], found.get("dropped", 0)


def render_one(adapters, chosen, schema_file, row, seed, folder, gates=()):
    """Render and measure one ROW into FOLDER; {"still", "views", "numbers", "gates", "verdict", "seconds"}."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    row_file = folder / "row.json"
    row_file.write_text(json.dumps(row))
    started = time.monotonic()
    still = folder / adapter_config.OUTPUT["render"]
    adapter_run.run(_pick(adapters, chosen, "render"),
                    {"row": row_file, "schema": schema_file, "seed": seed, "output": still, "out_dir": folder},
                    folder, log_name="render.log")
    if not still.is_file() or still.stat().st_size > MAX_BYTES:
        raise adapter_run.Refused("the render adapter wrote no still.png (or one over 8 MB)")
    measured = folder / adapter_config.OUTPUT["measure"]
    adapter_run.run(_pick(adapters, chosen, "measure"),
                    {"row": row_file, "image": still, "schema": schema_file, "seed": seed, "output": measured,
                     "out_dir": folder}, folder, log_name="measure.log")
    try:
        numbers = json.loads(measured.read_text())["numbers"]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in numbers.values()):
            raise ValueError("numbers must all be numbers")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise adapter_run.Refused(f"the measure adapter's measure.json is not {{\"numbers\": {{name: number}}}}: {error}") from error
    results = param_gates.evaluate(gates, numbers)
    views = sorted(p.name for p in folder.glob("still-*.png"))
    return {"still": still.name, "views": views, "numbers": numbers, "gates": results,
            "verdict": param_gates.overall(results), "seconds": round(time.monotonic() - started, 3)}


def run_batch(adapters, chosen, schema_file, kit_file, gates, subject, seed, count, folder):
    """The whole batch into FOLDER; returns what it writes to parametric.json."""
    folder = Path(folder)
    started = time.monotonic()
    inputs = folder / "inputs"
    rows, dropped = run_rules(adapters, chosen, schema_file, kit_file, subject, seed, count, inputs)
    rules_seconds = round(time.monotonic() - started, 3)

    def one(entry):
        tile = render_one(adapters, chosen, schema_file, entry["row"], entry["seed"], folder / "tiles" / entry["id"], gates)
        return {"id": entry["id"], "cell": entry["cell"], "seed": entry["seed"], "row": entry["row"], **tile}

    with ThreadPoolExecutor(WORKERS) as pool:
        tiles = list(pool.map(one, rows))
    batch = {"version": 1, "subject": subject, "seed": seed, "count": count, "dropped": dropped,
             "adapters": {k: _pick(adapters, chosen, k).id for k in ("rules", "render", "measure")},
             "gates": [{k: g[k] for k in ("id", "about", "measure", "verdict") if k in g} for g in gates],
             "seconds": {"rules": rules_seconds, "total": round(time.monotonic() - started, 3)}, "tiles": tiles}
    (folder / "parametric.json").write_text(json.dumps(batch, indent=1) + "\n")
    return batch
