# Integrating a model

Generative Stage ships no model. Every model stage (a concept image, an image-to-mesh step, a rig, a set of motions)
runs an **adapter**: a command on your computer that follows the contract on this page. Out of the box every kind runs on
a built-in **stand-in** (`adapters/standin/`): no model, no GPU, the Python standard library or headless Blender, the
same output for the same input. Install, the example, generation, export, the smoke test, the container and every test
use the stand-ins, so the whole tool runs on a computer with no GPU and no model installed.

To use a real model, write a small program that takes the contract's arguments and writes the contract's files, then
register it as an adapter entry in your machine config. The tool never imports your model, never downloads weights and
never names a model of its own; it runs your command, checks what it wrote and records what ran.

`pipeline/adapter_config.py` loads and checks the entries; `pipeline/adapter_run.py` runs one;
`adapters/adapter.schema.json` is the same format as a JSON Schema.

    python3 -I pipeline/adapter_config.py check [FILE]   list the adapters, the defaults, and whether this computer can run each
    python3 -I pipeline/adapter_config.py show ID        print one entry as the runner uses it

## The contract, kind by kind

Each kind has a fixed set of placeholders it may use and a fixed set of files it must write. The output file names are
fixed too: `{output}` is always the name in the table, inside the stage folder `{out_dir}`.

| Kind | Placeholders it may use | Must write | Run by |
|---|---|---|---|
| `image` | `{prompt}`, `{negative}`, `{seed}`, `{width}`, `{height}`, `{output}`, `{out_dir}` | `{output}` = `image.png`, a PNG of the asked size | the `concept` stage |
| `image-to-mesh` | `{image}`, `{seed}`, `{output}`, `{out_dir}` | `{output}` = `mesh.glb`, a binary glTF with at least one triangle | the `mesh` stage (params `steps` and `depth`, through `{params.steps}` and `{params.depth}`) |
| `material` | `{image}`, `{seed}`, `{out_dir}` | `{out_dir}/maps/basecolor.png`, `normal.png`, `height.png`, `roughness.png`, `metallic.png` | the optional `texture` stage ([pipeline files](pipeline_files.md)) |
| `rig` | `{mesh}`, `{seed}`, `{output}`, `{out_dir}` | `{output}` = `rigged.glb`, and `{out_dir}/rig.json`: the fitted rig profile in the [motion](motion.md) format, whose `roles` say which bone is which | the `rig` stage |
| `motion` | `{mesh}` (the rigged one), `{rig}` (its `rig.json`), `{seed}`, `{output}`, `{out_dir}` | `{output}` = `animated.glb`, one animation per clip | the `motion` stage (param `clips`) |
| `text` | `{prompt}`, `{seed}`, `{output}`, `{out_dir}` | `{output}` = `text.txt`, UTF-8 | no shipped stage yet; the shape is fixed so a tool can use one |
| `review` | `{image}`, `{prompt}` (the brief), `{seed}`, `{output}`, `{out_dir}` | `{output}` = `review.json`: `{"id", "score", "findings", "uncertainty"}` | no shipped stage yet; the shape is fixed so a tool can use one |
| `rules` | `{schema}`, `{kit}`, `{subject}`, `{seed}`, `{count}`, `{output}`, `{out_dir}` | `{output}` = `rows.json` | parametric generation ([parametric generators](parametric.md)) |
| `render` | `{row}`, `{schema}`, `{seed}`, `{output}`, `{out_dir}` | `{output}` = `still.png` (other views as `still-*.png`) | parametric generation |
| `measure` | `{row}`, `{image}`, `{schema}`, `{seed}`, `{output}`, `{out_dir}` | `{output}` = `measure.json`: `{"numbers": {name: number}}` | parametric generation |

Every kind may also use `{params.NAME}`, the stage's param `NAME` from the pipeline file, and `{python}` and `{repo}`
(below). Anything else the adapter writes in `{out_dir}` is kept with the stage and hashed into its outputs. An adapter
writes only inside `{out_dir}`; it reads only the input files it is given and its own program and weights.

### Placeholders

`{name}` in an entry is filled when the adapter runs. `{{` and `}}` are literal braces.

