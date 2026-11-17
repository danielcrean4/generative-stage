# Export bundle

An export bundle is how a project's content leaves the tool: a folder (or a zip of it) holding
the entities, their links and the asset files a person chose, in a form any engine or game can
read without the tool. The tool does not know who reads it; a game that needs its own data shapes
puts an adapter between the bundle and its files.

```
bundle/
  manifest.json                          what the bundle holds
  assets/<kind>/<entity id>/<slot><ext>  each chosen asset, copied byte for byte
```

`<ext>` keeps the candidate's own extension: `.glb` (glTF binary) for 3D models, `.png` for
images. `<slot>` is the choice's slot (`main` unless the person chose another, such as `icon`).

## The manifest

`manifest.json` is checked against `export/manifest.schema.json` (JSON Schema 2020-12, shipped
with the tool) before anything is written. `format` is `generative-stage-bundle`.

```json
{
  "format": "generative-stage-bundle",
  "format_version": 1,
  "project": {"slug": "sample-project", "name": "Sample Project"},
  "selection": {"kinds": [], "tags": ["outdoor"], "since": null},
  "kinds": [{"id": "prop", "label": "Prop", "plural_label": "Props", "title_field": "name",
             "brief_field": "brief", "tags_field": "tags", "icon": "category",
             "schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}],
  "link_types": [{"id": "found_in", "label": "found in", "inverse_label": "holds",
                  "source_kinds": ["prop"], "target_kinds": ["setting"]}],
  "entities": [{
    "id": "e7c1...", "kind": "prop", "revision": 3, "title": "Key",
    "data": {"name": "Key", "brief": "Opens the storage room.", "tags": ["outdoor", "metal"]},
    "assets": {"main": {
      "path": "assets/prop/e7c1.../main.glb", "media_type": "model/gltf-binary",
      "sha256": "9f2b...", "bytes": 48213,
      "provenance": {"run_id": "run-key", "candidate": "attempts/20261101T000000Z-aaaa0001/mesh/mesh.glb",
                     "attempt": "20261101T000000Z-aaaa0001", "stage": "mesh",
                     "entity_revision": 3, "chosen_at": "2026-11-01T10:00:00Z",
                     "prompt": "key, white background", "seed": 12,
                     "models": {"mesh": {"model": "standin-mesh", "weights_sha256": "cdcd..."}}}}}
  }],
  "links": [{"id": "l3a0...", "type": "found_in", "source": "e7c1...", "target": "a41d..."}]
}
```

- **kinds** and **link_types** are the project's own, with each kind's full JSON Schema, so a
  reader can check `data` without the project folder.
- **entities** are the live (not archived) entities the selection picked, sorted by id. `data`
  is the entity's data at `revision`; `title` comes from the kind's `title_field`.
- **assets** has one entry per slot with a current choice. `provenance` says where the file came
  from: the run and candidate, and, when the run's attempt record has them, the attempt and stage,
  the prompt (the stage's own, else the one that drew the image the stage worked from), the seed
  and each stage's model identity (adapter id and version, model name, weight hashes). Only ids,
  versions and hashes are copied: no machine path ever reaches a manifest.
- **links** are those whose two ends are both in the bundle and live.
- **removed** appears only in a changed-since bundle (below).

## Choosing what to export

- everything (the default);
- by kind (`kinds`: any of them) and by tag (`tags`: an entity with any of them); given both, an
  entity must pass each;
- **changed since an earlier bundle** (`since`): only entities that are new or have a higher
  revision than in that bundle's manifest. `selection.since` records the earlier entity revisions
  it compared against, and `removed` lists the ids that were in the earlier bundle and are now
  archived or gone.

## Guarantees

- **Deterministic.** The same project state and selection give byte-identical bundles: no export
  time is written, every list and key is sorted, and the zip has a fixed entry order and fixed
  timestamps.
- **Self-checking.** A chosen file that is missing, or a candidate reference that would leave its
  run folder (`..`, an absolute path, a symlink out), stops the export with an error naming the
  entity and slot. A bundle is only written into a missing or empty folder.

## Making one

- Command line: `uv run studio export --project <studio.project.json> --out <folder>
  [--kind K]... [--tag T]... [--since <earlier manifest.json>] [--zip <file.zip>]
  [--runs-root <folder>]` (run in `server/`). Assets are read from `--runs-root`, else the
  machine config's runs root.
- API: `POST /api/v1/projects/{slug}/exports` writes the bundle into the project's
  `exports/<export id>/` folder ([world model API](api.md#exports)).

## Reading one

`export/engines/godot_example/` is a small, engine-side example with no dependencies beyond
Python's standard library: it checks every file's hash and lays the models, images and an
`index.json` out in a folder a Godot project can load. A game with its own data shapes writes its
own reader the same way: read `manifest.json`, check `format` and `format_version`, verify each
asset's `sha256`, and never follow a path that leaves the bundle.
