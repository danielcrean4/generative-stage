# Architecture

Generative Stage has one job: keep a story world's records (settings, characters, props and the links between them),
turn their briefs into images, 3D models and motion clips with local models, and keep an exact record of how every
result was made. It names no game. Anything particular to one story or engine is data (kind schemas, pipeline files,
style packs, a vocabulary) or an adapter on the far side of the export bundle.

## The parts

```
generative-stage/
  core/       the world model: projects, kinds, entities with revisions, links, notes, vocabulary, story graph
  pipeline/   the runner and its deterministic stages; pipeline files, style packs and example data
  adapters/   the adapter format, the stand-in adapters (no model), examples for real local models
  server/     the HTTP API, the read-only run server, the web gateway, the MCP server, a command-line tool
  ui/         the Angular web app, built to static files; nothing is loaded from other hosts
  export/     the export bundle writer and its manifest schema; a Godot reader as an example
  blender/    scripts that run inside headless Blender (rigging, motion, example models)
  scripts/    install helpers, the process launcher, the smoke test, the example loader, the third-party list
  examples/   the example project
  docs/       these pages
```

| Part | What it knows | What it does not know |
|---|---|---|
| `core/` | kinds from JSON Schema, links, revisions, the project's SQLite store, references to runs | pipelines, models, HTTP |
| `pipeline/` | stages, gates, the attempt record, the adapter format | the world model, HTTP |
| `server/` | both of the above, and joins them | any particular model or game |
| `ui/` | the API's shapes | files on disk |

## Processes

`./start.sh` runs three programs on the loopback address and stops them together:

```
 browser ──► web gateway (4280) ──► API (8780)            records, links, jobs, traces, statistics, exports
 agent ──► MCP server (stdio) ──►     │
                                      └─► read-only run server (8781)   what each run did, read from files
```

- **The API** (`server/authoring/server.py`, routes in `api_v1.py`) serves everything under `/api/v1`. It owns the world model
  and the job queue.
- **The read-only run server** (`readonly_server.py`) reads run folders and project docs and writes nothing.
- **The web gateway** (`web_gateway.py`) serves the built web app and forwards `/api/ro` and `/api` to the two servers, so
  the browser sees one address.
- **The MCP server** (`server/mcp_server/`) is a thin client of the API: every tool is one API request. It has no logic of its
  own, so what the API refuses, the tools refuse.

Each server binds `127.0.0.1` only and refuses a request whose `Host` or `Origin` is not its own address, so another website
cannot call it. Every non-GET request also needs `X-Studio-Request: 1`. In the container the gateway listens on all
addresses and Docker publishes the port on the host's loopback only.

## Where state lives

| Where | What | Who writes it |
|---|---|---|
| the project folder | `studio.project.json`, `kinds/` (kinds, link types, vocabulary), `world.sqlite3` (entities, revisions, links, run references, choices), `jobs.sqlite3` (jobs, runs, candidates), `notes/`, `exports/` | the API |
| the runs root (`<data_dir>/asset-runs/<job id>/`) | one folder per job: the subject and pipeline copy, an `attempts/<id>/` folder per candidate with `attempt.json` and a folder per stage, and `final/` | the pipeline runner |
| the data folder (`data_dir`) | `registry.json`, the list of known projects; the runs root | the API |
| the machine config | where this computer's programs and models are, and the adapters | the person who owns the computer |

A project is a folder a person owns; removing it from the registry never touches the folder. Entities are referred to by id
only across the two stores, and the API joins them. The record of a run is plain files, so the trace, the statistics and the
read-only server need no database.

## One run, end to end

1. A person (or an agent) asks for a run on a record: a pipeline id, a prompt, adapters by kind and id, and the choices the
   pipeline declares (style, motif, seed, number of candidates). The request names nothing else
   (`server/authoring/run_request.py`).
2. The API stores it as a job (`job_store.py`) and the dispatcher (`jobs.py`) runs jobs one at a time.
3. `pipeline_job.py` writes the subject file from the prompt and a copy of the pipeline file whose model stages name the
   chosen adapters, then starts `pipeline/pipeline_run.py` once for the job. The command line is fixed in code.
4. The runner resolves the pipeline file with its subject, motif, style pack and contract into one job: per stage the tool,
   the adapter, the exact settings it reads, its inputs and outputs, and a hash of all of it. A stage whose hash matches an
   earlier attempt is reused rather than run again.
5. Each stage runs in the order the file gives. A model stage runs its adapter: the command from the machine config, with
   the stage's values filled in, in the network sandbox its entry asks for (a host that cannot apply it refuses the stage, it never runs with the
   network open), holding the GPU lock when the adapter asks for it. Deterministic stages (tidy the image, find the subject, clean, orient, size and decimate the mesh,
   the shape gate, the review sheet) run in the tools environment. Gated stages stop the run when a check fails, or send it
   to review.
6. Every stage leaves its files and a record in the attempt folder: inputs and outputs with SHA-256 hashes, the prompt,
   timings, the identity the adapter reported, and each check's value, limit and margin.
7. The finished files become the job's candidates. A person chooses one per slot (`main` for the picture, `mesh` for the
   model, `icon`); the choice is stored with the entity revision it was made at and is never overwritten.
8. The trace (`trace.py`) and the statistics (`statistics.py`) are worked out from the attempt records when asked. Nothing in
   them is invented: a field the run did not record is empty.
9. An export (`export/bundle.py`) writes the live records, their links and the chosen files into a bundle, with the
   provenance of each file. The same state always gives the same bytes.

## The trust rule

Only the machine config defines a command. Pipeline files, project files, entity data, HTTP requests and MCP calls choose an
adapter by id and set only the choices a pipeline declares; each is checked against that declaration and no tool, route or
file has a field that could carry a program, an argument list, an environment, a folder or an address. The tests try each
route ([adapters](adapters.md#trust-rule)).

## Platforms

One small layer, `pipeline/host.py`, is the only code that knows the operating system. It answers which accelerators exist,
which programs are on the path, whether a child process can be denied the network and where the GPU lock is. An adapter
declares what it needs (`apple_silicon`, `cuda`, `blender`, `network_denied`); before a run the runner checks the host and
stops with one specific sentence per unmet need. Nothing else branches on the operating system, so adding a platform means
adding adapters and host answers. See [platforms](platform.md).

## Extension points

| To change | Edit | Reference |
|---|---|---|
| what a story world holds | the project's `kinds/` folder: a JSON Schema per kind, `kinds.json`, `link_types.json` | [API](api.md#kinds) |
| the words a condition may use | `vocabulary.json` in the same folder | [vocabulary](vocabulary.md) |
| how an asset is made | a pipeline file, a style pack, a motif, a contract | [pipeline files](pipeline_files.md) |
| which pipelines serve which kind | `generation.json` in the project folder | [API](api.md#pipelines-and-adapters) |
| which model runs a stage | an adapter entry in the machine config | [adapters](adapters.md) |
| what leaves the tool | read the export bundle in your engine or game | [export bundle](export_bundle.md) |

## Where the name appears

The interface reads the product name from one constant (`ui/src/app/brand.ts`); the README's "The name" lists the older
names still read for one release. Some identifiers still say "Studio" (`studio.project.json`, the `X-Studio-Request`
header, the `studio` command) because they name a file format or a protocol rather than the product.
