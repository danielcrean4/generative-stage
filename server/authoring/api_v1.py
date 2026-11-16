"""The world-model HTTP API under /api/v1: request in, (status, JSON body) out, over core.

The server's handler passes every /api/v1 request here. This module applies the same local
Host/Origin guard as every other route and the `X-Studio-Request: 1` header on writes, parses the
body and query, calls core and turns core's errors into one error shape:

    {"error": {"status": 422, "code": "invalid_entity", "message": "...", "field": "/data/name"}}

docs/api.md documents every route.
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from authoring import (
    notes_api,
    parametric_api,
    pipeline_catalog,
    run_request,
    source_catalog,
    source_index,
    statistics,
    story_api,
    trace,
    vocabulary_api,
)
from authoring.job_store import JobStore
from authoring.jobs import Dispatcher, describe_steps
from authoring.machine_config import MachineConfig
from authoring.replies import BadRequest, FileBody
from authoring.request_guard import local_request_problem
from authoring.run_view import candidate_verdict, media_type
from core.errors import BadProjectFiles, Conflict, CoreError, Invalid, NotFound
from core.workspace import Workspace
from core.world import DEFAULT_SLOT, World
from export import project_exports, provenance

PREFIX = "/api/v1"
MAX_BODY = 1024 * 1024
STATUS = {NotFound: 404, Conflict: 409, Invalid: 422, BadProjectFiles: 422}

Reply = tuple[int, Any]
type Headers = "Message[str, str]"


@dataclass(frozen=True)
class Services:
    """What the v1 routes work over. Without a dispatcher, starting a job answers 503."""

    workspace: Workspace
    config: MachineConfig
    dispatcher: Dispatcher | None = None


def is_v1(path: str) -> bool:
    return path == PREFIX or path.startswith(PREFIX + "/")


def error(status: int, code: str, message: str, field: str | None = None) -> Reply:
    return status, {"error": {"status": status, "code": code, "message": message, "field": field}}


def _status(exc: CoreError) -> int:
    if isinstance(exc, BadRequest):
        return exc.status
    for cls, status in STATUS.items():
        if isinstance(exc, cls):
            return status
    return 500


def _body(method: str, headers: Headers, read: Callable[[int], bytes]) -> dict[str, Any]:
    if method in ("GET", "DELETE"):
        return {}
    try:
        length = int(headers.get("Content-Length") or "0")
    except ValueError as exc:
        raise BadRequest(400, "bad_request", "Content-Length is not a number") from exc
    if length > MAX_BODY:
        raise BadRequest(413, "too_large", f"the body is larger than {MAX_BODY} bytes")
    if length <= 0:
        return {}
    try:
        data = json.loads(read(length))
    except ValueError as exc:
        raise BadRequest(400, "bad_json", f"the body is not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise BadRequest(400, "bad_json", "the body must be a JSON object")
    return data


def _flag(query: dict[str, list[str]], name: str) -> bool:
    value = _one(query, name)
    if value in (None, "false", "0"):
        return False
    if value in ("true", "1"):
        return True
    raise Invalid(f"?{name}: expected true or false, not {value!r}", field=f"?{name}")


def _one(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    if len(values) > 1:
        raise Invalid(f"?{name}: give it once", field=f"?{name}")
    return values[0]


def _int(body: dict[str, Any], key: str) -> int:
    value = body.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise Invalid(f"/{key}: expected a whole number", field=f"/{key}")
    return value


def _segment_int(value: str, what: str) -> int:
    if not value.isdigit():
        raise NotFound(f"no {what} {value!r}", f"{what}_not_found")
    return int(value)


def handle(
    services: Services | None,
    method: str,
    target: str,
    headers: Headers,
    read: Callable[[int], bytes],
    port: int,
) -> Reply:
    """Answer one /api/v1 request."""
    problem = local_request_problem(headers, port)
    if problem:
        return error(403, "forbidden", problem)
    if method != "GET" and headers.get("X-Studio-Request") != "1":
        return error(403, "forbidden", "Missing Studio request header (X-Studio-Request: 1)")
    if services is None:
        return error(503, "not_configured", "the world model is not set up on this server")
    url = urlparse(target)
    parts = [unquote(p) for p in url.path[len(PREFIX) :].strip("/").split("/") if p]
    query = parse_qs(url.query, keep_blank_values=True)
    try:
        if (
            parts[:1] == ["projects"]
            and parts[2:3] == ["entities"]
            and notes_api.is_upload(method, parts[3:])
        ):
            body = notes_api.read_upload(headers, read)
        else:
            body = _body(method, headers, read)
        return _route(services, method, parts, query, body)
    except CoreError as exc:
        return error(_status(exc), exc.code, exc.message, exc.field)
    except Exception as exc:  # a bug: say so without leaking details, log the rest
        print(f"api/v1 {method} {url.path}: {exc!r}", file=sys.stderr, flush=True)
        return error(500, "internal", "internal error; see the server log")


def _not_allowed(method: str) -> BadRequest:
    return BadRequest(405, "method_not_allowed", f"{method} is not allowed here")


def _route(
    services: Services,
    method: str,
    parts: list[str],
    query: dict[str, list[str]],
    body: dict[str, Any],
) -> Reply:
    workspace = services.workspace
    if parts in (["pipelines"], ["adapters"]):
        if method != "GET":
            raise _not_allowed(method)
        if parts == [
            "pipelines"
        ]:  # the tool's defaults; a project's own are at /projects/{slug}/pipelines
            return 200, {
                "pipelines": pipeline_catalog.pipelines_view(None, _one(query, "entity_kind"))
            }
        return 200, {"adapters": pipeline_catalog.adapters_view()}
    if not parts or parts[0] != "projects":
        raise BadRequest(404, "route_not_found", "no such route")
    if len(parts) == 1:
        if method == "GET":
            return 200, {"projects": workspace.projects()}
        if method == "POST" and "project_file" in body:
            if set(body) != {"project_file"}:
                raise Invalid(
                    "give either project_file (open a project) or folder, slug and name "
                    "(create one)",
                    field="/project_file",
                )
            return 201, workspace.register(body["project_file"])
        if method == "POST":
            project = workspace.create(body.get("folder"), body.get("slug"), body.get("name"))
            return 201, project
        raise _not_allowed(method)
    slug, rest = parts[1], parts[2:]
    if not rest:
        if method == "GET":
            return 200, workspace.project(slug)
        if method == "DELETE":
            return 200, workspace.remove(slug)
        raise _not_allowed(method)
    if rest[0] == "vocabulary":  # before opening the world, so a broken file can be replaced
        schema_dir = workspace.registry.get(slug).schema_dir
        if schema_dir is None:
            raise Invalid("the project has no schema_dir", "bad_project_file")
        return vocabulary_api.route(schema_dir, method, rest[1:], body)
    return _project_route(services, workspace.open(slug), method, rest, query, body)


def _project_route(
    services: Services,
    world: World,
    method: str,
    rest: list[str],
    query: dict[str, list[str]],
    body: dict[str, Any],
) -> Reply:
    head = rest[0]
    if head == "entities":
        if len(rest) == 3 and rest[2] == "jobs":
            return _entity_jobs_route(services, world, method, rest[1], body)
        return _entities_route(services.config.runs_root, world, method, rest[1:], query, body)
    if head == "parametric":
        reply = parametric_api.route(services.config, world, method, rest[1:], body)
        if reply is None:
            raise _not_allowed(method)
        return reply
    if head == "jobs" and len(rest) == 2:
        if method != "GET":
            raise _not_allowed(method)
        return 200, _job_view(services, world, JobStore.for_project(world.project.root), rest[1])
    if head == "pipelines" and len(rest) == 1:
        if method != "GET":
            raise _not_allowed(method)
        view = pipeline_catalog.pipelines_view(world.project.root, _one(query, "entity_kind"))
        return 200, {"pipelines": view}
    if head == "sources":
        if method != "GET":
            raise _not_allowed(method)
        return 200, _sources_route(services, world, rest[1:])
    if head == "statistics" and len(rest) == 1:
        if method != "GET":
            raise _not_allowed(method)
        return 200, _statistics(services.config.runs_root, world)
    if head == "story" and len(rest) == 1:
        if method != "GET":
            raise _not_allowed(method)
        return 200, story_api.graph(world, _one(query, "entity"))
    if head == "exports":
        return _exports_route(services, world, method, rest[1:], body)
    if head == "kinds" and len(rest) <= 2:
        if method != "GET":
            raise _not_allowed(method)
        return 200, ({"kinds": world.kinds()} if len(rest) == 1 else world.kind(rest[1]))
    if head == "link-types" and len(rest) == 1:
        if method != "GET":
            raise _not_allowed(method)
        return 200, {"link_types": world.link_types()}
    if head == "links" and len(rest) == 1:
        if method != "POST":
            raise _not_allowed(method)
        return 201, world.add_link(body.get("type"), body.get("source"), body.get("target"))
    if head == "links" and len(rest) == 2:
        if method == "GET":
            return 200, world.get_link(rest[1])
        if method == "DELETE":
            return 200, world.delete_link(rest[1])
        raise _not_allowed(method)
    raise BadRequest(404, "route_not_found", "no such route")


def _entities_route(
    runs_root: Path,
    world: World,
    method: str,
    rest: list[str],
    query: dict[str, list[str]],
    body: dict[str, Any],
) -> Reply:
    if not rest:
        if method == "GET":
            entities = world.list_entities(
                kind=_one(query, "kind"),
                tag=_one(query, "tag"),
                text=_one(query, "q"),
                include_archived=_flag(query, "include_archived"),
            )
            return 200, {"entities": entities}
        if method == "POST":
            return 201, world.create_entity(
                body.get("kind"), body.get("data"), body.get("note", "")
            )
        raise _not_allowed(method)
    entity_id, action = rest[0], rest[1:]
    note = body.get("note", "")
    if not action:
        if method == "GET":
            return 200, world.get_entity(entity_id)
        if method == "PUT":
            return 200, world.update_entity(
                entity_id, _int(body, "revision"), body.get("data"), note
            )
        raise _not_allowed(method)
    name = action[0]
    if name in ("archive", "restore", "revert") and len(action) == 1:
        if method != "POST":
            raise _not_allowed(method)
        revision = _int(body, "revision")
        if name == "archive":
            return 200, world.archive_entity(entity_id, revision, note)
        if name == "restore":
            return 200, world.restore_entity(entity_id, revision, note)
        return 200, world.revert_entity(entity_id, revision, _int(body, "to"), note)
    if name == "revisions" and method == "GET":
        if len(action) == 1:
            return 200, {"revisions": world.revisions(entity_id)}
        if len(action) == 2:
            return 200, world.revision(entity_id, _segment_int(action[1], "revision"))
    if name == "links" and len(action) == 1 and method == "GET":
        links = world.links(
            entity_id,
            _one(query, "direction") or "both",
            _flag(query, "include_archived"),
        )
        return 200, {"links": links}
    if name == "sources" and len(action) == 1 and method == "GET":
        world.get_entity(entity_id)
        return 200, source_index.feeds(
            world, JobStore.for_project(world.project.root), runs_root, entity_id
        )
    if name == "runs" and len(action) == 3 and action[2] == "trace":
        if method != "GET":
            raise _not_allowed(method)
        return 200, _trace(world, runs_root, entity_id, action[1], _one(query, "attempt"))
    if name == "runs" and len(action) >= 4 and action[2] == "files":
        if method != "GET":
            raise _not_allowed(method)
        return 200, _run_file(world, runs_root, entity_id, action[1], "/".join(action[3:]))
    if name == "chosen" and len(action) == 3 and action[2] == "file":
        if method != "GET":
            raise _not_allowed(method)
        return 200, _chosen_file(world, runs_root, entity_id, action[1])
    if name == "runs":
        if len(action) == 1 and method == "GET":
            return 200, {"runs": world.runs(entity_id)}
        if len(action) == 1 and method == "POST":
            return 201, world.attach_run(entity_id, body.get("run_id"), note)
        if len(action) == 2 and method == "DELETE":
            world.detach_run(entity_id, action[1])
            return 200, {"entity_id": entity_id, "run_id": action[1], "detached": True}
    if name == "chosen" and len(action) == 1:
        if method == "GET":
            return 200, {"chosen": world.chosen(entity_id)}
        if method == "POST":
            choice = world.choose(
                entity_id,
                body.get("run_id"),
                body.get("candidate"),
                body.get("slot", DEFAULT_SLOT),
                note,
            )
            return 201, choice
    if name == "choices" and len(action) == 1 and method == "GET":
        return 200, {"choices": world.choices(entity_id)}
    if name == "notes":
        return notes_api.route(world, method, entity_id, action[1:], body)
    if name in ("revisions", "links", "runs", "chosen", "choices"):
        raise _not_allowed(method)
    raise BadRequest(404, "route_not_found", "no such route")


def _file_reply(file: Path) -> FileBody:
    kind = media_type(file.name)
    if kind is None:
        raise NotFound(f"{file.name!r} is not a type this server sends", "candidate_not_found")
    return FileBody(file.read_bytes(), kind, file.name, inline=kind.startswith("image/"))


def _chosen_file(world: World, runs_root: Path, entity_id: str, slot: str) -> FileBody:
    """The file of an entity's current choice in a slot."""
    choice = world.chosen(entity_id).get(slot)
    if choice is None:
        raise NotFound(f"nothing is chosen in slot {slot!r}", "no_choice")
    return _file_reply(provenance.read_provenance(runs_root, choice).file)


