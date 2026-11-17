# Generative Stage

Generative Stage is a local tool for planning and building the parts of a story world: settings,
characters and props. You write a brief for each and link them together. A pipeline turns a brief into concept
images, 3D models and motion clips; the tool keeps a record of every step, so you can open any asset and see the exact
prompt, inputs, outputs and time of each stage. What you choose is exported as a bundle (glTF models and a JSON
manifest) that any engine or game can read.

Everything runs on your computer. Nothing is sent anywhere, and **no model and no GPU are needed**: no model ships with
the tool, and every kind of stage runs on a built-in **stand-in** that makes plain placeholder output (a coloured disc, a
sphere). Install, the example, generation, export, the smoke test, the container and every test run that way. To use a
model of your own, write a small adapter for it and name it in one file ([Integrating a model](docs/adapters.md),
step 8).

It is a work in progress. Names, layout and interfaces may change.

## What you need

- macOS or Linux (Windows: use Docker or WSL; it is untested).
- `python3` (3.10 or newer) on your path, for the helper scripts (`scripts/load_example.py`, `scripts/smoke.py`).
- [uv](https://docs.astral.sh/uv/) and Node.js 22.22.3 or newer (24.15 or newer, or 26 and up, also work). uv fetches the
  Python version the server and tools use.
- Blender (optional, headless): only for the stages that rig and animate a character.
- A model of your own (optional): see step 8. None is needed.

## The walkthrough

These nine steps take you from nothing to an exported asset. Each is what the tool does today.

### 1. Install

From the repository's folder:

    ./install.sh

It checks the prerequisites, sets up the server and a pinned tools environment (for the image and mesh stages),
installs and builds the web app, and writes a default machine config in which every kind of stage runs on the stand-in.
It never overwrites a machine config you already have. Run it again at any time.

Or, with Docker and nothing else installed:

    docker compose up

### 2. Start it

    ./start.sh

then open <http://127.0.0.1:4280>. It starts the API (port 8780), the read-only run server (8781) and the web app
(4280), all on this computer only. Change a port with `GENSTAGE_API_PORT`, `GENSTAGE_READONLY_PORT` or `GENSTAGE_WEB_PORT`. Press Ctrl-C
to stop. To check a running install end to end: `python3 scripts/smoke.py http://127.0.0.1:4280`.

### 3. Open the example project (or make your own)

The example is a small, plain project: a lantern cove with a lighthouse, its keeper, two props and a short script. In a second
terminal, give it the address the web app is on (step 2; the default is shown):

    python3 scripts/load_example.py http://127.0.0.1:4280

It makes the project in `~/generative-stage-example` (change that with `--folder`; with Docker, `--folder /data/lantern-cove`)
and adds it to the project list. Reload the page; if another project is current, pick **Lantern Cove (example)** in the bar at the
top. It is safe to run again.

To make your own instead, open **Projects**, fill in **Make a new project** (a folder that is empty or does not exist, a short
name and a name) and press **Make project**; the default kinds (setting, character, prop, script) are copied into it. **Open an
existing project** adds a project you already have, by the path of its `studio.project.json`.

### 4. Write briefs and link them

Pick a kind in the left list (**Settings**, **Characters**, **Props**). **New prop** opens a form made from the kind's
JSON Schema: a name, a brief (what it is, what it looks like, why it matters) and the kind's other fields. Open a record to
see its profile: its fields, a notes box, its history, and **Related**, everything linked to it in both directions.
**Edit all fields** opens the full form, which also has the **Links** panel: **Add a link**, pick a link type
(a character *lives in* a setting, a prop *belongs to* a character, a prop *is found in* a setting, a setting is *part of*
a setting, a character *knows* a character) and the record to link to. The kinds and link types are files in the
project's `kinds/` folder; edit them to describe your own world ([API](docs/api.md#kinds)).

### 5. Generate on the stand-in

Open **Brass Signal Lantern** and press **Generate** in the picture panel. Leave **What to make** on *Props from a
concept image*, adjust the prompt if you like, and press **Start**. The steps run one after another: concept image,
tidy, find the subject, image to mesh, clean and size the mesh, reduce it, shape gate. The picture the run made appears
under **Candidates** on the **Image** tab: click it to preview it and press **Use this** to choose it. The model is a candidate
on the **3D** tab; choose it the same way, and the tab then shows it in the bundled viewer (drag to turn, scroll to zoom). On the stand-in the picture is a coloured disc and the model
a sphere: the point is that the whole chain, including its checks, runs with no model.

To rig and animate a character, run **Animated characters from a concept image** on **Ines Marlow** (needs `blender` on
your path). The 3D tab then has a clip player with the walk and other clips.

### 6. Read the trace

From a finished run, press **See how it was made**, or open the run from the record's history. Each stage shows
whether it completed, was supplied, or errored (with the error), what it took, the exact prompt and the settings and
shared values it read, its inputs and outputs with their hashes, the model or adapter that produced it, and the measures
of any check (value, limit, margin). Pictures and models open in place. The **Feeds this** panel on a record lists the
shared words (style, motif, contract) the last run read; open one to see what else reads it.

### 7. See the statistics, and export

**Statistics** (left list) shows, for the current project, runs over time, time per stage, completed against errored
runs, and candidates made against chosen. A stage "completes" or "errors"; whether the result is any good is your choice,
and the checks inform it without blocking it.

An export writes the project's records, links and chosen files as a bundle: `manifest.json` plus the `.glb` and `.png`
files, byte for byte ([format](docs/export_bundle.md)). There is no button yet; use the API or the command line:

    curl -s -X POST http://127.0.0.1:4280/api/v1/projects/lantern-cove/exports \
         -H 'Content-Type: application/json' -H 'X-Studio-Request: 1' -d '{}'

The bundle is written to `<project folder>/exports/<id>/`, and `.../exports/<id>/bundle.zip` downloads it. From `server/`:
`uv run studio export --project <project>/studio.project.json --out <empty folder>`. A small reader for it, for Godot,
is in `export/engines/godot_example/`.

### 8. Integrate a model (optional)

Every stage that runs a model names an **adapter** by id. An adapter is any program that takes the arguments of its kind
(a prompt, a seed and a size for an image; an image for image-to-mesh; ...) and writes the kind's files. The contract,
kind by kind, is in [Integrating a model](docs/adapters.md), with a worked example that wraps a dummy script
(`adapters/examples/dummy/`). The only place an adapter's command is defined is the machine config, a file you edit:
`~/.config/generative-stage/machine.json`, or the file named by `GENSTAGE_MACHINE_CONFIG`. Add your entry to its
`adapters` list and name it in `defaults`:

    {"adapters": [ ...your entry... ], "defaults": {"image": "my-image-model"}}

Check it with `python3 -I pipeline/adapter_config.py check`, which lists every adapter and whether this computer can run it,
then run step 5 again: the **Image model** list in the Generate panel now offers it, and the trace records the adapter,
the model identity and the weight hashes. Weights are never downloaded for you. Read your model's licence before you use
it, and note it in the entry. No other file, project record, API call or agent can define a command
([adapters](docs/adapters.md#trust-rule)).

### 9. Drive it from an agent (MCP)

The MCP server lets an agent read and write records and links, list pipelines and adapters, start a run, read its status
and trace, choose a candidate and export. It talks to the API, so it can do nothing the API refuses, and it can choose
an adapter but never define one. From `server/`, with `./start.sh` running:

    uv run python -m mcp_server --api http://127.0.0.1:8780 --project lantern-cove

Add that command to your MCP client's configuration ([MCP server](docs/mcp.md)). Then ask the agent to write a brief for a
new prop, link it to a setting, run the `prop` pipeline and show you the trace.

## Running the checks

After `./install.sh --dev`, one command runs the checks of each part (`e2e` adds the browser specs and needs
`npx playwright install chromium` once):

    scripts/check.sh pipeline server ui

These are also available one by one: the pipeline tests (`python3 -m unittest discover -s pipeline/tests`), the server,
`core/` and `export/` tests with linter and type checker (from `server/`: `uv run pytest -q`, `uv run ruff check . ../core ../export`,
`uv run mypy`) and the web app (from `ui/`: `npx ng test --watch=false`, `npx ng build`, `npm run test:node`). The full
pipeline check, which also builds the Blender examples headlessly, is `pipeline/check.sh`. The Linux run in a container
is in [platforms](docs/platform.md#checks-on-linux). No check needs a model or a GPU: every model stage runs on the stand-ins. The tests
that run the image and mesh tools, and the browser specs' throwaway server, use the tools interpreter named by
`GENSTAGE_TEST_TOOLS_PYTHON`, else the `tools_python` of your machine config (`./install.sh` sets it to `.venv-tools`).

## Documentation

- [Architecture](docs/architecture.md): the parts and how a run flows through them.
- [Platforms, ports and the image](docs/platform.md), [machine settings](docs/machine_settings.md) and [configuration](server/docs/configuration.md).
- [Integrating a model](docs/adapters.md): the adapter contract for each kind, a worked example, and the trust rule.
- [World model API](docs/api.md), [MCP server](docs/mcp.md), [export bundle](docs/export_bundle.md).
- [Pipeline files](docs/pipeline_files.md), [normalisers](docs/normalisers.md), [shape gate](docs/gate_v2.md), [motion](docs/motion.md), [GPU lock](docs/gpu_lock.md).
- [Condition vocabulary](docs/vocabulary.md) and [story graph](docs/story_graph.md).
- [Third-party software](THIRD_PARTY.md) and the [Blender scripts' licence note](blender/LICENSE-NOTE.md).

## Licence

MIT, see [LICENSE](LICENSE). The scripts in `blender/` use Blender's Python API and are offered under MIT or
GPL-3.0-or-later, your choice ([note](blender/LICENSE-NOTE.md)). Dependencies and the programs the tool can call have their
own licences: [THIRD_PARTY.md](THIRD_PARTY.md).
