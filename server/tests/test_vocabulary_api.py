"""The vocabulary routes (/api/v1/projects/<slug>/vocabulary) through HTTP: read, replace, check a
condition as an editor would, and a kind that marks values refusing bad ones on write."""

import json
import shutil
from pathlib import Path

from test_api_v1 import Api, api, project  # noqa: F401  (fixtures)

FIXTURE = Path(__file__).resolve().parents[2] / "core" / "tests" / "fixtures" / "lighthouse"


def lighthouse(api: Api, project: str) -> Path:  # noqa: F811
    """Swap the sample project's kinds for the invented lighthouse kinds and vocabulary."""
    kinds = api.root / "sample" / "kinds"
    shutil.rmtree(kinds)
    shutil.copytree(FIXTURE, kinds)
    return kinds


def test_a_project_without_a_vocabulary(api: Api, project: str) -> None:  # noqa: F811
    assert api.ok("GET", f"{project}/vocabulary") == {"vocabulary": None}
    api.fails("POST", f"{project}/vocabulary/check", {"condition": {}}, 404, "no_vocabulary")


def test_put_get_and_check(api: Api, project: str) -> None:  # noqa: F811
    raw = json.loads((FIXTURE / "vocabulary.json").read_text())
    bad = json.loads(json.dumps(raw))
    bad["operators"]["eq"]["types"] = ["text"]
    api.fails("PUT", f"{project}/vocabulary", bad, 422, "invalid", "/operators/eq/types/0")
    assert api.ok("GET", f"{project}/vocabulary") == {"vocabulary": None}
    assert api.ok("PUT", f"{project}/vocabulary", raw)["vocabulary"]["source"] == raw["source"]
    assert api.ok("GET", f"{project}/vocabulary")["vocabulary"] == raw
    good = {
        "all": [{"fact": "errand(fetch_oil).step", "gte": 10}, {"fact": "keeper.oil", "gte": 1}]
    }
    checked = api.ok("POST", f"{project}/vocabulary/check", {"condition": good})
    assert checked["problems"] == [] and checked["shorthand"] is False
    assert checked["text"] == "errand(fetch_oil).step is at least 10 and keeper.oil is at least 1"
    assert [r["path"] for r in checked["reads"]] == ["errand(fetch_oil).step", "keeper.oil"]
    typing = {
        "all": [{"fact": "errand(fetch_oil).ste"}]
    }  # half typed: problems are data, not an error
    checked = api.ok("POST", f"{project}/vocabulary/check", {"condition": typing})
    assert checked["problems"][0]["field"] == "/all/0"
    effects = api.ok(
        "POST",
        f"{project}/vocabulary/check",
        {"effects": [{"do": "say", "text": "Hello"}, {"do": "fly"}]},
    )
    assert effects["problems"] == [
        {
            "field": "/1/do",
            "message": "'fly' is not an effect (known: advance, light, say, set_mark)",
        }
    ]
    assert effects["text"] == "say text Hello; fly"
    assert (
        api.ok("POST", f"{project}/vocabulary/check", {"fact": "keeper.seen"})["reads"][0]["type"]
        == "id_set"
    )
    assert api.ok("POST", f"{project}/vocabulary/check", {"rule_mode": "once"})["problems"] == []
    api.fails(
        "POST", f"{project}/vocabulary/check", {"condition": {}, "fact": "x"}, 422, "invalid", "/"
    )
    api.fails("GET", f"{project}/vocabulary/check", None, 405, "method_not_allowed")
    api.fails("GET", f"{project}/vocabulary/other", None, 404, "route_not_found")


def test_a_broken_file_can_be_replaced(api: Api, project: str) -> None:  # noqa: F811
    kinds = lighthouse(api, project)
    (kinds / "vocabulary.json").write_text("{")
    api.fails("GET", f"{project}/kinds", None, 422, "bad_schema")
    raw = json.loads((FIXTURE / "vocabulary.json").read_text())
    api.ok("PUT", f"{project}/vocabulary", raw)
    assert len(api.ok("GET", f"{project}/kinds")["kinds"]) == 3


def test_marked_values_are_checked_on_write(api: Api, project: str) -> None:  # noqa: F811
    lighthouse(api, project)
    step = {"note": "Fill the lamp.", "when": {"fact": "keeper.oil", "gte": "lots"}}
    body = {
        "kind": "errand",
        "data": {"key": "fetch_oil", "name": "Fetch oil", "steps": {"10": step}},
    }
    api.fails("POST", f"{project}/entities", body, 422, "invalid_entity", "/data/steps/10/when/gte")
    step["when"] = {"fact": "keeper.oil", "gte": 2}
    assert api.ok("POST", f"{project}/entities", body, 201)["revision"] == 1
