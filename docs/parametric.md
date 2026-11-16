# Parametric generators

Some content is a row of numbers a game turns into geometry itself. This tool makes such rows without a model: a rules
stage draws seeded variants from a kit table, a render adapter shows each one, a measure adapter gives numbers, and gates
turn the numbers into pass, review or fail. Nothing here knows what the rows describe; a game supplies a schema, a kit
table, gates and two commands.

The example is a lamp: `examples/parametric/` holds its schema, kit table and gates, and
`python3 scripts/add_parametric_example.py PROJECT_FOLDER` adds them to a project. The stand-in render draws one bar per
numeric parameter, so the example shows the mechanism, not a lamp.

## What a game supplies

### 1. A kind schema (project data, `<schema_dir>/<kind>.schema.json`)

An ordinary kind schema ([vocabulary](vocabulary.md) and the kinds loader read it). These properties are parameters:

| In the schema | Parameter | Form |
|---|---|---|
| `type: number` or `integer` with `minimum` and `maximum` (optional `multipleOf`, `x-unit`, `default`) | a range | slider and number |
| `type: string` with `enum` | a choice | select |
| `type: boolean` | a switch | checkbox |
| `type: string` with `format: "color"` and a `#rrggbb` pattern | a colour | colour picker |

A kind with at least one bounded number is parametric: its profile gets the slider panel and its list gets "Make a batch".
Two optional features let the parameter set depend on the row (`core/parameters.py` is the owner):

- `"x-selector": "builder"` names an enum property that picks a variant. Each variant's own fields sit in
  `allOf: [{"if": {"properties": {"builder": {"const": "a"}}, "required": ["builder"]}, "then": {"properties": {...}}}]`.
  Close the schema with `unevaluatedProperties: false`.
- `"x-when": "<boolean property>"` on a property: the field applies only while that switch is true. It is hidden in the
  form, dropped from the row and never drawn by the rules stage when the switch is off.

Several tables in one game file are several kinds, one schema each.

### 2. A kit table (`<project>/parametric/<kind>.kit.json`)

```json
{"version": 1, "kind": "lamp",
 "subject_fields": ["theme", "material"],
 "rules": [{"about": "...", "when": {"theme": "modern"}, "builder": "drum",
            "ranges": {"height_cm": [60, 140]}, "choices": {"has_arm": [false]},
            "colours": {"colour": ["#f2efe6"]}}],
 "defaults": {"has_arm": false},
 "forbidden": [{"theme": "rustic", "shade": "cone"}]}
```

`subject_fields` are the fields of the subject sheet the rules read. A rule applies when every `when` field equals the
subject's. Rules apply in order and narrow each other (the intersection; an empty one is an error naming the cell).
`builder` limits the selector's variants, `ranges` narrows a number, `choices` limits an enum or a switch, `colours` a
colour. `defaults` fix a field no rule ranges. `forbidden` lists combinations never produced. The table is validated
against the schema (unknown fields, ranges outside the schema's, values not in an enum) and every problem is a line
`/pointer: message`.

### 3. Gates (`<project>/parametric/<kind>.gates.json`)

```json
{"version": 1, "kind": "lamp", "gates": [
  {"id": "not_empty", "about": "...", "measure": "ink_ratio", "min": 0.06, "verdict": "fail",
   "mutant": {"about": "...", "row": {...}}}]}
```

A gate reads one measured number, with `min`, `max` or both, and gives `fail` or `review` when it is out of range.
Each gate ships a mutant row it must fail; `param_gates.check_mutants` renders and measures each one and names a gate
whose mutant passes. A game runs it with its own adapters.

### 4. Render and measure commands (machine config only)

Entries in the machine config's `adapters` list, like any adapter ([adapters](adapters.md)); a request names them by id.

**render** (`kind: "render"`) draws one row. Placeholders: `{row}` (a JSON file holding the row), `{schema}` (the kind
schema, so a script need not hard-code field names), `{seed}`, `{output}` (`still.png`, the primary still, required),
`{out_dir}`. It may also write `still-<view>.png` beside it (front, side, back); these are listed as the tile's views.
It must write `still.png` and exit 0.

**measure** (`kind: "measure"`) measures one row. Placeholders: `{row}`, `{image}` (the still just rendered), `{schema}`,
`{seed}`, `{output}` (`measure.json`), `{out_dir}`. It writes `{"numbers": {"name": number, ...}}`; every value must be a
number. The gates' `measure` names pick from these. The game's gate numbers (poke-through counts, silhouette area, cuff
against wrist and so on) are just names in this file.

**rules** (`kind: "rules"`) is `rules-kit`, built in (`pipeline/rules_generate.py`, deterministic, no model, standard
library only, no network code). A game normally keeps it; the kind exists so a game may replace it.

All three may write `identity.json` beside their output. The stand-in pair is `adapters/standin/standin_param.py`.

## Running

`pipeline/param_run.py` runs the stages; the server wraps them:

| Route (under `/api/v1/projects/<slug>/parametric`) | What |
|---|---|
| `GET <kind>` | parameters, subject values, gates, adapters |
| `POST <kind>/preview` `{row, adapters?}` | render and measure one row (cached by content) |
| `POST <kind>/candidates` `{row}` | keep the preview as a run a record can attach and choose |
| `POST <kind>/batches` `{cross, subject?, seed, count, adapters?}` | rules, then render and measure each row |
| `GET batches/<id>`, `PUT batches/<id>/triage` | a batch; `{tile: {verdict: keep\|fix\|improve\|remove\|null, note}}` |
| `GET batches/<id>/files/tiles/<tile>/<file>`, `GET previews/<id>/<file>` | stills |

`cross` names up to two subject fields with the values to cross; `count` rows are drawn per combination (at most 500
rows in all). Each row is checked against the kind's schema. A batch is a run folder in the runs root (`parametric.json`,
`tiles/<id>/`), so a tile's still is an ordinary candidate: kept tiles become records with `choose`, and export like any
record. The game's adapter installs exported rows into its own parameter file.
