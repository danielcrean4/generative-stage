"""Steps 3 to 5 of the 1.0 walkthrough, done the way an agent would: over MCP on stdio, against a real HTTP server on a
temporary port and project, with the stand-in adapters only (no model, no GPU)."""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from running_server import Running
from test_api_v1 import Api

SERVER_DIR = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "list_projects", "list_kinds", "list_link_types", "get_vocabulary", "check_condition", "get_story_graph", "list_entities", "get_entity", "create_entity",
    "update_entity", "list_links", "create_link", "delete_link", "add_note", "list_pipelines",
    "list_adapters", "start_run", "get_run", "get_trace", "list_sources", "get_source", "choose_candidate",
    "export_bundle",
}  # fmt: skip


async def use(client: Client, name: str, **arguments: Any) -> Any:
    result = await client.call_tool(name, arguments)
    assert not result.is_error, f"{name}: {result.content}"
    return result.structured_content


async def wait_for_run(client: Client, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        done = await use(client, "get_run", run_id=run_id)
        status = done["runs"][0]["status"]
        if status in ("succeeded", "failed"):
            return done  # type: ignore[no-any-return]
        await asyncio.sleep(0.5)
    raise AssertionError("the run did not finish")


async def walk(port: int, project: str) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server", "--api", f"http://127.0.0.1:{port}", "--project", project],
        cwd=SERVER_DIR,
    )
    seen: dict[str, Any] = {}
    async with Client(parameters) as client:
        listed = await client.list_tools()
        seen["tools"] = {t.name for t in listed.tools}
        assert (await use(client, "list_projects"))["projects"] == [
            {"slug": project, "name": "Sample", "problem": None}
        ]
        kinds = {k["id"] for k in (await use(client, "list_kinds"))["kinds"]}
        assert {"setting", "character", "prop"} <= kinds

        # Step 3: briefs for a setting, a character and a prop, and the links between them.
        town = await use(
            client, "create_entity", kind="setting",
            data={"name": "Workshop", "brief": "A small workshop with a bench and a window."},
        )  # fmt: skip
        guide = await use(
            client, "create_entity", kind="character",
            data={"name": "Guide", "brief": "Shows visitors around the town.", "role": "guide"},
        )  # fmt: skip
        key = await use(
            client, "create_entity", kind="prop",
            data={"name": "Key", "brief": "A key to the storage room.", "size": "hand"},
        )  # fmt: skip
        ids = {"setting": town["id"], "character": guide["id"], "prop": key["id"]}
        await use(client, "create_link", type="lives_in", source=guide["id"], target=town["id"])
        await use(client, "create_link", type="belongs_to", source=key["id"], target=guide["id"])
        extra = await use(
            client, "create_link", type="found_in", source=key["id"], target=town["id"]
        )
        await use(client, "delete_link", link_id=extra["id"])
        seen["links"] = (await use(client, "list_links", entity_id=key["id"]))["links"]
        await use(client, "add_note", entity_id=key["id"], text="The key should look worn.")
        revised = await use(
            client, "update_entity", entity_id=key["id"], revision=key["revision"],
            data={**key["data"], "material": "brass"}, note="material",
        )  # fmt: skip
        assert revised["revision"] == 2
        stale = await client.call_tool(
            "update_entity",
            {"entity_id": key["id"], "revision": 1, "data": key["data"]},
        )
        assert stale.is_error and "revision_conflict" in json.dumps(
            [c.model_dump() for c in stale.content]
        )

        # Step 4: choose the pipeline and the adapters by id, run the prop on the stand-in, choose a candidate.
        adapters = (await use(client, "list_adapters"))["adapters"]
        assert {a["id"] for a in adapters if a["default"]} >= {"standin-image", "standin-mesh"}
        pipelines = (await use(client, "list_pipelines"))["pipelines"]
        assert "prop" in {p["id"] for p in pipelines}
        prop = next(p for p in pipelines if p["id"] == "prop")
        assert prop["choices"]["style"]["options"] == ["clay", "vinyl_toy"]
        refused = await client.call_tool(
            "start_run",
            {"entity_id": key["id"], "pipeline": "prop", "prompt": "x",
             "adapters": {"image": "standin-image"}, "command": ["/bin/sh"]},
        )  # fmt: skip
        assert refused.is_error  # a field the schema does not name never reaches the API
        started = await use(
            client, "start_run", entity_id=key["id"], pipeline="prop", prompt="a brass key",
            adapters={"image": "standin-image", "image-to-mesh": "standin-mesh"},
            choices={"style": "vinyl_toy", "seed": 7},
        )  # fmt: skip
        run_id = started["job"]["id"]
        done = await wait_for_run(client, run_id)
        assert done["runs"][0]["status"] == "succeeded", done["runs"][0]["log_tail"]
        candidates = [c["candidate"] for c in done["candidates"]]
        assert started["job"]["recipe"]["choices"]["style"] == "vinyl_toy"
        concept = next(c for c in candidates if c.endswith("concept/image.png"))
        mesh = next(c for c in candidates if c.startswith("final/"))
        await use(client, "choose_candidate", entity_id=key["id"], run_id=run_id, candidate=concept)
        await use(
            client, "choose_candidate", entity_id=key["id"], run_id=run_id, candidate=mesh,
            slot="mesh", note="the mesh",
        )  # fmt: skip

        # Step 5: the trace.
        seen["trace"] = await use(client, "get_trace", entity_id=key["id"], run_id=run_id)
        seen["sources"] = await use(client, "list_sources")
        seen["source"] = await use(client, "get_source", type="style", source_id="prop.vinyl_toy")
        seen["export"] = await use(client, "export_bundle", kinds=["prop"])
        seen["ids"], seen["run_id"] = ids, run_id
    return seen


