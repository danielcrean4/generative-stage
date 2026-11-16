"""Prompt parts in the trace, the source pages and the profile's feeds, over a real run on the stand-in adapters."""

from http.client import HTTPConnection
from pathlib import Path
from typing import Any

import pytest
from running_server import Running
from test_api_v1 import entity

from authoring import source_catalog


@pytest.fixture
def made(tmp_path: Path, standin_environment: Path) -> Any:
    """A prop with one finished `prop` pipeline run (style clay, motif repair_shop)."""
    found = Running(tmp_path)
    api, project = found.api, found.project
    record = entity(api, project, "prop", "Sample")
    request = {
        "pipeline": "prop",
        "prompt": "a brass key",
        "adapters": {"image": "standin-image"},
        "choices": {"seed": 5},
    }
    job = api.ok("POST", f"{project}/entities/{record['id']}/jobs", request, 202)["job"]
    assert found.dispatcher.run_next(timeout=0)
    try:
        yield found, record, job["id"]
    finally:
        found.close()


def test_the_trace_prompt_is_its_parts_and_each_part_links_to_its_source(made: Any) -> None:
    found, record, run = made
    trace = found.api.ok("GET", f"{found.project}/entities/{record['id']}/runs/{run}/trace")
    concept = trace["stages"][0]
    parts = concept["prompt_parts"]
    assert "".join(p["text"] for p in parts) == concept["prompt"]
    by_kind = {p["source"]["kind"]: p["source"] for p in parts}
    assert by_kind["subject"]["link"] == {"type": "entity", "id": record["id"], "kind": "prop"}
    assert by_kind["style_pack"]["link"] == {"type": "style", "id": "prop.clay", "changed": False}
    assert by_kind["motif"]["link"] == {"type": "motif", "id": "prop.repair_shop", "changed": False}
    assert by_kind["pipeline"]["link"] is None and by_kind["glue"]["link"] is None
    negative = concept["negative_parts"]
    assert "".join(p["text"] for p in negative) == concept["negative"]
    assert negative[0]["source"]["link"]["id"] == "prop.vinyl_toy"  # inherited from the parent pack


def test_a_source_page_shows_its_words_where_it_lives_and_who_read_it(made: Any) -> None:
    found, record, run = made
    page = found.api.ok("GET", f"{found.project}/sources/style/prop.clay")
    assert page["editable"] is False
    assert page["location"] == "pipeline/pipelines/examples/prop/styles/clay/style.json"
    assert [e["id"] for e in page["extends"]] == ["prop.vinyl_toy"]
    texts = {t["key"]: t for t in page["texts"]}
    assert "hand-sculpted clay" in texts["prompt.templates.prop"]["text"]
    assert texts["prompt.negative"]["from"] == "prop.vinyl_toy"
    assert {p["id"] for p in page["pipelines"]} == {"prop", "mesh"}
    [reader] = page["used_by"]
    assert reader["entity"]["id"] == record["id"] and reader["run_id"] == run
    assert reader["changed"] is False and reader["status"] in ("generated", "review")
    assert reader["thumbnail"] and f"/runs/{run}/files/" in reader["thumbnail"]
    client = HTTPConnection("127.0.0.1", found.api.port, timeout=10)
    client.request("GET", reader["thumbnail"])
    reply = client.getresponse()
    assert reply.status == 200 and reply.getheader("Content-Type") == "image/png"
    client.close()
    parent = found.api.ok("GET", f"{found.project}/sources/style/prop.vinyl_toy")
    assert parent["used_by"] == []  # the run read clay; the parent is only inherited from


def test_motif_and_contract_pages(made: Any) -> None:
    found, record, _ = made
    motif = found.api.ok("GET", f"{found.project}/sources/motif/prop.repair_shop")
    assert motif["texts"][0]["text"] == "repair-shop, brass and recycled parts"
    assert [r["entity"]["id"] for r in motif["used_by"]] == [record["id"]]
    assert found.api.ok("GET", f"{found.project}/sources/motif/prop.plain")["used_by"] == []
    contract = found.api.ok("GET", f"{found.project}/sources/contract/prop.contract")
    assert contract["texts"] == [] and "no words" in contract["note"]
    assert contract["content"]["face_budget"] == 8000
    assert len(contract["used_by"]) == 1


def test_the_index_lists_every_source_and_unknown_ones_are_not_found(made: Any) -> None:
    found, _, _ = made
    listed = found.api.ok("GET", f"{found.project}/sources")["sources"]
    ids = {(s["type"], s["id"]) for s in listed}
    assert {
        ("style", "prop.clay"),
        ("motif", "head.storybook"),
        ("contract", "tracer.contract"),
    } <= ids
    found.api.fails(
        "GET", f"{found.project}/sources/style/prop.nothing", None, 404, "source_not_found"
    )
    found.api.fails(
        "GET", f"{found.project}/sources/style/prop.clay/extra", None, 404, "route_not_found"
    )
    found.api.fails("POST", f"{found.project}/sources", {}, 405, "method_not_allowed")


def test_the_profile_lists_the_sources_its_last_run_read(made: Any) -> None:
    found, record, run = made
    feeds = found.api.ok("GET", f"{found.project}/entities/{record['id']}/sources")
    assert feeds["run_id"] == run
    assert [(s["type"], s["id"], s["changed"]) for s in feeds["sources"]] == [
        ("style", "prop.clay", False),
        ("motif", "prop.repair_shop", False),
        ("contract", "prop.contract", False),
        ("pipeline", None, False),
    ]
    other = entity(found.api, found.project, "prop", "Never run")
    empty = found.api.ok("GET", f"{found.project}/entities/{other['id']}/sources")
    assert empty == {"run_id": None, "attempt_id": None, "sources": []}


def test_a_run_that_read_an_older_file_says_so() -> None:
    clay = source_catalog.get("style", "prop.clay")
    assert clay is not None
    now = {"style": {"id": "clay", "flattened_sha256": clay.flattened_sha256}}
    assert source_catalog.refs_of(now, "prop")[0]["changed"] is False
    old = {"style": {"id": "clay", "flattened_sha256": "0" * 64}}
    assert source_catalog.refs_of(old, "prop")[0]["changed"] is True
    # without the run's pipeline the match is by hash, so an old hash finds nothing
    assert source_catalog.refs_of(old, None)[0]["id"] is None
    assert source_catalog.refs_of(now, None)[0]["id"] in {"prop.clay"}
    gone = {"style": {"id": "vanished", "flattened_sha256": "0" * 64}}
    assert source_catalog.refs_of(gone, "prop")[0]["id"] is None
