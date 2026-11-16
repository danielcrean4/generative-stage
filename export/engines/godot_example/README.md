# Godot example importer

`godot_import.py` reads an export bundle (a folder or a `.zip`) and lays it out for a Godot project:

    python3 godot_import.py <bundle folder or zip> <folder inside your Godot project>

It writes `models/<kind>/<entity id>.glb` for each chosen 3D model, `images/<kind>/<entity id>.png`
for each chosen image (a slot other than `main` adds `_<slot>` to the name) and `index.json`, which lists
every entity with its kind, title, data and the `res://`-relative paths of its files, plus the links.
Godot imports the `.glb` and `.png` files itself; a script can read `index.json` with `JSON.parse_string`.
It needs only Python's standard library, checks each file's hash against the manifest, and refuses a
non-empty target folder.
