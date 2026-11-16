"""A job that runs one of the repository's own pipelines (authoring/offered.json) with `pipeline/pipeline_run.py`.

The job holds a prompt, adapter ids and choices (authoring/run_request.py); nothing else reaches the runner. This module
(1) writes the subject file from the prompt, (2) writes a copy of the pipeline file whose model stages name the adapters
the request chose (an id in a stage's `model`, the only way a pipeline file names an adapter) and (3) runs
`pipeline_run.py` once for the whole job with `--candidates n`, which runs the seeds `seed`, `seed + 1`, and so on in one
process under one GPU lock. The command line is fixed here: the only values in it are file paths this module made or looked
up in the offer or in a run folder (the picture a record already has chosen, which starts the run at the stage the pipeline
file names), and whole numbers.

Layout under the run folder (`runs_root/<job id>/`, so the run view, trace and statistics find the attempts):
    pipeline_inputs/        subject.json and the pipeline copy
    attempts/<id>/          pipeline_run's attempts, one per candidate: attempt.json and a folder per stage
    final/seed-<n>/         the finished file of the candidate made with that seed, when its attempt generated one
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from authoring.job_store import JobStore
from authoring.machine_config import MachineConfig
from authoring.offered import PIPELINE_DIR, Offer, adapter_kind, offers
from authoring.steps import StepInfo, StepStatus, attempt_is_current
from export import provenance

RUNNER = PIPELINE_DIR / "pipeline_run.py"
INPUTS_DIR = "pipeline_inputs"
LOG_LINES = 30
KEEPS_FILES = ("generated", "review")  # attempt statuses that leave files to choose from
IMAGE_SUFFIXES = (".png",)


def prepare(run_root: Path, job_id: str, recipe: dict[str, Any], offer: Offer) -> tuple[Path, Path]:
    """Write this run's subject file and pipeline copy; return their paths."""
    raw = json.loads(offer.file.read_text())
    adapters = recipe.get("adapters", {})
    for stage in raw["stages"]:
        kind = adapter_kind(stage["tool"])
        if kind and adapters.get(kind):
            stage["model"] = adapters[kind]
    folder = run_root / INPUTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    subject = folder / "subject.json"
    body = {"id": job_id, "kind": offer.pipeline.kind, "text": recipe["prompt"]}
    if "hair_colour" in recipe["choices"]:
        body["hair_colour"] = recipe["choices"]["hair_colour"]
    subject.write_text(json.dumps(body, indent=2) + "\n")
    pipeline = folder / f"{offer.id}.pipeline.json"
    pipeline.write_text(json.dumps(raw, indent=2) + "\n")
    return subject, pipeline


def command(
    offer: Offer,
    run_root: Path,
    subject: Path,
    pipeline: Path,
    choices: dict[str, Any],
    start_image: Path | None = None,
) -> list[str]:
    """The one command line a pipeline job runs, for all its candidates. Its style and motif are looked up in the offer by ids that
    passed the pipeline's declaration; nothing else from a request is in it."""
    argv = [
        sys.executable,
        "-I",
        str(RUNNER),
        "--pipeline", str(pipeline),
        "--subject", str(subject),
        "--motif", str(offer.motif(choices["motif"])),
        "--style", str(offer.style(choices["style"])),
        "--contract", str(offer.contract),
        "--seed", str(choices["seed"]),
        "--candidates", str(choices["candidates"]),
        "--out-root", str(run_root),
        "--final-dir", str(run_root / "final"),
    ]  # fmt: skip
    if offer.sheet:
        argv += ["--review-sheet", str(offer.sheet)]
    if (
        start_image is not None
    ):  # the chosen picture stands in for the stage the pipeline file says it replaces
        spec = offer.pipeline.choices["start_image"]
        argv += ["--start-at", spec["start_at"], "--input", f"{spec['supplies']}={start_image}"]
    return argv


def _stream(store: JobStore, run_id: str, argv: list[str], lines: list[str]) -> int:
    process = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(PIPELINE_DIR)
    )
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line.rstrip())
        store.update_run(run_id, log_tail="\n".join(lines[-LOG_LINES:]))
    return process.wait()


