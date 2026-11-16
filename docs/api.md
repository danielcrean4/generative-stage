# World model API (v1)

The world model holds a story's settings, characters and props as **entities** of a **kind**,
joined by typed **links**, with every change kept as a **revision**. Entities can also point at
pipeline **runs** and at the **candidate** a person chose from one. The model is the `core/`
package; this API is the HTTP surface over it, served by the main server
(`python -m authoring.server`) under the prefix `/api/v1`.

The server serves nothing else: every route outside `/api/v1` is a 404.

## Conventions

- JSON in and out (`Content-Type: application/json`). Bodies are JSON objects of at most 1 MiB.
- The server listens on 127.0.0.1 only. Each request must name the server's own address in
  `Host` (and in `Origin`, if it sends one). Each request other than GET must also send
  `X-Studio-Request: 1`. Without these the answer is 403.
- Ids of entities and links are opaque strings chosen by the server; they are never names.
- Every error has one shape. `field` is the JSON pointer of the value at fault in the request
  body (`/data/name`), `?name` for a query parameter, or `null`.

```json
{"error": {"status": 422, "code": "invalid_entity", "message": "/data/name: '' should be non-empty", "field": "/data/name"}}
```

| Status | Meaning | Codes you will see |
|---|---|---|
| 400 | the body is not JSON, or not an object | `bad_json`, `bad_request` |
| 503 | this server was started without the world model | `not_configured` |
| 403 | the Host, Origin or request header check failed | `forbidden` |
| 404 | no such route, project, kind, entity, revision, link or run | `route_not_found`, `not_found`, `unknown_kind`, `entity_not_found`, `revision_not_found`, `link_not_found`, `run_not_found`, `run_not_attached`, `note_not_found`, `attachment_not_found`, `no_vocabulary` |
| 405 | the route exists but not with this method | `method_not_allowed` |
| 409 | the request clashes with the current state | `revision_conflict`, `entity_archived`, `already_archived`, `not_archived`, `duplicate_link`, `already_attached`, `run_has_choice`, `slug_taken`, `already_registered`, `folder_not_empty` |
| 413 | the body, or an attached image, is too large | `too_large` |
| 422 | a value does not fit, or a file in the project folder is wrong | `unsupported_type`, `too_many`, `bad_notes_file`, `invalid`, `invalid_entity`, `unknown_kind`, `unknown_link_type`, `link_kinds`, `self_link`, `bad_schema`, `bad_project_file`, `bad_machine_config`, `bad_pipeline_file` |
| 500 | a fault in the server; details go to the server log only | `internal` |

## Projects

A project is a folder that a person owns. It holds:

```
sample/
  studio.project.json     the project file
  kinds/                  kinds.json, link_types.json and one JSON Schema per kind
  world.sqlite3           the project's store: entities, revisions, links, run references
```

The project file:

```json
{"slug": "sample", "name": "Sample Project", "schema_dir": "kinds", "pipelines": []}
```

| Key | Required | What it is |
|---|---|---|
| `slug` | yes | the project id: lowercase letters, digits and hyphens, starting with a letter |
| `name` | yes | the name people see |
| `schema_dir` | for the world model | the folder holding the kinds |
| `pipelines` | no | the project's default pipeline files or folders |
| `store` | no | the store file (default `world.sqlite3`); created when missing |
| `docs_roots`, `docs_files`, `source_allowlist`, `external_docs` | no | what the docs view shows ([configuration](../server/docs/configuration.md)) |

Paths are relative to the folder and must stay inside it. The projects the API knows about are
listed in a registry file (`registry_file` in the machine config, by default
`<data_dir>/registry.json`). Removing a project from the registry never deletes or changes its
folder.

### `GET /api/v1/projects`

```json
{"projects": [{"slug": "sample", "name": "Sample Project", "folder": "/work/sample",
  "project_file": "/work/sample/studio.project.json", "schema_dir": "/work/sample/kinds",
  "pipelines": [], "store": "/work/sample/world.sqlite3", "problem": null}]}
```

