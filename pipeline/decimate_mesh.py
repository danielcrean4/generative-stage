"""Decimate a mesh to a face budget (tools interpreter: fast-simplification, scipy, trimesh).

python decimate_mesh.py INPUT.glb OUTPUT.glb --config CONFIG.json --report REPORT.json

Config keys (all required, no defaults; see docs/normalisers.md):
  face_budget        whole number above 0, the most faces the output may have
  preserve_topology  true or false: true never collapses an edge on an open border

A mesh already within the budget is copied unchanged and the report says so. Vertex colours are kept (each new
vertex takes the colour of the nearest original vertex); the report says whether they were. The report also
holds the mesh's topology (pieces, Euler characteristic, non-manifold edges) before and after, because the
collapse can close a thin handle or pinch two sheets together; see mesh_decimate.py. Exits 2 on bad input or config.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_decimate
import mesh_io
import normaliser_common as common

TOOL = "decimate_mesh"
SCHEMA = {"face_budget": common.positive_int, "preserve_topology": common.boolean}


def decimate_file(source, target, config):
    """Write TARGET and return the report body."""
    mesh = mesh_io.load_mesh(source, TOOL)
    before = mesh_io.summary(mesh)
    colors = mesh_io.vertex_colors(mesh)
    if len(mesh.faces) <= config["face_budget"]:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return {"changed": False, "note": "already within the face budget; copied unchanged",
                "before": before, "after": before,
                "vertex_colors": {"present": colors is not None, "preserved": colors is not None}}
    vertices, faces, new_colors = mesh_decimate.decimate(
        mesh.vertices, mesh.faces, config["face_budget"], config["preserve_topology"], colors)
    out = mesh_io.build(vertices, faces, new_colors, mesh.metadata)
    mesh_io.save_mesh(out, target)
    return {"changed": True, "before": before, "after": mesh_io.summary(out),
            "within_budget": bool(len(faces) <= config["face_budget"]),
            "topology": {"before": mesh_decimate.topology(mesh.vertices, mesh.faces),
                         "after": mesh_decimate.topology(vertices, faces)},
            "vertex_colors": {"present": colors is not None, "preserved": new_colors is not None}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    config, config_sha = common.load_config(args.config, SCHEMA, TOOL)
    common.require_file(args.input, TOOL, "input mesh")
    report = decimate_file(args.input, args.output, config)
    report.update({"tool": TOOL, "config": config, "config_sha256": config_sha})
    common.write_report(args.report, report)
    return 0


if __name__ == "__main__":
    sys.exit(common.run(TOOL, main))