def _run_file(
    world: World, runs_root: Path, entity_id: str, run_id: str, candidate: str
) -> FileBody:
    """The file of any candidate of a run attached to the entity."""
    world.get_entity(entity_id)
    if run_id not in {r["run_id"] for r in world.runs(entity_id)}:
        raise NotFound(f"run {run_id!r} is not attached to this entity", "run_not_attached")
    return _file_reply(provenance.candidate_file(runs_root, run_id, candidate))


def _attached_run(world: World, entity_id: str, run_id: str) -> dict[str, Any]:
    """The entity, once its attachment to the run is checked."""
    entity = world.get_entity(entity_id)
    if run_id not in {r["run_id"] for r in world.runs(entity_id)}:
        raise NotFound(f"run {run_id!r} is not attached to this entity", "run_not_attached")
    return entity


def _trace(
    world: World, runs_root: Path, entity_id: str, run_id: str, attempt_id: str | None
) -> dict[str, Any]:
    """One attempt of a run attached to the entity, stage by stage, with the files it made as URLs
    on the candidate-file route, the job's candidates with their verdicts and the entity's choices."""
    entity = _attached_run(world, entity_id, run_id)
    slug = world.project.slug
    base = f"{PREFIX}/projects/{quote(slug, safe='')}/entities/{quote(entity_id, safe='')}"

    def file_url(candidate: str) -> str:
        path = "/".join(quote(part, safe="") for part in candidate.split("/"))
        return f"{base}/runs/{quote(run_id, safe='')}/files/{path}"

    found = trace.build_trace(runs_root, run_id, attempt_id, file_url)
    store = JobStore.for_project(world.project.root)
    source_index.add_links(found["stages"], source_index.set_of(store, run_id), entity)
    candidates = []
    for c in store.candidates(run_id):
        ref = _candidate_ref(runs_root, run_id, c["output_ref"])
        if ref:
            candidates.append(
                {"candidate": ref, "verdict": candidate_verdict(runs_root, run_id, ref)}
            )
    return {
        **found,
        "entity": {"id": entity["id"], "kind": entity["kind"], "title": entity["title"]},
        "candidates": candidates,
        "chosen": world.chosen(entity_id),
    }