| Placeholder | Where | Value |
|---|---|---|
| `{python}` | anywhere | the interpreter running the pipeline |
| `{repo}` | anywhere | this repository's folder |
| `{prompt}` | `argv[1:]`; text, image, review | the stage's prompt (for review, the brief) |
| `{negative}` | `argv[1:]`; image | the negative prompt |
| `{seed}` | `argv[1:]`; every kind | the seed, a whole number below 2**32 |
| `{width}`, `{height}` | `argv[1:]`; image | the image size in pixels |
| `{image}` | `argv[1:]`; image-to-mesh, material, review, measure | the input image |
| `{mesh}` | `argv[1:]`; rig, motion | the input `.glb` (for motion, the rigged one) |
| `{rig}` | `argv[1:]`; motion | the rig profile `rig.json` the rig stage wrote |
| `{output}` | `argv[1:]`; every kind but material | the file to write (the table above) |
| `{out_dir}` | `argv[1:]`; every kind | the stage folder |
| `{row}`, `{schema}` | `argv[1:]`; render, measure, rules (`{schema}`) | the parameter row file and the kind's schema file |
| `{kit}`, `{subject}`, `{count}` | `argv[1:]`; rules | the kit table, the subject sheet and the rows per combination |
| `{params.NAME}` | `argv[1:]`; every kind | the stage's param `NAME` from the pipeline file |

`argv[0]`, `env` values, `cwd` and `model.weights` take only `{python}` and `{repo}`, so the program, its environment
and its folder are always the ones written in the entry. An unknown placeholder is an error when the file is loaded.
Each value fills one argument in one pass and is never read again (see "Trust rule"): pass a prompt as
`"--prompt={prompt}"` or as the argument after `"--prompt"`, never expect a shell to split it.

## An entry

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | what a stage, job or request names; letters, digits, `_` and `-`, up to 80 |
| `kind` | yes | one of the kinds above |
| `argv` | yes | the program and its arguments, one string each. Never a shell line: nothing is passed to a shell |
| `sandbox` | yes | `{"network": "deny"}`, `"loopback"` (this computer only) or `"allow"` |
| `licence` | yes | your note on the licences of the model and program you run, and any limits on where or how they may be used |
| `env` | no | extra environment variables, `NAME: text` |
| `cwd` | no | the working folder |
| `requires` | no | what the computer must have: `apple_silicon`, `cuda`, `cpu`, `blender`, `network_denied`, `network_loopback_only` |
| `gpu` | no | `true` holds the machine-wide GPU lock while it runs ([GPU lock](gpu_lock.md)); default `false` |
| `timeout_seconds` | no | default 1800, at most 86400 |
| `model` | no | `{"name": text, "weights": path}`; the weights file or folder is hashed into the model identity |
| `description` | no | one line for people |

A value may start with `~/` for the home folder. Before you register a model, read its licence at the source and write
what you found in `licence`; the tool shows it and records the adapter id with every output.

## Running

What the runner does for one stage, in order (`pipeline/adapter_run.py`):

1. **Host check.** Everything in `requires`, plus what `sandbox` needs, is checked against this computer
   (`pipeline/host.py`, below). An unmet requirement stops the stage before anything runs, one sentence per gap.
2. **Command.** The placeholders are filled. The program starts with `argv` exactly as rendered (no shell), the entry's
   `env` added to the runner's environment, and `cwd` when given. The runner also sets the variables that tell common
   machine-learning libraries to stay offline and send no telemetry (`pipeline/local_run.py`, `OFFLINE`).
3. **GPU lock.** An entry with `"gpu": true` runs only while the job holds the machine's GPU lock. The job takes it once,
   before its first such stage, and keeps it until the job ends; the adapter itself never takes it. Without the
   `gpu_lock` machine setting the stage is refused with a message naming that key. While another process runs the
   program or a fixed script of any `gpu` entry, the job waits for it ([GPU lock](gpu_lock.md)).
4. **Sandbox.** `deny` runs the command with no network; `loopback` allows this computer only. A sandbox the host cannot
   apply is a refusal, never a run with the network open. An adapter that needs a local server starts it itself, on
   loopback, and stops it before it exits.
5. **Timeout.** A command still running after `timeout_seconds` is stopped and the stage fails with "ran past its
   timeout".
6. **Exit code.** Exit 0 means done. Any other exit fails the stage with "adapter 'ID': stage exited N; see LOG". Print
   your reason on stderr: stdout and stderr both go to `step.log` in the stage folder, which a person reads next.
7. **Outputs.** After exit 0 every output the stage declares must exist and be non-empty, or the stage fails with
   "stage 'ID' did not write [...]". The later stages (tidy, matte, mesh clean-up, decimation, the gates) then judge
   what was made; a gate's `fail` can retry with the next seed.

`pipeline_run.py` exits 0 when an attempt is generated, 3 when it needs review and 1 when it failed or was refused; the
message names the stage, the adapter and the log.

### `identity.json` and what a run records

An adapter may write `{out_dir}/identity.json`, a JSON object of at most 64 KB, saying what it ran in its own words: a
name and version, a weights digest, the runtime's version. The runner keeps it out of the stage's output hashes and
copies it into the record as `model_reported`. Write only facts about the run; never a path that names a person or a
secret.

Each stage's record (`stage.json`, and the stage in `attempt.json`) holds:

