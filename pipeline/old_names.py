"""The names this tool used before it was called Generative Stage, still read for one release (standard library only).

    env(name, environ, older)     GENSTAGE_<name>, else DRAMATIS_<name> (or another older prefix) with a one-line
                                  note on stderr, else None
    renamed_env(new, old, environ) the variable NEW, else the older variable OLD with a one-line note on stderr
    home_file(base, name, home)   <home>/<base>/generative-stage/<name>, else the same file in an older folder when
                                  only that one exists (with a one-line note on stderr); per file, so a settings file
                                  that has not moved is found after another one has
    home_dir(base, home, older)   <home>/<base>/generative-stage, else an older folder when only that one exists
                                  (with a one-line note on stderr); for the data folder, which moves as one

The pipeline and the server both read their environment variables and default folders through here, so the
fallbacks are in one place and go away together. scripts/migrate_home.py moves the older folders to the new names.
"""
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

PREFIX = "GENSTAGE_"
OLD_PREFIX = "DRAMATIS_"  # read until the release after the rename
PORT_PREFIX = "DF_"  # the older prefix of the port variables (scripts/start.py), read for the same release
FOLDER = "generative-stage"
OLD_FOLDERS = ("dramatis-fabrica",)  # read until the release after the rename

_noted: set[str] = set()


def _note(message: str) -> None:
    if message not in _noted:  # once per process
        _noted.add(message)
        print(message, file=sys.stderr)


def env(name: str, environ: Mapping[str, str] | None = None, older: Sequence[str] = (OLD_PREFIX,)) -> str | None:
    """The value of GENSTAGE_<name>, else of the first older <prefix><name> set; an empty value counts as unset."""
    environ = os.environ if environ is None else environ
    value = environ.get(PREFIX + name)
    if value:
        return value
    for prefix in older:
        old = environ.get(prefix + name)
        if old:
            _note(f"note: {prefix}{name} is deprecated and will stop working; set {PREFIX}{name} instead")
            return old
    return None


def renamed_env(new: str, old: str, environ: Mapping[str, str] | None = None) -> str | None:
    """The value of NEW, else of the older variable OLD (with a note); an empty value counts as unset."""
    environ = os.environ if environ is None else environ
    if environ.get(new):
        return environ[new]
    if environ.get(old):
        _note(f"note: {old} is deprecated and will stop working; set {new} instead")
        return environ[old]
    return None


def home_file(base: str, name: str, home: Path | None = None, older: Sequence[str] = OLD_FOLDERS) -> Path:
    """<home>/<base>/generative-stage/<name> when that file exists or no older one does; else the older folder's file
    of the same name, with a note. Nothing is made here."""
    home = Path.home() if home is None else Path(home)
    new = home / base / FOLDER / name
    if new.is_file():
        return new
    for folder in older:
        old = home / base / folder / name
        if old.is_file():
            _note(f"note: using {old}; its new place is {new} (scripts/migrate_home.py moves it)")
            return old
    return new


def home_dir(base: str, home: Path | None = None, older: Sequence[str] = OLD_FOLDERS) -> Path:
    """<home>/<base>/generative-stage (base is e.g. ".config" or ".local/share"). While that folder is missing and an
    older one exists, the older one, with a note. The folder is never made here."""
    home = Path.home() if home is None else Path(home)
    new = home / base / FOLDER
    if new.exists():
        return new
    for name in older:
        old = home / base / name
        if old.exists():
            _note(f"note: using {old}; its new place is {new} (scripts/migrate_home.py moves it)")
            return old
    return new
