"""The errors core raises. Each carries a stable `code`, a message that is safe to show and, when
one value is at fault, the JSON pointer of that value in `field`. A front end maps the class to its
own answer (the HTTP server maps them to status codes); core knows nothing about HTTP."""


class CoreError(Exception):
    code = "error"

    def __init__(self, message: str, code: str | None = None, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.field = field


class NotFound(CoreError):
    """No project, kind, entity, revision or link with that id."""

    code = "not_found"


class Invalid(CoreError):
    """The data given does not fit: a field is missing, has the wrong shape or breaks a schema."""

    code = "invalid"


class Conflict(CoreError):
    """The request is well formed but clashes with the current state: a stale revision, a
    duplicate, an archived entity."""

    code = "conflict"


class BadProjectFiles(CoreError):
    """A file in the project folder (the project file, a kind descriptor, a schema, the link
    types) is wrong. The message names the file and the key or JSON pointer."""

    code = "bad_project_files"
