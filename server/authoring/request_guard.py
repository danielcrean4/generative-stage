"""The localhost Host and Origin check, shared by every Studio HTTP server (8780 and 8781).

A local bind alone does not stop a web page in the owner's browser from calling a local server, so
each request must name this server's own address in Host and, if it sends Origin, in Origin too.
"""

from email.message import Message


def local_request_problem(headers: "Message[str, str]", port: int) -> str | None:
    """None if the request may proceed, else the message for a 403 response."""
    if headers.get("Host", "") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
        return "Local requests only"
    origin = headers.get("Origin")
    if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
        return "Cross-origin requests are not allowed"
    return None
