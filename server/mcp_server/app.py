"""The MCP server: lists the tools of tools.py and answers a call with one API request.

An argument is checked against the tool's closed schema before anything is sent, so a field the schema does not name is
refused. The answer is the API's JSON, as text and as structured content; an API error comes back as a tool error
carrying the API's code and message, so an agent can read it and correct itself.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import mcp_types as types
from jsonschema import Draft202012Validator
from mcp.server.lowlevel import Server

from mcp_server.client import ApiClient, ApiError, segment
from mcp_server.tools import BY_NAME, TOOLS, Tool

SERVER_NAME = "generative-stage"
VALIDATORS = {tool.name: Draft202012Validator(tool.schema()) for tool in TOOLS}


@dataclass(frozen=True)
class Context:
    client: ApiClient
    project: (
        str | None
    )  # the project every project tool works in; None until the operator names one


class ToolError(Exception):
    """A call that cannot be made; the message goes back to the agent."""


def _refusal(tool: Tool, arguments: dict[str, Any]) -> str | None:
    errors = sorted(VALIDATORS[tool.name].iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return None
    first = errors[0]
    where = "/" + "/".join(str(p) for p in first.path) if first.path else "the arguments"
    return f"{tool.name}: {where}: {first.message}"


def request_for(tool: Tool, arguments: dict[str, Any], project: str | None) -> dict[str, Any]:
    """The one API request a call makes: method, path (encoded), query and body. Pure, so tests can read it."""
    if tool.needs_project and not project:
        raise ToolError(
            "no project is set: start the server with --project SLUG (list_projects shows the slugs)"
        )
    values = {k: segment(v) for k, v in arguments.items()}
    path = tool.path.replace("{project}", segment(project or ""))
    for name in arguments:
        path = path.replace("{" + name + "}", values[name])
    query = {k: arguments[k] for k in tool.query if k in arguments}
    body = {tool.rename.get(k, k): arguments[k] for k in tool.body if k in arguments}
    sends_body = tool.method in ("POST", "PUT", "PATCH")
    return {
        "method": tool.method,
        "path": path,
        "query": query or None,
        "body": body if sends_body else None,
    }


def call(context: Context, name: str, arguments: dict[str, Any] | None) -> Any:
    """Run one tool and return the API's answer, shaped by the tool's view. Raises ToolError or ApiError."""
    tool = BY_NAME.get(name)
    if tool is None:
        raise ToolError(f"no tool {name!r} (tools: {', '.join(BY_NAME)})")
    arguments = arguments or {}
    refusal = _refusal(tool, arguments)
    if refusal:
        raise ToolError(refusal)
    made = request_for(tool, arguments, context.project)
    answer = context.client.request(
        made["method"], made["path"], query=made["query"], body=made["body"]
    )
    return tool.view(answer) if tool.view else answer


def _result(answer: Any) -> types.CallToolResult:
    structured = answer if isinstance(answer, dict) else {"result": answer}
    text = json.dumps(answer, indent=2, ensure_ascii=False)
    return types.CallToolResult(
        content=[types.TextContent(text=text)], structured_content=structured
    )


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=message)], is_error=True)


def build_server(context: Context) -> Server[Any]:
    async def on_list_tools(
        ctx: Any, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(name=t.name, description=t.description, input_schema=t.schema())
                for t in TOOLS
            ]
        )

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            answer = await asyncio.to_thread(call, context, params.name, params.arguments)
        except ToolError as error:
            return _error(str(error))
        except ApiError as error:
            return _error(str(error))
        return _result(answer)

    return Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)
