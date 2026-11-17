"""Machine config: where it loads from, what it rejects, and that a Dispatcher still starts."""

import json
from pathlib import Path

import pytest
from studio_test_support import stand_in_config

from authoring.jobs import Dispatcher
from authoring.machine_config import (
    BUILT_IN,
    ENV_VAR,
    ConfigError,
    MachineConfig,
    load_machine_config,
)


def load(tmp_path: Path, raw: object, name: str = "machine.json") -> MachineConfig:
    file = tmp_path / name
    file.write_text(json.dumps(raw))
    return load_machine_config({ENV_VAR: str(file)}, home=tmp_path / "home")


def test_no_file_gives_the_default_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = load_machine_config({}, home=home)
    assert config.source == BUILT_IN
    assert config.runs_root == home / ".local/share/generative-stage/asset-runs"
    assert config.notes == ()


def test_default_file_location_is_read(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".config/generative-stage").mkdir(parents=True)
    (home / ".config/generative-stage/server.json").write_text('{"runs_root": "/opt/runs"}')
    config = load_machine_config({}, home=home)
    assert config.runs_root == Path("/opt/runs")
    assert config.source.endswith(".config/generative-stage/server.json")


def test_env_names_the_file_and_overrides_defaults(tmp_path: Path) -> None:
    config = load(tmp_path, {"data_dir": "/data/studio"})
    assert config.runs_root == Path("/data/studio/asset-runs")  # follows data_dir
    assert config.registry_file == Path("/data/studio/registry.json")


def test_relative_paths_are_taken_from_the_file_folder(tmp_path: Path) -> None:
    config = load(tmp_path, {"runs_root": "runs", "data_dir": "data"})
    assert config.runs_root == tmp_path / "runs"
    assert config.registry_file == tmp_path / "data/registry.json"


RETIRED = {
    "projects": ["one/studio.project.json"],
    "default_project": "one",
    "legacy_db_project": "one",
    "forge_path": "/opt/forge",
    "staging_root": "/opt/staging",
}


def test_retired_keys_are_accepted_and_noted(tmp_path: Path) -> None:
    """A file written for an earlier version loads: every key it once held is ignored with a note that names the key."""
    config = load(tmp_path, {**RETIRED, "data_dir": "/data/studio"})
    assert config.data_dir == Path("/data/studio")
    assert len(config.notes) == len(RETIRED)
    assert all("machine.json" in note for note in config.notes)
    for key in RETIRED:
        assert sum(f"key '{key}'" in note for note in config.notes) == 1
    assert not hasattr(config, "forge_path")


def test_the_forge_path_note_says_where_generation_went(tmp_path: Path) -> None:
    config = load(tmp_path, {"forge_path": "/opt/forge"})
    assert "no longer used" in config.notes[0] and "pipelines in this repository" in config.notes[0]


def test_unknown_key_names_key_and_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"machine\.json: key 'forge_pth': unknown key"):
        load(tmp_path, {"forge_pth": "/x"})


@pytest.mark.parametrize(
    "raw, key",
    [
        ({"runs_root": ""}, "runs_root"),
        ({"data_dir": ["a"]}, "data_dir"),
        ({"gpu_lock": 5}, "gpu_lock"),
    ],
)
def test_wrong_type_names_key_and_file(tmp_path: Path, raw: object, key: str) -> None:
    with pytest.raises(ConfigError, match=rf"machine\.json: key '{key}'"):
        load(tmp_path, raw)


def test_file_that_is_not_an_object_or_json_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"machine\.json: the file must hold a JSON object"):
        load(tmp_path, ["x"])
    bad = tmp_path / "broken.json"
    bad.write_text("{nope")
    with pytest.raises(ConfigError, match=r"broken\.json: cannot read as JSON"):
        load_machine_config({ENV_VAR: str(bad)}, home=tmp_path)


def test_env_pointing_at_a_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=ENV_VAR):
        load_machine_config({ENV_VAR: str(tmp_path / "gone.json")}, home=tmp_path)


def test_dispatcher_starts_with_stand_in_paths(tmp_path: Path) -> None:
    dispatcher = Dispatcher(stand_in_config(tmp_path))
    assert dispatcher.run_next(timeout=0) is False
