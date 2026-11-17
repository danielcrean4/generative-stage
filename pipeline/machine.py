"""Where this computer keeps the pipeline's models, interpreters and GPU lock. Nothing is guessed.

The file is JSON: the one named by the environment variable GENSTAGE_MACHINE_CONFIG (it must exist), else
~/.config/generative-stage/machine.json. A key whose file is missing is an error that names the key and the file,
raised where the path is first needed, so a tool that never needs a model never asks for one. `~` in a value means
the home folder; a relative value is taken from the file's folder.

    adapters          list of adapter entries: the only place a command is defined (adapter_config.py,
                      docs/adapters.md)
    defaults          {adapter kind: adapter id} used when a pipeline stage names no adapter
    tools_python      interpreter with numpy, scipy, trimesh, Pillow and fast-simplification for the image and mesh
                      tools; when unset, the interpreter running the pipeline
    gpu_lock          the machine-wide GPU lock file (gpu_lock.py; docs/gpu_lock.md); host.py has the default
    icon_dir          working folder of icon_batch.py
"""
import json
import os
import sys
from pathlib import Path

CONFIG_ENV = "GENSTAGE_MACHINE_CONFIG"
DEFAULT_NAME = "machine.json"  # in ~/.config/generative-stage
KEYS = ("gpu_lock", "icon_dir", "tools_python")  # path keys
VALUE_KEYS = ("adapters", "defaults")  # structured keys; adapter_config.py validates them


class MachineError(RuntimeError):
    """A key is missing or the file is unreadable; the message names the file and the key."""


def config_file(environ=None, home=None):
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    named = environ.get(CONFIG_ENV)
    if named:
        file = Path(named).expanduser()
        if not file.is_file():
            raise MachineError(f"env {CONFIG_ENV} names {named}, which is not a file")
        return file
    return home / ".config" / "generative-stage" / DEFAULT_NAME


def load(environ=None, home=None):
    """(parsed config object, file); an absent default file reads as an empty config."""
    file = config_file(environ, home)
    if not file.is_file():
        return {}, file
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MachineError(f"{file}: cannot read as JSON ({error})") from error
    if not isinstance(raw, dict):
        raise MachineError(f"{file}: the file must hold a JSON object")
    unknown = sorted(set(raw) - set(KEYS) - set(VALUE_KEYS))
    if unknown:
        raise MachineError(f"{file}: unknown key(s) {', '.join(unknown)} (known: {', '.join((*KEYS, *VALUE_KEYS))})")
    return raw, file


def path(key, environ=None, home=None):
    """The configured Path for KEY (`~` expanded, relative values taken from the file's folder)."""
    if key not in KEYS:
        raise KeyError(key)
    home = Path.home() if home is None else Path(home)
    raw, file = load(environ, home)
    if key not in raw:
        raise MachineError(f"{file}: key '{key}' is not set; set it to the {key.replace('_', ' ')} on this computer "
                           f"(keys and their meaning: pipeline/machine.py; the file is named by env {CONFIG_ENV})")
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        raise MachineError(f"{file}: key '{key}': expected a non-empty path string, got {value!r}")
    if value.startswith("~"):
        value = str(home) + value[1:]
    found = Path(value)
    return found if found.is_absolute() else file.parent / found


def tools_python(environ=None, home=None):
    """The interpreter of the image and mesh tools: tools_python, else the interpreter running this program (install
    pipeline/requirements.txt into it)."""
    raw, _ = load(environ, home)
    if "tools_python" in raw:
        return path("tools_python", environ, home)
    return Path(sys.executable)
