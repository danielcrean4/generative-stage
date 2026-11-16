"""The `studio` command line.

    studio export --project <studio.project.json> --out <folder> [--kind K]... [--tag T]...
                  [--since <earlier manifest.json>] [--zip <file.zip>] [--runs-root <folder>]

`export` writes an export bundle (docs/export_bundle.md) of the project's live entities into a
missing or empty folder, and optionally a zip of it. Chosen assets are read from the runs root:
--runs-root when given, else the machine config's.
"""

import argparse
import json
import sys
from pathlib import Path

from authoring.machine_config import ConfigError, load_machine_config
from authoring.run_view import run_exists
from core.errors import CoreError
from core.project_file import load_project_file
from core.workspace import open_world
from export.bundle import Selection, plan_bundle, since_from_manifest, write_bundle, write_zip


def cmd_export(args: argparse.Namespace) -> int:
    runs_root = args.runs_root if args.runs_root is not None else load_machine_config().runs_root
    project = load_project_file(args.project.resolve())
    world = open_world(project, lambda run_id: run_exists(runs_root, run_id))
    since = None
    if args.since is not None:
        since = since_from_manifest(json.loads(args.since.read_text(encoding="utf-8")))
    selection = Selection(tuple(args.kind), tuple(args.tag), since)
    plan = plan_bundle(world, runs_root, selection)
    out = write_bundle(plan, args.out)
    manifest = plan.manifest
    assets = sum(len(entity["assets"]) for entity in manifest["entities"])
    print(
        f"Exported {len(manifest['entities'])} entities, {assets} assets, "
        f"{len(manifest['links'])} links to {out}"
    )
    if "removed" in manifest:
        print(f"Archived or gone since the earlier bundle: {len(manifest['removed'])}")
    if args.zip is not None:
        print(f"Zipped to {write_zip(out, args.zip)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio", description="Generative Stage command line")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write an export bundle of a project")
    export.add_argument(
        "--project", type=Path, required=True, help="the project's studio.project.json"
    )
    export.add_argument("--out", type=Path, required=True, help="a missing or empty folder")
    export.add_argument("--kind", action="append", default=[], help="only this kind (repeatable)")
    export.add_argument(
        "--tag", action="append", default=[], help="only entities with this tag (repeatable)"
    )
    export.add_argument(
        "--since", type=Path, help="an earlier bundle's manifest.json: export only what changed"
    )
    export.add_argument("--zip", type=Path, help="also write the bundle as this zip file")
    export.add_argument(
        "--runs-root", type=Path, help="where the runs are (default: the machine config's)"
    )
    export.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except (CoreError, ConfigError) as error:
        print(f"studio {args.command}: {error}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
