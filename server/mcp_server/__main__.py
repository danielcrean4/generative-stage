"""Run the MCP server on stdin and stdout.

    python -m mcp_server --api http://127.0.0.1:8780 --project my-project

Both can come from the environment instead: GENSTAGE_API_URL and GENSTAGE_PROJECT.
"""

import argparse
import asyncio
import os
import sys

from mcp.server.stdio import stdio_server

from mcp_server.app import Context, build_server
from mcp_server.client import ApiClient

DEFAULT_API = "http://127.0.0.1:8780"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MCP server over the Generative Stage v1 HTTP API")
    parser.add_argument("--api", default=os.environ.get("GENSTAGE_API_URL") or DEFAULT_API)
    parser.add_argument("--project", default=os.environ.get("GENSTAGE_PROJECT"))
    args = parser.parse_args(argv)
    try:
        client = ApiClient(args.api)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    server = build_server(Context(client, args.project or None))

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    print(f"MCP server for {client.base} (project: {args.project or 'none'})", file=sys.stderr)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