If a registered project can no longer be loaded (for example, its folder was moved), it is still
listed. It then has only `slug`, `project_file` and a `problem` saying what is wrong.

### `POST /api/v1/projects`

This creates a new project. `folder` must be an absolute path to a folder that is missing or
empty. The default kinds are copied into `kinds/`.

```json
{"folder": "/work/sample", "slug": "sample", "name": "Sample Project"}
```

The answer is 201 with the project, as listed above but without `problem`.

### `POST /api/v1/projects` with `project_file`

The same route opens (registers) an existing project when the body holds only `project_file`.
Its project file and kinds must load. The answer is 201 with the project.

```json
{"project_file": "/work/sample/studio.project.json"}
```

### `GET /api/v1/projects/{slug}` and `DELETE /api/v1/projects/{slug}`

`GET` returns the project. `DELETE` unregisters it and returns
`{"slug": "sample", "project_file": "...", "removed": true}`.

## Kinds

A kind is a JSON Schema (draft 2020-12) file plus a descriptor in `kinds/kinds.json`:

```json
{"kinds": [{"id": "prop", "label": "Prop", "plural_label": "Props", "schema": "prop.schema.json",
            "family": "prop", "title_field": "name", "brief_field": "brief", "icon": "category"}]}
```

| Descriptor key | What it is |
|---|---|
| `id` | lowercase letters, digits and underscores; it never changes |
| `label`, `plural_label` | the names people see |
| `schema` | the schema file's name, in the same folder |
| `title_field` | the string property that titles an entity; the schema must require it |
| `brief_field` | optional: the string property holding a short description. Leave it out for a kind with none (the API then gives `null`) |
| `tags_field` | optional, default `tags`: an array-of-strings property used for tag filtering. If the schema has no such property, the kind has no tags |
| `icon` | an icon name for the interface |
| `family` | optional: which family the kind belongs to, one of `prop`, `character`, `setting`, `script` or `stage`. The app groups kinds by family (Props, Characters, Settings, Scripts, Stages); a kind with none is listed under Other. Any other value is refused |
| `form` | optional, for a kind whose `family` is `script` only: `linear` (its lines run in order) or `branching` (choices lead to different lines). The app shows it beside the kind's name. Any other value, or a `form` on a kind of another family, is refused |

The family and form only say how the app groups and labels a kind. They change no stored data, API
path or bundle.

A new project gets four kinds:

| Kind | Fields |
|---|---|
| `setting` | `name` (required), `brief`, `tags`, `era`, `atmosphere`, `scale` (room, building, street, district, town, region, world) |
| `character` | `name` (required), `brief`, `tags`, `role`, `appearance`, `voice` |
| `prop` | `name` (required), `brief`, `tags`, `material`, `size` (pocket, hand, arm, body, large, huge), `condition` |
| `script` | `name` (required), `brief`, `tags`, `lines`: a list of lines in order, each with `speaker` (the entity id of the character who speaks), `text` and an optional `direction`. Family `script`, form `linear`; each line is a story node, so a script shows on the Scripts page |

Each takes the family of the same name.

A project adds or changes kinds by editing these files. They are read again on every request, so
an edit applies at once. A wrong file makes every request about that project answer 422
`bad_schema`, with a message naming the file and the place in it. For example:
`/work/sample/kinds/prop.schema.json: /properties/size/type: not a valid JSON Schema (draft 2020-12): 'sizeish' is not valid under any of the given schemas`.

Each schema must:
- be valid draft 2020-12 and describe an object with `properties`;
- have a title field and a brief field that are string properties, with the title field required;
- have a tags field, if any, that is an array of strings;
- use only local references (`$ref` starting with `#`). Nothing is fetched from the network or
  another file.

