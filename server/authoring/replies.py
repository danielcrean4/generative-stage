"""The two replies besides plain JSON that a route can raise or return, shared by the route modules."""

from typing import NamedTuple

from core.errors import CoreError


class FileBody(NamedTuple):
    """A reply that is a file rather than JSON (an export's zip, a run's candidate).

    An image is sent `inline` so a page can show it; anything else is sent as a download."""

    data: bytes
    media_type: str
    filename: str
    inline: bool = False


class BadRequest(CoreError):
    """The request itself is malformed: not JSON, too large, an unknown route or method."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message, code, field)
        self.status = status
