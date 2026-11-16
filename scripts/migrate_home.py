"""Move this computer's folders from the tool's earlier name (Dramatis Fabrica) to Generative Stage.

    python3 scripts/migrate_home.py [--dry-run] [--home DIR]

Moves each folder below that exists to its new name:

    ~/.config/dramatis-fabrica         ->  ~/.config/generative-stage        (settings)
    ~/.local/share/dramatis-fabrica    ->  ~/.local/share/generative-stage   (data: registry, projects, runs)
    ~/.cache/dramatis-fabrica          ->  ~/.cache/generative-stage         (the model identity cache)

It refuses, changing nothing, when a new folder already exists beside its old one. After the move it rewrites the paths
that name an old folder (absolute, or written from `~`) inside the JSON files that hold settings: every .json file of the
settings folder (server.json, machine.json, proxy configs) and, in the data folder, registry.json and the project
files under projects/ (studio.project.json). Run records and archives are history and are left as written. Then it reports what it did;
with --dry-run it reports what it would do and changes nothing.

Stop the tool's server and any running job first: they hold paths in the old folders.
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

OLD = "dramatis-fabrica"
NEW = "generative-stage"
BASES = (".config", ".local/share", ".cache")
SETTINGS, DATA = ".config", ".local/share"
PROJECT_FILE_NAME = "studio.project.json"


def moves(home: Path) -> list[tuple[Path, Path]]:
    """(old folder, new folder) for each old folder that exists."""
    return [(home / base / OLD, home / base / NEW) for base in BASES if (home / base / OLD).is_dir()]


def json_files(folder: Path, base: str) -> list[Path]:
    """The JSON files of a moved folder whose paths are rewritten."""
    if base == SETTINGS:
        return sorted(folder.rglob("*.json"))
    if base == DATA:
        registry = [folder / "registry.json"] if (folder / "registry.json").is_file() else []
        return registry + sorted((folder / "projects").rglob(PROJECT_FILE_NAME))
    return []


def rewriter(home: Path, pairs: list[tuple[Path, Path]]):
    """A function from a string to the string with every old folder path replaced by its new one."""
    swaps: dict[str, str] = {}
    for old, new in pairs:
        swaps[str(old)] = str(new)
        swaps["~/" + old.relative_to(home).as_posix()] = "~/" + new.relative_to(home).as_posix()
    # a path, not part of a longer name: nothing path-like before it, and a separator or the end after it
    pattern = re.compile(r"(?<![\w.~/-])(" + "|".join(re.escape(old) for old in sorted(swaps, key=len, reverse=True))
                         + r")(?=/|$|[^\w.-])")
    return lambda text: pattern.sub(lambda match: swaps[match.group(1)], text)


def rewrite_value(value, rewrite):
    if isinstance(value, str):
        return rewrite(value)
    if isinstance(value, list):
        return [rewrite_value(item, rewrite) for item in value]
    if isinstance(value, dict):
        return {rewrite(key): rewrite_value(item, rewrite) for key, item in value.items()}
    return value


def rewrite_file(file: Path, rewrite, write: bool) -> bool:
    """Whether FILE names an old folder; when `write`, it is rewritten in place (atomically)."""
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    changed = rewrite_value(value, rewrite)
    if changed == value:
        return False
    if write:
        temporary = file.with_name(file.name + ".migrate-tmp")
        temporary.write_text(json.dumps(changed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, file)
    return True


def migrate(home: Path, dry_run: bool, out=sys.stdout) -> int:
    pairs = moves(home)
    if not pairs:
        print(f"Nothing to move: no {OLD} folder under {home}/.config, .local/share or .cache.", file=out)
        return 0
    taken = [new for _, new in pairs if new.exists()]
    if taken:
        for new in taken:
            print(f"Refused: {new} already exists. Merge or remove it by hand, then run this again.", file=out)
        print("Nothing was changed.", file=out)
        return 1
    rewrite = rewriter(home, pairs)
    verb = "Would move" if dry_run else "Moved"
    for old, new in pairs:
        base = old.parent.relative_to(home).as_posix()
        if not dry_run:
            shutil.move(str(old), str(new))
        print(f"{verb} {old} -> {new}", file=out)
        folder = old if dry_run else new
        for file in json_files(folder, base):
            if rewrite_file(file, rewrite, write=not dry_run):
                shown = new / file.relative_to(folder)
                print(f"  {'would rewrite' if dry_run else 'rewrote'} paths in {shown}", file=out)
    if dry_run:
        print("Dry run: nothing was changed.", file=out)
    else:
        print("Done. Settings that name an old folder outside the files above (shell profiles, MCP client configs) "
              "still need editing by hand.", file=out)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report what would be done and change nothing")
    parser.add_argument("--home", type=Path, default=Path.home(), help="the home folder (default: yours)")
    args = parser.parse_args(argv)
    return migrate(args.home.expanduser().absolute(), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
