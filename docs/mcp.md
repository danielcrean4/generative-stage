# MCP server

The MCP server lets an agent (a program that talks to a language model) read and write the world model and run
pipelines. It is a thin client of the [v1 HTTP API](api.md): every tool makes one API request and returns the answer.
It has no logic of its own, so what the API refuses, the tools refuse.

## Run it

Start the main server first (`python -m authoring.server`, listening on 127.0.0.1:8780 by default). Then, from the
`server/` folder:

    uv run python -m mcp_server --api http://127.0.0.1:8780 --project my-project

| Option | Environment variable | Meaning |
|---|---|---|
| `--api` | `GENSTAGE_API_URL` | the API's address, `http://127.0.0.1:8780` if not given |
| `--project` | `GENSTAGE_PROJECT` | the slug of the project every project tool works in |

The server speaks MCP over standard input and output (stdio). Nothing else is printed to standard output. Without
`--project`, `list_projects` still works and the other project tools answer that no project is set.

## Add it to an MCP client

Most clients take a command and its arguments. A generic entry:

```json
{
  "mcpServers": {
    "generative-stage": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/repository/server", "python", "-m", "mcp_server",
               "--api", "http://127.0.0.1:8780", "--project", "my-project"]
    }
  }
}
```

The file's name and place depend on the client. The server inherits only the environment variables the client passes.

## Tools

| Tool | What it does | API route |
|---|---|---|
| `list_projects` | project slugs and names | `GET /projects` |
| `list_kinds` | the kinds, each with its JSON Schema | `GET .../kinds` |
| `list_link_types` | the link types and the kinds they join | `GET .../link-types` |
| `get_vocabulary` | the condition vocabulary ([vocabulary](vocabulary.md)) | `GET .../vocabulary` |
| `check_condition` | a condition's problems, plain words and the facts it reads | `POST .../vocabulary/check` |
| `get_story_graph` | the story graph, or one record's story in full ([story graph](story_graph.md)) | `GET .../story` |
| `list_entities` | records, filtered by kind, tag or text | `GET .../entities` |
| `get_entity` | one record and its revision | `GET .../entities/{id}` |
| `create_entity` | a record of a kind | `POST .../entities` |
| `update_entity` | replace a record's data; needs the revision read | `PUT .../entities/{id}` |
| `list_links` | a record's links | `GET .../entities/{id}/links` |
| `create_link` | link two records | `POST .../links` |
| `delete_link` | delete a link | `DELETE .../links/{id}` |
| `add_note` | add a note to a record | `POST .../entities/{id}/notes` |
| `list_pipelines` | pipelines a run can use in this project, with their stages | `GET .../pipelines` |
| `list_adapters` | adapters: id, kind, description, default, runnable | `GET /adapters` |
| `start_run` | start a pipeline run for a record: a pipeline id, a prompt, optional `adapters` (kind to adapter id) and `choices` (style, motif, seed, candidates, hair_colour, start_image); `prompt` may be left out when `start_image` is given | `POST .../entities/{id}/jobs` |
| `get_run` | a run's status, log tail, steps and candidates | `GET .../jobs/{id}` |
| `get_trace` | a run stage by stage | `GET .../entities/{id}/runs/{run}/trace` |
| `list_sources` | the style packs, motifs and contracts prompts are made from | `GET .../sources` |
| `get_source` | one source: its words, its file (read-only), the pipelines and runs that use it | `GET .../sources/{type}/{id}` |
| `choose_candidate` | choose a candidate of a run for a record | `POST .../entities/{id}/chosen` |
| `export_bundle` | write an export bundle | `POST .../exports` |

An update with an old revision fails with `revision_conflict` and changes nothing: read the record again and apply the
change again. An API error comes back as a tool error that starts with the API's error code and gives its message
and, when one value is at fault, its place in the request (`/data/name`).

`list_pipelines` shows, for each pipeline, the kinds of record it serves, its stages and the choices it declares with
their options, ranges and defaults; `entity_kind` narrows the list to the pipelines that serve one kind of record.
`start_run`'s `choices` take only those names and are checked against the pipeline's own declaration, so a style
or motif that the pipeline does not offer, or a seed or candidate count outside its range, is refused with the field
named. A choice left out takes the pipeline's default. `start_image` names a slot (`main`) of the record whose chosen picture a run starts from, for a pipeline that declares it (the 3D one). A trace's prompt parts name the source of each piece of a prompt, and `get_source` reads that source.

A run is queued when `start_run` answers. `get_run` shows its status (`queued`, `running`, `succeeded`, `failed`); when
it has succeeded, `candidates` lists what to choose from, and `get_trace` shows how each was made.

## Trust rule

An agent can choose; it cannot define. A command exists only in the machine config, a file the person who owns the
computer edits ([adapters](adapters.md)).

- No tool has a field for a command, an argument list, an environment, a file, a folder or an address. A run names a
  pipeline and adapters by id (`pipeline`, `adapters`), may set the pipeline's declared choices by name (`choices`:
  a style or motif id, a seed, a candidate count) and the server alone decides what is started. Every tool's input is a closed schema; a call with a field it does not name is refused before any request
  is made.
- `list_adapters` and `list_pipelines` show ids, kinds, descriptions, stages and declared choices. Commands, environments, folders and
  model files are never part of an answer.
- Every id is percent-encoded into one path segment, and ids are limited to letters, digits and `_ . -`, so an id
  cannot reach another route.
- `candidate` (in `choose_candidate`) is the one field that looks like a path. It is a name inside a run folder, as
  `get_run` and `get_trace` give it: relative, with no `..`, `~`, backslash or leading `/`. The API resolves it inside
  the run and refuses anything that leaves it. `get_run` leaves out the place of each candidate's file on this computer.
- The one open object is `data` of `create_entity` and `update_entity`: the API checks it against the kind's schema.
- The server's address and project come from the operator's arguments or environment, never from a tool call.

`server/tests/test_mcp_trust.py` walks every tool's schema and fails if a field of that kind appears, and checks that
crafted calls change nothing in what a run starts. `server/tests/test_mcp_walkthrough.py` does steps 3 to 5 of the
walkthrough (briefs and links, a prop run on the stand-in adapters, choosing a candidate, reading the trace) through a
real MCP session on stdio.
