"""The notes routes under /api/v1/projects/<slug>/entities/<id>/notes: what a note is lives in
core.notes; this module reads the request, checks the entity and mentions and shapes the reply.

An image goes up as the raw body of `POST .../notes/<note id>/attachments` (the content type says
which image type), not as JSON, so a screenshot is not inflated by base64.
"""

from collections.abc import Callable
from email.message import Message
from typing import Any
from urllib.parse import unquote

from authoring.replies import BadRequest, FileBody
from core.errors import Invalid, NotFound
from core.notes import MAX_IMAGE_BYTES, Notes, parse_mentions
from core.world import World

UPLOAD = "attachments"
FILE_NAME_HEADER = "X-File-Name"
type Headers = "Message[str, str]"
type Reply = tuple[int, Any]


def is_upload(method: str, rest: list[str]) -> bool:
    """Whether a request to /entities/<rest...> carries a raw image rather than JSON."""
    return method == "POST" and len(rest) == 4 and rest[1] == "notes" and rest[3] == UPLOAD


def read_upload(headers: Headers, read: Callable[[int], bytes]) -> dict[str, Any]:
    """The body of an upload as a dict the route takes: bytes, content type and file name."""
    try:
        length = int(headers.get("Content-Length") or "0")
    except ValueError as exc:
        raise Invalid("Content-Length is not a number", "bad_request") from exc
    if length > MAX_IMAGE_BYTES:
        raise BadRequest(413, "too_large", f"the image is larger than {MAX_IMAGE_BYTES} bytes")
    kind = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return {
        "bytes": read(length) if length > 0 else b"",
        "media_type": kind,
        "name": unquote(headers.get(FILE_NAME_HEADER, "")),
    }


def _mentions(world: World, text: str, picked: object) -> list[dict[str, str]]:
    """The entities a text points to: every `@kind/id` that is a real entity of that kind, plus the
    ones the caller named in `mentions` (which must all exist)."""
    refs: list[dict[str, str]] = []
    for ref in parse_mentions(text):
        try:
            if world.get_entity(ref["id"])["kind"] == ref["kind"]:
                refs.append(ref)
        except NotFound:
            continue
    if picked is None:
        return refs
    if not isinstance(picked, list):
        raise Invalid("/mentions: expected a list of {kind, id}", field="/mentions")
    for i, item in enumerate(picked):
        if not (isinstance(item, dict) and isinstance(item.get("id"), str)):
            raise Invalid(f"/mentions/{i}: expected {{kind, id}}", field=f"/mentions/{i}")
        entity = world.get_entity(item["id"])
        ref = {"kind": entity["kind"], "id": entity["id"]}
        if ref not in refs:
            refs.append(ref)
    return refs


def route(
    world: World, method: str, entity_id: str, rest: list[str], body: dict[str, Any]
) -> Reply:
    """`rest` is what follows `/notes`. The entity must exist; archived ones take notes too, as a
    note is not a change to the entity."""
    world.get_entity(entity_id)
    notes = Notes(world.project.root)
    if not rest:
        if method == "GET":
            return 200, {"notes": notes.listing(entity_id)}
        if method == "POST":
            text = body.get("text", "")
            clean = text if isinstance(text, str) else ""
            mentions = _mentions(world, clean, body.get("mentions"))
            return 201, notes.add(entity_id, text, body.get("pinned", False), mentions)
        raise BadRequest(405, "method_not_allowed", f"{method} is not allowed here")
    note_id = rest[0]
    if len(rest) == 1:
        if method == "PATCH":
            text = body.get("text")
            found = _mentions(world, text, body.get("mentions")) if isinstance(text, str) else None
            return 200, notes.update(entity_id, note_id, text, body.get("pinned"), found)
        if method == "DELETE":
            notes.delete(entity_id, note_id)
            return 200, {"entity_id": entity_id, "note_id": note_id, "deleted": True}
        raise BadRequest(405, "method_not_allowed", f"{method} is not allowed here")
    if rest[1] == UPLOAD and len(rest) == 2 and method == "POST":
        attachment = notes.add_attachment(
            entity_id, note_id, body["bytes"], body["media_type"], body["name"]
        )
        return 201, attachment
    if rest[1] == UPLOAD and len(rest) == 3 and method == "GET":
        file, kind = notes.attachment_file(entity_id, note_id, rest[2])
        return 200, FileBody(file.read_bytes(), kind, file.name, inline=True)
    if rest[1] == UPLOAD and len(rest) <= 3:
        raise BadRequest(405, "method_not_allowed", f"{method} is not allowed here")
    raise BadRequest(404, "route_not_found", "no such route")
