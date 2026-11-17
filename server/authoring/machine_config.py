"""Machine config: where this computer keeps the Studio's working folders. The one owner of those paths;
docs/configuration.md lists every key.

Load order: the file named by env GENSTAGE_SERVER_CONFIG (it must exist), else ~/.config/generative-stage/server.json if
present, else the built-in defaults below. Build one MachineConfig in main() and pass it to whatever needs a path; nothing here is a global.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "GENSTAGE_SERVER_CONFIG"
DEFAULT_NAME = "server.json"  # in ~/.config/generative-stage (under ~/.config/generative-stage)
BUILT_IN = "built-in defaults (no machine config file found)"

# Every path key. data_dir defaults to the data folder (default_data_dir); runs_root and
# registry_file hang off data_dir unless the file sets them.
PATH_KEYS = ("data_dir", "runs_root", "registry_file")
# Keys of the pipeline's own machine settings (docs/machine_settings.md). One file may serve both, so they are accepted
# and checked here but not used: the server runs pipelines through the pipeline's own config.
SHARED_KEYS = ("gpu_lock", "tools_python", "icon_dir")
# Keys an earlier version of this tool read. A file shared with that version may still hold them:
# they are accepted, ignored and named in `notes`, which the server prints at start.
RETIRED_KEYS = {
    "projects": "projects are listed in the registry file (registry_file) and opened through /api/v1",
    "default_project": "every /api/v1 route names its project in the path",
    "legacy_db_project": "the earlier record store is gone",
    "forge_path": "generation runs the pipelines in this repository on the adapters of the pipeline's machine config "
    "(docs/adapters.md)",
    "staging_root": "runs no longer stage inputs outside their run folder",
}
KNOWN_KEYS = (*PATH_KEYS, *SHARED_KEYS, *RETIRED_KEYS)


class ConfigError(RuntimeError):
    """A config file or key is wrong; the message names the file and the key."""


@dataclass(frozen=True)
class MachineConfig:
    source: str  # the file this came from, or BUILT_IN; used in every error message
    data_dir: Path
    runs_root: Path
    registry_file: Path  # the editable list of world-model projects (core/registry.py)
    notes: tuple[str, ...] = ()  # one line per retired key found in the file


def _fail(source: str, key: str, problem: str) -> ConfigError:
    return ConfigError(f"{source}: key '{key}': {problem}")


def _path(source: str, key: str, value: object, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise _fail(source, key, f"expected a non-empty path string, got {value!r}")
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path)


def parse_machine_config(raw: object, source: str, base: Path, home: Path) -> MachineConfig:
    """Validate one parsed config file. Relative paths are taken from `base`, the file's folder;
    `~` means `home`."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: the file must hold a JSON object, got {type(raw).__name__}")
    for key in raw:
        if key not in KNOWN_KEYS:
            raise _fail(source, str(key), f"unknown key (known keys: {', '.join(KNOWN_KEYS)})")
    paths: dict[str, Path] = {}
    for key in PATH_KEYS:
        if key in raw:
            value = raw[key]
            if isinstance(value, str) and value.startswith("~"):
                value = str(home) + value[1:]
            paths[key] = _path(source, key, value, base)
    if "data_dir" not in paths:
        paths["data_dir"] = default_data_dir(home)
    for key in SHARED_KEYS:
        if key in raw:
            _path(source, key, raw[key], base)  # checked, not kept
    paths.setdefault("runs_root", paths["data_dir"] / "asset-runs")
    paths.setdefault("registry_file", paths["data_dir"] / "registry.json")
    notes = tuple(
        f"{source}: key '{key}' is no longer used and was ignored ({why})"
        for key, why in RETIRED_KEYS.items()
        if key in raw
    )
    return MachineConfig(source=source, notes=notes, **paths)


def default_data_dir(home: Path) -> Path:
    return home / ".local/share" / "generative-stage"


def _config_file(home: Path) -> Path:
    return home / ".config" / "generative-stage" / DEFAULT_NAME


def load_machine_config(
    env: Mapping[str, str] | None = None, home: Path | None = None
) -> MachineConfig:
    """The machine config for this run. `env` and `home` exist so a check can pass its own."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    named = env.get(ENV_VAR)
    if named:
        file = Path(named).expanduser()
        if not file.is_file():
            raise ConfigError(f"{named}: env {ENV_VAR} names a file that does not exist")
    else:
        file = _config_file(home)
        if not file.is_file():
            return parse_machine_config({}, BUILT_IN, home, home)
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"{file}: cannot read as JSON ({error})") from error
    return parse_machine_config(raw, str(file), file.parent, home)
