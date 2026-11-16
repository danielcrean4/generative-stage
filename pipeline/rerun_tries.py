"""Run saved tries through the finishing chain and tabulate them (tools interpreter: numpy, trimesh, PIL).

python rerun_tries.py INDEX.json MAPPING.json OUT_DIR [--only N,N,...]

One job: take tries recorded earlier and run each saved `mesh.glb` with its `mesh.input.png` through
mesh_finish (normalise, decimate, v2 gate), then write what came out in one place.

INDEX.json is a list of [n, path to the try's mesh-validation.json, v1_passed]; the mesh and the image
sit in the same folder as that file, and the path names the run and attempt
(.../<run>/attempts/<attempt>/mesh/try-K/mesh-validation.json).
MAPPING.json is data, one owner for which config judges which try:
  {"configs": {"KIND": "path to a finish config", ...},
   "face_budget": 20000,                 (optional: written into scratch copies of the configs, nothing else changes)
   "tries": {"0": "KIND", ...},          (every index entry needs a kind)
   "contact": {"per_page": 8, "columns": 2, "scale": 0.6}}
Output, all under OUT_DIR: configs/ (the config files actually used), NN/ (a mesh_finish folder with
gate/review-sheet.png, and try.json), results.json, results.csv, contact_PP.png (the review sheets of
tries PP*per_page onward, numbered NN as in the index; look values come from the config's review_sheet block).
--only re-runs just those indices and rebuilds the tables from every NN/try.json present.
Exit codes: 0 done, 1 a try raised an error (recorded as verdict "error"), 2 usage or config error.
"""
import argparse
import csv
import json
import sys
import time
import traceback
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_finish
import normaliser_common as common

TOOL = "rerun_tries"
MESH_NAME, IMAGE_NAME = "mesh.glb", "mesh.input.png"
FIXED_COLUMNS = ["n", "run", "attempt", "try", "kind", "v1_passed", "v2_verdict", "pieces_before", "pieces_after",
                 "faces_before", "faces_after", "seconds", "camera_yaw", "camera_elevation", "reasons"]
CONTACT_KEYS = {"per_page": common.positive_int, "columns": common.positive_int, "scale": common.positive_number}


class UsageError(Exception):
    """The index or mapping is unreadable or inconsistent (the message names the file and key)."""


def _read_json(path, what):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise UsageError(f"{path}: cannot read {what}: {exc}")


def read_index(path):
    """[(n, validation path, v1_passed)] with the run and attempt ids checked against the path layout."""
    raw = _read_json(path, "index")
    entries = []
    for item in raw:
        if not (isinstance(item, list) and len(item) == 3 and type(item[0]) is int and type(item[2]) is bool):
            raise UsageError(f"{path}: every entry must be [n, path, v1_passed], got {item!r}")
        entries.append((item[0], Path(item[1]), item[2]))
    if sorted(n for n, _, _ in entries) != list(range(len(entries))):
        raise UsageError(f"{path}: indices must be 0..{len(entries) - 1} without gaps or repeats")
    return sorted(entries)


def ids_of(validation):
    """(run, attempt, try) from .../<run>/attempts/<attempt>/mesh/<try>/mesh-validation.json."""
    parts = validation.parts
    if len(parts) < 6 or parts[-5] != "attempts" or parts[-3] != "mesh":
        raise UsageError(f"{validation}: not of the form <run>/attempts/<attempt>/mesh/<try>/mesh-validation.json")
    return parts[-6], parts[-4], parts[-2]