def _sources_route(services: Services, world: World, rest: list[str]) -> dict[str, Any]:
    """The Sources index (no segments) or one source's page: its file and words, the pipelines that use it and the runs of
    this project's entities that read it."""
    if not rest:
        return {"sources": source_catalog.listing()}
    if len(rest) != 2:
        raise BadRequest(404, "route_not_found", "no such route")
    found = source_catalog.get(rest[0], rest[1])
    if found is None:
        raise NotFound(f"no {rest[0]} source {rest[1]!r}", "source_not_found")
    slug = quote(world.project.slug, safe="")

    def file_url(entity_id: str, run_id: str, candidate: str) -> str:
        path = "/".join(quote(part, safe="") for part in candidate.split("/"))
        return (
            f"{PREFIX}/projects/{slug}/entities/{quote(entity_id, safe='')}"
            f"/runs/{quote(run_id, safe='')}/files/{path}"
        )

    store = JobStore.for_project(world.project.root)
    runs = source_index.readers(world, store, services.config.runs_root, found.id, file_url)
    return {**source_catalog.view(found), "used_by": runs}


def _statistics(runs_root: Path, world: World) -> dict[str, Any]:
    """The figures for the project's runs (those attached to its entities, and its jobs' runs)."""
    store = JobStore.for_project(world.project.root)
    run_ids: set[str] = set()
    candidates = choices = chosen_slots = with_choice = 0
    entities = world.list_entities(include_archived=True)
    for entity in entities:
        run_ids |= {r["run_id"] for r in world.runs(entity["id"])}
        chosen = world.chosen(entity["id"])
        chosen_slots += len(chosen)
        with_choice += 1 if chosen else 0
        choices += len(world.choices(entity["id"]))
        for job in store.jobs_of(entity["id"]):
            run_ids.add(job["id"])
            candidates += len(store.candidates(job["id"]))
    rows = statistics.read_attempts(runs_root, run_ids)
    return statistics.summarise(
        rows,
        candidates=candidates,
        choices=choices,
        chosen_slots=chosen_slots,
        entities=len(entities),
        entities_with_choice=with_choice,
    )


