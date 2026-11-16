"""Notes on entities: free text, pins, mentions and image attachments, kept beside the project.

A note is not a revision: nothing here touches the entity or its store. The layout, in the
project folder, is plain files that are easy to read, back up or migrate:

    notes/<entity id>/notes.json                  {"format": "notes-1", "notes": [<note>, ...]}
    notes/<entity id>/files/<attachment id>.<ext> one image

    note = {"id", "created_at", "updated_at", "text", "pinned",
            "mentions": [{"kind", "id"}], "attachments": [{"id", "name", "media_type", "size"}]}

Notes are stored oldest first and listed newest first. This module checks shapes and sizes only;
whether a mentioned entity exists is the caller's business (see `parse_mentions`).
"""

import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.errors import BadProjectFiles, Invalid, NotFound
from core.ids import new_id

FORMAT = "notes-1"
NOTES_DIR = "notes"
MAX_TEXT = 5000
MAX_ATTACHMENTS = 8
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_NAME = 120
# The image types a note takes, each with the bytes its file must start with.
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MENTION = re.compile(r"@([a-z][a-z0-9_]{0,63})/([A-Za-z0-9][A-Za-z0-9-]{0,63})")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def parse_mentions(text: str) -> list[dict[str, str]]:
    """The `@kind/id` references in a text, once each, in order of appearance."""
    found: list[dict[str, str]] = []
    for kind, entity_id in MENTION.findall(text):
        ref = {"kind": kind, "id": entity_id}
        if ref not in found:
            found.append(ref)
    return found


def sniff_image(data: bytes) -> str | None:
    """The media type of an image from its first bytes, or None if it is not a png, jpeg or webp."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _text(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise Invalid(f"/text: expected text of at most {MAX_TEXT} characters", field="/text")
    return value.strip()


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise Invalid("/pinned: expected true or false", field="/pinned")
    return value


class Notes:
    """The notes of one project folder."""

    def __init__(self, project_root: Path) -> None:
        self.base = project_root / NOTES_DIR

    # Paths

    def _dir(self, entity_id: str) -> Path:
        if not _SAFE_ID.fullmatch(entity_id):
            raise NotFound(f"no entity {entity_id!r}", "entity_not_found")
        return self.base / entity_id

    def _file(self, entity_id: str) -> Path:
        return self._dir(entity_id) / "notes.json"

    def _read(self, entity_id: str) -> list[dict[str, Any]]:
        file = self._file(entity_id)
        if not file.is_file():
            return []
        try:
            doc = json.loads(file.read_text(encoding="utf-8"))
            if doc["format"] != FORMAT:
                raise ValueError(f"format {doc['format']!r}")
            notes: list[dict[str, Any]] = doc["notes"]
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise BadProjectFiles(f"{file}: not a notes file ({exc})", "bad_notes_file") from exc
        return notes

    def _write(self, entity_id: str, notes: list[dict[str, Any]]) -> None:
        folder = self._dir(entity_id)
        folder.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"format": FORMAT, "notes": notes}, out, ensure_ascii=False, indent=1)
        os.replace(temp, folder / "notes.json")

    def _find(self, notes: list[dict[str, Any]], note_id: str) -> dict[str, Any]:
        for note in notes:
            if note["id"] == note_id:
                return note
        raise NotFound(f"no note {note_id!r}", "note_not_found")

    # Notes

    def listing(self, entity_id: str) -> list[dict[str, Any]]:
        """Newest first."""
        with _LOCK:
            return list(reversed(self._read(entity_id)))

    def add(
        self,
        entity_id: str,
        text: object,
        pinned: object = False,
        mentions: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        clean = _text(text)
        with _LOCK:
            notes = self._read(entity_id)
            now = _now()
            note: dict[str, Any] = {
                "id": new_id(),
                "created_at": now,
                "updated_at": now,
                "text": clean,
                "pinned": _flag(pinned),
                "mentions": mentions if mentions is not None else parse_mentions(clean),
                "attachments": [],
            }
            notes.append(note)
            self._write(entity_id, notes)
            return note

    def update(
        self,
        entity_id: str,
        note_id: str,
        text: object | None,
        pinned: object | None,
        mentions: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        with _LOCK:
            notes = self._read(entity_id)
            note = self._find(notes, note_id)
            if text is not None:
                note["text"] = _text(text)
                note["mentions"] = (
                    mentions if mentions is not None else parse_mentions(note["text"])
                )
            if pinned is not None:
                note["pinned"] = _flag(pinned)
            note["updated_at"] = _now()
            self._write(entity_id, notes)
            return note

    def delete(self, entity_id: str, note_id: str) -> None:
        with _LOCK:
            notes = self._read(entity_id)
            note = self._find(notes, note_id)
            self._write(entity_id, [n for n in notes if n is not note])
            for attachment in note["attachments"]:
                self._path_of(entity_id, attachment).unlink(missing_ok=True)

    # Attachments

    def _path_of(self, entity_id: str, attachment: dict[str, Any]) -> Path:
        return (
            self._dir(entity_id)
            / "files"
            / f"{attachment['id']}.{IMAGE_TYPES[attachment['media_type']]}"
        )

    def add_attachment(
        self, entity_id: str, note_id: str, data: bytes, media_type: str | None, name: object
    ) -> dict[str, Any]:
        """Store an image on a note. The bytes must be what the media type says, and a png, jpeg or
        webp within the size cap."""
        if media_type not in IMAGE_TYPES:
            raise Invalid("only png, jpeg and webp images can be attached", "unsupported_type")
        if len(data) > MAX_IMAGE_BYTES:
            raise Invalid(f"the image is larger than {MAX_IMAGE_BYTES} bytes", "too_large")
        if sniff_image(data) != media_type:
            raise Invalid(f"the file is not a {media_type} image", "unsupported_type")
        label = name.strip()[:MAX_NAME] if isinstance(name, str) else ""
        with _LOCK:
            notes = self._read(entity_id)
            note = self._find(notes, note_id)
            if len(note["attachments"]) >= MAX_ATTACHMENTS:
                raise Invalid(f"a note takes at most {MAX_ATTACHMENTS} images", "too_many")
            attachment = {
                "id": new_id(),
                "name": label or "image",
                "media_type": media_type,
                "size": len(data),
            }
            target = self._path_of(entity_id, attachment)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            note["attachments"].append(attachment)
            note["updated_at"] = _now()
            self._write(entity_id, notes)
            return attachment

    def attachment_file(self, entity_id: str, note_id: str, attachment_id: str) -> tuple[Path, str]:
        """The file and media type of an attachment the note records. The id is looked up in the
        note, never joined into a path, and the resolved file must sit in the entity's folder."""
        with _LOCK:
            note = self._find(self._read(entity_id), note_id)
        for attachment in note["attachments"]:
            if attachment["id"] == attachment_id:
                path = self._path_of(entity_id, attachment)
                folder = self._dir(entity_id).resolve()
                try:
                    real = path.resolve(strict=True)
                except OSError as exc:
                    raise NotFound("the image file is missing", "attachment_not_found") from exc
                if not real.is_relative_to(folder):
                    raise NotFound("no such attachment", "attachment_not_found")
                return real, attachment["media_type"]
        raise NotFound(f"no attachment {attachment_id!r}", "attachment_not_found")
