"""Identifier shapes. A slug names a project; entity and link ids are opaque and never names."""

import re
from uuid import uuid4

SLUG = re.compile(r"[a-z][a-z0-9-]{0,48}")  # a project slug: lowercase letters, digits, hyphens
NAME_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")  # a kind or link type id, such as lives_in


def new_id() -> str:
    """A fresh opaque id for an entity or a link."""
    return str(uuid4())
