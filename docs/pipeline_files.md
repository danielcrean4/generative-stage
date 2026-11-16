# Pipeline files

A pipeline file says, as data, how one kind of asset is made: which stages run, in what order,
with which settings, and what each gate requires. This page is the **one owner** of that format.
The runner, the server's views and the style packs all point here.

`pipeline/pipeline_run.py` is the one runner: it runs a pipeline file's stages, mesh chain included (see Running). The
normalisers keep their separate config files ([normalisers](normalisers.md)); the runner builds them from the pipeline file.

## Why
- One step list, written once as data, serves the runner, the server and the web app: no second copy to drift.
- Look rules do not live in code. Background colour, sizes, budgets and thresholds are values in a file a person can read
  and change.
- A changed setting must mark the right outputs stale. That only works if each stage declares what it reads.

## Who owns what
| Thing | Lives in | Example |
|---|---|---|
| How a kind is made (stages, capture rules, gates) | a pipeline file in this repo, `pipelines/<kind>.json`. It names no game. A project may list its own pipeline files in its project file when a kind needs a different recipe | `pipelines/prop.json` |
| How it is drawn (prompt wording, palette, surface finish) | a style pack | "soft vinyl toy" |
| What it is | a subject spec | "a hand drill with a side handle" |
| In-game size, origin, up and front axes, collision and the **face budget** | the contract for the kind (data the engine or game supplies; read by stages through `reads: ["contract"]`) | props stand on their base, 20,000 faces |
| Machine paths, model weights, Python environments | machine config | where the image model is |

This repo ships example pipeline files under `pipeline/pipelines/examples/`. They are examples, never
defaults: a missing value is an error, not a fallback.

## Shape (version 1)
The full example is `pipeline/pipelines/examples/prop.pipeline.json` (validated by the tests); this is it. The icon
example and the reason there is no head example are under "Examples" below.
```json
{
  "version": 1,
  "id": "prop",
  "name": "Props from a concept image",
  "kind": "prop",
  "capture": {
    "background": {
      "method": "near_white",
      "color": [
        255,
        255,
        255
      ],
      "tolerance": 236,
      "words": "plain white background"
    },
    "framing": {
      "words": "single object, whole object in frame, even light, no cast shadow"
    },
    "view": {
      "words": "three-quarter view",
      "camera": {
        "yaw": [
          -30,
          30,
          15
        ],
        "elevation": [
          -30,
          0,
          10
        ]
      }
    }
  },
  "stages": [
    {
      "id": "concept",
      "label": "Concept image",
      "tool": "concept",
      "inputs": {},
      "reads": [
        "capture",
        "style.prompt",
        "subject",
        "motif"
      ],
      "params": {
        "width": 512,
        "height": 512
      },
      "outputs": [
        "image.png"
      ]
    },
    {
      "id": "tidy_image",
      "label": "Tidy the image",
      "tool": "normalize_image",
      "inputs": {
        "image": "concept/image.png"
      },
      "reads": [
        "capture.background"
      ],
      "params": {
        "canvas_size": 512,
        "margin": 32,
        "output_mode": "rgba"
      },
      "outputs": [
        "image.png"
      ]
    },
    {
      "id": "matte",
      "label": "Find the subject",
      "tool": "matte",
      "inputs": {
        "image": "tidy_image/image.png"
      },
      "reads": [
        "capture.background"
      ],
      "params": {},
      "gate": {
        "min_largest_share": 0.95,
        "min_coverage": 0.05,
        "max_coverage": 0.9,
        "allow_border": false
      },
      "outputs": [
        "matte.png",
        "matte.json"
      ]
    },
    {
      "id": "mesh",
      "label": "Image to mesh",
      "tool": "mesh",
      "inputs": {
        "image": "tidy_image/image.png"
      },
      "reads": [],
      "params": {
        "steps": 50,
        "depth": 8
      },
      "outputs": [
        "mesh.glb"
      ]
    },
    {
      "id": "clean_mesh",
      "label": "Clean, orient and size the mesh",
      "tool": "normalize_mesh",
      "inputs": {
        "mesh": "mesh/mesh.glb"
      },
      "reads": [
        "contract"
      ],
      "params": {
        "weld_distance_share": 1e-05,
        "small_piece_area_share": 0.01,
        "orientation": {
          "view": {
            "drop_axis": 2,
            "transpose": false,
            "flip_x": false,
            "flip_y": true
          }
        }
      },
      "outputs": [
        "mesh.glb"
      ]
    },
    {
      "id": "decimate",
      "label": "Reduce to the face budget",
      "tool": "decimate_mesh",
      "inputs": {
        "mesh": "clean_mesh/mesh.glb"
      },
      "reads": [
        "contract"
      ],
      "params": {
        "preserve_topology": true
      },
      "outputs": [
        "mesh.glb"
      ]
    },
    {
      "id": "shape_gate",
      "label": "Shape gate",
      "tool": "mesh_gates",
      "inputs": {
        "mesh": "decimate/mesh.glb",
        "image": "tidy_image/image.png"
      },
      "reads": [
        "capture.background",
        "capture.view",
        "contract"
      ],
      "params": {},
      "gate": {
        "profile": "v2",
        "thin": false,
        "min_silhouette_iou": 0.6,
        "max_deficit": 0.15,
        "max_excess": 0.15,
        "max_aspect_error": 0.15,
        "min_depth_ratio": 0.25,
        "max_thin_sheet_share": 0.2,
        "max_pieces": 1,
        "review_margin": 0.05,
        "orientation_margin": 0.1,
        "search_seconds": 10
      },
      "retry": {
        "on": [
          "fail"
        ],
        "restart_at": "mesh",
        "max": 2,
        "seed_step": 1
      },
      "outputs": [
        "mesh-validation.json"
      ]
    }
  ]
}
```

