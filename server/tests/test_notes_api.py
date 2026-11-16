"""Notes on entities through the public HTTP surface: text, pins, mentions, image attachments."""

import json
from http.client import HTTPConnection
from typing import Any

from test_api_v1 import Api, api, entity, fetch, project  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 " + b"\x00" * 16
WRITE = {"X-Studio-Request": "1"}


def upload(
    api: Api,
    path: str,
    data: bytes,
    kind: str = "image/png",
    headers: dict[str, str] | None = None,
    declared: int | None = None,
) -> tuple[int, Any]:
    """POST a raw image; `declared` lies about the length to test the size cap without sending it."""
    client = HTTPConnection("127.0.0.1", api.port, timeout=10)
    try:
        sent = {**WRITE, "Content-Type": kind, "X-File-Name": "my%20shot.png", **(headers or {})}
        sent["Content-Length"] = str(len(data) if declared is None else declared)
        client.putrequest("POST", path, skip_accept_encoding=True)
        for name, value in sent.items():
            client.putheader(name, value)
        client.endheaders(data)
        response = client.getresponse()
        return response.status, json.loads(response.read())
    finally:
        client.close()


def make(api: Api, project: str) -> tuple[dict[str, Any], str]:
    key = entity(api, project, "prop", "Key")
    return key, f"{project}/entities/{key['id']}/notes"


def test_create_list_edit_pin_delete(api: Api, project: str) -> None:
    key, base = make(api, project)
    assert api.ok("GET", base) == {"notes": []}
    first = api.ok("POST", base, {"text": "  the key is too big  "}, 201)
    assert first["text"] == "the key is too big"
    assert (first["pinned"], first["mentions"], first["attachments"]) == (False, [], [])
    assert first["created_at"] == first["updated_at"]
    second = api.ok("POST", base, {"text": "brass, not iron", "pinned": True}, 201)
    assert second["pinned"] is True
    assert [n["id"] for n in api.ok("GET", base)["notes"]] == [second["id"], first["id"]]

    edited = api.ok("PATCH", f"{base}/{first['id']}", {"text": "smaller", "pinned": True})
    assert (edited["text"], edited["pinned"]) == ("smaller", True)
    assert edited["updated_at"] >= first["updated_at"]
    unpinned = api.ok("PATCH", f"{base}/{first['id']}", {"pinned": False})
    assert (unpinned["text"], unpinned["pinned"]) == ("smaller", False)

    gone = api.ok("DELETE", f"{base}/{first['id']}")
    assert gone["deleted"] is True
    assert [n["id"] for n in api.ok("GET", base)["notes"]] == [second["id"]]
    api.fails("DELETE", f"{base}/{first['id']}", None, 404, "note_not_found")
    api.fails("PATCH", f"{base}/{first['id']}", {"text": "x"}, 404, "note_not_found")


def test_a_note_never_changes_the_entity(api: Api, project: str) -> None:
    key, base = make(api, project)
    entity_path = f"{project}/entities/{key['id']}"
    before = api.ok("GET", entity_path)
    note = api.ok("POST", base, {"text": "a thought"}, 201)
    api.ok("PATCH", f"{base}/{note['id']}", {"pinned": True})
    assert upload(api, f"{base}/{note['id']}/attachments", PNG)[0] == 201
    api.ok("DELETE", f"{base}/{note['id']}")
    assert api.ok("GET", entity_path) == before
    assert len(api.ok("GET", f"{entity_path}/revisions")["revisions"]) == 1