def test_an_agent_does_steps_three_to_five_over_mcp(
    tmp_path: Path, standin_environment: Path
) -> None:
    found = Running(tmp_path)
    found.start_dispatcher()
    try:
        seen = asyncio.run(walk(found.api.port, "sample"))
        api: Api = found.api
        project, ids = found.project, seen["ids"]

        assert seen["tools"] == EXPECTED_TOOLS
        # The records and links exist in the world model, whichever door they came through.
        records = api.ok("GET", f"{project}/entities")["entities"]
        assert {r["kind"] for r in records} == {"setting", "character", "prop"}
        prop = api.ok("GET", f"{project}/entities/{ids['prop']}")
        assert prop["revision"] == 2 and prop["data"]["material"] == "brass"
        assert [(link["type"], link["direction"]) for link in seen["links"]] == [
            ("belongs_to", "out")
        ]
        out = api.ok("GET", f"{project}/entities/{ids['prop']}/links")["links"]
        assert [link["type"] for link in out] == ["belongs_to"]
        notes = api.ok("GET", f"{project}/entities/{ids['prop']}/notes")["notes"]
        assert [n["text"] for n in notes] == ["The key should look worn."]

        # The run, the choices and the trace.
        runs = api.ok("GET", f"{project}/entities/{ids['prop']}/runs")["runs"]
        assert [r["run_id"] for r in runs] == [seen["run_id"]]
        chosen = api.ok("GET", f"{project}/entities/{ids['prop']}/chosen")["chosen"]
        assert set(chosen) == {"main", "mesh"} and chosen["main"]["run_id"] == seen["run_id"]
        trace = seen["trace"]
        stages = {s["id"]: s for s in trace["stages"]}
        assert trace["status"] == "generated" and trace["entity"]["id"] == ids["prop"]
        assert (
            stages["concept"]["status"] == "completed" and stages["mesh"]["status"] == "completed"
        )
        assert "a brass key" in stages["concept"]["prompt"]
        parts = stages["concept"]["prompt_parts"]
        assert "".join(p["text"] for p in parts) == stages["concept"]["prompt"]
        assert {"style", "motif", "contract"} <= {s["type"] for s in seen["sources"]["sources"]}
        assert [r["entity"]["id"] for r in seen["source"]["used_by"]] == [ids["prop"]]
        assert stages["concept"]["adapter"]["adapter_id"] == "standin-image"
        assert stages["mesh"]["adapter"]["adapter_id"] == "standin-mesh"
        assert set(trace["chosen"]) == {"main", "mesh"} and seen["export"]["entities"] == 1
    finally:
        found.close()
