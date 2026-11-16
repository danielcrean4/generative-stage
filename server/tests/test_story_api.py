"""The story graph route (/api/v1/projects/<slug>/story) through HTTP, on the invented lighthouse kinds."""

from test_api_v1 import Api, api, project  # noqa: F401  (fixtures)
from test_vocabulary_api import lighthouse


def test_the_overview_and_one_entity_in_full(api: Api, project: str) -> None:  # noqa: F811
    lighthouse(api, project)
    lamp = api.ok(
        "POST",
        f"{project}/entities",
        {"kind": "lamp", "data": {"key": "north", "name": "North"}},
        201,
    )
    steps = {
        "10": {"note": "Find the oil.", "effects": [{"do": "light", "lamp": "north"}]},
        "20": {"note": "Up."},
    }
    errand = api.ok(
        "POST",
        f"{project}/entities",
        {"kind": "errand", "data": {"key": "fetch_oil", "name": "Fetch oil", "steps": steps}},
        201,
    )
    overview = api.ok("GET", f"{project}/story")
    assert overview["view"] == "overview"
    assert {n["id"] for n in overview["nodes"]} == {lamp["id"], errand["id"]}
    assert [(e["kind"], e["from"], e["to"]) for e in overview["edges"]] == [
        ("effect", errand["id"], lamp["id"])
    ]
    focus = api.ok("GET", f"{project}/story?entity={errand['id']}")
    assert focus["view"] == "focus" and len(focus["nodes"]) == 4
    step = next(n for n in focus["nodes"] if n["pointer"] == "/steps/10")
    assert step["effects"][0]["text"] == "light lamp north"
    api.fails("GET", f"{project}/story?entity=e-missing", None, 404, "entity_not_found")
    api.fails("POST", f"{project}/story", {}, 405, "method_not_allowed")