- `model`: the identity known before the run, which is also part of the reuse key: the adapter `id` and `kind`, the
  entry's `model.name`, `template_sha256` (a hash of the entry's argv, env, cwd and model), `files_sha256` (the hash of
  each fixed argv element that is a file: the program and its scripts) and `weights_sha256` (the hash of
  `model.weights`; a weights path that does not exist is an error naming the adapter). Folder hashes are cached in
  `~/.cache/generative-stage/model-identity.json`, or the file named by `GENSTAGE_IDENTITY_CACHE`.
- `model_reported`: the adapter's `identity.json`, when it wrote one.
- `inputs` and `outputs`: the sha256 of every input and output file.
- `timing`: `seconds`, and `load_seconds` and `generate_seconds` when the adapter printed a timing line (below).

`attempt.json` also has `versions`: for each adapter a stage used, named by its id and never by path, the Python and
package versions beside its program when it is a Python environment. Change the program, its scripts, its weights or
its entry and the stage's key changes, so nothing is reused across a model change.

### Timing

Optional. If the adapter prints one line `load Xs, generate Ys` (seconds), or a progress bar whose last line reads
`N/N [MM:SS<...`, the runner records `load_seconds` and `generate_seconds` from it.

## Registering and choosing an adapter

Adapters live in the machine config ([machine settings](machine_settings.md)): `~/.config/generative-stage/machine.json`,
or the file named by `GENSTAGE_MACHINE_CONFIG`. It is the only place a command is defined.

```json
{
  "tools_python": "/path/to/.venv-tools/bin/python",
  "gpu_lock": "~/.local/state/generative-stage/gpu-lock",
  "adapters": [ { "id": "my-image-model", "kind": "image", "argv": ["..."], "sandbox": {"network": "deny"},
                  "gpu": true, "licence": "..." } ],
  "defaults": {"image": "my-image-model"}
}
```

Which adapter a stage runs:

1. the id the stage names: a pipeline file stage's `model`, or a job request's `adapters` map
   (`{"image": "my-image-model"}`, `POST .../entities/{id}/jobs`, [API](api.md)), or the MCP server's `adapters`
   argument ([MCP server](mcp.md)). The id must be configured and of the stage's kind;
2. else `defaults[kind]` in the machine config;
3. else the stand-in of that kind. With no machine config every kind but `material` has a stand-in default. No shipped pipeline has a `texture` stage, so nothing a stranger runs needs a material adapter; a pipeline you add a `texture` stage to, with no material adapter configured, stops at that stage with "no adapter of kind 'material' is configured" (the earlier stages keep their results), and the tool never offers a stand-in map.

An unknown id is an error; it never falls back to another adapter. The built-in ids (`standin-*`, `rules-kit`) are
taken. `GET /api/v1/adapters` and `python3 -I pipeline/adapter_config.py check` list what is configured, the default
of each kind, and whether this computer can run each.

## A worked example

`adapters/examples/dummy/` is a complete image adapter that wraps a dummy script instead of a model. Its entry, ready to
paste into a machine config:

```json
{
  "adapters": [
    {
      "id": "dummy-image",
      "kind": "image",
      "description": "The worked example of docs/adapters.md: a flat colour, no model",
      "argv": ["{python}", "-I", "{repo}/adapters/examples/dummy/dummy_image.py", "--prompt={prompt}",
               "--seed", "{seed}", "--width", "{width}", "--height", "{height}", "--output", "{output}"],
      "requires": ["cpu"],
      "sandbox": {"network": "deny"},
      "gpu": false,
      "timeout_seconds": 60,
      "model": {"name": "dummy-image 1"},
      "licence": "MIT (this repository). No model and no weights."
    }
  ],
  "defaults": {"image": "dummy-image"}
}
```

`dummy_image.py` takes `--prompt`, `--seed`, `--width`, `--height` and `--output`, writes a PNG of one colour taken
from the prompt and seed, writes `identity.json` (`{{"name": "dummy-image", "version": 1}}`), prints
`load 0.00s, generate 0.00s`, and exits 0; a size out of range is one line on stderr and exit 1. To try it:

    python3 -I pipeline/adapter_config.py check adapters/examples/dummy/adapters.json

then copy the entry into your machine config, run a concept pipeline, and look at the stage's `stage.json`: `model`
names `dummy-image` and `model_reported` holds what the script wrote. To integrate a real image model, replace the body
of `make()` with a call to it, keep the arguments and files the same, set `gpu` and `requires` to what the model needs,
point `model.weights` at its weights, and fill in `licence`. The other kinds work the same way with the arguments and
files in the table above.

## Trust rule

Only the machine config defines a command. Everything else chooses an adapter by id:

- a pipeline file's stage names it in `model`; any other key, or a `model` that is not an id, is refused when the file
  loads;
- a resolved job (`pipeline_run.py --job`) is checked the same way before anything runs, and the runner reads nothing
  from a stage but its id, prompt, size, params and input files;
