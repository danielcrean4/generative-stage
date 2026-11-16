"""The story graph: x-story marks in kind schemas, and the nodes, edges, conditions and effects read
from an invented lighthouse project's entities (core/tests/fixtures/lighthouse)."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from core import story
from core.errors import BadProjectFiles
from core.kinds import load_catalogue
from core.project_file import load_project_file, write_project_file
from core.story_marks import marks
from core.workspace import open_world
from core.world import World

FIXTURE = Path(__file__).parent / "fixtures" / "lighthouse"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    target = tmp_path / "kinds"
    shutil.copytree(FIXTURE, target)
    return target


@pytest.fixture
def world(folder: Path) -> World:
    project = write_project_file(folder.parent, "lighthouse", "Lighthouse", "kinds")
    return open_world(load_project_file(project))


def _fill(world: World) -> dict[str, str]:
    lamp = world.create_entity("lamp", {"key": "north", "name": "North lamp"})
    errand = world.create_entity(
        "errand",
        {
            "key": "fetch_oil",
            "name": "Fetch oil",
            "steps": {
                "20": {"note": "Carry it up.", "when": {"fact": "keeper.oil", "gte": 2}},
                "10": {"note": "Find the oil.", "effects": [{"do": "light", "lamp": "north"}]},
                "100": {"note": "Done.", "effects": [{"do": "set_mark", "mark": "x", "value": 5}]},
            },
        },
    )
    talk = world.create_entity(
        "talk",
        {
            "key": "keeper",
            "opening": {
                "line": "Evening.",
                "replies": [
                    {"say": "Need oil?", "goto": "oil"},
                    {"say": "Bye.", "requires": {"fact": "lamp(north).lit", "eq": True}},
                ],
            },
            "lines": {
                "oil": {
                    "line": "Two litres, please.",
                    "errand": {"key": "fetch_oil", "step": 10},
                    "replies": [
                        {
                            "say": "On it.",
                            "effects": [{"do": "advance", "errand": "fetch_oil", "step": 20}],
                        },
                        {"say": "Lost?", "goto": "nowhere"},
                    ],
                },
                "thanks": {"line": "Thank you.", "requires": {"after_step": 20}},
            },
        },
    )
    world.add_link("tends", errand["id"], lamp["id"])
    return {"lamp": lamp["id"], "errand": errand["id"], "talk": talk["id"]}


def _graph(world: World) -> dict[str, Any]:
    entities = world.list_entities()
    links = [link for e in entities for link in world.links(e["id"], "out")]
    return story.build(world.catalogue, entities, links)


def _edges(graph: dict[str, Any], kind: str) -> list[tuple[str, str | None]]:
    return [(e["from"], e["to"]) for e in graph["edges"] if e["kind"] == kind]


# Marks


def test_the_fixture_marks_nodes_edges_and_refs(folder: Path) -> None:
    catalogue = load_catalogue(folder)
    talk = {(m.role, m.label) for m in catalogue.kinds["talk"].story}
    assert talk == {("node", "line"), ("edge", "reply"), ("ref", "")}
    (step,) = catalogue.kinds["errand"].story
    assert step.path == ("steps", "*") and step.sequence and step.text == "note"


@pytest.mark.parametrize(
    ("mark", "words"),
    [
        ({"node": "x", "edge": "y"}, "exactly one of node, edge or ref"),
        ({"node": "x", "colour": "red"}, "unknown keys colour"),
        ({"edge": "x", "to": "goto", "target": "/lines/x"}, "holding {}"),
        ({"ref": {"id_kind": "errand"}}, "ref.id must be a non-empty string"),
        ({"node": "x", "sequence": "yes"}, "sequence must be true or false"),
    ],
)
def test_a_bad_mark_is_refused_with_its_pointer(
    folder: Path, mark: dict[str, Any], words: str
) -> None:
    schema = json.loads((folder / "lamp.schema.json").read_text())
    schema["properties"]["name"]["x-story"] = mark
    (folder / "lamp.schema.json").write_text(json.dumps(schema))
    with pytest.raises(BadProjectFiles, match="/properties/name/x-story") as caught:
        load_catalogue(folder)
    assert words in str(caught.value)
    with pytest.raises(ValueError):
        marks(schema)


# The graph


def test_every_entity_and_marked_node_is_a_node(world: World) -> None:
    ids = _fill(world)
    nodes = {n["id"]: n for n in _graph(world)["nodes"]}
    assert nodes[ids["errand"]]["text"] == "Fetch oil" and nodes[ids["errand"]]["label"] == "Errand"
    assert nodes[f"{ids['errand']}#/steps/10"]["label"] == "step 10"
    assert nodes[f"{ids['errand']}#/steps/10"]["text"] == "Find the oil."
    assert nodes[f"{ids['talk']}#/opening"]["label"] == "line"
    assert nodes[f"{ids['talk']}#/lines/oil"]["text"] == "Two litres, please."
    assert len([n for n in nodes.values() if n["entity"] == ids["talk"]]) == 4


def test_steps_follow_in_number_order_and_only_the_first_is_contained(world: World) -> None:
    ids = _fill(world)
    graph = _graph(world)
    e = ids["errand"]
    assert _edges(graph, "sequence") == [
        (f"{e}#/steps/10", f"{e}#/steps/20"),
        (f"{e}#/steps/20", f"{e}#/steps/100"),
    ]
    assert (e, f"{e}#/steps/10") in _edges(graph, "contains")
    assert (e, f"{e}#/steps/20") not in _edges(graph, "contains")


def test_replies_lead_to_lines_end_or_say_what_is_missing(world: World) -> None:
    ids = _fill(world)
    t = ids["talk"]
    replies = {e["text"]: e for e in _graph(world)["edges"] if e["kind"] == "edge"}
    assert (replies["Need oil?"]["from"], replies["Need oil?"]["to"]) == (
        f"{t}#/opening",
        f"{t}#/lines/oil",
    )
    assert replies["Bye."]["to"] is None and replies["Bye."]["ends"]
    assert replies["Lost?"]["to"] is None and not replies["Lost?"]["ends"]
    assert replies["Lost?"]["problem"] == "leads to /lines/nowhere, which this talk does not have"
    contained = _edges(_graph(world), "contains")
    assert (t, f"{t}#/lines/oil") not in contained and (t, f"{t}#/lines/thanks") in contained


def test_conditions_belong_to_the_reply_or_node_holding_them_in_plain_words(world: World) -> None:
    ids = _fill(world)
    graph = _graph(world)
    bye = next(e for e in graph["edges"] if e.get("text") == "Bye.")
    (condition,) = bye["conditions"]
    assert condition["text"] == "lamp(north).lit is true"
    assert condition["reads"][0]["ids"] == [{"id_kind": "lamp", "id": "north"}]
    assert condition["problems"] == [] and not condition["shorthand"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    thanks = nodes[f"{ids['talk']}#/lines/thanks"]["conditions"][0]
    assert thanks["shorthand"] and thanks["text"] == "after_step: 20" and thanks["reads"] == []
    step = nodes[f"{ids['errand']}#/steps/20"]["conditions"][0]
    assert step["text"] == "keeper.oil is at least 2"


def test_effects_refs_reads_and_links_reach_other_entities(world: World) -> None:
    ids = _fill(world)
    graph = _graph(world)
    e, t, lamp = ids["errand"], ids["talk"], ids["lamp"]
    assert (f"{e}#/steps/10", lamp) in _edges(graph, "effect")
    assert (f"{t}#/lines/oil", f"{e}#/steps/20") in _edges(graph, "effect")  # advance to step 20
    assert (f"{t}#/lines/oil", f"{e}#/steps/10") in _edges(graph, "ref")  # the hook's step
    assert (f"{t}#/opening", lamp) in _edges(graph, "reads")
    assert _edges(graph, "link") == [(e, lamp)]


def test_a_bad_effect_shows_its_problem_where_it_sits(world: World) -> None:
    """Writes are checked, so a bad value comes from a vocabulary changed since; build from data."""
    ids = _fill(world)
    errand = world.get_entity(ids["errand"])
    errand["data"]["steps"]["100"]["effects"][0]["value"] = 500
    graph = story.build(world.catalogue, [errand], [])
    nodes = {n["id"]: n for n in graph["nodes"]}
    (effect,) = nodes[f"{ids['errand']}#/steps/100"]["effects"]
    assert effect["text"] == "set_mark mark x, value 500"
    assert effect["problems"] == [{"field": "/steps/100/effects/0/value", "message": "at most 99"}]


def test_a_reference_to_nothing_is_a_problem_on_its_edge(world: World) -> None:
    world.create_entity(
        "talk", {"key": "stray", "opening": {"line": "Hm.", "errand": {"key": "gone"}}}
    )
    (ref,) = [e for e in _graph(world)["edges"] if e["kind"] == "ref"]
    assert ref["to"] is None and ref["problem"] == "no errand 'gone' in this project"


# Views


def test_the_overview_shows_entities_and_counts_the_edges_between_them(world: World) -> None:
    ids = _fill(world)
    view = story.overview(_graph(world))
    assert {n["id"] for n in view["nodes"]} == set(ids.values())
    between = {(e["kind"], e["from"], e["to"]): e["count"] for e in view["edges"]}
    assert between[("effect", ids["errand"], ids["lamp"])] == 1
    assert between[("effect", ids["talk"], ids["errand"])] == 1
    assert between[("reads", ids["talk"], ids["lamp"])] == 1
    talk = next(n for n in view["nodes"] if n["id"] == ids["talk"])
    assert talk["inner"] == 3 and talk["condition_count"] == 2 and talk["problem_count"] == 1


def test_focus_shows_one_entity_in_full_and_its_neighbours_as_entities(world: World) -> None:
    ids = _fill(world)
    view = story.focus(_graph(world), ids["talk"])
    shown = {n["id"] for n in view["nodes"]}
    assert ids["errand"] in shown and ids["lamp"] in shown
    assert f"{ids['errand']}#/steps/10" not in shown
    assert all(e["from"] in shown and (e["to"] is None or e["to"] in shown) for e in view["edges"])
    assert story.focus(_graph(world), "e-none")["nodes"] == []
