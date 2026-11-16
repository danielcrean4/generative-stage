# Run view server

A second, read-only Studio server that shows what each pipeline run did, step by step. It reads
the folders the forge already writes under the runs root (`runs_root` in the
[machine config](configuration.md)) and changes nothing, so it is safe to start, stop and restart
at any time. The main server is not involved.

## Start it

```sh
cd server
uv run python -m authoring.readonly_server --port 8781
```

Port 8781 is the default. It listens on 127.0.0.1 only and applies the same Host and Origin
checks as the main Studio, so a web page from another site cannot read through it. It stops with
an error if `runs_root` is not a folder. Only GET works; any other method answers 405.

## What it reads

```
<runs_root>/<run id>/latest.json                   points at the newest attempt
<runs_root>/<run id>/attempts/<attempt id>/attempt.json
<runs_root>/<run id>/attempts/<attempt id>/<stage>/   stage.json, reports, outputs, step.log
<runs_root>/<run id>/<file>                        a run made by an older version of the tool may keep files here
```

The step names are not listed in the server. They come from `attempt.json` (in the order the
attempt ran them) plus any stage folder the attempt did not record, such as a stage that failed.
When the pipeline file exists, it becomes the one place that names steps (D26).

## Routes

Errors are JSON `{"error": "..."}`: 404 for anything unknown or not allowed, 400 for a bad
`limit`, 403 for a bad Host or Origin, 405 for a method other than GET, 500 if a file on disk is
not valid JSON (the message names the file).

### `GET /api/ro/health`

```json
{"ok": true, "runs_root": "/home/me/.local/share/generative-stage/asset-runs"}
```

### `GET /api/ro/runs?limit=50`

The most recently changed run folders first (limit 1 to 500). Each row summarises its latest
attempt. A run with no attempts (an icon run) has `null` status and an empty `stages` list.

```json
{"runs": [{"run_id": "2c0eca0f-...", "latest_attempt_id": "20261111T020834Z-d595dbad",
  "status": "generated", "error": null, "started": "2026-11-11T02:08:34Z",
  "finished": "2026-11-11T02:09:13Z", "stages": ["concept", "matte"],
  "modified": "2026-11-11T02:09:13Z"}], "total": 129, "limit": 50}
```

### `GET /api/ro/runs/{run_id}`

Every attempt, newest first, and the extra files kept at the run root.

```json
{"run_id": "52772873-...", "latest_attempt_id": "20261110T125903Z-06ce31ad",
 "attempts": [{"attempt_id": "20261110T125903Z-06ce31ad", "status": "failed",
   "error": "mesh failed the shape gate after 3 tries ...", "started": "...", "finished": "...",
   "seed": 51, "stages": ["concept", "matte", "mesh"]}],
 "root_files": [{"name": "bust_raw.png", "size": 123456, "media_type": "image/png",
   "url": "/api/ro/runs/52772873-.../files/_root/bust_raw.png"}]}
```

An attempt whose `attempt.json` is missing or unreadable (still running, or interrupted) shows
`null` status and a `problem` text.

### `GET /api/ro/runs/{run_id}/attempts/{attempt_id}`

The step-by-step view: attempt status, error, times, seed, the attempt recipe, and `stages` in
run order. Each stage has:

| Key | Meaning |
|---|---|
| `stage` | the stage id (folder name) |
| `recorded` | false if `attempt.json` does not list it (a stage that failed part way) |
| `cache_key`, `reused` | from `attempt.json`; `reused` true means the cached output was used |
| `status` | set by the forge for a stage that did not succeed, such as `gate_failed` |
| `seed`, `seed_used`, `tries` | the stage seed; the seed of the passing mesh try; every mesh try with its report path, pass flag and reasons |
| `recipe` | `recipe` from `stage.json`, including the resolved prompt for a concept stage (`settings.prompt`). `versions` is left out and a model's file hash table is replaced by `file_count` |
| `gates` | one entry per report found: `image-validation.json`, `matte.json`, `mesh-validation.json` and each try's report. Each has `file`, `url`, `passed`, `reasons`, `measures`, `thresholds` |
| `files` | every servable file in the stage folder (two levels deep): `name`, `size`, `media_type`, `url` |

Each gate also has `verdict`: the report's own word (`pass`, `review`, `fail` from gate v2), or null for an older report. A `review` is not a failure (`passed` is false, a person looks at the review sheet, which is an ordinary image in the stage's files).

An attempt written by the pipeline runner (`pipeline_run.py`) has its `seed` at the top, a stage per folder, and its stages are shown in the order of its `resolved_job` (the file is saved with sorted keys).

`passed` is `true` or `false` when the report says so. The image check
(`image-validation.json`) lists the images it opened and has no verdict of its own, so its
`passed` is `null`.

```json
{"stage": "matte", "recorded": true, "cache_key": "86871068...", "reused": false, "seed": 337,
 "recipe": {"stage": "matte", "seed": 337, "settings": {"tolerance": 236}},
 "gates": [{"file": "matte.json", "passed": true, "reasons": [],
   "measures": {"subject_share": 0.2895, "component_count": 15}, "thresholds": null,
   "url": ".../files/matte/matte.json"}],
 "files": [{"name": "matte.png", "size": 20511, "media_type": "image/png",
   "url": "/api/ro/runs/2c0eca0f-.../attempts/20261111T020834Z-d595dbad/files/matte/matte.png"}]}
```

### `GET /api/ro/runs/{run_id}/attempts/{attempt_id}/files/{stage}/{path}`

The file itself. Allowed types: png, jpg, gif, glb, json, log, txt, sent with their own media
type and `X-Content-Type-Options: nosniff`. A `.log` larger than 200 KB is sent as its last
200 KB, with the headers `X-Truncated` (says so) and `X-Total-Size`. `path` may go one folder
down (`try-1/mesh.glb`).

### `GET /api/ro/runs/{run_id}/files/_root/{name}`

A file kept at the run root (`bust_raw.png`, `icon.png`, `icon.source.json`). The same file is
reachable at `/attempts/{attempt_id}/files/_root/{name}`. `latest.json` is not served.

## What is refused

Run, attempt and stage ids and every path segment must match a strict pattern (letters, digits,
`_`, `-`, and `.` inside file names; no leading dot, no empty segment). Every file is resolved,
symlinks included, and must stay inside its run folder, so `..`, encoded `%2e%2e`, absolute
paths and a symlink pointing outside the runs root all answer 404. Symlinked run folders are not
runs. There is no directory listing apart from the shapes above, and the forge's `cache/` folder
is not exposed.

## Runs view in the Studio UI

With the run view server on 8781 and the UI dev server running (`ng serve` in `ui/`), open `/runs` or click **Runs** in the left nav. The dev proxy sends `/api/ro` to 8781 and everything else under `/api` to 8780.

- `/runs`: recent runs, newest first, with a limit selector and a filter on run id.
- `/runs/<run id>`: that run's attempts and the files kept at its root.
- `/runs/<run id>/attempts/<attempt id>`: one panel per step, in the order the server returns them, with the recipe (prompt first), gate reports, tries and output files (images, 3D preview, logs).

If the server is down the pages say so and show the start command above.

## What it will be used for

The Studio's run view (D26 slice 4): the UI shows each stage of an attempt with its images,
3D preview, log, gate measures and verdict. The routes stay stable while the UI is built.
