"""Add the example parametric kind (a lamp) to a project folder: its schema, kit table and gates.

    python3 scripts/add_parametric_example.py PROJECT_FOLDER

Copies examples/parametric/schema/lamp.schema.json into the project's schema folder, adds the kind to its kinds.json
(once) and copies examples/parametric/parametric/ into the project. Nothing else in the project changes.
"""
import json
import shutil
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "parametric"
KIND = {"id": "lamp", "label": "Lamp", "plural_label": "Lamps", "schema": "lamp.schema.json", "title_field": "name",
        "brief_field": "brief", "icon": "lightbulb", "family": "prop"}


def add(project: Path) -> None:
    project_file = json.loads((project / "studio.project.json").read_text())
    schema_dir = project / project_file.get("schema_dir", "kinds")
    shutil.copy(EXAMPLE / "schema" / "lamp.schema.json", schema_dir / "lamp.schema.json")
    kinds_file = schema_dir / "kinds.json"
    kinds = json.loads(kinds_file.read_text())
    if not any(k["id"] == "lamp" for k in kinds["kinds"]):
        kinds["kinds"].append(KIND)
        kinds_file.write_text(json.dumps(kinds, indent=2) + "\n")
    shutil.copytree(EXAMPLE / "parametric", project / "parametric", dirs_exist_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    add(Path(sys.argv[1]))
