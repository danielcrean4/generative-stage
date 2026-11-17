# Configuration: machine config and project files

The tool reads two kinds of config. Neither is needed to start it.

| File | Describes | Lives in |
|---|---|---|
| Machine config (`server.json`) | this computer: the tool's working folders | `~/.config/generative-stage/server.json` |
| Project file (`studio.project.json`) | one project: its kinds, store, pipelines and docs | the project's folder |

The tool's code names no project and no project path. Projects are listed in the registry file
and opened through the world-model API ([world model API](../../docs/api.md)).

## Machine config

The tool looks for the file in this order and uses the first one it finds:

1. the path in the environment variable `GENSTAGE_SERVER_CONFIG` (the file must exist);
2. `~/.config/generative-stage/server.json`;
3. built-in defaults.

The tool never creates the file. Every key is optional; a key you leave out keeps its default.
Paths may start with `~`; a relative path is taken from the folder holding the file.

```json
{ "data_dir": "~/studio-data" }
```

| Key | What it is | Default |
|---|---|---|
| `data_dir` | the tool's working folder | `~/.local/share/generative-stage` |
| `runs_root` | where each generation run keeps its files | `<data_dir>/asset-runs` |
| `registry_file` | the list of world-model projects that the `/api/v1` routes create, open and remove; the server writes it, people need not | `<data_dir>/registry.json` |

If you set `data_dir` but not `runs_root` or `registry_file`, those follow `data_dir`.
The exact defaults are in `server/authoring/machine_config.py`. The keys of the pipeline's own machine
settings that are paths (`gpu_lock`, `tools_python`, `icon_dir`; [machine settings](../../docs/machine_settings.md))
are accepted and checked here but not used, so one file can serve both.

**Retired keys.** `projects`, `default_project` and `legacy_db_project` belonged to an earlier
version that kept records in its own store; `forge_path` named the separate forge
checkout that ran generation, and `staging_root` the scratch folder it was handed. Generation now runs the pipelines
in this repository on those adapters, so neither is used. A file shared with an earlier version may still hold any
of them: they are accepted and ignored, and the server prints one "no longer used" note for each at start. Remove
them when convenient; nothing else changes.

### What counts as an error

The file is checked once, when it loads. The error names the file and the key.

- A key that is not in the table above or the retired list (a typo shows up here).
- A value of the wrong type: paths are non-empty strings.
- A file that is not a JSON object, or not valid JSON.
- `GENSTAGE_SERVER_CONFIG` naming a file that does not exist.

What a run can use (models, interpreters, the GPU lock) is in the pipeline's machine config, not here
([adapters](../../docs/adapters.md), [machine settings](../../docs/machine_settings.md)). The server starts and serves
the world model without it; a run whose adapter this computer cannot run fails with a log that says why.

## Project file

`studio.project.json` sits in the project's folder. Paths in it are relative to that folder and
must stay inside it.

| Key | Required | What it is |
|---|---|---|
| `slug` | yes | short id: lowercase letters, digits and hyphens, starting with a letter |
| `name` | yes | the name people see |
| `schema_dir` | for the world model | the folder of kinds (`kinds.json`, one JSON Schema per kind, `link_types.json`) |
| `pipelines` | no | list of pipeline files or folders |
| `store` | no | the world model's store file (default `world.sqlite3`) |
| `docs_roots` | no | list of folders of markdown docs the docs view shows |
| `docs_files` | no | list of single markdown files that are docs too, such as `README.md` (each must be an existing `.md` file) |
| `source_allowlist` | no | list of code folders the docs view may show read-only |
| `external_docs` | no | list of absolute paths of markdown folders outside the project, shown read-only in the docs view |

A project folder may also hold `generation.json`, which says which of the tool's pipelines serve which kinds of record
(`{"version": 1, "serves": {"<kind>": ["<pipeline id>", ...]}}`). It is not a key of the project file; without it the tool's
defaults in `server/authoring/offered.json` apply ([API](../../docs/api.md), "Pipelines and adapters").

`external_docs` is the one key that takes absolute paths, because `docs_roots` must stay inside
the project folder. Each path must be an existing folder (not in `.git`), or the project file is
refused. Its `.md` files appear in the docs view under `external/<folder name>/`; two folders with
the same name get `-2`, `-3`. They are never writable, and their files cannot be opened as source.

Any other key is refused, naming the file and the key. Jobs a project starts are kept beside its
store in `jobs.sqlite3`.

## Registering a project

Create or open a project through the API (`POST /api/v1/projects`) or the Projects page; both
write the registry file. The read-only server shows the docs of every project in the registry and
also takes `--project FILE` (repeatable) for files that are not registered:
`uv run python -m authoring.readonly_server --project /path/to/studio.project.json`. See
[docs view](docs_view.md).