def test_bad_notes_are_refused(api: Api, project: str) -> None:
    key, base = make(api, project)
    api.fails("POST", base, {"text": "x" * 5001}, 422, "invalid", "/text")
    api.fails("POST", base, {"text": 5}, 422, "invalid", "/text")
    api.fails("POST", base, {"text": "x", "pinned": "yes"}, 422, "invalid", "/pinned")
    note = api.ok("POST", base, {"text": "x"}, 201)
    api.fails("PATCH", f"{base}/{note['id']}", {"text": "x" * 5001}, 422, "invalid", "/text")
    api.fails("PUT", base, {}, 405, "method_not_allowed")
    api.fails("POST", f"{base}/{note['id']}", {}, 405, "method_not_allowed")
    api.fails("GET", f"{base}/{note['id']}/other", None, 404, "route_not_found")
    # An unknown entity has no notes, and cannot be given any.
    api.fails("GET", f"{project}/entities/nobody/notes", None, 404, "entity_not_found")
    api.fails("POST", f"{project}/entities/nobody/notes", {"text": "x"}, 404, "entity_not_found")
    api.fails("GET", f"{project}/entities/..%2F..%2Fx/notes", None, 404, "entity_not_found")


def test_writes_need_the_studio_header(api: Api, project: str) -> None:
    key, base = make(api, project)
    got, data = api.call("POST", base, {"text": "x"}, headers={})
    assert got == 403, data
    note = api.ok("POST", base, {"text": "x"}, 201)
    assert api.call("PATCH", f"{base}/{note['id']}", {"pinned": True}, headers={})[0] == 403
    assert api.call("DELETE", f"{base}/{note['id']}", None, headers={})[0] == 403
    assert (
        upload(api, f"{base}/{note['id']}/attachments", PNG, headers={"X-Studio-Request": "0"})[0]
        == 403
    )
    assert api.ok("GET", base)["notes"][0]["pinned"] is False


def test_mentions_come_from_the_text_and_from_picks(api: Api, project: str) -> None:
    key, base = make(api, project)
    mechanic = entity(api, project, "character", "Mechanic")
    text = f"ask @character/{mechanic['id']} about it, and @prop/nothing, and @prop/{key['id']}"
    note = api.ok("POST", base, {"text": text}, 201)
    assert note["mentions"] == [
        {"kind": "character", "id": mechanic["id"]},
        {"kind": "prop", "id": key["id"]},
    ]
    # A wrong kind on a real id is not a mention.
    wrong = api.ok("POST", base, {"text": f"@prop/{mechanic['id']}"}, 201)
    assert wrong["mentions"] == []
    picked = api.ok("POST", base, {"text": "see her", "mentions": [{"id": mechanic["id"]}]}, 201)
    assert picked["mentions"] == [{"kind": "character", "id": mechanic["id"]}]
    api.fails("POST", base, {"text": "x", "mentions": [{"id": "nobody"}]}, 404, "entity_not_found")
    api.fails("POST", base, {"text": "x", "mentions": "all"}, 422, "invalid", "/mentions")
    # Editing the text re-reads the mentions.
    edited = api.ok("PATCH", f"{base}/{note['id']}", {"text": "no one now"})
    assert edited["mentions"] == []