def _strings(body: dict[str, Any], key: str) -> tuple[str, ...]:
    value = body.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise Invalid(f"/{key}: expected a list of names", field=f"/{key}")
    return tuple(value)


def _exports_route(
    services: Services, world: World, method: str, rest: list[str], body: dict[str, Any]
) -> Reply:
    runs_root = services.config.runs_root
    if not rest:
        if method == "GET":
            return 200, {"exports": project_exports.list_exports(world)}
        if method == "POST":
            since = body.get("since")
            if since is not None and not isinstance(since, str):
                raise Invalid("/since: expected an export id", field="/since")
            unknown = set(body) - {"kinds", "tags", "since"}
            if unknown:
                key = sorted(unknown)[0]
                raise Invalid(f"/{key}: unknown key (known: kinds, tags, since)", field=f"/{key}")
            created = project_exports.create_export(
                world, runs_root, _strings(body, "kinds"), _strings(body, "tags"), since
            )
            return 201, created
        raise _not_allowed(method)
    if method != "GET":
        raise _not_allowed(method)
    if len(rest) == 1:
        return 200, project_exports.manifest_of(world, rest[0])
    if len(rest) == 2 and rest[1] == "bundle.zip":
        data = project_exports.zip_bytes(world, rest[0])
        return 200, FileBody(data, "application/zip", f"{world.project.slug}-{rest[0]}.zip")
    raise BadRequest(404, "route_not_found", "no such route")


