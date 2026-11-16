"""Run a resolved job's stages: image tools, and the prop mesh chain (plain Python, one job: run and record).

    python3 -I pipeline/pipeline_run.py (--job RESOLVED.json | --pipeline P --subject S --motif M --style STYLE \\
        --contract C --seed N) --out-root DIR [--final-dir DIR] [--run-id TEXT] [--review-sheet FILE] [--lint] [--dry-run] [--candidates N]

Runs `concept` (an image adapter), `normalize_image`, `crop_image`, `matte` (gated), `mesh` (an image-to-mesh
adapter), `colour_head`, and the chain `normalize_mesh`, `decimate_mesh`, `mesh_gates` (gate v2 and its review sheet), and, when a pipeline names it, `texture` (the optional material stage),
`rig` (a rig adapter), `rig_gate` (gated: weights and bones in the mesh) and `motion` (a motion adapter), each as
one stage in the pipeline file's order, each given only the inputs and reads it declares. A model stage runs the adapter entry its
`model` names, or the machine config's default adapter of its kind (adapter_config.py, docs/adapters.md): the entry
is the only source of the command; the stage supplies only placeholder values. The three chain stages run
through `pipeline/mesh_finish.py step ...` under the tools interpreter (machine.tools_python), so mesh_finish stays the one owner of the
chain's config and functions. A pipeline that names a tool without a runner is refused before anything runs.
The GPU lock has one owner per job: main() opens one GpuSession (pipeline/gpu_session.py) and the two model runners only
call hold() on it, so a batch (pipeline/pipeline_batch.py) holds it across its seeds, and so does --candidates N: it runs the
seeds SEED to SEED + N - 1 one after another in this process (a seed that is refused is reported and the next still runs), each
seed's final file under <final-dir>/seed-<n>, and the exit code is the worst of them (1, else 3, else 0). --start-at STAGE with --input
STAGE/FILE=PATH starts from saved outputs of the earlier stages (docs/head_pipeline.md); such a run never takes the lock.
--review-sheet is a JSON file with a `review_sheet` block (the look of the sheet; the finish.*.json examples have
one): required when the pipeline has a `mesh_gates` stage.

A gate stage ends in `pass`, `review` or `fail` (docs/gate_v2.md; the matte gate is pass or fail). On `fail`, or on
any verdict listed in the gate's `retry.on`, a stage with a `retry` block restarts at `retry.restart_at` with the seed
moved by `retry.seed_step`, up to `retry.max` times; stages before `restart_at` are reused as they are. Any other
non-pass verdict ends the attempt: `failed` (every try's verdict and review sheet are kept) or `review` (a person
looks; nothing is installed). The exit code is 0 for generated, 3 for review, 1 for failed or refused.

Output layout under --out-root:

    attempts/<utc>-<id>/attempt.json            the resolved job, source hashes, seed, models, tries, per-stage keys, timing, verdicts
    attempts/<utc>-<id>/<stage id>/<outputs>    what the stage wrote, with a stage.json beside it (a retried stage: <stage id>.try<k>)
    <final-dir>/<style id>/<asset id>.<ext>     the final file (the last image, or the mesh the last gate passed), with
                                                <asset id>.source.json beside it; written only for a generated attempt

Reuse. A stage's full key is the sha256 of {key_inputs from the resolved job, seed (stages that use one), the
tool's version (hash of its source files, listed per tool in pipeline_file.TOOLS), the model identity
(adapter_config.identity: the adapter id, its command template, its program files and weights), the sha256 of each
input file}. The identity an adapter reports while it runs (identity.json) is recorded as `model_reported`. Before running a stage, every earlier attempt under the same --out-root is searched for a stage.json
with the same stage id and full key whose recorded outputs still exist with the same hashes. If one is found its files
are copied into the new attempt (stage.json says `reused_from`) and nothing runs. `--dry-run` prints what would run
and what would be reused and starts nothing.

Nothing about a look is in this file: prompts, key colours, sizes and words all arrive in the resolved job.
The injectable seam is the `runners` argument (principle 2): tests pass stand-in runners, so no model is needed.
"""
import argparse
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapter_config
import adapter_run
import gpu_session
import host
import local_run
import machine
import pipeline_file as pf
import pipeline_resolve as pr
import provenance

TOOLS_DIR = Path(__file__).resolve().parent
SIDECAR_VERSION = 1
BOOKKEEPING = ("stage.json", "step.log", adapter_run.REPORTED)  # files in a stage folder that are not outputs
UNDER_ALPHA = [0, 0, 0]  # the colour stored under alpha 0 (invisible; normalize_image requires one)
GPU_WAIT_S = 3600  # how long the job waits for the machine GPU lock (another job's model may hold it)
STAGE_TIMEOUT_S = 1800
PACKAGE_PROBE = """
import importlib.metadata as metadata, json, sys
found = {}
for name in sys.argv[1:]:
    try:
        found[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        pass
print(json.dumps({"python": sys.version.split()[0], "packages": found}))
"""  # run as `python -I -c`: the Python version and the versions of the named packages that are installed
PROBED_PACKAGES = ("torch", "diffusers", "transformers", "Pillow", "numpy", "scipy", "trimesh", "fast-simplification")
# Optional timing lines an adapter may print (docs/adapters.md, "Timing"): the last progress-bar line, such as
# "4/4 [00:14<00:00", or one line "load Xs, generate Ys".
SAMPLING_TIME = re.compile(r"\d+/\d+ \[(\d+):(\d+)<")
MESH_TIMES = re.compile(r"load ([\d.]+)s, generate ([\d.]+)s")
ADAPTER_KIND = {"concept": "image", "mesh": "image-to-mesh", "texture": "material", "rig": "rig",
                "motion": "motion"}  # pipeline_file.TOOLS[...].kind