### Rules
- **`stages` order is the run order.** There is no other stage list anywhere.
- **`inputs`** names each input as `<stage id>/<file>`, so two stages that both write `mesh.glb`
  are never confused. An input must come from an earlier stage.
- **`retry`** belongs to a gate stage: which verdicts trigger it, the stage to restart at, how
  many times, and how the seed moves. `review` does not retry unless it is listed; it waits for a
  person. Stages before `restart_at` are reused.
- **`label`** is the text people see in the web app. It lives here so the UI never invents one.
- **`tool`** names a registered tool in this repo. A pipeline file can pick a registered tool and,
  for a tool that runs a model, an adapter by id in **`model`** (optional: without it the machine
  config's default adapter of the tool's kind runs). It cannot name a program, an argument or an
  environment variable: commands live only in the machine config ([adapters](adapters.md), "Trust
  rule").
- **`params`** are the tool's own settings. Every key the tool needs must be present, on every stage
  (`{}` for a tool with none). Values the file owns elsewhere are not repeated here: capture values
  (`background_tolerance` or `background`, `background_color`, camera ranges) come from `capture`, and the contract's
  `up_axis`, `front_axis`, `target_size`, `scale_axis` and `face_budget` come from the contract. A stage
  that reads nothing from `capture` may not carry a capture value in `params`, and the face budget
  may appear nowhere in a pipeline file.
- **`gate`** holds thresholds. A stage with a gate ends in `pass`, `review` or `fail`
  ([gate v2](gate_v2.md)). `matte`, `mesh_gates` and `rig_gate` have one (required), no other tool does. The `matte`
  gate holds `min_largest_share`, `min_coverage`, `max_coverage`, `allow_border` (its tolerance is
  `capture.background.tolerance`). The `mesh_gates` gate is the v2 gate block; its frame is the
  `orientation.view` of the nearest earlier `normalize_mesh` stage (one owner, not repeated) and its
  face budget is the contract's. The `rig_gate` gate holds `min_weighted_share`, `max_influences` and
  `min_inside_share` (see "Rig and motion" below).
- **`retry`** `restart_at` is a stage at or before the gate stage; `max` is 1 to `pipeline_file.MAX_RETRIES` (2).
- **`reads`** lists what the stage is given from outside the pipeline file: parts of `capture`,
  named style-pack fields (`style.prompt`, `style.palette`, `style.surface`), `subject`, `motif`,
  or the `contract` for the kind. The runner passes a stage only what it declares. This is
  what makes staleness honest: a stage's cache key is the hash of its tool version, model
  identity, `params`, `gate`, the values it `reads`, and its input files.
- **`capture`** is the contract between the image prompt and the steps that cut the subject out.
  Each part holds its words for the prompt beside the values the tools use (the background's
  `words` sit next to its `color`, `tolerance` and `method`), so one edit changes both. `method`
  says how the subject is separated: `near_white` (the default) or `chroma_key`
  (icons use a magenta key); the keys each method takes are in the table below. `view.camera` gives the gate's camera tolerance as
  `[from, to, step]` in degrees ([gate v2](gate_v2.md)). A style pack may not change `capture`.
  `view` is optional: a kind with no 3D step (icons) has none, and then no stage may read `capture.view`.

  **`capture.background` keys.** `pipeline/background_spec.py` owns them (one validator, also used by
  `normalize_image`, `matte`, `mesh_gates` and `mesh_finish`; the loader only adds that every key is
  present). `method` decides which keys are allowed; all are required in a pipeline file.

  | Key | `near_white` | `chroma_key` |
  |---|---|---|
  | `method` | yes | yes |
  | `color` | `[r, g, b]`, the colour the prompt asks for (the mask ignores it) | `[r, g, b]`, the flat key colour |
  | `tolerance` | 0..255, a channel level: border-connected pixels with every channel at or above it are background | 0..360, a distance from the key: pixels this close or closer are key (alpha 0) |
  | `feather` | - | 0.5..360, the distance past `tolerance` over which alpha ramps from 0 to 1 |
  | `luma_weight` | - | 0..1, how much brightness differences count in the distance (low: tolerate lighting drift) |
  | `holes` | - | true: key-coloured regions enclosed by the subject are background too; false: only border-connected key is background |
  | `despill` | - | 0..1, how far partly see-through edge pixels are pushed away from the key colour |
  | `words` | yes | yes (prompt wording, not mask data) |

  There are no defaults for any of them. The measure and the rules are in [normalisers](normalisers.md),
  "Background separation".
- **Tool identity.** Each registered tool lists its source files (its script and the shared
  modules it imports). The hash of those files is the tool's version in a cache key, so a change
  to a shared module marks every stage that uses it stale.
- Unknown keys are errors. A missing key is an error naming the file and key.

### Choices
A pipeline file may end with a `choices` block: the few things a person or an agent may set when they start a run
from the tool (the profile page's Generate, the job API, MCP `start_run`). It is optional; the runner and the
resolver ignore it, and it changes no stage key. The names are a closed list, because what each one means is fixed in
code, not in the file:

| Name | Declaration | What a run does with the value |
|---|---|---|
| `style` | `label`, `options` (1 to 20 style pack ids), `default` (one of them) | the pack `styles/<id>` in the pipeline's data folder |
| `motif` | `label`, `options` (1 to 20 ids), `default` | the file `motifs/<id>.json` in the data folder |
| `seed` | `label`, `min`, `max` (inside 0 to 4294967295), `default` | the first seed |
| `candidates` | `label`, `min`, `max` (inside 1 to 8), `default` | how many runs, with seeds `seed`, `seed + 1`, and so on, in one `pipeline_run.py --candidates n` process under one GPU lock |
| `hair_colour` | `label`, `options` (1 to 20 `"#rrggbb"` colours), optional `default` (one of them) | written to the subject file as `hair_colour`, which `colour_head` reads; left unset, the subject has none and the head's hair colour comes from the picture alone |
| `start_image` | `label`, `slots` (1 to 20 slot names; the 3D pipeline lists only `main`, because an icon's keyed background is not the one its matte expects), `start_at` (a stage id), `supplies` (a picture one earlier stage makes, `"concept/image.png"`); no `default` | optional. The value is a slot (`main`, `icon`); the run starts at `start_at` with the picture chosen for that slot standing in for `supplies` (`--start-at`, `--input`), so the stages before it do not run |

```json
"choices": {
  "style": {"label": "Style", "options": ["clay", "vinyl_toy"], "default": "clay"},
  "motif": {"label": "Motif", "options": ["repair_shop", "plain"], "default": "repair_shop"},
  "seed": {"label": "Seed", "min": 0, "max": 4294967295, "default": 1},
  "candidates": {"label": "Candidates", "min": 1, "max": 4, "default": 1}
}
```

`pipeline_file.resolve_choices(pipeline, given)` is the one check: a name the pipeline did not declare, a style or
motif that is not one of its options, or a number outside its range is an error naming the choice; every choice left
out takes its default, except `start_image` and a `hair_colour` that declares none, which stay unset: a run that does not name it starts at the first stage. The loader refuses an unknown name, an option that is not an id, a default outside the options
or the range, and any other key. The data folder (contract, `motifs/`, `styles/`) is named by the server's
`authoring/offered.json`, and a test fails when an offered option has no file there.

## How the pieces combine at run time
`resolve(pipeline file, subject spec, motif, style pack, contract, seed)` produces a fully
resolved job: every stage with its exact inputs, including the final prompt text. The resolved
job is what gets recorded in `attempt.json`, with the hash of each source. `resolve --dry-run`
prints it without touching the GPU, so a person or an agent can read the prompt before spending
time on it.

## Registered tools
`TOOLS` in `pipeline/pipeline_file.py` is the one owner of the tool names a pipeline file may use and of
what each takes (the adapter kind it runs, inputs, outputs, the reads it needs, its param keys). Which adapter ids
exist is the machine config's business and is checked when the stage runs ([adapters](adapters.md)). A stage's `outputs` must list exactly the tool's files. Each entry also lists the tool's `sources` (its script and the shared modules it imports, relative to `tools/`); the runner hashes them as the tool's version in a cache key ("Tool identity" above).

| Tool | Adapter kind | Inputs | Outputs | Must read | `params` |
|---|---|---|---|---|---|
| `concept` | image | none | image.png | capture, style.prompt, subject, motif | width, height |
| `matte` (gate) | none | image | matte.png, matte.json | capture.background | none |
| `mesh` | image-to-mesh | image | mesh.glb | nothing | steps, depth |
| `texture` (optional, off by default: see below) | material | image | maps/basecolor, normal, height, roughness, metallic .png | nothing | none |
| `normalize_image` | none | image | image.png | capture.background | canvas_size, margin, output_mode |
| `normalize_mesh` | none | mesh | mesh.glb | contract | weld_distance_share, small_piece_area_share, orientation |
| `decimate_mesh` | none | mesh | mesh.glb | contract | preserve_topology |
| `mesh_gates` (gate) | none | mesh, image | mesh-validation.json | capture.background, capture.view, contract | none |
| `rig` | rig | mesh | rigged.glb, rig.json | nothing | none |
| `rig_gate` (gate) | none | mesh (the rigged .glb) | rig-validation.json | nothing | none |
| `motion` | motion | mesh (the rigged .glb), rig (a `.json` rig profile) | animated.glb | nothing | clips |
| `crop_image` | none | image | image.png | capture.background | keep_share |
| `colour_head` | none | mesh, image | mesh.glb | capture.background, subject | working_faces, posterize, seen_facing, depth_resolution, depth_tolerance, min_seen_share, horizontal_bias, toon_colours, broad_share, nape_height, temple_height, temple_side, ear_top, ear_side, hair_match (the subject's optional `hair_colour` is passed in by the runner) |

### Rig and motion
`pipeline/pipelines/examples/character.pipeline.json` is the prop recipe followed by three stages: `rig` gives the cleaned mesh a
skeleton and skin, `rig_gate` checks the skin, and `motion` keys clips on it. The final file is the motion stage's
`animated.glb`: the mesh, its skeleton, its skin and one glTF animation per clip, which the 3D viewer's clip player plays
and the export bundle carries as it is.

- **`rig`** runs a `rig` adapter on `mesh`. It writes `rigged.glb` and `rig.json`, the fitted rig profile
  ([motion](motion.md): joints with offsets, sites, roles), so the motion stage knows which bone plays which role.
- **`rig_gate`** reads the rigged `.glb` with the standard library (`pipeline/rig_gate.py`) and fails when
  `weighted_share` (vertices with any bone weight) is below `min_weighted_share`, when a vertex follows more than
  `max_influences` bones, or when `inside_share` (deforming joints that sit inside the mesh, from the skin's inverse
  bind matrices) is below `min_inside_share`. The example asks for 1.0, 4 and 1.0. `pipeline/tests/rig_fixtures.py`
  makes the mutants it must catch (unweighted lower half, a bone outside the body, five influences).
- **`motion`** runs a `motion` adapter on the rigged `.glb` and `rig.json`. `clips` is one text of clip names joined by
  commas (`"idle,walk,run,flinch"`), so it fills one argument of the adapter's command; each name is lower-case letters,
  digits and `_`, at most 16.

### The texture tool
`texture` makes five tileable PBR maps (basecolor, normal, height, roughness, metallic) from one picture through a
material adapter; the maps are not mapped onto a mesh. It is **optional and off by default**: no shipped pipeline file
names it, a test fails if one does, and a pipeline gets it only by adding a stage that names the tool. There is no
stand-in for the `material` kind, so the stage also needs a material adapter in the machine config
([adapters](adapters.md)); without one it stops with "no adapter of kind 'material'". The command, network sandbox,
timeout and GPU lock come from that entry, as for every model stage. A stage for it looks like this:

```json
{"id": "material", "label": "Material maps", "tool": "texture", "model": "my-material-adapter",
 "inputs": {"image": "concept/image.png"}, "reads": [], "params": {}, "outputs": ["maps/basecolor.png", "maps/normal.png",
 "maps/height.png", "maps/roughness.png", "maps/metallic.png"]}
```

Before you enable it, read the licence of the material model you put behind the adapter: its terms travel with the maps
it makes.

Param values are checked with the tools' own checks (`normaliser_common`, `gate_settings`,
`gate_v2_config`). The `normalize_*` and `decimate_mesh` scripts import numpy, so the loader cannot
import their `SCHEMA`; their key lists are re-listed in `TOOLS` and a test compares them with the real
`SCHEMA`s when the tools interpreter is present.

## Source shapes
`resolve` reads four sources: a subject, a motif, a style pack and a contract. Each is validated in one place
(`pipeline/pipeline_resolve.py`), with errors naming file and key. The shapes may still change.

| Source | File | Keys |
|---|---|---|
| subject | one JSON file | `id`, `kind`, `text`; optional `colours` (list of `"#rrggbb"`), `materials` (list of text), `hair_colour` (`"#rrggbb"`, read by `colour_head`) |
| motif | one JSON file (`motifs/<id>.json` in an offered data folder) | `id`, `text` |
| style | a folder with `style.json`, or a `.json` file | `id`, `extends` (null or a style id); optional `name`, `version`, `prompt` (`templates` per kind, `negative`), `palette`, `surface`, `presentation`, `terms` |
| contract | one JSON file | `kind`, `up_axis`, `front_axis`, `target_size`, `scale_axis`, `face_budget` |

- `kind` must agree between the pipeline, the subject and the contract.
- Templates may contain `{subject}` and `{motif}` only, and must contain both.
- `extends`: the parent is the sibling `<id>/style.json` or `<id>.json` beside the pack; cycles and
  missing parents are errors. Flattening goes parents first, child over parent: objects merge key by key
  (so a child can change one kind's template and inherit the rest), everything else (text, numbers,
  lists such as `terms`) is replaced. The flattened style is hashed as canonical JSON.
- `palette`, `surface` and `presentation` are passed through as declared; nothing here interprets them.
  A stage that reads `style.palette` or `style.surface` and finds none is an error.
- `terms` (the pack's style words) are used only by the lint, over every pack in the `extends` chain.

## Resolve and the prompt
`python3 -I pipeline/pipeline_resolve.py --pipeline P --subject S --motif M --style STYLE --contract C --seed N
(--dry-run | --out FILE) [--lint]` loads and validates everything, then produces the resolved job. It
never starts a model. `--dry-run` prints the prompt and the stage table and writes nothing; `--out` writes
the job as sorted JSON (the same inputs give the same bytes). `--lint` fails, naming the term and the
place, when a style word appears in the subject text, the motif text or the capture words.

The resolved job holds `sources` (sha256 of the pipeline, subject, motif and contract files, and of the
flattened style with each pack's own hash) and, per stage: `tool`, `model`, `params`, `gate`, `retry`,
`inputs`, `outputs`, `reads` (the value of each declared read and nothing else: a stage that does not
declare `style.prompt` gets no style text) and `key_inputs`, the sha256 of canonical JSON of
`{tool, model, params, gate, reads}`. It is local to the stage: it holds no seed and no input file
hashes; the runner combines it with the input file hashes (slice 3). `style.prompt` is the template for
the pipeline's kind plus the negative prompt, so editing another kind's template changes no key.

**Prompt order.** The concept stage's `prompt` is the style template for the kind with `{subject}` and
`{motif}` filled in (one pass, trailing spaces and commas trimmed), then `capture.background.words`,
`capture.framing.words`, and `capture.view.words` if the capture has a view, all joined with `", "`.
The negative prompt is carried in `reads["style.prompt"]["negative"]` and is not part of the text.

**Prompt parts.** The concept stage also carries `prompt_parts` and `negative_parts`: the prompt as an ordered list of
pieces, so a reader can see where each word came from without re-implementing the assembly. The resolver builds the
prompt from the parts, so the two cannot drift: the prompt is exactly the pieces' `text` joined with nothing between
them (a test holds this for every style). Each piece is `{text, source, start, end}`; `start` and `end` are offsets in
the prompt in Unicode code points. `source.kind` is one of:

| `kind` | Is | Other source fields |
|---|---|---|
| `style_pack` | the template's own words, or the negative prompt | `id` (the pack of the `extends` chain that set the key, so a child that inherits a template names its parent), `key` (`prompt.templates.<kind>` or `prompt.negative`), `version` (the pack's, when it has one), `sha256` (that pack's file) |
| `motif` | the motif text filled in for `{motif}` | `id`, `sha256` |
| `subject` | the subject text filled in for `{subject}` | `id`, `sha256` |
| `pipeline` | the capture words (background, framing, view) | `id` (the pipeline), `key` (`capture.background.words`, ...), `sha256` |
| `glue` | the `, ` the resolver puts between the template and each capture block | none |

The contract adds no words to a prompt, so it is never a part. The pieces are recorded in `stage.json` and in the attempt's
resolved job; they are not an input to any stage key (`key_inputs` hashes only what a stage reads), so recording them
changed no cache key. An attempt made before they were recorded has none, and a reader shows its plain `prompt`.

### Worked dry run
`tests/fixtures/pipeline_files/` holds a subject, motif, contract and two styles (`clay` extends
`vinyl_toy`, which carries `terms`):
```
python3 -I pipeline/pipeline_resolve.py --pipeline pipeline/pipelines/examples/prop.pipeline.json \
  --subject tests/fixtures/pipeline_files/subject.json --motif tests/fixtures/pipeline_files/motif.json \
  --style tests/fixtures/pipeline_files/styles/clay --contract tests/fixtures/pipeline_files/contract.json \
  --seed 42 --lint --dry-run
```
```
prompt (concept): a hand drill with a side handle made of repair-shop, brass and recycled parts, hand-sculpted clay, visible thumb marks, plain white background, single object, whole object in frame, even light, no cast shadow, three-quarter view
negative (concept): text, watermark
stage       tool             model  reads                                       key_inputs
concept     concept          -      capture, style.prompt, subject, motif       04dda79d5578
tidy_image  normalize_image  -      capture.background                          53a51f9f82fe
matte       matte            -      capture.background                          be954c8e21b7
mesh        mesh             -      -                                           8431f29533a1
clean_mesh  normalize_mesh   -      contract                                    4325c71adc00
decimate    decimate_mesh    -      contract                                    ac14ce4f840a
shape_gate  mesh_gates       -      capture.background, capture.view, contract  790366fd319a
style clay flattened_sha256 656fe01bdfa8
```

## Running
`pipeline/pipeline_run.py` runs a resolved job's stages in the pipeline file's order, each given only the inputs and reads it
declares. It runs `concept`, `normalize_image`, `crop_image`, `matte`, `mesh`, `colour_head`, `normalize_mesh`, `decimate_mesh`, `mesh_gates`,
the optional `texture`, and `rig`, `rig_gate` and `motion`; a pipeline that names a tool the runner has no function for is refused before anything runs. `pipeline/style_tracer.py` uses it to compare styles on the same subjects (`pipeline/pipelines/examples/tracer/`).

```
python3 -I pipeline/pipeline_run.py --pipeline P --subject S --motif M --style STYLE --contract C --seed N \
  --review-sheet pipeline/pipelines/examples/finish.prop.json --out-root DIR [--final-dir DIR] [--lint] [--dry-run]
```

**The tools.** `concept`, `mesh`, `texture`, `rig` and `motion` run their adapter entry ([adapters](adapters.md)): the command, network
sandbox, timeout and GPU lock come from the entry, the stage supplies only placeholder values. The lock has one owner
per job, the entry point's `GpuSession` (`pipeline/gpu_session.py`); the runners only call `hold()` ([head pipeline](head_pipeline.md)). `normalize_image`
and `matte` run under the tools interpreter (machine setting `tools_python`; numpy, Pillow). The chain `normalize_mesh`, `decimate_mesh`, `mesh_gates`
runs through `pipeline/mesh_finish.py step <clean_mesh|decimate|shape_gate>`: **mesh_finish stays the one owner of the chain**
(its config validation, the cross-check that the contract's axes and the mesh model's frame agree, and the functions that
`mesh_finish.py MESH IMAGE OUT` also calls), so the runner and the one-shot command cannot drift. The cost is one
interpreter start per stage (about a second each). The runner builds mesh_finish's one config from the resolved job
(`contract` from the gate stage's reads, `clean_mesh` and `decimate` from those stages' params, the camera from
`capture.view`, the gate block) plus the review sheet's look, which is not in the pipeline file: it comes from
`--review-sheet FILE` (any JSON file with a `review_sheet` block, such as `pipeline/pipelines/examples/finish.prop.json`) and is
required when the pipeline has a `mesh_gates` stage. Each chain process is handed the whole validated config and uses only
its own part; the config is written once per attempt as `finish-config.json`.

**Starting from saved files.** `--start-at STAGE --input STAGE/FILE=PATH ...` skips the stages before STAGE and takes their
outputs from the given files (all the later stages read, nothing else; errors name the stage and file). `attempt.json` records
`start_at` and `supplied` (path and sha256 of each file); the skipped stages have no entry in `stages`. A `retry` that would
restart before STAGE is switched off. `--gpu-wait SECONDS` sets how long to wait for the machine GPU lock.

**Versions.** `attempt.json` has a `versions` block: the Python that ran the runner and, for the tools interpreter
(`tools_python`) and each adapter a model stage uses (named by setting or adapter id, never by path), that interpreter's Python and the versions of the packages the
pipeline uses (torch, diffusers, transformers, Pillow, numpy, scipy, trimesh, fast-simplification). It is evidence, not part
of any stage key: a new Python or package does not make a stage stale on its own (the tool's source hash, the model's weights
hash and the inputs still decide that). An interpreter that is not configured or cannot be asked is recorded as such; the
attempt still runs.

**Verdicts and retries.** A stage with a `gate` ends in `pass`, `review` or `fail` (the matte gate: pass or fail, from
`matte.json`; the shape gate: gate v2). The matte gate is judged right after the matte, so a bad cut-out fails the attempt
before any mesh time is spent.
- `fail` at the stage with a `retry` block, or at any stage from `restart_at` up to it (a chain stage that cannot finish its
  work, such as a mesh with no faces, counts as a `fail`), restarts at `retry.restart_at` with the seed moved by
  `retry.seed_step`, up to `retry.max` extra tries. Stages before `restart_at` are reused. Stages with a seed (`concept`,
  `mesh`) use the base seed before `restart_at` and `seed + try x seed_step` from it; the per-try seed is in the stage key.
- `review` is not retried unless `retry.on` lists it. The attempt ends `review`: nothing is written to `--final-dir`, a person
  looks at the sheet.
- When the tries are used up the attempt ends `failed`, with every try's verdict, deciding measures and review sheet kept.
- Exit codes: 0 generated, 3 review, 1 failed or refused.

**The attempt.** `attempts/<utc>-<id>/attempt.json` holds `status` (`generated`, `review`, `failed`), the resolved job,
`sources`, `models` (per stage: the model identity, and for the gate the frame and sheet-look hashes), `stages`, `tries`, and,
for a stop, `verdict` and `not_run`. A retried stage's folder is `<stage id>.try<k>`; `stages` is keyed by folder name.
- Each `stages.<folder>` has `stage`, `tool`, `key`, `key_inputs`, `seed` (null for a stage without one), `model` (for a model
  stage the adapter identity: id, kind, command-template hash, program-file hashes, weights hash), `model_reported` (what the
  adapter wrote in `identity.json`, when it did), `tool_version`
  (the hash of the tool's source files: the `sources` list of that tool in `pipeline_file.TOOLS`, the one place), `outputs`
  (sha256 per file, so the review sheet is listed), `timing`, `reused`, `reused_from` and, for a gate stage, `gate`
  (`verdict`, `reasons`, `measures`). `timing` has `seconds` (0.0 when reused) and, where the tool allows, `load_seconds` and
  `generate_seconds` (from the timing lines an adapter may print: [adapters](adapters.md), "Timing") and `peak_rss_bytes`
  for the two models (the largest child process so far in this run, a high-water mark, so a later model stage cannot report
  less than an earlier one).
- Each `tries[]` has `try`, `seed`, `stage` (the gate that decided), `verdict`, `reasons`, `deciding` (the measures that are
  not a plain pass, with value, limit, margin and outcome), `seconds` (the stages run in that try), `stages` (stage id to
  folder) and `review_sheet` (path relative to `--out-root`, or null when no sheet could be made).

**Reuse** works as for images, extended to every stage: a stage is reused from an earlier attempt when its full key matches
and its recorded outputs still hash the same. A rerun of an unchanged job makes nothing, and neither does a rerun after a
failed first try (every try's stages are found by their keys). The chain stages' keys are those of their tool sources, their
`key_inputs` and their input files; the gate's also holds the hash of the frame it looks through (from the `clean_mesh`
params) and of the sheet's look.

**The sidecar.** For a `generated` attempt with `--final-dir` the runner copies the final file to
`<final-dir>/<style id>/<subject id>.<ext>` (the last image, or the mesh the last gate passed) and writes
`<subject id>.source.json` beside it, the icon sidecar's shape: `asset`, `subject`, `motif`, `style` (id, flattened hash,
chain), `style_reads`, `pipeline`, `contract`, `seed`, `run_id`, `attempt`, `models`, `stages` (key, key_inputs, reused,
reused_from; the last try's for a retried stage) and the file under `image` or, for a mesh, `mesh` (`path`, `sha256`). A mesh
sidecar adds `verdict` (`stage`, `try`, `seed`, `verdict`, `reasons`, `deciding`) and `review_sheet`, the sheet's path
relative to the out-root. Paths in it are relative.

## Examples
- `pipeline/pipelines/examples/prop.pipeline.json`: the example above.
- `pipeline/pipelines/examples/concept.pipeline.json` (one concept image) and `pipeline/pipelines/examples/mesh.pipeline.json` (concept,
  tidy, matte and a rough mesh with no finishing chain): the two smallest pipelines the server offers
  (`server/authoring/offered.json`), beside `prop`, `character`, `icon` and `head`.
- `pipeline/pipelines/examples/icon.pipeline.json`: concept, then `normalize_image`, no mesh, a `chroma_key`
  background (magenta) and no `view`. The background carries real chroma settings (below), so the
  `normalize_image` stage can key it out; the settings were chosen to track `pipeline/icon_batch.py`'s key
  (see [normalisers](normalisers.md), "Matching the icon routine"). It fits 224 pixels in a 256 canvas
  (`canvas_size` 256, `margin` 16 here). Whether the runner passes a stage's `capture.background` on to the
  tool is the runner's job, not this loader's.
- `pipeline/pipelines/head.json`: Concept bust, `crop_image`, matte (`allow_border`), mesh,
  `colour_head`, then the same clean, decimate and gate v2 chain as props, with the head's camera ranges
  and no `retry`. It is a real pipeline (`pipeline/pipelines/`), not an example, and it names no game or look: see
  [head pipeline](head_pipeline.md), which also covers the two head tools, running from saved inputs, the seed
  batch and the one-owner GPU lock.

## What each normaliser config becomes
| Standalone config file | In a pipeline file |
|---|---|
| normalize_image: `background_tolerance` (or `background`), `background_color` | `capture.background` (read, not repeated); `background_color`, the colour under alpha 0, is not in `capture.background` and is the runner's to supply |
| normalize_image: `canvas_size`, `margin`, `output_mode` | that stage's `params` |
| normalize_mesh: `up_axis`, `front_axis`, `target_size`, `scale_axis` | the `contract` for the kind (read) |
| normalize_mesh: `orientation` | that stage's `params.orientation`, the generator's fixed frame `{"view": ...}` (a model's frame is fixed, so it is never searched). The gate reads the same frame from this stage |
| normalize_mesh: `weld_distance_share`, `small_piece_area_share` | that stage's `params` |
| decimate_mesh: `face_budget` | the `contract` for the kind (one owner; the gate reads the same value) |
| decimate_mesh: `preserve_topology` | that stage's `params` |

The standalone scripts keep working with a config file; the runner builds that config from the
pipeline file.
