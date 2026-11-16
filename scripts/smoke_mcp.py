"""Steps 3 to 5 of the walkthrough through the MCP server, as an agent does them (run by smoke.py with `--mcp-python`).

    server/.venv/bin/python scripts/smoke_mcp.py http://127.0.0.1:4280 PROJECT_SLUG

PROJECT_SLUG is an empty project. Starts `python -m mcp_server` on standard input and output, writes briefs for a setting,
a character and a prop, links them, runs the prop on the stand-in adapters, reads the run's trace and exports. Prints one
line per step; any failure raises.
"""

import asyncio
import json
import sys
import time
from typing import Any

from mcp import Client, StdioServerParameters


async def use(client: Client, name: str, **arguments: Any) -> Any:
    result = await client.call_tool(name, arguments)
    assert not result.is_error, f"{name}: {result.content}"
    return result.structured_content


async def main(api: str, project: str) -> None:
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server", "--api", api, "--project", project])
    async with Client(parameters) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert {"create_entity", "create_link", "start_run", "get_trace", "export_bundle"} <= tools, sorted(tools)
        print(f"MCP: {len(tools)} tools listed")
        cove = await use(client, "create_entity", kind="setting", data={"name": "Quay", "brief": "A stone quay with a crane."})
        keeper = await use(client, "create_entity", kind="character", data={"name": "Harbour master", "brief": "Watches the quay."})
        buoy = await use(client, "create_entity", kind="prop", data={"name": "Buoy", "brief": "A red marker buoy.", "size": "arm"})
        await use(client, "create_link", type="lives_in", source=keeper["id"], target=cove["id"])
        await use(client, "create_link", type="found_in", source=buoy["id"], target=cove["id"])
        print("MCP: a setting, a character and a prop written and linked")
        started = await use(
            client, "start_run", entity_id=buoy["id"], pipeline="prop", prompt="a red marker buoy",
            adapters={"image": "standin-image", "image-to-mesh": "standin-mesh"}, choices={"seed": 3},
        )  # fmt: skip
        run_id = started["job"]["id"]
        deadline = time.monotonic() + 180
        while True:
            done = await use(client, "get_run", run_id=run_id)
            status = done["runs"][0]["status"]
            if status in ("succeeded", "failed"):
                break
            assert time.monotonic() < deadline, "the run did not finish in 180 s"
            await asyncio.sleep(0.5)
        assert status == "succeeded", done["runs"][0]["log_tail"]
        trace = await use(client, "get_trace", entity_id=buoy["id"], run_id=run_id)
        stages = {s["id"]: s["status"] for s in trace["stages"]}
        assert stages.get("concept") == "completed" and stages.get("mesh") == "completed", stages
        print(f"MCP: prop run on the stand-in succeeded; trace has {len(stages)} stages, all completed")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