A kind schema may mark values as conditions, effects, rule modes or fact paths with `x-vocabulary`;
those are then checked against the project's `vocabulary.json` on every write
([condition vocabulary](vocabulary.md)). It may mark story nodes, edges and references with
`x-story`, which the [story graph](story_graph.md) reads.

### `GET /api/v1/projects/{slug}/kinds`

```json
{"kinds": [{"id": "prop", "label": "Prop", "plural_label": "Props", "icon": "category",
  "title_field": "name", "brief_field": "brief", "tags_field": "tags",
  "family": "prop", "form": null, "schema_file": "prop.schema.json", "schema": {"type": "object", "...": "..."}}]}
```

### `GET /api/v1/projects/{slug}/kinds/{kind}`

This returns one kind in the same shape.

## Entities

```json
{"id": "6f1c2d0e-0c55-4a8e-9a43-1f0c3b7d2e11", "kind": "prop", "revision": 3, "archived": false,
 "title": "Key",
 "data": {"name": "Key", "brief": "A key to the storage room.",
          "tags": ["hall"], "material": "steel"},
 "created_at": "2026-11-12T10:00:00+00:00", "updated_at": "2026-11-12T10:20:00+00:00"}
```

`data` is what the kind's schema describes. `title` is read-only and is copied from the title
field. `kind` never changes. `revision` counts every write, starting at 1.

Create, update and revert check `data` against the kind's current schema. Archive and restore
only change the `archived` flag and do not check `data` again, so editing a schema never leaves
an entity stuck. An archived entity is read-only until it is restored.

### `GET /api/v1/projects/{slug}/entities`

| Query | What it does |
|---|---|
| `kind=prop` | only this kind |
| `tag=hall` | only entities whose tags include this one exactly |
| `q=storage` | text found, ignoring case, in the title, the brief or a tag |
| `include_archived=true` | include archived entities (default `false`) |

The answer is `{"entities": [...]}`, with the most recently changed first.

### `POST /api/v1/projects/{slug}/entities`

```json
{"kind": "character", "data": {"name": "Guide", "brief": "Shows visitors around the town.", "role": "guide"}, "note": "first draft"}
```

The answer is 201 with the entity at revision 1. `note` is optional (at most 500 characters) and
is kept with the revision.

### `GET /api/v1/projects/{slug}/entities/{id}`

### `PUT /api/v1/projects/{slug}/entities/{id}`

```json
{"revision": 1, "data": {"name": "Guide", "brief": "...", "voice": "calm"}, "note": "voice"}
```

`revision` is the revision you read. If someone wrote in between, the answer is 409
`revision_conflict` and nothing changes. Reload the entity and apply your change again. `data`
replaces the whole of the old data.

### `POST .../entities/{id}/archive`, `.../restore`, `.../revert`

Archive and restore take `{"revision": 3}`. Revert takes `{"revision": 4, "to": 1}` and writes a
new revision holding revision 1's data, checked against the current schema. Each takes an
optional `note`, and each answers with the entity.

### `GET .../entities/{id}/revisions` and `GET .../entities/{id}/revisions/{n}`

```json
{"revisions": [{"entity_id": "6f1c...", "revision": 2, "archived": false,
  "data": {"name": "Key", "...": "..."}, "note": "Steel, not iron",
  "created_at": "2026-11-12T10:20:00+00:00"}]}
```

These are newest first. The second route returns one revision.

## Link types and links

Link types live in `kinds/link_types.json`:

```json
{"link_types": [{"id": "lives_in", "label": "lives in", "inverse_label": "home of",
                 "source_kinds": ["character"], "target_kinds": ["setting"]}]}
```

A new project gets `lives_in` (character to setting), `belongs_to` (prop to character),
`found_in` (prop or character to setting), `part_of` (setting to setting) and `knows`
(character to character). The file is optional. Each kind it names must exist.

### `GET /api/v1/projects/{slug}/link-types`

The answer is `{"link_types": [...]}`, in the shape above.

