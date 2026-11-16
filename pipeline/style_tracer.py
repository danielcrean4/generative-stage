"""The style tracer: the same subject files and the same pipeline file through several style packs, then a report.

    TOOLS_PYTHON -I pipeline/style_tracer.py --data pipeline/pipelines/examples/tracer \\
        --out ROOT [--only-subject ID] [--only-style ID] [--dry-run]

Runs under the interpreter that has numpy and Pillow (it draws the contact sheets and measures the cut-outs);
the model itself still runs in its own process through pipeline_run. Everything about the run (which pack, which
subject, which seed, spill and sheet settings) is in the tracer file `DATA/tracer.json`; nothing about a look is here.

Writes under ROOT: attempts/ (pipeline_run's), final/<style>/<subject>.png with sidecars, contact.png (tidied
icons), contact_raw.png (the untidied concept images), tracer_report.json. Prints the line
`STYLE_TRACER_RUN images=<n> generated=<n> reused=<n> gpu_seconds=<s>`.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_session
import pipeline_file as pf
import pipeline_resolve as pr
import pipeline_run as run

TRACER_KEYS = ("version", "pipeline", "motif", "contract", "styles", "subjects", "spill", "sheet")


def load_tracer(data):
    raw, _ = pf.read_json(Path(data) / "tracer.json", "tracer")
    missing = [k for k in TRACER_KEYS if k not in raw]
    if missing:
        raise pf.PipelineError([f"{data}/tracer.json: missing keys {missing}"])
    return raw


def spill_share(image, key, edge_px, max_distance):
    """Share of edge pixels (visible pixels within EDGE_PX of a transparent one) whose colour is within MAX_DISTANCE of KEY."""
    from scipy import ndimage
    rgba = np.asarray(image.convert("RGBA")).astype(float)
    visible = rgba[..., 3] > 0
    if not visible.any():
        return 0.0
    inner = ndimage.binary_erosion(visible, iterations=edge_px, border_value=1)
    edge = visible & ~inner
    if not edge.any():
        return 0.0
    distance = np.linalg.norm(rgba[..., :3] - np.array(key, float), axis=-1)
    return round(float((distance[edge] <= max_distance).mean()), 4)


def measure(final_png, report_json, key, spill):
    image = Image.open(final_png)
    alpha = np.asarray(image.convert("RGBA"))[..., 3]
    report = json.loads(Path(report_json).read_text())
    return {"subject_coverage": round(float((alpha > 127).mean()), 4),
            "raw_subject_coverage": report["coverage"],
            "subject_touches_raw_border": report["touched_border"],
            "edge_key_spill_share": spill_share(image, key, spill["edge_px"], spill["max_distance_to_key"])}


def contact_sheet(cells, subjects, styles, sheet, out):
    """cells[(subject, style)] -> image path. Rows are subjects, columns are styles, both labelled."""
    size, label, ground = sheet["cell"], sheet["label_height"], tuple(sheet["background"])
    width, height = size * len(styles) + 160, size * len(subjects) + label
    canvas = Image.new("RGB", (width, height), ground)
    draw = ImageDraw.Draw(canvas)
    for c, style in enumerate(styles):
        draw.text((160 + c * size + 6, 6), style, fill=(255, 255, 255))
    for r, subject in enumerate(subjects):
        draw.text((6, label + r * size + size // 2), subject, fill=(255, 255, 255))
        for c, style in enumerate(styles):
            tile = Image.open(cells[(subject, style)]).convert("RGBA").resize((size, size), Image.LANCZOS)
            canvas.paste(tile, (160 + c * size, label + r * size), tile)
    canvas.save(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only-subject")
    parser.add_argument("--only-style")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    with gpu_session.GpuSession(lambda message: print(message, flush=True), run.GPU_WAIT_S) as session:  # the one owner of the GPU lock
        return trace(args, session)


def trace(args, session):
    tracer = load_tracer(args.data)
    pipeline = pf.load(args.data / tracer["pipeline"])
    motif, contract = pr.load_motif(args.data / tracer["motif"]), pr.load_contract(args.data / tracer["contract"])
    key = pipeline.capture["background"]["color"]
    styles = [s for s in tracer["styles"] if args.only_style in (None, s)]
    subjects = [(pr.load_subject(args.data / e["file"]), e["seed"]) for e in tracer["subjects"] if args.only_subject in (None, pr.load_subject(args.data / e["file"]).body["id"])]
    runners = run.default_runners(None, None, session)
    versions = None  # asked once, at the first job: every job of one pipeline file runs the same tools
    run_id = "tracer-" + uuid.uuid4().hex[:8]
    rows, cells, raw_cells = [], {}, {}
    for subject, seed in subjects:
        for style_id in styles:
            style = pr.load_style(args.data / "styles" / style_id)
            found = pr.lint(pipeline, subject, motif, style)
            if found:
                raise pf.PipelineError(found)
            job = pr.resolve(pipeline, subject, motif, style, contract, seed)
            if args.dry_run:
                print(f"{subject.body['id']} / {style_id}: seed {seed}\n" + pr.dry_run_text(job) + "\n" + "\n".join(run.dry_run_lines(job, args.out, runners)))
                continue
            versions = versions or run.environment_versions(job)
            record = run.run_job(job, args.out, runners, run_id, args.out / "final", versions=versions)
            attempt = args.out / "attempts" / record["attempt"]
            final = args.out / "final" / style_id / f"{subject.body['id']}.png"
            cells[(subject.body["id"], style_id)] = final
            raw_cells[(subject.body["id"], style_id)] = attempt / "concept" / "image.png"
            concept = record["stages"]["concept"]
            rows.append({"subject": subject.body["id"], "style": style_id, "seed": seed, "prompt": job["stages"][0]["prompt"],
                         "negative": job["stages"][0]["reads"]["style.prompt"]["negative"],
                         "attempt": record["attempt"], "concept_reused": concept["reused"],
                         "concept_seconds": concept["timing"].get("seconds", 0.0) if not concept["reused"] else 0.0,
                         "peak_rss_bytes": concept["timing"].get("peak_rss_bytes"),
                         **measure(final, attempt / "tidy_image" / "report.json", key, tracer["spill"])})
    if args.dry_run:
        return 0
    names, order = [s.body["id"] for s, _ in subjects], styles
    contact_sheet(cells, names, order, tracer["sheet"], args.out / "contact.png")
    contact_sheet(raw_cells, names, order, tracer["sheet"], args.out / "contact_raw.png")
    # round trip: sidecars of one subject differ only where a style swap explains
    checks = []
    for name in names:
        sidecars = [json.loads(cells[(name, s)].with_suffix(".source.json").read_text()) for s in order]
        for other in sidecars[1:]:
            checks.append({"subject": name, "styles": [sidecars[0]["style"]["id"], other["style"]["id"]],
                           "unexpected_differences": run.style_only_violations(sidecars[0], other)})
    generated = sum(1 for r in rows if not r["concept_reused"])
    gpu = round(sum(r["concept_seconds"] for r in rows), 1)
    report = {"run_id": run_id, "images": rows, "sidecar_checks": checks, "generations": generated,
              "reused_concepts": len(rows) - generated, "gpu_seconds": gpu,
              "seconds_per_generated_image": round(gpu / generated, 1) if generated else None}
    run.write_json(args.out / "tracer_report.json", report)
    print(f"STYLE_TRACER_RUN images={len(rows)} generated={generated} reused={len(rows) - generated} gpu_seconds={gpu}")
    return 1 if any(c["unexpected_differences"] for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
