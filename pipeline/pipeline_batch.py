"""Run one pipeline file for N seeds of one subject, one after another, and make one contact sheet (plain Python).

    python3 -I pipeline/pipeline_batch.py --pipeline P --subject S --motif M --style STYLE --contract C --seeds 5,6,7,8 \\
        --review-sheet FILE --out-root DIR [--lint] [--gpu-wait SECONDS] [--dry-run]

Each seed is a full `pipeline_run.run_job` in this process, in the order given. The batch is ONE job for the GPU lock:
it opens one GpuSession (pipeline/gpu_session.py) at the top, so the first model stage that runs takes the machine
lock and it is held until the last seed ends, and nothing below takes it again. A seed that fails, asks for review
or crashes does not stop the others; its row says so. Stages a seed shares with an earlier attempt under --out-root
are reused as for any run.

Output under --out-root: attempts/ (pipeline_run's, one per seed) and batches/<utc>-<id>/ holding batch.json (one
row per seed: attempt, status, verdict, reasons, review sheet, final file, seconds, error), contact-sheet.png (the
seeds' review sheets stacked, each labelled with its seed and verdict; pipeline/batch_sheet.py draws it under the
tools interpreter) and seed-<n>/ (each generated seed's final file and sidecar). The exit code is 0 when every seed
ran to a verdict, 1 when any seed crashed or the batch was refused. Prints `PIPELINE_BATCH seeds=<n> generated=<n> review=<n> failed=<n> error=<n>`.
"""
import argparse
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_session
import machine
import pipeline_file as pf
import pipeline_resolve as pr
import pipeline_run as run

TOOLS_DIR = Path(__file__).resolve().parent
SHEET_NAME = "contact-sheet.png"
BATCH_VERSION = 1


def parse_seeds(text):
    """The seeds of "5,6,7" as ints: a non-empty list of distinct whole numbers."""
    try:
        seeds = [int(part) for part in text.split(",")]
    except ValueError:
        raise run.RunError(f"--seeds {text!r}: expected whole numbers separated by commas")
    if len(set(seeds)) != len(seeds):
        raise run.RunError(f"--seeds {text!r}: a seed is listed twice")
    return seeds


def make_sheet(batch_file, out, out_root, review_sheet_file):
    """Draw the contact sheet with batch_sheet.py under the interpreter that has Pillow."""
    try:
        python = machine.tools_python()
    except machine.MachineError as exc:
        raise run.RunError(f"the contact sheet needs the tools interpreter (it has Pillow): {exc}") from exc
    result = subprocess.run([str(python), "-I", str(TOOLS_DIR / "batch_sheet.py"), str(batch_file), str(out),
                             "--root", str(out_root), "--config", str(review_sheet_file)], capture_output=True, text=True)
    if result.returncode != 0:
        raise run.RunError("the contact sheet failed: " + (result.stderr.strip() or result.stdout.strip()))


def row_of(record):
    """The batch row for a finished attempt."""
    verdict = record.get("verdict")
    final = record.get("final", {}).get("path")
    return {"seed": record["seed"], "attempt": record["attempt"], "status": record["status"],
            "verdict": verdict["verdict"] if verdict else None, "reasons": verdict["reasons"] if verdict else [],
            "review_sheet": verdict["review_sheet"] if verdict else None, "final": final,
            "seconds": record.get("wall_seconds"), "error": None}


def run_batch(pipeline, subject, motif, style, contract, seeds, out_root, review_sheet, review_sheet_file, session, log=print,
              sheet_maker=make_sheet, lint=False, runners=None):
    """Run every seed and return (batch dict, batch folder). SESSION is the batch's GpuSession (the one lock owner).
    RUNNERS replaces the real stage runners (tests; principle 2)."""
    if lint:
        found = pr.lint(pipeline, subject, motif, style)
        if found:
            raise pf.PipelineError(found)
    jobs = [pr.resolve(pipeline, subject, motif, style, contract, seed) for seed in seeds]  # every seed is checked before any model time
    versions = None if runners else run.environment_versions(jobs[0])  # real runners: record what software made the attempts
    runners = runners or run.default_runners(jobs[0], review_sheet, session)
    out_root = Path(out_root)
    batch_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    folder = out_root / "batches" / batch_id
    folder.mkdir(parents=True)
    rows, began = [], time.monotonic()
    for job in jobs:
        log(f"seed {job['seed']}: starting")
        try:
            record = run.run_job(job, out_root, runners, f"{batch_id}-{job['seed']}", folder / f"seed-{job['seed']}", log=log,
                              versions=versions)
            rows.append(row_of(record))
        except Exception as exc:  # a crashed seed is a row, not the end of the batch
            rows.append({"seed": job["seed"], "attempt": None, "status": "error", "verdict": None, "reasons": [],
                         "review_sheet": None, "final": None, "seconds": None, "error": f"{type(exc).__name__}: {exc}"})
            log(f"seed {job['seed']}: crashed: {exc}")
    batch = {"batch_version": BATCH_VERSION, "batch": batch_id, "subject": subject.body["id"], "style": style.id,
             "pipeline": {"id": jobs[0]["pipeline"]["id"], "sources": jobs[0]["sources"]}, "seeds": seeds, "rows": rows, "wall_seconds": round(time.monotonic() - began, 2),
             "contact_sheet": None}
    run.write_json(folder / "batch.json", batch)
    sheet_maker(folder / "batch.json", folder / SHEET_NAME, out_root, review_sheet_file)
    batch["contact_sheet"] = f"batches/{batch_id}/{SHEET_NAME}"
    run.write_json(folder / "batch.json", batch)
    return batch, folder


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("pipeline", "subject", "motif", "style", "contract"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--seeds", required=True, help="comma-separated whole numbers, run in this order")
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--review-sheet", type=Path, required=True, help="a JSON file with a `review_sheet` block (the sheets' look)")
    parser.add_argument("--lint", action="store_true")
    parser.add_argument("--gpu-wait", type=int, default=run.GPU_WAIT_S, metavar="SECONDS")
    parser.add_argument("--dry-run", action="store_true", help="print each seed's prompt and stage table; run nothing")
    args = parser.parse_args(argv)
    try:
        seeds = parse_seeds(args.seeds)
        pipeline = pf.load(args.pipeline)
        subject, motif = pr.load_subject(args.subject), pr.load_motif(args.motif)
        style, contract = pr.load_style(args.style), pr.load_contract(args.contract)
        review_sheet = run.load_review_sheet(args.review_sheet)
        if args.dry_run:
            for seed in seeds:
                print(f"seed {seed}\n" + pr.dry_run_text(pr.resolve(pipeline, subject, motif, style, contract, seed)))
            return 0
        with gpu_session.GpuSession(lambda message: print(message, flush=True), args.gpu_wait) as session:
            batch, folder = run_batch(pipeline, subject, motif, style, contract, seeds, args.out_root, review_sheet, args.review_sheet,
                                      session, log=lambda message: print(message, flush=True), lint=args.lint)  # flushed: a caller reading a pipe sees progress
    except (pf.PipelineError, run.RunError) as exc:
        print(exc, file=sys.stderr)
        return 1
    counts = {name: sum(1 for r in batch["rows"] if r["status"] == name) for name in ("generated", "review", "failed", "error")}
    print(f"PIPELINE_BATCH seeds={len(seeds)} " + " ".join(f"{k}={v}" for k, v in counts.items()) + f" sheet={folder / SHEET_NAME}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
