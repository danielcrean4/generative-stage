"""Kinds and link types from a schema folder: the defaults load, and every bad file is refused with
a message naming the file and the place in it."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from core.errors import BadProjectFiles, Invalid
from core.kinds import load_catalogue
from core.workspace import TEMPLATES


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    target = tmp_path / "kinds"
    shutil.copytree(TEMPLATES, target)
    return target


def edit(file: Path, change: Any) -> None:
    raw = json.loads(file.read_text())
    change(raw)
    file.write_text(json.dumps(raw))


def test_default_kinds_and_link_types(folder: Path) -> None:
    catalogue = load_catalogue(folder)
    assert list(catalogue.kinds) == ["setting", "character", "prop", "script"]
    for kind in catalogue.kinds.values():
        assert (kind.title_field, kind.brief_field, kind.tags_field) == ("name", "brief", "tags")
        assert kind.schema["required"] == ["name"]
    families = {k.id: (k.family, k.form) for k in catalogue.kinds.values()}
    assert families == {
        "setting": ("setting", None),
        "character": ("character", None),
        "prop": ("prop", None),
        "script": ("script", "linear"),
    }
    script = catalogue.kinds["script"]
    assert [m.role for m in script.story] == ["node"]
    assert script.describe()["family"] == "script" and script.describe()["form"] == "linear"
    script.check(
        {"name": "Hello", "lines": [{"speaker": "e-1", "text": "Hi.", "direction": "softly"}]}
    )
    with pytest.raises(Invalid):
        script.check({"name": "Hello", "lines": [{"text": "Hi."}]})
    assert catalogue.link_types["lives_in"].source_kinds == ("character",)
    assert catalogue.link_types["lives_in"].inverse_label == "home of"


def problem(folder: Path) -> str:
    with pytest.raises(BadProjectFiles) as caught:
        load_catalogue(folder)
    return caught.value.message


def test_a_schema_that_is_not_json_schema(folder: Path) -> None:
    edit(folder / "prop.schema.json", lambda s: s["properties"].update(size={"type": "sizeish"}))
    assert problem(folder).startswith(f"{folder / 'prop.schema.json'}: /properties/size/type:")


@pytest.mark.parametrize(
    "change, where",
    [
        (lambda s: s.update(type="array"), "/type"),
        (lambda s: s["properties"].pop("name"), "/properties/name"),
        (lambda s: s["properties"].update(name={"type": "integer"}), "/properties/name"),
        (lambda s: s.update(required=[]), "/required"),
        (lambda s: s["properties"].update(tags={"type": "string"}), "/properties/tags"),
        (
            lambda s: s["properties"].update(owner={"$ref": "https://example.com/x.json"}),
            "/properties/owner/$ref",
        ),
        (
            lambda s: s["properties"].update(owner={"$ref": "other.schema.json"}),
            "/properties/owner/$ref",
        ),
        (
            lambda s: s["properties"].update(owner={"$ref": "#/$defs/missing"}),
            "/properties/owner/$ref",
        ),
    ],
)
def test_a_schema_that_does_not_fit_its_descriptor(folder: Path, change: Any, where: str) -> None:
    edit(folder / "character.schema.json", change)
    assert problem(folder).startswith(f"{folder / 'character.schema.json'}: {where}:")


@pytest.mark.parametrize(
    "change, where",
    [
        (lambda k: k["kinds"][0].pop("label"), "key 'kinds[0]'.label: missing"),
        (lambda k: k["kinds"][0].update(colour="red"), "key 'kinds[0]'.colour: unknown key"),
        (lambda k: k["kinds"][1].update(id="Character"), "key 'kinds[1]'.id"),
        (
            lambda k: k["kinds"][2].update(id="setting"),
            "key 'kinds[2]'.id: 'setting' is listed twice",
        ),
        (lambda k: k["kinds"][0].update(schema="../x.json"), "key 'kinds[0]'.schema"),
        (lambda k: k["kinds"][0].update(tags_field="labels"), ""),
        (lambda k: k.update(kinds=[]), "key 'kinds': list at least one kind"),
        (
            lambda k: k["kinds"][0].update(family="vehicle"),
            "key 'kinds[0]'.family: expected one of prop, character, setting, script, stage, "
            "got 'vehicle'",
        ),
        (
            lambda k: k["kinds"][3].update(form="looping"),
            "key 'kinds[3]'.form: expected one of linear, branching, got 'looping'",
        ),
        (
            lambda k: k["kinds"][2].update(form="linear"),
            'key \'kinds[2]\'.form: only a kind with "family": "script" has a form',
        ),
        (
            lambda k: k["kinds"][3].pop("family"),
            'key \'kinds[3]\'.form: only a kind with "family": "script" has a form',
        ),
    ],
)
def test_a_bad_kinds_file(folder: Path, change: Any, where: str) -> None:
    edit(folder / "kinds.json", change)
    message = problem(folder)
    if where:
        assert message.startswith(f"{folder / 'kinds.json'}: {where}")
    else:  # a tags_field the schema lacks is reported in the schema file
        assert "setting.schema.json: /properties/labels" in message


def test_a_bad_link_types_file(folder: Path) -> None:
    edit(folder / "link_types.json", lambda t: t["link_types"][0].update(target_kinds=["vehicle"]))
    assert problem(folder).startswith(
        f"{folder / 'link_types.json'}: key 'link_types[0]'.target_kinds[0]: 'vehicle' is not a kind"
    )


def test_missing_files(folder: Path, tmp_path: Path) -> None:
    (folder / "link_types.json").unlink()
    assert load_catalogue(folder).link_types == {}
    (folder / "kinds.json").unlink()
    assert problem(folder) == f"{folder / 'kinds.json'}: missing"
    assert "does not exist" in problem(tmp_path / "nowhere")


def test_a_project_can_add_a_kind(folder: Path) -> None:
    schema = {
        "type": "object",
        "required": ["title"],
        "$defs": {"text": {"type": "string", "maxLength": 20}},
        "properties": {
            "title": {"$ref": "#/$defs/text", "type": "string"},
            "summary": {"type": "string"},
        },
    }
    (folder / "vehicle.schema.json").write_text(json.dumps(schema))
    edit(
        folder / "kinds.json",
        lambda k: k["kinds"].append(
            {
                "id": "vehicle",
                "label": "Vehicle",
                "plural_label": "Vehicles",
                "schema": "vehicle.schema.json",
                "title_field": "title",
                "brief_field": "summary",
                "icon": "boat",
            }
        ),
    )
    vehicle = load_catalogue(folder).kinds["vehicle"]
    assert vehicle.tags_field is None
    assert (vehicle.family, vehicle.form) == (None, None)  # no family: listed under Other
    assert vehicle.check({"title": "Cart"}) == {"title": "Cart"}
    with pytest.raises(Invalid) as caught:
        vehicle.check({"title": "A cart with a very long name"})
    assert caught.value.field == "/data/title"


def add_kind(folder: Path, kind_id: str, schema: dict[str, Any], **descriptor: str) -> None:
    (folder / f"{kind_id}.schema.json").write_text(json.dumps(schema))
    entry = {
        "id": kind_id,
        "label": kind_id.title(),
        "plural_label": kind_id.title() + "s",
        "schema": f"{kind_id}.schema.json",
        "icon": "category",
        **descriptor,
    }
    edit(folder / "kinds.json", lambda k: k["kinds"].append(entry))


def test_a_kind_may_have_no_brief_field(folder: Path) -> None:
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}, "weight": {"type": "number"}},
    }
    add_kind(folder, "cargo", schema, title_field="name")
    cargo = load_catalogue(folder).kinds["cargo"]
    assert cargo.brief_field is None and cargo.describe()["brief_field"] is None
    assert cargo.check({"name": "Crate of oil", "weight": 12.5})["weight"] == 12.5


def test_a_named_brief_field_must_still_be_a_string(folder: Path) -> None:
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
            "notes": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    add_kind(folder, "cargo", schema, title_field="name", brief_field="notes")
    assert "brief_field 'notes' must be a string property" in problem(folder)


def test_a_kind_generated_from_nested_data_models(folder: Path) -> None:
    """The shape a model library writes for nested records: $defs, references, optional values
    as anyOf with null, closed objects, maps of objects and lists of records."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "name", "berths"],
        "$defs": {
            "Berth": {
                "type": "object",
                "additionalProperties": False,
                "required": ["number"],
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "covered": {"default": False, "type": "boolean"},
                },
            },
            "Timetable": {
                "type": "object",
                "additionalProperties": {"type": "array", "items": {"type": "string"}},
            },
        },
        "properties": {
            "id": {"type": "string", "pattern": "^[a-z_]+$"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "berths": {"type": "array", "items": {"$ref": "#/$defs/Berth"}},
            "timetable": {"anyOf": [{"$ref": "#/$defs/Timetable"}, {"type": "null"}]},
            "position": {
                "type": "array",
                "prefixItems": [{"type": "number"}] * 3,
                "minItems": 3,
                "maxItems": 3,
            },
        },
    }
    add_kind(folder, "sample", schema, title_field="name", brief_field="description")
    sample = load_catalogue(folder).kinds["sample"]
    good = {
        "id": "north_quay",
        "name": "North quay",
        "berths": [{"number": 1}, {"number": 2}],
        "timetable": {"monday": ["06:00", "18:00"]},
        "position": [1.0, 0.0, -4.5],
    }
    assert sample.check(good) == good
    assert sample.check({**good, "timetable": None})["timetable"] is None
    with pytest.raises(Invalid) as caught:
        sample.check({**good, "berths": [{"number": 0}]})
    assert caught.value.field == "/data/berths/0/number"
    with pytest.raises(Invalid) as caught:
        sample.check({**good, "berths": [{"number": 1, "crane": True}]})
    assert caught.value.field is not None and caught.value.field.startswith("/data/berths/0")
    with pytest.raises(Invalid) as caught:
        sample.check({**good, "timetable": {"monday": [6]}})
    assert caught.value.field == "/data/timetable/monday/0"