### `POST /api/v1/projects/{slug}/links`

```json
{"type": "belongs_to", "source": "<key id>", "target": "<guide id>"}
```

The answer is 201:
`{"id": "...", "type": "belongs_to", "source": "...", "target": "...", "created_at": "..."}`.

A link is refused when:

| Problem | Answer |
|---|---|
| the type is not declared | 422 `unknown_link_type` |
| the source or target is of a kind the type does not allow | 422 `link_kinds` |
| the source and target are the same entity | 422 `self_link` |
| the source or target does not exist | 404 `entity_not_found` |
| the source or target is archived | 409 `entity_archived` |
| the same type, source and target already exist | 409 `duplicate_link` |

### `GET /api/v1/projects/{slug}/links/{id}` and `DELETE /api/v1/projects/{slug}/links/{id}`

`DELETE` removes the link and answers with it.

### `GET .../entities/{id}/links?direction=out|in|both&include_archived=true`

Each link is listed from this entity's side. `label` is the type's label for an outgoing link
and its inverse label for an incoming one.

```json
{"links": [{"id": "...", "type": "belongs_to", "source": "<key id>",
  "target": "<guide id>", "created_at": "...", "direction": "in", "label": "owns",
  "other": {"id": "<key id>", "kind": "prop", "title": "Key", "archived": false}}]}
```

`direction` defaults to `both`. Archiving an entity keeps its links. Links whose other end is
archived are left out unless `include_archived=true`, and restoring the entity shows them again.
Entities are never deleted in this version, only archived.

## Runs and chosen candidates

An entity can point at pipeline runs and at the candidate chosen from a run. The run store
itself is not changed. `run_id` is the id of a run folder in the runs root, and the server
checks that the run exists. `candidate` is a reference into that run, such as
`concept/candidate-2.png`. Only its shape is checked: 1 to 500 characters, with no control
characters. Both records keep the entity revision they were made at.

### `GET .../entities/{id}/runs` and `POST .../entities/{id}/runs`

```json
{"run_id": "2c0eca0f-7d3e-4bb0-9c61-0d6e2f9b8a14", "note": "first concept pass"}
```

The answer is 201:
`{"entity_id": "...", "run_id": "...", "entity_revision": 2, "note": "...", "attached_at": "..."}`.
`GET` answers `{"runs": [...]}`.

### `DELETE .../entities/{id}/runs/{run_id}`

This detaches a run. It is refused (409 `run_has_choice`) if a candidate from that run has been
chosen for the entity.

### `POST .../entities/{id}/chosen`

```json
{"run_id": "2c0eca0f-...", "candidate": "concept/candidate-2.png", "slot": "main", "note": "the second one"}
```

`slot` is optional (default `main`; lowercase letters, digits and underscores), so an entity can
have one choice per slot, such as `main` and `mesh`. Choosing also attaches the run. Choices are
never overwritten: the newest choice in a slot is the current one.

### `GET .../entities/{id}/chosen` and `GET .../entities/{id}/choices`

`chosen` returns the current choice per slot:
`{"chosen": {"main": {"entity_id": "...", "slot": "main", "run_id": "...", "candidate": "...", "entity_revision": 2, "note": "...", "chosen_at": "..."}}}`.
`choices` returns every choice ever made, newest first: `{"choices": [...]}`.

### `GET .../entities/{id}/chosen/{slot}/file` and `GET .../entities/{id}/runs/{run_id}/files/{candidate}`

These send the file of a candidate so a page can show it. The first is the entity's current
choice in a slot (404 `no_choice` when nothing is chosen there). The second is any candidate of
a run attached to the entity, named as in `POST .../chosen` (for example
`attempts/<attempt>/concept/final.png`); a run that is not attached answers 404
`run_not_attached`.

