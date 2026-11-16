"""The tools, as data. Each one is a name, a description, a closed input schema and the one API request it makes.

There is no field in any schema for a command, an argument list, an environment, a folder, a file or an address: a run
names a pipeline and adapters by id, and the server alone decides what is started (docs/adapters.md, "Trust rule").
`tests/test_mcp_trust.py` walks every schema and fails if that changes.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"}  # never `.` or `..`
# A reference into a run folder (`attempts/<attempt>/concept/image.png`), as get_run and get_trace name it: relative, no
# `..`, no `~`, no backslash. The server resolves it inside the run and refuses anything that leaves it.
CANDIDATE = {
    "type": "string",
    "maxLength": 500,
    "pattern": r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.@=+ -]*(/[A-Za-z0-9_.@=+ -]+)*$",
}
ADAPTER_ID = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"}
# The adapter kinds a pipeline stage can run (pipeline_file.TOOLS); a run names an adapter for a kind by id.
ADAPTER_KINDS = ("image", "image-to-mesh", "material", "rig", "motion")
# The choices a pipeline file may declare (pipeline_file.CHOICE_NAMES). Each value is an id or a whole number that the
# server checks against the pipeline's own declaration (its options and ranges); none is a name or place on disk.
CHOICES = {
    "style": ADAPTER_ID,
    "motif": ADAPTER_ID,
    "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
    "candidates": {"type": "integer", "minimum": 1, "maximum": 8},
    "hair_colour": {"type": "string", "pattern": r"^#[0-9a-fA-F]{6}$"},
    "start_image": ADAPTER_ID,  # the slot (`main`, `icon`) whose chosen picture the run starts from
}
NOTE = {"type": "string", "maxLength": 500}
NAME = ADAPTER_ID  # a kind, link type, slot or pipeline: the server checks that it exists


def _view_projects(answer: dict[str, Any]) -> dict[str, Any]:
    """A project is shown by slug and name: its folder on this computer is not the agent's business."""
    keep = ("slug", "name", "problem")
    return {"projects": [{k: p[k] for k in keep if k in p} for p in answer["projects"]]}


def _view_run(answer: dict[str, Any]) -> dict[str, Any]:
    """A run is shown by candidate name: the file's place on this computer (`output_ref`) is left out."""
    return {
        **answer,
        "candidates": [
            {k: v for k, v in c.items() if k != "output_ref"} for c in answer.get("candidates", [])
        ],
    }


@dataclass(frozen=True)
class Tool:
    """`path` is below /api/v1; `{project}` is the server's project and every other `{name}` is an argument.
    `query`, `body` and `rename` (argument name -> body key) say where the other arguments go."""

    name: str
    description: str
    method: str
    path: str
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    rename: dict[str, str] = field(default_factory=dict)
    view: Callable[[Any], Any] | None = None

    @property
    def needs_project(self) -> bool:
        return "{project}" in self.path

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": self.properties,
            "required": list(self.required),
            "additionalProperties": False,
        }