def test_images_attach_and_are_served(api: Api, project: str) -> None:
    key, base = make(api, project)
    note = api.ok("POST", base, {"text": ""}, 201)
    path = f"{base}/{note['id']}/attachments"
    served = {}
    for data, kind in ((PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")):
        status, attachment = upload(api, path, data, kind)
        assert status == 201, attachment
        assert (attachment["media_type"], attachment["size"], attachment["name"]) == (
            kind,
            len(data),
            "my shot.png",
        )
        served[attachment["id"]] = (data, kind)
    listed = api.ok("GET", base)["notes"][0]["attachments"]
    assert [a["id"] for a in listed] == list(served)
    for attachment_id, (data, kind) in served.items():
        status, got_kind, headers, body = fetch(api, f"{path}/{attachment_id}")
        assert (status, got_kind, body) == (200, kind, data)
        assert headers["content-disposition"].startswith("inline;")
        assert headers["x-content-type-options"] == "nosniff"
    # Deleting the note deletes its files.
    files = list((api.root / "sample" / "notes" / key["id"] / "files").iterdir())
    assert len(files) == 3
    api.ok("DELETE", f"{base}/{note['id']}")
    assert list((api.root / "sample" / "notes" / key["id"] / "files").iterdir()) == []
    assert fetch(api, f"{path}/{next(iter(served))}")[0] == 404


def test_attachments_are_checked(api: Api, project: str) -> None:
    key, base = make(api, project)
    note = api.ok("POST", base, {"text": "x"}, 201)
    path = f"{base}/{note['id']}/attachments"

    def refused(data: bytes, kind: str, status: int, code: str, **more: Any) -> None:
        got, body = upload(api, path, data, kind, **more)
        assert (got, body["error"]["code"]) == (status, code), body

    refused(PNG, "image/gif", 422, "unsupported_type")
    refused(PNG, "text/html", 422, "unsupported_type")
    refused(b"<script>alert(1)</script>", "image/png", 422, "unsupported_type")  # not a png
    refused(JPEG, "image/png", 422, "unsupported_type")  # a jpeg called a png
    refused(PNG, "", 422, "unsupported_type")
    refused(PNG, "image/png", 413, "too_large", declared=5 * 1024 * 1024 + 1)
    for _ in range(8):
        assert upload(api, path, PNG)[0] == 201
    refused(PNG, "image/png", 422, "too_many")
    assert upload(api, f"{base}/nope/attachments", PNG)[1]["error"]["code"] == "note_not_found"
    got, body = upload(api, f"{project}/entities/nobody/notes/{note['id']}/attachments", PNG)
    assert (got, body["error"]["code"]) == (404, "entity_not_found")
    assert len(api.ok("GET", base)["notes"][0]["attachments"]) == 8


def test_attachment_paths_cannot_leave_the_note(api: Api, project: str) -> None:
    key, base = make(api, project)
    other = entity(api, project, "prop", "Lamp")
    note = api.ok("POST", base, {"text": "x"}, 201)
    lamp_note = api.ok("POST", f"{project}/entities/{other['id']}/notes", {"text": "y"}, 201)
    _, attachment = upload(api, f"{base}/{note['id']}/attachments", PNG)
    (api.root / "secret.png").write_bytes(PNG)
    path = f"{base}/{note['id']}/attachments"

    def refused(url: str) -> None:
        status, kind, _, body = fetch(api, url)
        assert status == 404 and "json" in kind, body
        assert json.loads(body)["error"]["code"] in {
            "attachment_not_found",
            "note_not_found",
            "entity_not_found",
            "route_not_found",
        }

    refused(f"{path}/..%2F..%2F..%2Fnotes.json")
    refused(f"{path}/..%2Fnotes.json")
    refused(f"{path}/%2e%2e%2f%2e%2e%2fsecret.png")
    refused(f"{path}/{attachment['id']}.png")
    refused(f"{path}/{attachment['id']}%2F..%2F{attachment['id']}")
    refused(f"{path}/missing")
    # Another note, or another entity's note, cannot reach this attachment.
    refused(f"{base}/{lamp_note['id']}/attachments/{attachment['id']}")
    refused(f"{project}/entities/{other['id']}/notes/{note['id']}/attachments/{attachment['id']}")
    refused(f"{project}/entities/..%2F..%2F/notes/{note['id']}/attachments/{attachment['id']}")
    # A note record naming a path of its own is still served only from the entity's folder.
    store = api.root / "sample" / "notes" / key["id"] / "notes.json"
    doc = json.loads(store.read_text())
    doc["notes"][0]["attachments"][0]["id"] = "../../../../secret"
    store.write_text(json.dumps(doc))
    refused(f"{path}/..%2F..%2F..%2F..%2Fsecret")
    api.fails("POST", f"{path}/{attachment['id']}", {}, 405, "method_not_allowed")
    api.fails("DELETE", f"{path}/{attachment['id']}", None, 405, "method_not_allowed")


def test_notes_are_plain_files_in_the_project_folder(api: Api, project: str) -> None:
    key, base = make(api, project)
    note = api.ok("POST", base, {"text": "hello", "pinned": True}, 201)
    doc = json.loads((api.root / "sample" / "notes" / key["id"] / "notes.json").read_text())
    assert doc == {"format": "notes-1", "notes": [note]}
    (api.root / "sample" / "notes" / key["id"] / "notes.json").write_text("{not json")
    api.fails("GET", base, None, 422, "bad_notes_file")