def read_mapping(path, count):
    """Validated mapping: {"configs": {kind: path}, "face_budget": int or None, "tries": {n: kind}, "contact": {...}}."""
    raw = _read_json(path, "mapping")
    for key in ("configs", "tries", "contact"):
        if not isinstance(raw.get(key), dict):
            raise UsageError(f"{path}: missing object {key}")
    unknown = set(raw) - {"configs", "face_budget", "tries", "contact"}
    if unknown:
        raise UsageError(f"{path}: unknown key {sorted(unknown)[0]}")
    budget = raw.get("face_budget")
    if budget is not None:
        try:
            common.positive_int(budget)
        except ValueError as exc:
            raise UsageError(f"{path}: face_budget {exc}")
    tries = {}
    for n in range(count):
        kind = raw["tries"].get(str(n))
        if kind not in raw["configs"]:
            raise UsageError(f"{path}: tries.{n} must be one of {sorted(raw['configs'])}, got {kind!r}")
        tries[n] = kind
    contact = raw["contact"]
    if set(contact) != set(CONTACT_KEYS):
        raise UsageError(f"{path}: contact must hold exactly {', '.join(CONTACT_KEYS)}")
    for key, check in CONTACT_KEYS.items():
        try:
            check(contact[key])
        except ValueError as exc:
            raise UsageError(f"{path}: contact.{key} {exc}")
    return {"configs": raw["configs"], "face_budget": budget, "tries": tries, "contact": contact}


def prepare_configs(mapping, out_dir):
    """Write the configs actually used into OUT_DIR/configs (face_budget replaced when the mapping says) and load them."""
    loaded = {}
    for kind, source in mapping["configs"].items():
        raw = _read_json(source, "config")
        if mapping["face_budget"] is not None:
            raw["contract"]["face_budget"] = mapping["face_budget"]
        target = out_dir / "configs" / f"finish.{kind}.json"
        common.write_report(target, raw)
        loaded[kind] = mesh_finish.load(target)
    return loaded


def run_try(n, validation, v1_passed, kind, loaded, out_dir):
    """Run one try through the chain; returns its row (also saved as NN/try.json)."""
    steps, sha = loaded[kind]
    run, attempt, name = ids_of(validation)
    folder = out_dir / f"{n:02d}"
    v1 = _read_json(validation, "v1 report")
    row = {"n": n, "run": run, "attempt": attempt, "try": name, "kind": kind, "v1_passed": v1_passed,
           "v1_reasons": v1.get("reasons", []), "config_sha256": sha}
    start = time.monotonic()
    try:
        mesh, image = validation.parent / MESH_NAME, validation.parent / IMAGE_NAME
        common.require_file(mesh, TOOL, "saved mesh")
        common.require_file(image, TOOL, "saved image")
        result = mesh_finish.finish(mesh, image, folder, steps, sha)
        common.write_report(folder / "finish.json", result)
        report = json.loads((folder / "gate" / "mesh-validation.json").read_text()) if result["outputs"].get("gate_report") else None
        row.update({"v2_verdict": result["verdict"], "reasons": result["reasons"], "before": result["before"],
                    "after": result["after"], "measures": report and report["measures"],
                    "camera": report and report["camera"], "error": None})
    except Exception:  # one bad try must not stop the other 63; it is recorded, and the exit code says so
        row.update({"v2_verdict": "error", "reasons": [], "before": None, "after": None, "measures": None,
                    "camera": None, "error": traceback.format_exc()})
    row["seconds"] = round(time.monotonic() - start, 2)
    common.write_report(folder / "try.json", row)
    return row


def flat(row):
    """One CSV line: the fixed columns, then each measure's value and margin."""
    out = {"n": row["n"], "run": row["run"], "attempt": row["attempt"], "try": row["try"], "kind": row["kind"],
           "v1_passed": row["v1_passed"], "v2_verdict": row["v2_verdict"], "seconds": row["seconds"],
           "pieces_before": row["before"] and row["before"]["pieces"], "pieces_after": row["after"] and row["after"]["pieces"],
           "faces_before": row["before"] and row["before"]["faces"], "faces_after": row["after"] and row["after"]["faces"],
           "camera_yaw": row["camera"] and row["camera"]["yaw"], "camera_elevation": row["camera"] and row["camera"]["elevation"],
           "reasons": " | ".join(row["reasons"] or ([row["error"].strip().splitlines()[-1]] if row["error"] else []))}
    for name, m in (row["measures"] or {}).items():
        out[name] = m["value"]
        out[f"{name}_margin"] = m["margin"]
    return out