- a job request to the HTTP API (`POST .../entities/{id}/jobs`) names a pipeline this server offers by id, adapters by
  kind and id (each must be configured and of that kind), and the choices the pipeline file declares (a style or motif
  id from its options, a seed, a candidate count, inside its range); it refuses any other key, and the style and motif
  files are looked up from the declared ids, never built from request text; query strings are not read;
- the MCP server's tools have no field for a command, an argument list, an environment, a file, a folder or an address:
  a run names a pipeline, adapters and declared choices by id or number, and a call with any other field is refused before a request is made
  ([MCP server](mcp.md));
- entity data is checked against its kind's schema, and job files hold only the keys a runner reads;
- a project file refuses keys it does not know, so it cannot define an adapter;
- an export bundle read back in is checked against its schema, and the Godot importer only copies files.

The values a stage supplies (a prompt, a seed, a param) fill placeholders in one pass. Each lands inside one argument
and is never read again for placeholders, so a prompt such as `x --output /etc/passwd; rm -rf ~` stays one argument and
`{out_dir}` inside a prompt stays as written. A stage that names an id that is not configured is an error; it never falls
back to another adapter.

`pipeline/tests/test_trust_rule.py`, `server/tests/test_trust_rule.py` and `server/tests/test_mcp_trust.py` try each of these routes.

## Host capabilities

`pipeline/host.py` is the one place that knows the operating system. Nothing else branches on it; a test checks.

    python3 -I pipeline/host.py      print what this computer offers

It answers: which accelerators exist (`apple_silicon`, `cuda`, always `cpu`); which programs are on PATH (`blender`,
for the rig and motion stand-ins); whether a child process can be denied the
network (macOS: `sandbox-exec`; Linux: an unprivileged network namespace through `unshare -rn`) or held to this computer
only (macOS); and where the GPU lock is (the `gpu_lock` setting). Before an adapter runs, everything in `requires`, plus
what its `sandbox` needs, is checked against the host; an unmet requirement stops the stage with one sentence per gap,
for example "needs an Apple Silicon Mac (this host is Linux on x86_64)". A sandbox the host cannot apply is a refusal,
never a run with the network open.

## The stand-ins

`adapters/standin/` is built in: four entries (`standin-image`, `standin-mesh`, `standin-text`, `standin-review`) that
run `adapters/standin/standin.py` under `{python}` with the Python standard library only, and two (`standin-rig`,
`standin-motion`) that run `adapters/standin/standin_blender.py`, which runs one script in background Blender. No model,
CPU only, the same output for the same input; the first four take a second or two per call at most, the Blender two a
second or two:

- image: a PNG of the asked size: a procedural drawing, made by code, of the subject the prompt's words point to (a stringed
  instrument, a lantern, a book, a standing figure, a vessel, or a cut gem for anything else), lit like clay and centred on
  white, its proportions and palette varied by the seed and the prompt. The words and the families are one table at the
  top of `adapters/standin/standin_subjects.py`;
- image-to-mesh: a closed solid of a few thousand faces as `.glb`, raised from the image's own silhouette (the outline is
  inflated into a pillow, mirrored front and back) with normals and vertex colours taken from the image's pixels, so it
  matches what the picture shows and the shape gate measures it for real;
- text: a few lines that name the prompt and seed;
- review: `{"id", "score", "findings", "uncertainty"}`; the score comes from the image's hash;
- rig (`blender/rig_standin.py`): fits the example biped profile (`blender/examples/rigs/biped.json`) to the mesh by its
  bounds (height sets the scale, the half-width the arm spread, the feet stand on its lowest point), pulls any joint
  that falls outside the body just inside it, and gives every vertex the weights of its nearest bone segments, at most
  four, summing to one. Writes `rigged.glb`, `rig.json` (ground at y = 0) and `rig-report.json`. Expect it to work on
  chunky A-pose bodies with separate limbs, and to pinch at shoulders and hips; capes, skirts, fused arms and T-poses
  rig poorly;
- motion (`blender/animate_standin.py`): makes the clips the stage names with the procedural families
  (`blender/motions/`, picked through `blender/examples/motion_manifest.json` for a rig called `biped`) for the fitted
  profile, keys them on the rigged mesh, checks every bone against the profile's kinematics, and writes `animated.glb`
  (one animation per clip) and `clips.json` (each clip's checks).

The two Blender entries require `blender`: without it on PATH the stage stops with "needs Blender, run headless".

Its outputs pass the pipeline's later stages, so `pipeline/pipelines/examples/prop.pipeline.json` and
`character.pipeline.json` (the same, then rigged, gated and animated) run end to end on a computer with no model (the
image and mesh tools need `tools_python`; the character's last stages need Blender). On the stand-in the
character is the drawn standing figure raised into a solid, rigged, and it walks.
