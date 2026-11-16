"""Check a request to start a run and turn it into the recipe a job stores.

A request is `{"pipeline": id, "prompt": text, "adapters": {kind: adapter id}, "choices": {name: value}}`; `adapters` and
`choices` are optional. It can name a pipeline this server offers (offered.json), an adapter the machine config has and
that fits the kind of stage it is for, and the choices that pipeline declares with values inside the declaration. Any
other key is refused, so a request cannot carry a command, a path or an environment (docs/adapters.md, "Trust rule").
The recipe holds the prompt, the adapters named and every choice with its value (a declared default where the request
named none).
"""

import re
from pathlib import Path
from typing import Any

from authoring import generation_file
from authoring.offered import Offer, offers
from authoring.pipeline_catalog import machine_adapters
from core.errors import Invalid, NotFound
from export import provenance

REQUEST_KEYS = ("pipeline", "prompt", "adapters", "choices")
MAX_TEXT = 20000
MAX_NAME = 100
ADAPTER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
PIPELINE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
IMAGE_SUFFIXES = (".png",)


def _object(body: dict[str, Any], key: str) -> dict[str, Any]:
    value = body.get(key, {})
    if not isinstance(value, dict):
        raise Invalid(f"/{key}: expected an object", field=f"/{key}")
    return value


def _offer(body: dict[str, Any], entity_kind: str, project_root: Path) -> Offer:
    name = body.get("pipeline")
    if not isinstance(name, str) or not PIPELINE_ID.fullmatch(name):
        raise Invalid(
            "/pipeline: expected a pipeline id (see GET /api/v1/pipelines)", field="/pipeline"
        )
    offer = offers().get(name)
    if offer is None:
        known = ", ".join(sorted(offers()))
        raise Invalid(f"/pipeline: no pipeline {name!r} (known: {known})", field="/pipeline")
    serving = [o.id for o in generation_file.offered_for(project_root, entity_kind)]
    if offer.id not in serving:
        raise Invalid(
            f"/pipeline: the {name!r} pipeline does not serve a {entity_kind!r} record "
            f"(it serves: {', '.join(serving) or 'none'})",
            field="/pipeline",
        )
    return offer


def _adapters(given: dict[str, Any], offer: Offer) -> dict[str, str]:
    """Each adapter named for a kind this pipeline runs, by id, and the id must be one the machine config has for that kind."""
    wanted = offer.adapter_kinds()
    entries = machine_adapters()
    chosen: dict[str, str] = {}
    for kind, adapter in given.items():
        at = f"/adapters/{kind}"
        if kind not in wanted:
            raise Invalid(
                f"{at}: the {offer.id!r} pipeline runs no {kind!r} adapter (it runs: {', '.join(wanted) or 'none'})",
                field=at,
            )
        if not isinstance(adapter, str) or not ADAPTER_ID.fullmatch(adapter):
            raise Invalid(
                f"{at}: expected an adapter id (letters, digits, '_' and '-'); commands are set only in the machine config",
                field=at,
            )
        entry = entries.get(adapter)
        if entry is None or entry.kind != kind:
            raise Invalid(
                f"{at}: no {kind!r} adapter {adapter!r} (GET /api/v1/adapters lists them)", field=at
            )
        chosen[kind] = adapter
    return chosen


def _start_image(slot: str, chosen: dict[str, Any], runs_root: Path) -> dict[str, str]:
    """The image already chosen for SLOT as a reference into its run (`slot`, `run_id`, `candidate`), checked to be a
    picture that is still there. The run reads it again from the run folder when it starts."""
    choice = chosen.get(slot)
    at = "/choices/start_image"
    if choice is None:
        raise Invalid(f"{at}: nothing is chosen for {slot!r} on this record yet", field=at)
    try:
        file = provenance.candidate_file(runs_root, choice["run_id"], choice["candidate"])
    except NotFound as error:
        raise Invalid(f"{at}: {error.message}", field=at) from error
    if file.suffix.lower() not in IMAGE_SUFFIXES:
        raise Invalid(f"{at}: what is chosen for {slot!r} is not a picture", field=at)
    return {"slot": slot, "run_id": choice["run_id"], "candidate": choice["candidate"]}


def check(
    body: dict[str, Any],
    entity: dict[str, Any],
    project_root: Path,
    chosen: dict[str, Any],
    runs_root: Path,
) -> tuple[str, dict[str, Any]]:
    """The pipeline id and the recipe for a request made for ENTITY (its kind and title), in the project at PROJECT_ROOT, with
    CHOSEN the entity's current choices; raises Invalid with a field pointer. Without a prompt a run that starts from a
    chosen image uses the record's title as the subject text."""
    unknown = sorted(set(body) - set(REQUEST_KEYS))
    if unknown:
        raise Invalid(
            f"/{unknown[0]}: unknown key (known: {', '.join(REQUEST_KEYS)})", field=f"/{unknown[0]}"
        )
    offer = _offer(body, entity["kind"], project_root)
    try:
        choices = offer.choose(_object(body, "choices"))
    except ValueError as error:
        name = str(error).split(":", 1)[0]
        raise Invalid(f"/choices/{error}", field=f"/choices/{name}") from error
    prompt = body.get("prompt")
    if "start_image" in choices and (prompt is None or prompt == ""):
        prompt = entity.get("title") or entity["kind"]
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_TEXT:
        raise Invalid(f"/prompt: expected text of 1 to {MAX_TEXT} characters", field="/prompt")
    adapters = _adapters(_object(body, "adapters"), offer)
    recipe: dict[str, Any] = {"prompt": prompt, "adapters": adapters, "choices": choices}
    if "start_image" in choices:
        recipe["start_image"] = _start_image(choices["start_image"], chosen, runs_root)
    return offer.id, recipe