def _attempts(run_root: Path) -> set[Path]:
    return {p.parent for p in (run_root / "attempts").glob("*/attempt.json")}


def _candidate_files(run_root: Path, record: dict[str, Any], attempt: Path) -> list[Path]:
    """What a person can choose from one attempt: the first concept picture (unless the final file is a picture too) and
    the final file, when they exist."""
    final = (record.get("final") or {}).get("path")
    files = [run_root / final] if final else []
    if not (final and final.endswith(IMAGE_SUFFIXES)):
        for entry in record.get("stages", {}).values():
            if entry.get("tool") == "concept":
                files.insert(0, attempt / entry["folder"] / "image.png")
                break
    return [f for f in files if f.is_file()]


def run_pipeline_job(
    store: JobStore, job: dict[str, Any], run_id: str, job_id: str, config: MachineConfig
) -> None:
    """Run the pipeline the job names, once per candidate; each concept picture and finished file becomes a candidate."""
    recipe = job["recipe"]
    offer = offers()[job["pipeline"]]
    choices = recipe["choices"]
    run_root = config.runs_root / job_id
    run_root.mkdir(parents=True, exist_ok=True)
    subject, pipeline = prepare(run_root, job_id, recipe, offer)
    lines: list[str] = []
    first = None
    made = 0
    before = _attempts(run_root)
    start = recipe.get("start_image")
    image = (
        provenance.candidate_file(config.runs_root, start["run_id"], start["candidate"])
        if start
        else None
    )
    code = _stream(
        store, run_id, command(offer, run_root, subject, pipeline, choices, image), lines
    )
    new = sorted(_attempts(run_root) - before)
    if not new:
        first_seed, count = choices["seed"], choices["candidates"]
        which = (
            f"seed {first_seed}"
            if count == 1
            else f"seeds {first_seed} to {first_seed + count - 1}"
        )
        lines.append(f"{which}: the runner exited with {code} and made no attempt")
    for attempt in new:
        record = json.loads((attempt / "attempt.json").read_text())
        files = (
            _candidate_files(run_root, record, attempt) if record["status"] in KEEPS_FILES else []
        )
        lines.append(f"seed {record['seed']}: {record['status']}, {len(files)} file(s)")
        for path in files:
            candidate = store.add_candidate(
                job_id, str(path), f"run {run_id} seed {record['seed']}"
            )
            first = first or candidate["id"]
            made += 1
    tail = "\n".join(lines[-LOG_LINES:])
    if not made:
        store.update_run(run_id, status="failed", log_tail=tail or "the attempt made no file")
        return
    store.update_run(run_id, status="succeeded", candidate_id=first, log_tail=tail)


def describe_pipeline_steps(
    job: dict[str, Any], run: dict[str, Any] | None, config: MachineConfig
) -> list[StepInfo]:
    """The job's stages from its pipeline copy; a stage is done when the newest current attempt has its stage.json,
    and failed when its gate did not pass."""
    copy = config.runs_root / job["id"] / INPUTS_DIR / f"{job['pipeline']}.pipeline.json"
    if not copy.is_file():
        return []
    attempts = config.runs_root / job["id"] / "attempts"
    found = sorted(p for p in attempts.iterdir() if p.is_dir()) if attempts.is_dir() else []
    attempt = found[-1] if found else None
    if attempt and run and not attempt_is_current(attempt, run["created_at"]):
        attempt = None
    steps: list[StepInfo] = []
    blocked = False
    for stage in json.loads(copy.read_text())["stages"]:
        status: StepStatus
        record = attempt / stage["id"] / "stage.json" if attempt else None
        if record is not None and record.is_file():
            gate = json.loads(record.read_text()).get("gate")
            status = "failed" if gate and gate["verdict"] != "pass" else "succeeded"
        elif run is None or blocked:
            status = "pending"
        elif run["status"] == "running":
            status, blocked = "running", True
        elif run["status"] == "failed":
            status, blocked = "failed", True
        elif run["status"] == "succeeded":
            status = "skipped"
        else:
            status, blocked = "pending", True
        steps.append(
            {
                "id": stage["id"],
                "label": stage["label"],
                "file": f"pipeline/pipeline_run.py (tool: {stage['tool']})",
                "status": status,
            }
        )
    return steps