def _candidate_ref(runs_root: Path, job_id: str, output_ref: str) -> str | None:
    """A candidate file as the path relative to its run folder, the form `chosen` takes."""
    run = (runs_root / job_id).resolve()
    try:
        return Path(output_ref).resolve().relative_to(run).as_posix()
    except ValueError:
        return None


def _job_view(services: Services, world: World, store: JobStore, job_id: str) -> dict[str, Any]:
    job = store.job(job_id)
    runs_root = services.config.runs_root
    runs = [
        {**run, "steps": describe_steps(job, run, services.config)} for run in store.runs_of(job_id)
    ]
    candidates = []
    for c in store.candidates(job_id):
        ref = _candidate_ref(runs_root, job_id, c["output_ref"])
        verdict = candidate_verdict(runs_root, job_id, ref) if ref else None
        candidates.append({**c, "candidate": ref, "verdict": verdict})
    attached = job_id in {r["run_id"] for r in world.runs(job["entity_id"])}
    return {"job": job, "runs": runs, "candidates": candidates, "attached": attached}


def _attach_when_done(
    world: World, entity_id: str, job_id: str, runs_root: Path
) -> Callable[[str], None]:
    """What runs when a job's run ends: attach the run to its entity. A run that failed is attached only if it got as far as
    an attempt, so its trace can be opened; one that died before any attempt has nothing to show but its log."""

    def attach(status: str) -> None:
        if status == "failed" and not (runs_root / job_id / "attempts").is_dir():
            return
        note = "made by a job" if status == "succeeded" else "made by a job that failed"
        try:
            world.attach_run(entity_id, job_id, note)
        except Conflict as exc:
            if exc.code != "already_attached":  # a second run of the same job: already there
                raise

    return attach


def _entity_jobs_route(
    services: Services, world: World, method: str, entity_id: str, body: dict[str, Any]
) -> Reply:
    store = JobStore.for_project(world.project.root)
    if method == "GET":
        world.get_entity(entity_id)
        return 200, {
            "jobs": [_job_view(services, world, store, j["id"]) for j in store.jobs_of(entity_id)]
        }
    if method != "POST":
        raise _not_allowed(method)
    if services.dispatcher is None:
        return error(503, "not_configured", "this server cannot run jobs")
    entity = world.get_entity(entity_id)
    if entity["archived"]:
        raise Conflict(f"entity {entity_id!r} is archived; restore it first", "entity_archived")
    pipeline, recipe = run_request.check(
        body,
        entity,
        world.project.root,
        world.chosen(entity_id),
        services.config.runs_root,
    )
    job = store.create_job(entity, pipeline, recipe)
    run = store.create_run(job["id"])
    services.dispatcher.enqueue(
        store,
        run["id"],
        job["id"],
        _attach_when_done(world, entity_id, job["id"], services.config.runs_root),
    )
    return 202, _job_view(services, world, store, job["id"])