SEED_LIMIT = 2**32
STEP_OF_TOOL = {"normalize_mesh": "clean_mesh", "decimate_mesh": "decimate", "mesh_gates": "shape_gate"}  # mesh_finish.STEP_NAMES
MATTE_MEASURES = ("subject_share", "largest_component_share", "component_count", "border_contact")  # matte.json keys a verdict shows
SHEET_FILE = "review-sheet.png"
EXIT_FOR_STATUS = {"generated": 0, "failed": 1, "review": 3}  # the gate's own exit codes


class RunError(RuntimeError):
    """A loud, readable failure of the runner (refused pipeline, missing output, missing model)."""


class StageFailed(RunError):
    """A stage could not finish its work on this input (an empty mesh, say): a `fail` try, not a crashed runner."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_files(paths):
    """One hash over the given source files (the tool version); [] hashes to a fixed value."""
    digest = hashlib.sha256()
    for path in sorted(map(str, paths)):
        digest.update(path.rsplit("/", 1)[-1].encode() + b"\0" + Path(path).read_bytes() + b"\0")
    return digest.hexdigest()


def folder_hashes(folder):
    return {str(p.relative_to(folder)): sha256_file(p)
            for p in sorted(Path(folder).rglob("*")) if p.is_file() and p.name not in BOOKKEEPING}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:6]}")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class StageRunner:
    """How one tool runs. `run(stage, inputs, folder, seed)` writes the stage's outputs into `folder` and returns a
    timing dict (`seconds`, optionally `load_seconds`, `generate_seconds`, `peak_rss_bytes`); `identity(stage)` is the
    model identity (plus any non-file input the stage's work depends on) that joins the key ({} for a tool with none);
    `tool_files` are the sources whose hash is the tool's version; `seeded` says whether the seed is part of the key.
    A run may raise StageFailed when the input cannot be worked on."""
    run: Callable
    identity: Callable
    tool_files: tuple
    seeded: bool


def peak_children_rss():
    """The largest resident size of any child process of this run so far (bytes). A high-water mark over every child
    since the process started, so it is recorded only for the neural stages, whose runs it describes."""
    return host.rss_bytes(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)


def registry_files(tool):
    """The source files of a registered tool (pipeline_file.TOOLS is their one owner), as absolute paths."""
    return tuple(dict.fromkeys((TOOLS_DIR / name).resolve() for name in pf.TOOLS[tool].sources))


def finish_config(job, review_sheet):
    """The one config mesh_finish validates, built from the resolved job's chain stages (docs/gate_v2.md "Finishing
    chain"). Each step uses only its own part; the file is validated whole so the pieces cannot disagree."""
    by_tool = {}
    for stage in job["stages"]:
        if stage["tool"] in STEP_OF_TOOL:
            by_tool.setdefault(stage["tool"], stage)
    missing = [tool for tool in STEP_OF_TOOL if tool not in by_tool]
    if missing:
        raise RunError("the mesh chain needs these tools in the pipeline, in order: " + ", ".join(STEP_OF_TOOL) + "; missing " + ", ".join(missing))
    clean, decimate, gate = by_tool["normalize_mesh"], by_tool["decimate_mesh"], by_tool["mesh_gates"]
    if review_sheet is None:
        raise RunError("this pipeline has a mesh_gates stage, which writes a review sheet: give --review-sheet FILE (a JSON file with a `review_sheet` block)")
    return {"contract": gate["reads"]["contract"], "clean_mesh": clean["params"], "decimate": decimate["params"],
            "capture": {"background": gate["reads"]["capture.background"], "view": {"camera": gate["reads"]["capture.view"]["camera"]}},
            "gate": gate["gate"], "review_sheet": review_sheet}


def load_review_sheet(path):
    """The `review_sheet` block of the JSON file at PATH (a finish config or a file holding just that key)."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise RunError(f"{path}: cannot read the review sheet config: {exc}") from exc
    if not isinstance(raw, dict) or "review_sheet" not in raw:
        raise RunError(f"{path}: missing key review_sheet")
    return raw["review_sheet"]


def adapter_values(stage, inputs, folder, seed):
    """The placeholder values a model stage gives its adapter: the stage's prompt and size, its input files (image,
    mesh, rig), the output path and folder, the seed, and its params as params.<name>. Nothing else of the job reaches
    a command."""
    kind = ADAPTER_KIND[stage["tool"]]
    values = {"seed": seed, "out_dir": folder, **{f"params.{k}": v for k, v in stage["params"].items()}}
    if kind in adapter_config.OUTPUT:
        values["output"] = folder / adapter_config.OUTPUT[kind]
    for name in ("image", "mesh", "rig"):
        if name in inputs:
            values[name] = inputs[name]
    if kind == "image":
        values.update(prompt=stage["prompt"], negative=stage["reads"]["style.prompt"]["negative"],
                      width=stage["params"]["width"], height=stage["params"]["height"])
    return {name: value for name, value in values.items() if name in adapter_config.DATA[kind]
            or adapter_config.PARAM.fullmatch(name)}


def default_runners(job=None, review_sheet=None, gpu=None, adapters=None):
    """The real runners: each model stage through its adapter entry (adapter_config.py), the numpy tools under the
    tools interpreter, and (with JOB, which supplies the chain's config) the mesh chain through mesh_finish.py.
    Adapters and interpreters come from the machine config (machine.py) when a stage first needs one, so a stage that
    never runs asks for nothing. ADAPTERS (an adapter_config.Adapters) replaces the machine config's, for tests.

    GPU is the job's GpuSession (pipeline/gpu_session.py), the one owner of the GPU lock: an adapter whose entry says
    `gpu` only calls `gpu.hold()`, it never takes the lock itself. Without one such an adapter refuses to run."""
    found = {}

    def adapter_of(stage):
        try:
            if "all" not in found:
                found["all"] = adapters or adapter_config.from_machine()
            return found["all"].pick(stage.get("model"), ADAPTER_KIND[stage["tool"]])
        except adapter_config.AdapterError as exc:
            raise RunError(f"stage '{stage['id']}': {exc}") from exc

    def python_for(what):
        try:
            return machine.tools_python()
        except machine.MachineError as exc:
            raise RunError(f"{what} needs the tools interpreter: {exc}") from exc

    def model_identity(stage):
        entry = adapter_of(stage)
        try:
            return adapter_config.identity(entry)
        except adapter_config.AdapterError as exc:
            raise RunError(f"stage '{stage['id']}': {exc}") from exc

    def run_model(stage, inputs, folder, seed):
        entry = adapter_of(stage)
        try:
            seconds = adapter_run.run(entry, adapter_values(stage, inputs, folder, seed), folder, gpu)
        except (adapter_run.Refused, adapter_run.Failed) as exc:
            raise RunError(f"stage '{stage['id']}': {exc}") from exc
        timing = {"seconds": seconds, "peak_rss_bytes": peak_children_rss()}
        printed = (folder / "step.log").read_text(errors="replace")
        sampling, mesh_times = SAMPLING_TIME.findall(printed), MESH_TIMES.findall(printed)
        if sampling:  # a progress bar says how long the steps took; the rest of the run is loading
            minutes, secs = map(int, sampling[-1])
            timing.update(generate_seconds=minutes * 60 + secs, load_seconds=round(seconds - (minutes * 60 + secs), 2))
        elif mesh_times:  # the adapter printed "load Xs, generate Ys"
            timing.update(load_seconds=float(mesh_times[-1][0]), generate_seconds=float(mesh_times[-1][1]))
        return timing

    def run_tidy(stage, inputs, folder, seed):
        python = python_for("normalize_image")
        config = {"background": stage["reads"]["capture.background"], "background_color": UNDER_ALPHA,
                  **{key: stage["params"][key] for key in ("canvas_size", "margin", "output_mode")}}
        write_json(folder / "config.json", config)
        started = time.monotonic()
        local_run.execute([python, "-I", TOOLS_DIR / "normalize_image.py", inputs["image"], folder / "image.png",
                           "--config", folder / "config.json", "--report", folder / "report.json"],
                          folder / "step.log", STAGE_TIMEOUT_S)
        return {"seconds": round(time.monotonic() - started, 2)}

    def run_crop(stage, inputs, folder, seed):
        python = python_for("crop_image")
        write_json(folder / "config.json", {"background": stage["reads"]["capture.background"], "keep_share": stage["params"]["keep_share"]})
        started = time.monotonic()
        local_run.execute([python, "-I", TOOLS_DIR / "crop_image.py", inputs["image"], folder / "image.png",
                           "--config", folder / "config.json", "--report", folder / "report.json"], folder / "step.log", STAGE_TIMEOUT_S)
        return {"seconds": round(time.monotonic() - started, 2)}

    def run_colour(stage, inputs, folder, seed):
        python = python_for("colour_head")
        config = {"background": stage["reads"]["capture.background"], "hair_colour": stage["reads"]["subject"].get("hair_colour"),
                  **stage["params"]}
        write_json(folder / "config.json", config)
        started = time.monotonic()
        local_run.execute([python, "-I", TOOLS_DIR / "colour_head.py", inputs["mesh"], inputs["image"], folder / "mesh.glb",
                           "--config", folder / "config.json", "--report", folder / "report.json"], folder / "step.log", STAGE_TIMEOUT_S)
        return {"seconds": round(time.monotonic() - started, 2)}

    def run_matte(stage, inputs, folder, seed):
        python = python_for("matte")
        gate = stage["gate"]
        write_json(folder / "background.json", stage["reads"]["capture.background"])
        command = [python, "-I", TOOLS_DIR / "matte.py", inputs["image"], "--out", folder, "--method", "border-flood",
                   "--background", folder / "background.json", "--min-largest-share", gate["min_largest_share"],
                   "--min-coverage", gate["min_coverage"], "--max-coverage", gate["max_coverage"]]
        started = time.monotonic()
        try:
            local_run.execute(command + (["--allow-border"] if gate["allow_border"] else []), folder / "step.log", STAGE_TIMEOUT_S)
        except RuntimeError:  # a failed check exits 1 after writing matte.json: that is a verdict, not a crash
            if not (folder / "matte.json").is_file():
                raise
        return {"seconds": round(time.monotonic() - started, 2)}

    def run_rig_gate(stage, inputs, folder, seed):
        write_json(folder / "gate.json", stage["gate"])
        started = time.monotonic()
        try:
            local_run.execute([sys.executable, "-I", TOOLS_DIR / "rig_gate.py", inputs["mesh"], "--gate", folder / "gate.json",
                               "--out", folder], folder / "step.log", STAGE_TIMEOUT_S)
        except RuntimeError:  # a failed gate exits 1 after writing its report: that is a verdict, not a crash
            if not (folder / "rig-validation.json").is_file():
                raise
        return {"seconds": round(time.monotonic() - started, 2)}

    def chain_identity(stage):
        """The non-file inputs of a chain stage that its declared key_inputs do not hold: the gate looks through the
        frame of the clean_mesh stage, and the sheet's look is a file given on the command line."""
        if stage["tool"] != "mesh_gates":
            return {}
        return {"frame_sha256": pr.canonical_sha256(finish_config(job, review_sheet)["clean_mesh"]["orientation"]),
                "review_sheet_sha256": pr.canonical_sha256(review_sheet)}

    def run_chain(stage, inputs, folder, seed):
        python = python_for(stage["tool"])
        config = folder.parent / "finish-config.json"  # one per attempt, shared by the chain's stages
        if not config.is_file():
            write_json(config, finish_config(job, review_sheet))
        command = [python, "-I", TOOLS_DIR / "mesh_finish.py", "step", STEP_OF_TOOL[stage["tool"]], inputs["mesh"], folder,
                   "--config", config] + (["--image", inputs["image"]] if "image" in inputs else [])
        started = time.monotonic()
        try:
            local_run.execute(command, folder / "step.log", STAGE_TIMEOUT_S)
        except RuntimeError:
            if (folder / "step-failed.json").is_file():
                raise StageFailed(json.loads((folder / "step-failed.json").read_text())["reasons"])
            if not (folder / "mesh-validation.json").is_file():  # the gate's fail and review exits leave a report
                raise
        return {"seconds": round(time.monotonic() - started, 2)}  # no peak: the child high-water mark would be the mesh model's

    runners = {
        "concept": StageRunner(run_model, model_identity, registry_files("concept"), True),
        "normalize_image": StageRunner(run_tidy, lambda stage: {}, registry_files("normalize_image"), False),
        "matte": StageRunner(run_matte, lambda stage: {}, registry_files("matte"), False),
        "crop_image": StageRunner(run_crop, lambda stage: {}, registry_files("crop_image"), False),
        "colour_head": StageRunner(run_colour, lambda stage: {}, registry_files("colour_head"), False),
        "mesh": StageRunner(run_model, model_identity, registry_files("mesh"), True),
        "texture": StageRunner(run_model, model_identity, registry_files("texture"), True),
        "rig": StageRunner(run_model, model_identity, registry_files("rig"), True),
        "rig_gate": StageRunner(run_rig_gate, lambda stage: {}, registry_files("rig_gate"), False),
        "motion": StageRunner(run_model, model_identity, registry_files("motion"), True)}
    if job is not None and any(stage["tool"] in STEP_OF_TOOL for stage in job["stages"]):
        finish_config(job, review_sheet)  # a missing chain stage or sheet config is refused now, before any model time is spent
        for tool in STEP_OF_TOOL:
            runners[tool] = StageRunner(run_chain, chain_identity, registry_files(tool), False)
    return runners


def environment_versions(job, probe=None, adapters=None):
    """What software made this attempt, for attempt.json: this runner's Python; the tools interpreter's Python and
    package versions when a numpy tool runs (key `tools_python`); and for each adapter a model stage uses, keyed by
    its id, the Python beside its program when it has one. PROBE(python, packages) -> dict is the injectable seam
    (tests pass a stand-in); the real probe runs `python -I` once per interpreter. Paths are never recorded, and
    anything not configured or not probeable is recorded as such, never an error: the attempt is still worth keeping."""
    probe = probe or probe_interpreter
    tools = {stage["tool"] for stage in job["stages"]}
    versions = {"python": sys.version.split()[0]}

    def probed(found):
        try:
            return probe(found, PROBED_PACKAGES) if found.is_file() else "not found"
        except (OSError, ValueError, subprocess.SubprocessError):
            return "unavailable"

    if tools & {"normalize_image", "crop_image", "matte", "colour_head", *STEP_OF_TOOL}:
        try:
            versions["tools_python"] = probed(machine.tools_python())
        except machine.MachineError:
            versions["tools_python"] = "not configured"
    for stage in job["stages"]:
        if stage["tool"] not in ADAPTER_KIND:
            continue
        try:
            adapters = adapters or adapter_config.from_machine()
            entry = adapters.pick(stage.get("model"), ADAPTER_KIND[stage["tool"]])
        except adapter_config.AdapterError:
            versions[f"stage {stage['id']}"] = "adapter not configured"
            continue
        program = adapter_config.program(entry)
        if not program.name.startswith("python"):
            program = program.with_name("python")  # a venv's commands sit beside its interpreter
        versions[entry.id] = probed(program) if program.is_absolute() else "not a Python program"
    return versions


def probe_interpreter(python, packages):
    """{"python": version, "packages": {name: version}} of the interpreter at PYTHON."""
    result = subprocess.run([str(python), "-I", "-c", PACKAGE_PROBE, *packages], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def check_supported(job, runners):
    for stage in job["stages"]:  # a stage chooses its adapter by id only (docs/adapters.md, "Trust rule")
        chosen = stage.get("model")
        if chosen is not None and (not isinstance(chosen, str) or not adapter_config.IDENTIFIER.fullmatch(chosen)):
            raise RunError(f"stage '{stage.get('id')}': `model` must be an adapter id, not "
                           f"{json.dumps(chosen)[:60]}")
    unsupported = [f"stage '{s['id']}' uses the tool '{s['tool']}'" for s in job["stages"] if s["tool"] not in runners]
    if unsupported:
        raise RunError("this runner only runs " + ", ".join(sorted(runners)) + ", so it refuses this pipeline: " + "; ".join(unsupported))
    for stage in job["stages"]:
        if stage.get("gate") and stage["tool"] not in GATE_READERS:
            raise RunError(f"stage '{stage['id']}': the tool '{stage['tool']}' has a gate but this runner cannot read its verdict")


def read_matte(folder):
    report = json.loads((folder / "matte.json").read_text())
    return {"verdict": "fail" if report["reasons"] else "pass", "reasons": report["reasons"],
            "measures": {name: report[name] for name in MATTE_MEASURES}}


def read_rig_gate(folder):
    report = json.loads((folder / "rig-validation.json").read_text())
    return {"verdict": report["verdict"], "reasons": report["reasons"], "measures": report["measures"]}


def read_mesh_gate(folder):
    report = json.loads((folder / "mesh-validation.json").read_text())
    return {"verdict": report["verdict"], "reasons": report["reasons"], "measures": report["measures"]}


GATE_READERS = {"matte": read_matte, "mesh_gates": read_mesh_gate, "rig_gate": read_rig_gate}  # a gate tool's report file -> {verdict, reasons, measures}


def deciding_measures(gate):
    """The measures that are not a plain pass, with value, limit and margin (the gate's own words), for the tries table."""
    return {name: {key: m[key] for key in ("value", "limit", "margin", "outcome")}
            for name, m in sorted((gate["measures"] or {}).items()) if isinstance(m, dict) and m.get("outcome") not in (None, "pass")}


def stage_key(stage, seed, runner, identity, input_hashes):
    body = {"key_inputs": stage["key_inputs"], "tool_version": sha256_files(runner.tool_files), "model": identity,
            "inputs": input_hashes}
    if runner.seeded:
        body["seed"] = seed
    return pr.canonical_sha256(body)


def find_reusable(out_root, stage_id, key):
    """The newest earlier stage folder under OUT_ROOT with this stage id and full key whose outputs still match
    (a retried stage's folder is `<id>.try<k>`)."""
    for stage_json in sorted(Path(out_root).glob(f"attempts/*/{stage_id}*/stage.json"), reverse=True):
        try:
            record = json.loads(stage_json.read_text())
        except (OSError, ValueError):
            continue
        folder = stage_json.parent
        if record.get("stage") == stage_id and record.get("key") == key and record.get("outputs") and folder_hashes(folder) == record["outputs"]:
            return folder
    return None


def style_reads_of(job):
    """{stage id: {pack field: sha256 of the value the stage read}} for the style fields each stage declared."""
    return {s["id"]: {name: pr.canonical_sha256(value) for name, value in s["reads"].items() if name.startswith("style.")}
            for s in job["stages"] if any(name.startswith("style.") for name in s["reads"])}


def plan_stage(stage, seed, runner, stage_folders, out_root):
    """(key, input paths, identity) for a stage whose input stages are in STAGE_FOLDERS, or None when an input is not there yet."""
    inputs = {}
    for name, reference in stage["inputs"].items():
        stage_id, filename = reference.split("/", 1)
        path = stage_folders.get(stage_id, Path("/nonexistent")) / filename
        if not path.is_file():
            return None
        inputs[name] = path
    hashes = {name: sha256_file(path) for name, path in inputs.items()}
    identity = runner.identity(stage)
    return stage_key(stage, seed, runner, identity, hashes), inputs, identity


def dry_run_lines(job, out_root, runners):
    check_supported(job, runners)
    folders, lines = {}, []
    for stage in job["stages"]:
        runner = runners[stage["tool"]]
        planned = plan_stage(stage, job["seed"], runner, folders, out_root)
        if planned is None:
            lines.append(f"{stage['id']}: would run (its input is not made yet)")
            continue
        found = find_reusable(out_root, stage["id"], planned[0])
        lines.append(f"{stage['id']}: would reuse {found.relative_to(out_root)}" if found else f"{stage['id']}: would run")
        if found:
            folders[stage["id"]] = found
    return lines


def retry_plan(job):
    """(index of the stage whose gate retries, index it restarts at, its retry block) or (None, 0, None)."""
    ids = [s["id"] for s in job["stages"]]
    for index, stage in enumerate(job["stages"]):
        if stage.get("retry"):
            retry = stage["retry"]
            if job["seed"] + retry["max"] * retry["seed_step"] >= SEED_LIMIT:
                raise RunError(f"seed {job['seed']} plus {retry['max']} retries of step {retry['seed_step']} must stay below 2**32")
            return index, ids.index(retry["restart_at"]), retry
    return None, 0, None


def execute_stage(stage, runner, name, seed, folders, attempt, out_root, log):
    """Run or reuse one stage into attempt/NAME; returns (stage record for attempt.json, gate result or None).
    The stage's folder is added to FOLDERS only when it made its outputs."""
    planned = plan_stage(stage, seed, runner, folders, out_root)
    if planned is None:
        raise RunError(f"stage '{stage['id']}': an input file is missing: {stage['inputs']}")
    key, inputs, identity = planned
    target = attempt / name
    reused_from = find_reusable(out_root, stage["id"], key)
    timing, failed = {"seconds": 0.0}, None
    if reused_from:
        shutil.copytree(reused_from, target, ignore=shutil.ignore_patterns("stage.json"))
        log(f"{name}: reused {reused_from.relative_to(out_root)}")
    else:
        target.mkdir()
        log(f"{name}: running")
        try:
            timing = runner.run(stage, inputs, target, seed)
        except StageFailed as exc:
            failed = exc.reasons
    outputs = {} if failed else folder_hashes(target)
    missing = [] if failed else [f for f in stage["outputs"] if f not in outputs or (target / f).stat().st_size == 0]
    if missing:
        raise RunError(f"stage '{stage['id']}' did not write {missing}")
    gate = {"verdict": "fail", "reasons": failed, "measures": None} if failed else (
        GATE_READERS[stage["tool"]](target) if stage.get("gate") else None)
    stage_record = {"stage": stage["id"], "tool": stage["tool"], "key": key, "key_inputs": stage["key_inputs"],
                    "seed": seed if runner.seeded else None, "model": identity, "tool_version": sha256_files(runner.tool_files),
                    "inputs": {n: {"from": stage["inputs"][n], "sha256": sha256_file(path)} for n, path in inputs.items()},
                    "outputs": outputs, "timing": timing, "reused_from": str(reused_from.relative_to(out_root)) if reused_from else None}
    reported = None if reused_from or failed else adapter_run.reported(target)
    if reported is not None:
        stage_record["model_reported"] = reported
    if "prompt" in stage:
        stage_record["prompt"] = stage["prompt"]
        stage_record["negative"] = stage["reads"]["style.prompt"]["negative"]
        for field in ("prompt_parts", "negative_parts"):  # absent from a job resolved before they were recorded
            if field in stage:
                stage_record[field] = stage[field]
    if gate:
        stage_record["gate"] = gate
    write_json(target / "stage.json", stage_record)
    if not failed:
        folders[stage["id"]] = target
    entry = {key_: stage_record[key_] for key_ in ("stage", "tool", "key", "key_inputs", "seed", "model", "tool_version", "outputs", "timing", "reused_from")}
    if reported is not None:
        entry["model_reported"] = reported
    entry.update(reused=bool(reused_from), folder=name, **({"gate": gate} if gate else {}))
    if failed:
        entry["failed"] = failed
    return entry, gate


def supply_stages(job, start_at, supplied, attempt):
    """Prepare a run that starts at stage START_AT from saved files. SUPPLIED maps "<stage id>/<file>" to the path of
    a file standing in for that output of an earlier stage. Every output of an earlier stage that a later stage reads
    must be supplied (RunError names the stage and file), and nothing else may be. The files are copied into the
    attempt under the earlier stages' ids and hashed. Returns (index of START_AT, {stage id: folder}, record body);
    the earlier stages are recorded as supplied, never as run."""
    ids = [stage["id"] for stage in job["stages"]]
    if start_at not in ids:
        raise RunError(f"--start-at {start_at!r} is not a stage of this pipeline ({', '.join(ids)})")
    start = ids.index(start_at)
    needed = sorted({reference for stage in job["stages"][start:] for reference in stage["inputs"].values()
                     if reference.split("/", 1)[0] in ids[:start]})
    missing = [reference for reference in needed if reference not in supplied]
    if missing:
        raise RunError(f"starting at '{start_at}' needs the saved output(s) {', '.join(missing)}; give each as --input STAGE/FILE=PATH")
    unused = sorted(set(supplied) - set(needed))
    if unused:
        raise RunError(f"nothing from '{start_at}' on reads {', '.join(unused)}; remove it from the saved inputs")
    folders, record = {}, {}
    for reference in needed:
        stage_id, filename = reference.split("/", 1)
        source = Path(supplied[reference])
        if not source.is_file() or source.stat().st_size == 0:
            raise RunError(f"saved input {reference}: {source} is missing or empty")
        target = attempt / stage_id / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        folders[stage_id] = attempt / stage_id
        record[reference] = {"path": str(source), "sha256": sha256_file(target)}
    return start, folders, record


def run_job(job, out_root, runners, run_id=None, final_dir=None, log=print, start_at=None, supplied=None, versions=None):
    """Run every stage of the resolved JOB (or reuse it), write attempt.json, and, for a generated attempt with
    FINAL_DIR, the final file and its sidecar. Returns the attempt record; its status is `generated`, `review`
    (a gate asked for a person) or `failed` (a gate failed for good). A crash raises and leaves status `failed`
    with the error in the record.

    START_AT names a stage to start at, with SUPPLIED the saved files the earlier stages would have made
    (see supply_stages): the earlier stages do not run, the record says `start_at` and lists `supplied` files with
    their hashes, and a retry that would restart before START_AT is switched off (a failure there ends the attempt).

    VERSIONS (environment_versions(job)) is recorded in the attempt as `versions`; it is evidence only, never part of
    a stage key. Without it the record holds this process's Python version alone."""
    check_supported(job, runners)
    if supplied and start_at is None:
        raise RunError("saved inputs were given without --start-at")
    retry_at, restart, retry = retry_plan(job)
    out_root = Path(out_root)
    attempt_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    attempt = out_root / "attempts" / attempt_id
    attempt.mkdir(parents=True)
    run_id = run_id or attempt_id
    seed = job["seed"]
    began = time.monotonic()
    record = {"attempt": attempt_id, "run_id": run_id, "status": "running", "started_utc": utc_now(), "seed": seed,
              "versions": versions if versions is not None else {"python": sys.version.split()[0]},
              "resolved_job": job, "sources": job["sources"], "models": {}, "stages": {}, "tries": []}
    stages, folders = job["stages"], {}
    try:
        try_no, start = 0, 0
        if start_at is not None:
            start, folders, record["supplied"] = supply_stages(job, start_at, supplied or {}, attempt)
            record["start_at"] = start_at
            if retry and restart < start:
                log(f"retry is off: it would restart at '{retry['restart_at']}', before the start stage '{start_at}'")
                retry = None
        while True:
            try_seed = seed + try_no * (retry["seed_step"] if retry else 0)
            names, seconds, stopped = {}, 0.0, None
            for index in range(start, len(stages)):
                stage = stages[index]
                stage_seed = try_seed if index >= restart else seed
                names[stage["id"]] = stage["id"] if try_no == 0 else f"{stage['id']}.try{try_no}"
                entry, gate = execute_stage(stage, runners[stage["tool"]], names[stage["id"]], stage_seed, folders, attempt, out_root, log)
                record["stages"][names[stage["id"]]] = entry
                if entry["model"]:
                    record["models"][stage["id"]] = entry["model"]
                seconds += entry["timing"]["seconds"]
                if gate and gate["verdict"] != "pass":
                    stopped = (stage, gate, entry["folder"])
                    break
            decided = stopped or next(((s, record["stages"][names[s["id"]]]["gate"], names[s["id"]]) for s in reversed(stages)
                                       if s["id"] in names and s.get("gate")), None)
            if decided:
                gate_stage, gate, folder = decided
                sheet = f"attempts/{attempt_id}/{folder}/{SHEET_FILE}" if (attempt / folder / SHEET_FILE).is_file() else None
                record["tries"].append({"try": try_no, "seed": try_seed, "stage": gate_stage["id"], "verdict": gate["verdict"],
                                        "reasons": gate["reasons"], "deciding": deciding_measures(gate), "seconds": round(seconds, 2),
                                        "stages": dict(names), "review_sheet": sheet})
            if stopped and retry and restart <= stages.index(stopped[0]) <= retry_at and stopped[1]["verdict"] in retry["on"] and try_no < retry["max"]:
                log(f"{stopped[0]['id']}: {stopped[1]['verdict']} on try {try_no} (seed {try_seed}); trying again from '{retry['restart_at']}'")
                try_no, start = try_no + 1, restart
                continue
            break
        record["status"] = {"pass": "generated", "review": "review", "fail": "failed"}[stopped[1]["verdict"]] if stopped else "generated"
        if stopped:
            record["verdict"] = {**record["tries"][-1], "stage": stopped[0]["id"]}
            record["not_run"] = [s["id"] for s in stages[stages.index(stopped[0]) + 1:]]
        elif record["tries"]:
            record["verdict"] = record["tries"][-1]
        if record["status"] == "generated":
            final_stage, final_file = final_of(job)
            final = folders[final_stage] / final_file
            record["final"] = {"stage": final_stage, "file": final_file, "sha256": sha256_file(final)}
            if final_dir is not None:
                record["final"]["path"] = write_final(job, record, final, out_root, Path(final_dir))
    except BaseException as exc:
        record["status"] = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
        record["error"] = str(exc)
        raise
    finally:
        record["finished_utc"] = utc_now()
        record["wall_seconds"] = round(time.monotonic() - began, 2)
        write_json(attempt / "attempt.json", record)
    return record


def final_of(job):
    """(stage id, file) of what the pipeline makes: the mesh the last gate judged, or the last stage's first output."""
    last = job["stages"][-1]
    if last.get("gate") and "mesh" in last["inputs"]:
        stage_id, filename = last["inputs"]["mesh"].split("/", 1)
        return stage_id, filename
    return last["id"], last["outputs"][0]


def build_sidecar(job, record, file_name):
    """The D25 section 4 provenance for one finished file: what made it, by hash, with relative paths only. A mesh
    adds the verdict that passed it and the relative path of its review sheet."""
    sources = job["sources"]
    latest = {entry["stage"]: entry for entry in record["stages"].values()}  # a retried stage: its last try
    is_mesh = file_name.endswith(".glb")
    sidecar = {"sidecar_version": SIDECAR_VERSION,
               "asset": {"id": sources["subject"]["id"], "kind": job["pipeline"]["kind"]},
               "subject": sources["subject"], "motif": sources["motif"],
               "style": {"id": sources["style"]["id"], "flattened_sha256": sources["style"]["flattened_sha256"],
                         "chain": sources["style"]["chain"]},
               "style_reads": style_reads_of(job),
               "pipeline": sources["pipeline"], "contract": sources["contract"],
               "seed": record["seed"], "run_id": record["run_id"], "attempt": f"attempts/{record['attempt']}",
               "models": record["models"],
               "stages": {sid: {"key": s["key"], "key_inputs": s["key_inputs"], "reused": s["reused"], "reused_from": s["reused_from"]}
                          for sid, s in latest.items()},
               ("mesh" if is_mesh else "image"): {"path": file_name, "sha256": record["final"]["sha256"]}}
    if "verdict" in record:
        verdict = record["verdict"]
        sidecar["verdict"] = {key: verdict[key] for key in ("stage", "try", "seed", "verdict", "reasons", "deciding")}
        sidecar["review_sheet"] = verdict["review_sheet"]
    return sidecar


def write_final(job, record, image, out_root, final_dir):
    """Copy the final file to FINAL_DIR/<style id>/<asset id>.<ext> and write <asset id>.source.json beside it."""
    style_id, asset_id = job["sources"]["style"]["id"], job["sources"]["subject"]["id"]
    target = final_dir / style_id / f"{asset_id}{image.suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + f".tmp-{uuid.uuid4().hex[:6]}")
    shutil.copy2(image, temp)
    os.replace(temp, target)
    write_json(target.with_suffix(".source.json"), build_sidecar(job, record, target.name))
    return str(target.relative_to(out_root)) if out_root in target.parents else target.name


def leaves(value, prefix=""):
    """{dotted path: leaf} where a list counts as one leaf."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(leaves(item, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: value}


def style_only_violations(first, second):
    """Paths where two sidecars of the SAME subject, pipeline and seed differ beyond what a style swap explains.

    Allowed: the style identity and hashes, every style_reads entry, the full key of any stage (it includes the
    input image, which the style changed), the key_inputs of a stage that reads a style field, and what the
    attempt itself is (attempt id, the image hash). Anything else is a leak of the look or the run into the record."""
    a, b = leaves(first), leaves(second)
    style_stages = set(first["style_reads"]) | set(second["style_reads"])
    allowed_exact = {"style.id", "style.flattened_sha256", "style.chain", "attempt", "image.sha256"}
    violations = []
    for path in sorted(set(a) | set(b)):
        if a.get(path, "<absent>") == b.get(path, "<absent>"):
            continue
        parts = path.split(".")
        ok = (path in allowed_exact or parts[0] == "style_reads"
              or (parts[0] == "stages" and parts[2:] == ["key"])
              or (parts[0] == "stages" and parts[2:] == ["key_inputs"] and parts[1] in style_stages)
              or (parts[0] == "stages" and parts[2:] == ["reused_from"]))
        if not ok:
            violations.append(path)
    return violations


def build_job(args, seed=None):
    if args.job:
        return json.loads(args.job.read_text())
    pipeline = pf.load(args.pipeline)
    subject, motif = pr.load_subject(args.subject), pr.load_motif(args.motif)
    style, contract = pr.load_style(args.style), pr.load_contract(args.contract)
    if args.lint:
        found = pr.lint(pipeline, subject, motif, style)
        if found:
            raise pf.PipelineError(found)
    return pr.resolve(pipeline, subject, motif, style, contract, args.seed if seed is None else seed)


def parse_inputs(items):
    """{"stage/file": path} from repeated STAGE/FILE=PATH arguments."""
    supplied = {}
    for item in items:
        reference, _, path = item.partition("=")
        if "/" not in reference or not path:
            raise RunError(f"--input {item!r}: expected STAGE/FILE=PATH")
        if reference in supplied:
            raise RunError(f"--input {reference} is given twice")
        supplied[reference] = Path(path)
    return supplied


def main(argv=None, runners=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job", type=Path, help="a resolved job written by pipeline_resolve --out")
    for name in ("pipeline", "subject", "motif", "style", "contract"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--lint", action="store_true")
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--final-dir", type=Path, help="default: <out-root>/final")
    parser.add_argument("--run-id")
    parser.add_argument("--review-sheet", type=Path, help="a JSON file with a `review_sheet` block; needed when the pipeline has a mesh_gates stage")
    parser.add_argument("--dry-run", action="store_true", help="print what would run or be reused; run nothing")
    parser.add_argument("--start-at", metavar="STAGE", help="start at this stage, with the earlier stages' outputs given by --input")
    parser.add_argument("--input", action="append", default=[], metavar="STAGE/FILE=PATH",
                        help="a saved output of a stage before --start-at (repeat for each one the later stages read)")
    parser.add_argument("--gpu-wait", type=int, default=GPU_WAIT_S, metavar="SECONDS",
                        help="how long to wait for the machine GPU lock before the first model stage that runs")
    parser.add_argument("--candidates", type=int, metavar="N",
                        help="run N seeds, SEED, SEED + 1 and so on, one after another in this process under one GPU lock; "
                             "each seed's final file goes in <final-dir>/seed-<n>")
    args = parser.parse_args(argv)
    sources = [args.pipeline, args.subject, args.motif, args.style, args.contract, args.seed]
    if bool(args.job) == all(s is not None for s in sources) or (args.job and any(s is not None for s in sources)):
        parser.error("give either --job or all of --pipeline --subject --motif --style --contract --seed")
    if args.candidates is not None and (args.job or args.candidates < 1):
        parser.error("--candidates needs a whole number of 1 or more and cannot be used with --job")
    try:
        seeds = [None] if args.candidates is None else [args.seed + i for i in range(args.candidates)]
        jobs = [build_job(args, seed) for seed in seeds]  # every seed is checked before any model time
        review_sheet = load_review_sheet(args.review_sheet) if args.review_sheet else None
        supplied = parse_inputs(args.input)
        if args.dry_run:
            with gpu_session.GpuSession(lambda message: print(message, flush=True), args.gpu_wait) as gpu:
                runners = runners or default_runners(jobs[0], review_sheet, gpu)
                for job in jobs:
                    print(pr.dry_run_text(job))
                    print("\n".join(dry_run_lines(job, args.out_root, runners)))
            return 0
        return run_jobs(args, jobs, review_sheet, supplied, runners)
    except (pf.PipelineError, RunError) as exc:
        print(exc, file=sys.stderr)
        return 1


def run_jobs(args, jobs, review_sheet, supplied, runners=None):
    """Run each of JOBS in this process under ONE GpuSession, so the GPU lock is taken once for all of them (the first
    model stage that runs) and held until the last ends. A seed that raises RunError or PipelineError is reported and
    the next still runs. Returns the exit code: 1 if any attempt failed or errored, else 3 if any asked for review, else 0."""
    final_base = args.final_dir or args.out_root / "final"
    versions = environment_versions(jobs[0])
    codes = []
    with gpu_session.GpuSession(lambda message: print(message, flush=True), args.gpu_wait) as gpu:
        runners = runners or default_runners(jobs[0], review_sheet, gpu)
        for job in jobs:
            final_dir = final_base / f"seed-{job['seed']}" if args.candidates is not None else final_base
            try:
                record = run_job(job, args.out_root, runners, args.run_id, final_dir,
                                 start_at=args.start_at, supplied=supplied, versions=versions)
            except (pf.PipelineError, RunError) as exc:
                print(exc, file=sys.stderr)
                codes.append(1)
                continue
            print(f"attempt {record['attempt']}: {record['status']}; " + (f"final {record['final'].get('path')}" if "final" in record else
                  "; ".join(record["verdict"]["reasons"]) + f" (review sheet {record['verdict']['review_sheet']})"), flush=True)
            codes.append(EXIT_FOR_STATUS[record["status"]])
    return 1 if 1 in codes else 3 if 3 in codes else 0


if __name__ == "__main__":
    sys.exit(main())
