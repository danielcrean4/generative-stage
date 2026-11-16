"""One HTTP client for the v1 API: the base URL comes from the operator, every id is percent-encoded into its path
segment, writes carry `X-Studio-Request: 1`, and an error answer becomes an `ApiError` with the API's own code and
message (docs/api.md, "Conventions")."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

PREFIX = "/api/v1"
TIMEOUT_SECONDS = 60
OPENER = build_opener(ProxyHandler({}))  # the API is on this computer: never through a proxy


class ApiError(Exception):
    """The API refused the request, or could not be reached. `code` is the API's error code, or `unreachable`."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field

    def __str__(self) -> str:
        where = f" (at {self.field})" if self.field else ""
        return f"{self.code}: {self.message}{where}" + (
            f" [HTTP {self.status}]" if self.status else ""
        )


def segment(value: object) -> str:
    """One path segment: `/`, `..` and `%` in an id cannot change which route is called."""
    return quote(str(value), safe="")


class ApiClient:
    def __init__(self, base_url: str) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or not parts.hostname:
            raise ValueError(
                f"the API address must look like http://127.0.0.1:8780, not {base_url!r}"
            )
        self.base = f"http://{parts.netloc}{PREFIX}"

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Send one request; `path` is below /api/v1 and already encoded. Returns the decoded JSON answer."""
        url = self.base + path
        if query:
            url += "?" + urlencode({k: _text(v) for k, v in query.items()})
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if method != "GET":
            headers["X-Studio-Request"] = "1"
        try:
            with OPENER.open(
                Request(url, data, headers, method=method), timeout=TIMEOUT_SECONDS
            ) as reply:
                return json.loads(reply.read() or b"null")
        except HTTPError as error:
            raise _api_error(error) from None
        except (URLError, OSError) as error:
            raise ApiError(
                0, "unreachable", f"cannot reach the API at {self.base}: {error}"
            ) from None


def _text(value: object) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def _api_error(error: HTTPError) -> ApiError:
    try:
        detail = json.loads(error.read())["error"]
        return ApiError(error.code, detail["code"], detail["message"], detail.get("field"))
    except (ValueError, KeyError, TypeError):
        return ApiError(error.code, "http_error", f"the API answered {error.code} {error.reason}")