E_ = "/projects/{project}/entities/{entity_id}"
TOOLS: tuple[Tool, ...] = (
    Tool(
        "list_projects",
        "List the projects this server can open: slug and name.",
        "GET",
        "/projects",
        view=_view_projects,
    ),
    Tool(
        "list_kinds",
        "List the kinds of record in the project (setting, character, prop, script, ...), each with its JSON Schema.",
        "GET",
        "/projects/{project}/kinds",
    ),
    Tool(
        "list_link_types",
        "List the link types: which kinds each one may join.",
        "GET",
        "/projects/{project}/link-types",
    ),
    Tool(
        "get_vocabulary",
        "Get the project's condition vocabulary: the facts a condition may read, the operators, the effects and the "
        "rule modes (null when the project has none).",
        "GET",
        "/projects/{project}/vocabulary",
    ),
    Tool(
        "check_condition",
        "Check a condition against the vocabulary before writing it: every problem with its JSON pointer, the "
        "condition in plain words and the facts it reads.",
        "POST",
        "/projects/{project}/vocabulary/check",
        properties={"condition": {"type": "object"}},
        required=("condition",),
        body=("condition",),
    ),
    Tool(
        "get_story_graph",
        "Get the story graph: every record and the story edges between them, or with entity one record's story "
        "nodes in full (steps, lines, replies), each with its conditions in plain words, the facts they read and "
        "its effects.",
        "GET",
        "/projects/{project}/story",
        properties={"entity": ID},
        query=("entity",),
    ),
    Tool(
        "list_entities",
        "List records, most recently changed first. Filter by kind, an exact tag or text in the title, brief or tags.",
        "GET",
        "/projects/{project}/entities",
        properties={
            "kind": NAME,
            "tag": {"type": "string", "maxLength": 100},
            "q": {"type": "string", "maxLength": 200},
            "include_archived": {"type": "boolean"},
        },
        query=("kind", "tag", "q", "include_archived"),
    ),
    Tool(
        "get_entity",
        "Get one record with its current revision.",
        "GET",
        E_,
        properties={"entity_id": ID},
        required=("entity_id",),
    ),
    Tool(
        "create_entity",
        "Create a record of a kind. `data` must fit the kind's schema (see list_kinds); the answer holds its id.",
        "POST",
        "/projects/{project}/entities",
        properties={"kind": NAME, "data": {"type": "object"}, "note": NOTE},
        required=("kind", "data"),
        body=("kind", "data", "note"),
    ),
    Tool(
        "update_entity",
        "Replace a record's `data`. Send the `revision` you read; if someone wrote in between the call fails with "
        "revision_conflict and nothing changes, so read the record again and retry.",
        "PUT",
        E_,
        properties={
            "entity_id": ID,
            "revision": {"type": "integer", "minimum": 1},
            "data": {"type": "object"},
            "note": NOTE,
        },
        required=("entity_id", "revision", "data"),
        body=("revision", "data", "note"),
    ),
    Tool(
        "list_links",
        "List the links of a record, from its side: type, label, direction and the record at the other end.",
        "GET",
        E_ + "/links",
        properties={
            "entity_id": ID,
            "direction": {"enum": ["out", "in", "both"]},
            "include_archived": {"type": "boolean"},
        },
        required=("entity_id",),
        query=("direction", "include_archived"),
    ),
    Tool(
        "create_link",
        "Link two records with a declared type (see list_link_types), for example belongs_to from a prop to a character.",
        "POST",
        "/projects/{project}/links",
        properties={"type": NAME, "source": ID, "target": ID},
        required=("type", "source", "target"),
        body=("type", "source", "target"),
    ),
    Tool(
        "delete_link",
        "Delete a link by its id.",
        "DELETE",
        "/projects/{project}/links/{link_id}",
        properties={"link_id": ID},
        required=("link_id",),
    ),
    Tool(
        "add_note",
        "Add a note to a record. Notes are context for people; they are not revisions and do not change the record.",
        "POST",
        E_ + "/notes",
        properties={
            "entity_id": ID,
            "text": {"type": "string", "maxLength": 5000},
            "pinned": {"type": "boolean"},
        },
        required=("entity_id", "text"),
        body=("text", "pinned"),
    ),
    Tool(
        "list_pipelines",
        "List the pipelines a run can use: id, name, kind, the record kinds each serves, its stages (a stage that "
        "runs a model names the adapter kind it needs) and the choices it declares with their options, ranges and "
        "defaults. Pass `entity_kind` to list only those that serve a kind of record (the project's generation.json "
        "can change which pipelines serve a kind).",
        "GET",
        "/projects/{project}/pipelines",
        properties={"entity_kind": NAME},
        query=("entity_kind",),
    ),
    Tool(
        "list_adapters",
        "List the adapters this computer has: id, kind, description, whether it is the default of its kind and "
        "whether this computer can run it. Commands and folders are never shown.",
        "GET",
        "/adapters",
    ),
    Tool(
        "start_run",
        "Start a pipeline run for a record. Name the pipeline by id (list_pipelines). `adapters` picks an adapter by "
        "id for a kind of model stage (list_adapters); a kind left out uses this computer's default. `choices` sets "
        "the pipeline's declared choices by name (style, motif, seed, candidates, hair_colour, start_image); a choice "
        "left out takes the pipeline's default. `start_image` names a slot (main) whose chosen picture a run "
        "starts from, for a pipeline that declares it (the 3D one does); `prompt` may then be left to the title. The run id in the answer is the job's id. The run is queued: poll get_run.",
        "POST",
        E_ + "/jobs",
        properties={
            "entity_id": ID,
            "pipeline": NAME,
            "prompt": {"type": "string", "minLength": 1, "maxLength": 20000},
            "adapters": {
                "type": "object",
                "properties": {kind: ADAPTER_ID for kind in ADAPTER_KINDS},
                "additionalProperties": False,
            },
            "choices": {"type": "object", "properties": CHOICES, "additionalProperties": False},
        },
        required=("entity_id", "pipeline"),
        body=("pipeline", "prompt", "adapters", "choices"),
        view=_view_run,
    ),
    Tool(
        "get_run",
        "Read a run: its status (queued, running, succeeded, failed), the end of its log, its steps and the "
        "candidates it made, each with a gate verdict.",
        "GET",
        "/projects/{project}/jobs/{run_id}",
        properties={"run_id": ID},
        required=("run_id",),
        view=_view_run,
    ),
    Tool(
        "get_trace",
        "Read a run stage by stage: the exact prompt, adapter identity, inputs, outputs, gates, time and status "
        "of each stage, with the prompt as the pieces it was made from and where each came from. The run must be attached to the record (a run that succeeded, or that failed after starting an attempt, is).",
        "GET",
        E_ + "/runs/{run_id}/trace",
        properties={"entity_id": ID, "run_id": ID, "attempt": ID},
        required=("entity_id", "run_id"),
        query=("attempt",),
    ),
    Tool(
        "list_sources",
        "List the shared sources prompts are made from: style packs, motifs and contracts, each with an id "
        "(`<set>.<name>`, such as `prop.clay`) and the pipelines that use it.",
        "GET",
        "/projects/{project}/sources",
    ),
    Tool(
        "get_source",
        "Read one shared source: its words, the file it lives in (these files belong to the tool, so they are "
        "read-only), the pipelines that use it and the runs of this project's records that read it, newest first. "
        "A trace's prompt parts name the source each piece of the prompt came from.",
        "GET",
        "/projects/{project}/sources/{type}/{source_id}",
        properties={"type": {"enum": ["style", "motif", "contract"]}, "source_id": ID},
        required=("type", "source_id"),
    ),
    Tool(
        "choose_candidate",
        "Choose a candidate of a run for a record. `candidate` is the name get_run or get_trace gives for it. "
        "A new choice in a slot replaces the current one; earlier choices are kept in history.",
        "POST",
        E_ + "/chosen",
        properties={
            "entity_id": ID,
            "run_id": ID,
            "candidate": CANDIDATE,
            "slot": NAME,
            "note": NOTE,
        },
        required=("entity_id", "run_id", "candidate"),
        body=("run_id", "candidate", "slot", "note"),
    ),
    Tool(
        "export_bundle",
        "Write the project's records, links and chosen assets as an export bundle. Filter by kinds or tags, or "
        "send an earlier export id as `since` to learn what was removed.",
        "POST",
        "/projects/{project}/exports",
        properties={
            "kinds": {"type": "array", "items": NAME, "maxItems": 50},
            "tags": {
                "type": "array",
                "items": {"type": "string", "maxLength": 100},
                "maxItems": 50,
            },
            "since": ID,
        },
        body=("kinds", "tags", "since"),
    ),
)
BY_NAME = {tool.name: tool for tool in TOOLS}