The file is found by the rules of the read-only run view: every path segment is plain (no `..`,
no absolute path, nothing encoded that decodes to one) and the file, with symlinks followed, must
stay inside the run folder. A missing file, a path that leaves the run and a file type the server
does not send (it sends png, jpg, jpeg, webp, gif, glb, json, log and txt) all answer 404 `candidate_not_found`.
Images are sent inline with their own content type; every other type is sent as a download.
Replies carry `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`. Both routes are
`GET` only.

### `GET .../entities/{id}/runs/{run_id}/trace`

One attempt of a run attached to the entity, stage by stage, as one JSON object (a run that is
not attached answers 404 `run_not_attached`). `?attempt=<attempt id>` picks an attempt; without it
the newest is used. An unknown run or attempt answers 404 `trace_not_found`. `GET` only.

Top level: `run_id`, `attempt_id`, `attempts` (every attempt: `attempt_id`, `status`, `started`),
`status` (`generated`, `review`, `failed`, `interrupted`, `running`), `error`, `problem` (why
`attempt.json` could not be read), `started`, `finished`, `seconds`, `seed`, `sources` (the style
pack and other shared inputs as recorded), `tries`, `entity` (`id`, `kind`, `title`), `candidates`
(the job's candidates: `candidate`, `verdict`; empty when the run has no job), `chosen` (the
entity's current choice per slot, as `GET .../chosen`) and `stages`.

Each stage, in the order it ran, then planned stages that never started:

| Field | Meaning |
|---|---|
| `id`, `folder`, `retry`, `label`, `tool` | The stage id, its folder in the attempt (`mesh.try1` for a retry), which retry it is (0 for the first try), the pipeline file's label and the tool |
| `status` | `completed`, `supplied` (a saved file, such as a picture already chosen, stood in for it; it did not run and has no prompt), `errored`, `running` or `not_run` |
| `error` | The error text of an `errored` stage: the tool's reasons, or the attempt's error when the attempt stopped inside the stage |
| `reused`, `reused_from` | Whether the stage's outputs came from an earlier attempt, and which |
| `seconds`, `started`, `finished`, `times` | The recorded duration. Start and end are worked out from the attempt's start and each stage's duration (the runner records no per-stage clock); `times` says so, or is null when they could not be |
| `seed`, `key` | The seed used and the cache key |
| `adapter` | Identity as recorded: `adapter_id`, `adapter_version`, `model`/`reported_model`, hashes. Never a path |
| `prompt`, `negative`, `params`, `reads` | The exact prompt (null for a stage that has none), the settings the stage ran with and the shared values it read |
| `prompt_parts`, `negative_parts` | The prompt and the negative prompt as the ordered pieces they were made from, or null for an attempt that did not record them, or whose pieces do not join to exactly the prompt. Each piece is `{text, start, end, source}`; `source` is `{kind, id, key, version, sha256, link}` ([pipeline files](pipeline_files.md), "Resolve and the prompt"). `link` says where to read the source, or is null: `{type: "style" or "motif", id, changed}` for a source page (`changed` is true when the file has changed since the run read it) and `{type: "entity", id, kind}` for the subject text, which is the description the run was started with |
| `inputs` | `[{name, from, sha256}]` |
| `gates` | `[{file, outcome, reasons, measures, limits}]`; `outcome` is `pass`, `review`, `fail` or null; `measures` and `limits` are `[{name, value}]` |
| `files` | `[{name, kind, media_type, size, candidate, url}]`; `kind` is `image`, `model` or `other`; `candidate` is the path inside the run that `POST .../chosen` takes; `url` serves it through the candidate-file route above |

### `GET /api/v1/projects/{slug}/statistics`

Figures for the project's runs: those attached to its entities and those its jobs made. A "run"
here is one attempt. `GET` only.

```json
{
  "runs": {"total": 2, "completed": 1, "errored": 1, "other": 0, "seconds": 270.0},
  "by_day": [{"day": "2026-11-05", "completed": 1, "errored": 0, "other": 0}],
  "by_stage": [{"stage": "concept", "ran": 2, "reused": 0, "errored": 0,
                "total_seconds": 105.0, "average_seconds": 52.5, "slowest_seconds": 60.0}],
  "assets": {"candidates": 4, "choices": 3, "chosen_slots": 1, "entities": 2, "entities_with_choice": 1}
}
```

`completed` is an attempt that finished (`generated`, or `review` when a gate asked for a person);
`errored` is `failed` or `interrupted`; `other` is still running or without a readable record.
`by_day` uses the UTC day the attempt started. `by_stage` leaves reused stages out of the time
figures and counts them in `reused`. In `assets`, `candidates` is what jobs made, `choices` every
choice ever made and `chosen_slots` the choices in force now.

## Sources

The shared files a prompt is made from: style packs, motifs and contracts, in the data folders of the offered
pipelines. They belong to the tool (they live under `pipeline/pipelines/` in its repository), so these routes only read.
A source's id is `<set>.<name>`, where the set is its data folder's name (`prop.clay`, `head.storybook`): two sets can
each hold a style or motif of the same name with different words. A contract has no name and is `<set>.contract`.

### `GET /api/v1/projects/{slug}/sources`

`{"sources": [{type, id, name, set, pipelines}]}`, every source, by type (`style`, `motif`, `contract`).

### `GET /api/v1/projects/{slug}/sources/{type}/{id}`

One source: `location` (its file, relative to the tool's repository), `editable` (always false), `sha256`, `content` (the
file), `extends` (a style's parent packs, nearest first), `texts` (`[{label, key, text, from}]`: the words it supplies to a
prompt; `from` is the source that set the key, a parent for an inherited one; empty for a contract, whose `note` says it
adds no words), `pipelines` (`[{id, name}]` that can read it) and `used_by`: the runs attached to this project's records
whose newest attempt read it, newest first, each `{entity, run_id, attempt_id, started, status, changed, thumbnail}`
(`changed`: the run read an older version of the file; `thumbnail`: a URL of the run's first picture). An unknown source
answers 404 `source_not_found`. `GET` only.

### `GET .../entities/{id}/sources`

What the record's last run read: `{run_id, attempt_id, sources: [{type, id, name, changed}]}` for the newest attached run
that recorded sources (`style`, `motif`, `contract` and the `pipeline` whose capture words it used; `id` is null when the
file is gone or the source has no page). All null and empty when no run has been made.

## Vocabulary

`GET`, `PUT .../vocabulary` and `POST .../vocabulary/check` read, replace and check against the
project's condition vocabulary. They are described in [condition vocabulary](vocabulary.md).

## Story graph

`GET .../story` and `GET .../story?entity=<id>` give the project's story graph, read from its
entities, links and `x-story` marks. They are described in [story graph](story_graph.md).

## Notes

A note is free context about an entity: text, a pin, mentions of other entities and up to eight
images. Notes are not revisions. Posting, editing or deleting one never changes the entity, its
revision or its history, so there is no revision to send and no conflict to meet; an archived
entity takes notes too. Notes stay inside the tool (they are not in export bundles) and are not
read by generation.

They are plain files in the project folder: `notes/<entity id>/notes.json`
(`{"format": "notes-1", "notes": [...]}`, oldest first) and `notes/<entity id>/files/` for images.

A note:

```json
{"id": "...", "created_at": "...", "updated_at": "...", "text": "the bench should be lower",
 "pinned": false, "mentions": [{"kind": "character", "id": "..."}],
 "attachments": [{"id": "...", "name": "shot.png", "media_type": "image/png", "size": 1234}]}
```

### `GET .../entities/{id}/notes` and `POST .../entities/{id}/notes`

`GET` returns `{"notes": [...]}`, newest first. `POST` takes `{"text": "...", "pinned": false,
"mentions": [{"id": "..."}]}` and answers 201 with the note. `text` is at most 5000 characters
and may be empty (a note that is only images is made by posting an empty text, then attaching).
Mentions are the `@kind/id` references in the text that name a real entity of that kind, plus any
entity named in `mentions` (an unknown one answers 404 `entity_not_found`). An unknown entity
answers 404 `entity_not_found`.

### `PATCH .../entities/{id}/notes/{note_id}` and `DELETE .../entities/{id}/notes/{note_id}`

`PATCH` changes `text` and/or `pinned` (send either or both) and answers with the note; changing
the text reads its mentions again. `DELETE` removes the note and its image files. An unknown note
answers 404 `note_not_found`.

### `POST .../notes/{note_id}/attachments` and `GET .../notes/{note_id}/attachments/{attachment_id}`

`POST` takes the image itself as the request body (not JSON), with `Content-Type` of
`image/png`, `image/jpeg` or `image/webp`, and the file name in an `X-File-Name` header. The
bytes must be that image type (checked by their first bytes) and at most 5 MiB. It answers 201
with the attachment. A wrong type or bytes answer 422 `unsupported_type`, a ninth image 422
`too_many`, an oversize image 413 `too_large`.

`GET` sends the image inline with its own content type. The attachment id is looked up in the
note's record, never joined into a path, and the file must stay inside the entity's notes folder;
anything else is 404 `attachment_not_found`.

## Pipelines and adapters

### `GET /api/v1/projects/{slug}/pipelines` and `GET /api/v1/pipelines`

The pipelines a job can run: the entries of `server/authoring/offered.json`, each a pipeline file of this
repository. Add `?entity_kind=prop` to list only those that serve that kind of record. The project route applies the
project's `generation.json` (below); `GET /api/v1/pipelines`, which is not inside a project, answers with the tool's
defaults alone.

```json
{"pipelines": [{"id": "prop", "name": "Props from a concept image", "kind": "prop", "entity_kinds": ["prop"],
  "stages": [{"id": "concept", "label": "Concept image", "tool": "concept", "adapter_kind": "image"},
             {"id": "matte", "label": "Find the subject", "tool": "matte", "adapter_kind": null}],
  "choices": {"style": {"label": "Style", "options": ["clay", "vinyl_toy"], "default": "clay"},
              "seed": {"label": "Seed", "min": 0, "max": 4294967295, "default": 1}}}]}
```

`entity_kinds` is the tool's default list (`null`: every kind of record). `adapter_kind` is the kind of adapter a
stage runs (`image`, `image-to-mesh`, `material`, `rig`, `motion`), or `null` for a stage that runs no model. `choices`
are the pipeline file's declared run choices ([pipeline files](pipeline_files.md), "Choices").

**Which pipelines serve a kind (`generation.json`).** A project may hold `generation.json` in its folder:

```json
{"version": 1, "serves": {"setting": ["concept", "icon"], "prop": ["prop", "mesh"]}}
```

A kind listed under `serves` is served by exactly the pipelines listed (in that order, ids the tool offers), in place
of the tool's defaults for that kind; a kind that is not listed keeps the defaults, and a project with no file keeps
the defaults for every kind. A wrong file (not JSON, an unknown pipeline id, a list that is not a list) answers 422
`bad_generation_file` from the pipeline list and from starting a job, naming the file and the key.

### `GET /api/v1/adapters`

The adapters configured on this computer, from the pipeline's machine config
([adapters](adapters.md)): `id`, `kind`, `description`, `default` (the default of its kind),
`runnable` (whether this computer meets its requirements) and `unmet` (one sentence per gap).
A command, an environment variable, a folder or a model file is never part of the answer.

## Generation jobs

A job asks for generation for one entity. The server queues it and a worker runs it: every job is a pipeline file
of this repository run by `pipeline/pipeline_run.py` on adapters from the pipeline's machine config
([adapters](adapters.md)). Jobs are kept per project, in `jobs.sqlite3` beside the store. A job row an earlier
version made (`asset_job`, `icon_job`, `heads_bodies_job`) is still listed with its candidates and runs; it is not
offered and cannot be run again.

### `POST .../entities/{id}/jobs`

```json
{"pipeline": "prop", "prompt": "a brass key",
 "adapters": {"image": "standin-image", "image-to-mesh": "standin-mesh"},
 "choices": {"style": "vinyl_toy", "motif": "plain", "seed": 11, "candidates": 2}}
```

`pipeline` is required, and so is `prompt` unless `choices.start_image` is given (then the record's title is the subject
text). `pipeline` is an id from `GET .../pipelines` that serves the record's kind in this project.
`adapters` is optional: a map from an adapter kind the pipeline runs to an adapter id from `GET /api/v1/adapters`
of that kind; a kind left out uses this computer's default for it. `choices` is optional: the pipeline's own
declared choices by name, each value one of its options or inside its range; a choice left out takes the
pipeline's default. `hair_colour` is a `#rrggbb` from the head pipeline's options; unset by default. `start_image` is a slot (the 3D
pipeline accepts `main`) of the record that has a chosen picture: the run starts at the stage the pipeline file names with that
picture standing in for the stage before it, so a 3D model can be made from the picture a person already chose
(refused with 422 `/choices/start_image` when nothing is chosen in the slot, the file is gone or it is not a `.png`; the
recipe keeps the run and candidate it resolved to, never a path). A request never holds a command, a path or an environment; any other key, a choice the
pipeline does not declare, an out-of-range value, an adapter id that is not configured or is of the wrong kind
is refused with 422 and a field pointer such as `/choices/seed` ([adapters](adapters.md), "Trust rule").

The job's recipe keeps the prompt, the adapters named and every choice with its value, so a later reader sees
what the run used. `candidates: n` runs the pipeline for `n` seeds, `seed`, `seed + 1`, and so on, in one process
(`pipeline_run.py --candidates n`) that takes the machine GPU lock once and holds it until the last seed ends; each seed
is its own attempt. A succeeded run offers, for every attempt that produced files, the first concept
image (unless the finished file is itself a picture) and the finished file (`final/seed-<n>/...`) as candidates;
a run with no file fails and its `log_tail` says why (a failed gate names the measure). The job records the
entity's current revision and data. The answer is 202 with the job and its first run. When a run ends it is attached to
the entity (see Runs and chosen candidates): a succeeded run so a person can choose a candidate from it, a failed one
(when it got as far as an attempt) so its trace shows where it stopped.

### `GET .../entities/{id}/jobs` and `GET .../jobs/{job_id}`

`{"jobs": [...]}` for an entity, or one job: `{"job": {...}, "runs": [...], "candidates": [...], "attached": true}`
(`attached`: the run is attached to the entity, so `GET .../runs/{run}/trace` answers).
Each candidate has `candidate` (its path inside the run, as `chosen` takes it) and `verdict`:
`pass`, `review` or `fail`, the worst gate report of the stage that made it, or `null` when the
candidate has no stage report (it is not under `attempts/<attempt>/<stage>/`).
A run has a `status` and a `log_tail` (the end of its log).

## Exports

An export writes the project's live entities, links and chosen assets as a bundle
([export bundle](export_bundle.md)) under `<project folder>/exports/<export id>/`. The id is the
first 16 hex digits of the manifest's sha256, so the same state and selection always give the
same id.

### `POST .../exports`

`{"kinds": ["prop"], "tags": ["outdoor"], "since": "<earlier export id>"}`, every key optional (an
empty body exports everything). The answer is 201:
`{"id": "...", "entities": 2, "links": 1, "assets": 1, "removed": [...]}` (`removed` only with
`since`: ids archived or gone since that export).

### `GET .../exports`, `GET .../exports/{id}` and `GET .../exports/{id}/bundle.zip`

The list of exports (`{"exports": [{"id": ..., ...}]}`), one export's `manifest.json`, or the
bundle as a zip (`application/zip`).

