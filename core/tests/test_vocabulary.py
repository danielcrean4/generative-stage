"""The condition vocabulary: the file format, conditions and effects checked, shown and read against
it, and kinds whose schemas mark values with x-vocabulary. The fixture is an invented lighthouse
(core/tests/fixtures/lighthouse), so nothing here knows a real project."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from core import conditions
from core.annotations import ANY, instances, sites
from core.errors import BadProjectFiles, Invalid
from core.kinds import load_catalogue
from core.project_file import load_project_file, write_project_file
from core.vocabulary import VOCABULARY_FILE, Vocabulary, load_vocabulary, parse, write_vocabulary
from core.workspace import open_world
from core.world import World

FIXTURE = Path(__file__).parent / "fixtures" / "lighthouse"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    target = tmp_path / "kinds"
    shutil.copytree(FIXTURE, target)
    return target


@pytest.fixture
def vocab(folder: Path) -> Vocabulary:
    loaded = load_vocabulary(folder)
    assert loaded is not None
    return loaded


@pytest.fixture
def world(folder: Path) -> World:
    project = load_project_file(
        write_project_file(folder.parent, "lighthouse", "Lighthouse", "kinds")
    )
    return open_world(project)


def raw(folder: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / VOCABULARY_FILE).read_text())
    return data


# The file


def test_the_fixture_loads_and_paths_match_patterns(vocab: Vocabulary) -> None:
    read = vocab.read("errand(fetch_oil).step")
    assert (
        read is not None
        and read.fact.pattern == "errand(errand).step"
        and read.ids == (("errand", "fetch_oil"),)
    )
    assert vocab.read("keeper.oil") is not None
    assert vocab.read("mark(spare parts.2)") is not None  # an id may hold spaces and dots
    for wrong in ("errand.step", "keeper(x).oil", "keeper", "Keeper.oil", "errand(A).step", 3):
        assert vocab.read(wrong) is None, wrong
    assert vocab.entity_kinds("errand") == (("errand",), "key")
    assert vocab.entity_kinds("mark") == ((), "key")


def test_the_format_id_from_before_the_rename_is_read(folder: Path) -> None:
    raw = json.loads((folder / VOCABULARY_FILE).read_text())
    raw["format"] = "dramatis-vocabulary"
    assert parse(raw, folder / VOCABULARY_FILE).raw["format"] == "dramatis-vocabulary"


@pytest.mark.parametrize(
    ("change", "pointer", "words"),
    [
        (
            lambda v: v.update(format="other"),
            "/format",
            "is not one of ['generative-stage-vocabulary', 'dramatis-vocabulary']",
        ),
        (lambda v: v["facts"][0].update(type="float"), "/facts/0/type", "not one of the types"),
        (lambda v: v["facts"].append(dict(v["facts"][0])), "/facts/8/pattern", "listed twice"),
        (
            lambda v: v["facts"][0].update(pattern="Errand.step"),
            "/facts/0/pattern",
            "does not match",
        ),
        (
            lambda v: v["operators"]["eq"]["types"].append("text"),
            "/operators/eq/types/3",
            "not one of the types",
        ),
        (
            lambda v: v["operators"]["eq"].update(operand="any"),
            "/operators/eq/operand",
            "is not one of",
        ),
        (
            lambda v: v["effects"]["kinds"]["say"]["args"].update(do={"type": "string"}),
            "/effects/kinds/say/args",
            "may not be named 'do'",
        ),
        (
            lambda v: v["effects"]["kinds"]["say"].update(required=["words"]),
            "/effects/kinds/say/required",
            "not one of its args",
        ),
        (
            lambda v: v["effects"]["kinds"]["light"]["ref"].update(id="bulb"),
            "/effects/kinds/light/ref/id",
            "not one of its args",
        ),
        (lambda v: v["id_kinds"].pop("mark"), "/facts/7/pattern", "'mark' is not in id_kinds"),
        (lambda v: v.update(extra=1), "/", "Additional properties"),
    ],
)
def test_a_bad_file_names_the_file_and_pointer(
    folder: Path, change: Any, pointer: str, words: str
) -> None:
    data = raw(folder)
    change(data)
    (folder / VOCABULARY_FILE).write_text(json.dumps(data))
    with pytest.raises(BadProjectFiles) as caught:
        load_catalogue(folder)
    assert caught.value.code == "bad_schema"
    assert caught.value.message.startswith(f"{folder / VOCABULARY_FILE}: {pointer}: "), (
        caught.value.message
    )
    assert words in caught.value.message


def test_write_checks_before_writing(folder: Path) -> None:
    before = (folder / VOCABULARY_FILE).read_text()
    data = raw(folder)
    data["facts"][0]["type"] = "float"
    with pytest.raises(Invalid) as caught:
        write_vocabulary(folder, data)
    assert caught.value.field == "/facts/0/type"
    assert (folder / VOCABULARY_FILE).read_text() == before
    data["facts"][0]["type"] = "int"
    data["source"] = "rewritten"
    assert write_vocabulary(folder, data).raw["source"] == "rewritten"
    assert raw(folder)["source"] == "rewritten"


# Conditions


def leaf(fact: str, op: str, value: Any) -> dict[str, Any]:
    return {"fact": fact, op: value}


@pytest.mark.parametrize(
    "condition",
    [
        leaf("keeper.oil", "gte", 2),
        leaf("keeper.place", "eq", "gallery"),
        leaf("keeper.seen", "has", "cellar"),
        leaf("keeper.place", "in", ["gallery", "cellar"]),
        {"all": [leaf("lamp(north).lit", "eq", False), {"not": leaf("tide.height", "lt", 3)}]},
        {"any": [leaf("errand(fetch_oil).done", "eq", True), {"after_step": 10}]},
        {"after_step": 10},
    ],
)
def test_good_conditions_have_no_problems(vocab: Vocabulary, condition: Any) -> None:
    assert conditions.problems(vocab, condition) == []


@pytest.mark.parametrize(
    ("condition", "pointer", "words"),
    [
        ({}, "", "non-empty object"),
        ([], "", "non-empty object"),
        (leaf("keeper.fuel", "gte", 1), "/fact", "not a fact the vocabulary lists"),
        (leaf("keeper.oil", "more", 1), "/more", "not an operator"),
        (
            leaf("keeper.oil", "has", "x"),
            "/has",
            "has does not apply to keeper.oil (int; has takes id_set)",
        ),
        (leaf("keeper.oil", "gte", "2"), "/gte", "must be a JSON integer"),
        (leaf("keeper.oil", "gte", True), "/gte", "must be a JSON integer"),
        (leaf("keeper.seen", "has", 3), "/has", "takes one id"),
        (leaf("keeper.place", "in", []), "/in", "non-empty list"),
        (leaf("keeper.place", "in", ["a", 2]), "/in/1", "expected an id"),
        ({"fact": "keeper.oil", "gte": 1, "lt": 3}, "", "exactly one operator"),
        ({"all": []}, "/all", "non-empty list"),
        ({"all": [leaf("keeper.oil", "gte", 1)], "any": []}, "", "exactly one of"),
        ({"all": [leaf("keeper.oil", "gte", 1)], "after_step": 2}, "", "exactly one of"),
        ({"not": {"any": [leaf("tide.hight", "lt", 1)]}}, "/not/any/0/fact", "not a fact"),
        ({"after_stage": 3}, "/after_stage", "is not a condition key"),
    ],
)
def test_bad_conditions_name_the_pointer(
    vocab: Vocabulary, condition: Any, pointer: str, words: str
) -> None:
    found = conditions.problems(vocab, condition)
    assert found and found[0][0] == pointer, found
    assert words in found[0][1], found


def test_every_problem_is_listed(vocab: Vocabulary) -> None:
    condition = {
        "all": [
            leaf("keeper.fuel", "gte", 1),
            leaf("keeper.oil", "gte", "x"),
            leaf("tide.height", "lt", 2),
        ]
    }
    assert [p for p, _ in conditions.problems(vocab, condition)] == ["/all/0/fact", "/all/1/gte"]


def test_text_and_reads(vocab: Vocabulary) -> None:
    condition = {
        "all": [
            leaf("errand(fetch_oil).step", "gte", 10),
            {"any": [leaf("keeper.oil", "gte", 2), {"not": leaf("lamp(north).lit", "eq", True)}]},
            leaf("errand(fetch_oil).step", "lt", 30),
        ]
    }
    assert conditions.text(vocab, condition) == (
        "errand(fetch_oil).step is at least 10 and (keeper.oil is at least 2 or not (lamp(north).lit is true))"
        " and errand(fetch_oil).step is below 30"
    )
    assert [r.path for r in conditions.reads(vocab, condition)] == [
        "errand(fetch_oil).step",
        "keeper.oil",
        "lamp(north).lit",
    ]
    view = conditions.read_view(conditions.reads(vocab, condition)[0])
    assert view["ids"] == [{"id_kind": "errand", "id": "fetch_oil"}] and view["type"] == "int"
    assert conditions.text(vocab, {"after_step": 10}) == "after_step: 10"
    assert conditions.is_shorthand(vocab, {"after_step": 10})
    assert conditions.reads(vocab, {"after_step": 10}) == []
    assert (
        conditions.text(vocab, leaf("keeper.place", "in", ["a", "b"]))
        == "keeper.place is one of a, b"
    )


# Effects and modes


def test_effects(vocab: Vocabulary) -> None:
    good = [
        {"do": "set_mark", "mark": "bell", "value": 3},
        {"do": "advance", "errand": "fetch_oil", "step": 20},
    ]
    assert conditions.effect_problems(vocab, good) == []
    assert conditions.effect_text(vocab, good[1]) == "advance errand fetch_oil, step 20"
    bad = [
        {"do": "set_mark", "value": 300, "colour": "red"},
        {"do": "fly"},
        {"say": "hi"},
        {"do": "say", "text": ""},
        {"do": "set_mark", "mark": "Bell"},
    ]
    assert conditions.effect_problems(vocab, bad) == [
        ("/0/colour", "set_mark takes no 'colour' (it takes: mark, value)"),
        ("/0", "set_mark needs 'mark'"),
        ("/0/value", "at most 99"),
        ("/1/do", "'fly' is not an effect (known: advance, light, say, set_mark)"),
        ("/2", "an effect is an object whose 'do' names its kind"),
        ("/3/text", "at least 1 characters"),
        ("/4/mark", "does not match ^[a-z][a-z0-9_]*$"),
    ]
    assert conditions.effect_problems(vocab, {"do": "say"}) == [("", "effects are a list")]
    assert conditions.rule_mode_problems(vocab, "each") == []
    assert (
        conditions.rule_mode_problems(vocab, "twice")[0][1] == "expected a rule mode (once, each)"
    )


# Marked kinds


def test_sites_follow_refs_items_and_maps(folder: Path) -> None:
    catalogue = load_catalogue(folder)
    talk = {(s.path, s.role) for s in catalogue.kinds["talk"].sites}
    assert talk == {
        (("opening", "requires"), "condition"),
        (("opening", "replies", ANY, "requires"), "condition"),
        (("opening", "replies", ANY, "effects"), "effects"),
        (("lines", ANY, "requires"), "condition"),
        (("lines", ANY, "replies", ANY, "requires"), "condition"),
        (("lines", ANY, "replies", ANY, "effects"), "effects"),
    }
    data = {"lines": {"a/b": {"replies": [{"say": "x", "requires": {"after_step": 1}}]}}}
    assert list(instances(data, ("lines", ANY, "replies", ANY, "requires"))) == [
        ("/lines/a~1b/replies/0/requires", {"after_step": 1})
    ]


def test_recursive_schemas_end() -> None:
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/n"}},
        "$defs": {
            "n": {
                "type": "object",
                "properties": {"child": {"$ref": "#/$defs/n"}, "if": {"x-vocabulary": "condition"}},
            }
        },
    }
    assert [s.path for s in sites(schema)] == [("node", "if")]


def test_marked_values_are_checked_on_every_write(world: World) -> None:
    good: dict[str, Any] = {
        "key": "fetch_oil",
        "name": "Fetch oil",
        "steps": {
            "10": {
                "note": "n",
                "when": leaf("keeper.oil", "gte", 1),
                "effects": [{"do": "say", "text": "Done"}],
                "mode": "once",
            }
        },
    }
    made = world.create_entity("errand", good)
    changes: list[tuple[Callable[[Any], None], str]] = [
        (
            lambda d: d["steps"]["10"].update(when=leaf("keeper.oil", "gte", "one")),
            "/data/steps/10/when/gte",
        ),
        (lambda d: d["steps"]["10"].update(effects=[{"do": "fly"}]), "/data/steps/10/effects/0/do"),
        (lambda d: d["steps"]["10"].update(mode="twice"), "/data/steps/10/mode"),
    ]
    for change, field in changes:
        bad = json.loads(json.dumps(good))
        change(bad)
        with pytest.raises(Invalid) as caught:
            world.update_entity(made["id"], 1, bad)
        assert caught.value.field == field and caught.value.code == "invalid_entity"
        with pytest.raises(Invalid):
            world.create_entity("errand", {**bad, "key": "other"})
    good["steps"]["10"]["when"] = None  # null is "absent"
    assert world.update_entity(made["id"], 1, good)["revision"] == 2


def test_a_marked_kind_needs_a_vocabulary(folder: Path) -> None:
    (folder / VOCABULARY_FILE).unlink()
    with pytest.raises(BadProjectFiles) as caught:
        load_catalogue(folder)
    assert (
        "errand.schema.json: /$defs/step/properties/when/x-vocabulary: marks a condition but the folder has no vocabulary.json"
        in caught.value.message
    )


def test_an_unknown_role_is_refused(folder: Path) -> None:
    schema = json.loads((folder / "lamp.schema.json").read_text())
    schema["properties"]["name"]["x-vocabulary"] = "spell"
    (folder / "lamp.schema.json").write_text(json.dumps(schema))
    with pytest.raises(BadProjectFiles) as caught:
        load_catalogue(folder)
    assert (
        "/properties/name/x-vocabulary: 'spell' is not one of condition, effects, rule_mode, fact"
        in caught.value.message
    )


def test_parse_takes_any_folder_name(tmp_path: Path) -> None:
    data = json.loads((FIXTURE / VOCABULARY_FILE).read_text())
    assert parse(data, tmp_path / "v.json").effect_key == "do"