def write_tables(rows, out_dir):
    common.write_report(out_dir / "results.json", rows)
    lines = [flat(r) for r in rows]
    measures = sorted({k for line in lines for k in line if k not in FIXED_COLUMNS})
    with open(out_dir / "results.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIXED_COLUMNS + measures)
        writer.writeheader()
        writer.writerows(lines)


def write_contact_sheets(rows, mapping, out_dir, style):
    """Pages of per_page review sheets, laid out in columns, each captioned with index, kind, v1 and v2 verdicts."""
    contact = mapping["contact"]
    font = ImageFont.load_default(size=style["font_size"])
    text, pad, gap = tuple(style["text"]), style["padding"], style["gap"]
    paths = []
    for page, start in enumerate(range(0, len(rows), contact["per_page"])):
        cells = []
        for row in rows[start:start + contact["per_page"]]:
            sheet_path = out_dir / f"{row['n']:02d}" / "gate" / "review-sheet.png"
            caption = (f"{row['n']:02d}  {row['kind']}  v1 {'pass' if row['v1_passed'] else 'fail'}  v2 {row['v2_verdict']}")
            colour = tuple(style["verdict_colours"].get(row["v2_verdict"], style["text"]))
            if sheet_path.is_file():
                image = Image.open(sheet_path).convert("RGB")
                image = image.resize((round(image.width * contact["scale"]), round(image.height * contact["scale"])), Image.LANCZOS)
            else:
                image = Image.new("RGB", (round(1000 * contact["scale"]), style["line_height"]), tuple(style["sheet_background"]))
            cells.append((caption, colour, image))
        cell_w, cell_h = max(c[2].width for c in cells), max(c[2].height for c in cells) + style["line_height"]
        columns = min(contact["columns"], len(cells))
        lines = -(-len(cells) // columns)
        page_image = Image.new("RGB", (2 * pad + columns * cell_w + (columns - 1) * gap, 2 * pad + lines * cell_h + (lines - 1) * gap),
                               tuple(style["sheet_background"]))
        draw = ImageDraw.Draw(page_image)
        for i, (caption, colour, image) in enumerate(cells):
            x, y = pad + (i % columns) * (cell_w + gap), pad + (i // columns) * (cell_h + gap)
            draw.text((x, y), caption, fill=colour, font=font)
            page_image.paste(image, (x, y + style["line_height"]))
        path = out_dir / f"contact_{page:02d}.png"
        page_image.save(path)
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("index", type=Path)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--only", help="comma-separated indices to (re)run; the tables cover every NN/try.json present")
    args = parser.parse_args()
    try:
        entries = read_index(args.index)
        mapping = read_mapping(args.mapping, len(entries))
        loaded = prepare_configs(mapping, args.out_dir)
        only = {int(v) for v in args.only.split(",")} if args.only else {n for n, _, _ in entries}
    except (UsageError, mesh_finish.ConfigError, ValueError, KeyError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return common.EXIT_BAD_INPUT
    for n, validation, v1_passed in entries:
        if n in only:
            row = run_try(n, validation, v1_passed, mapping["tries"][n], loaded, args.out_dir)
            print(f"{n:02d} {row['kind']:5} v1={'pass' if v1_passed else 'fail'} v2={row['v2_verdict']:6} {row['seconds']}s", flush=True)
    rows = [json.loads((args.out_dir / f"{n:02d}" / "try.json").read_text())
            for n, _, _ in entries if (args.out_dir / f"{n:02d}" / "try.json").is_file()]
    write_tables(rows, args.out_dir)
    style = next(iter(loaded.values()))[0]["review_sheet"]
    for path in write_contact_sheets(rows, mapping, args.out_dir, style):
        print(path)
    return 1 if any(r["v2_verdict"] == "error" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
