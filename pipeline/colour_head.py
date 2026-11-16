"""Paint a head mesh from the front image it was made from; geometry untouched (tools interpreter:
numpy, scipy, Pillow, trimesh, fast-simplification).

python colour_head.py MESH.glb IMAGE.png OUTPUT.glb --config CONFIG.json --report REPORT.json

The mesh model makes shape only. Colour comes from projecting the front image straight through the mesh along
its depth axis (up is +Y, the image's right is +X, depth is Z, the front faces +Z: the mesh model's
image-aligned frame, which is also what the gate's fixed view assumes). The work is done on a decimated working
copy of the largest piece, then handed to every vertex of the real mesh by nearest working vertex, so the output
has the input's vertices and faces exactly and only gains vertex colours. Later stages (normalize_mesh,
decimate_mesh) keep vertex colours.

On the working copy: vertices the front camera sees (facing it, not hidden behind nearer geometry: a depth
buffer) take the image colour, after the image is reduced to a few flat colours. Every other vertex takes the
colour that diffuses in from the seen area across the mesh (a Laplace fill, level edges weighted up so colour
wraps round the head by rows), as a vote between the broad flat colours of the seen area, so hair meets hair and
skin meets skin. With a hair colour, the back and upper sides of the head take it.

Config keys (all required, no defaults; see docs/head_pipeline.md):
  background         `capture.background` of the pipeline file, near_white only: which pixels are the subject
                     (its bounding box is what the mesh is mapped to) and which samples are background
  hair_colour        "#rrggbb" or null (the subject's hair colour; null leaves the hidden area to the vote alone)
  working_faces      faces of the working copy the colours are computed on
  posterize          colours the image is reduced to before projecting, 0 to skip (0 also swaps the vote for a blend)
  seen_facing        normals pointing less than this toward the camera are not seen (-1..1)
  depth_resolution   depth buffer side for the visibility test, in pixels
  depth_tolerance    share of the height a vertex may sit behind the nearest one and still count as seen
  min_seen_share     fewer seen vertices than this share means the projection missed the mesh: an error
  horizontal_bias    extra weight on level edges in the fill
  toon_colours       flat colours the seen area is grouped into before the hidden area votes
  broad_share        a group needs this share of the seen vertices to vote (small features such as eyes do not)
  nape_height, temple_height, temple_side, ear_top, ear_side
                     where hair stops (shares of the height or the half-width; see the code below)
  hair_match         a flat colour this close (0..1 colour distance) to hair_colour is used as the hair colour
Exits 2 on bad input or config, and when the projection misses the mesh.
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import scipy.cluster.vq as vq
import scipy.sparse as sp
import scipy.sparse.linalg as spla
import trimesh
from PIL import Image
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import background_spec
import mesh_decimate
import mesh_io
import normaliser_common as common
import subject_mask

TOOL = "colour_head"
FILL_REGULARISATION = 1e-6  # keeps the fill solvable if a patch is disconnected from the seen area
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
MAX_CHANNEL = 255
KMEANS_SEED = 0  # fixed: the same input must colour the same way
POSTERIZE_COLOURS_PER_SETTING = 3  # PIL's median cut gets this many colours per posterize setting before the vote groups them


class Missed(common.NormaliserError):
    """The front projection does not land on the mesh."""


def background(value):
    try:
        if background_spec.parse(value)["method"] != background_spec.NEAR_WHITE:
            raise ValueError("must use the near_white method (colour_head tells background samples by their level)")
    except background_spec.BackgroundError as exc:
        raise ValueError(str(exc))


def hair_colour(value):
    if value is not None and not (isinstance(value, str) and HEX_COLOUR.fullmatch(value)):
        raise ValueError('must be null or "#rrggbb"')


def whole_from(low):
    def check(value):
        if type(value) is not int or value < low:
            raise ValueError(f"must be a whole number, {low} or more")
    return check


SCHEMA = {"background": background, "hair_colour": hair_colour, "working_faces": whole_from(100), "posterize": whole_from(0),
          "seen_facing": common.number_between(-1, 1), "depth_resolution": whole_from(8),
          "depth_tolerance": common.number_between(0, 1), "min_seen_share": common.number_between(0, 1),
          "horizontal_bias": common.number_between(0, 100), "toon_colours": whole_from(1),
          "broad_share": common.number_between(0, 1), "nape_height": common.number_between(0, 1),
          "temple_height": common.number_between(0, 1), "temple_side": common.number_between(0, 1),
          "ear_top": common.number_between(0, 1), "ear_side": common.number_between(0, 1),
          "hair_match": common.number_between(0, 2)}


def working_copy(mesh, faces):
    """The largest piece of MESH decimated to about FACES faces, as a Trimesh."""
    pieces = mesh.split(only_watertight=False)
    if len(pieces) > 1:
        mesh = max(pieces, key=lambda piece: len(piece.faces))
    vertices, new_faces, _ = mesh_decimate.decimate(mesh.vertices, mesh.faces, faces, preserve_topology=False)
    return trimesh.Trimesh(vertices, new_faces, process=True)


def prepare_image(path, config):
    """(float RGB 0..1, subject bounding box (x0, x1, y0, y1)) of the front image."""
    image = Image.open(path)
    image.load()
    separation = subject_mask.separate(image, config["background"])
    ys, xs = np.nonzero(separation.subject)
    if not len(ys):
        raise common.NormaliserError(f"{TOOL}: no subject found in {path} (the whole image reads as background)")
    box = (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))
    rgb = Image.fromarray(separation.rgb).convert("RGB")
    if config["posterize"] > 0:
        rgb = rgb.quantize(colors=config["posterize"] * POSTERIZE_COLOURS_PER_SETTING, method=Image.Quantize.MEDIANCUT).convert("RGB")
    return np.asarray(rgb).astype(np.float32) / MAX_CHANNEL, box


def hex_to_unit(text):
    return np.array([int(text[i:i + 2], 16) for i in (1, 3, 5)]) / MAX_CHANNEL


def hidden_fill(mesh, cols, seen, config, bounds):
    """Colours for the vertices the camera does not see (Laplace fill, voted between flat colours)."""
    v = mesh.vertices
    lo, hi = bounds
    span = hi - lo
    unseen = np.nonzero(~seen)[0]
    count = len(v)
    edges = mesh.edges_unique
    run = v[edges[:, 1]] - v[edges[:, 0]]
    level = 1.0 - np.abs(run[:, 1]) / np.maximum(np.linalg.norm(run, axis=1), 1e-9)  # 1 for a level edge
    adjacency = sp.coo_matrix((1.0 + config["horizontal_bias"] * level, (edges[:, 0], edges[:, 1])), shape=(count, count))
    adjacency = (adjacency + adjacency.T).tocsr()
    laplacian = sp.diags(np.asarray(adjacency.sum(axis=1)).ravel()) - adjacency
    seen_idx = np.nonzero(seen)[0]
    l_uu = laplacian[unseen][:, unseen] + FILL_REGULARISATION * sp.identity(len(unseen))
    l_us = laplacian[unseen][:, seen_idx]
    if config["posterize"] <= 0:
        for channel in range(3):
            cols[unseen, channel] = spla.spsolve(l_uu.tocsc(), -(l_us @ cols[seen_idx, channel]))
        return
    centres, labels = vq.kmeans2(cols[seen_idx].astype(np.float64), config["toon_colours"], minit="++", seed=KMEANS_SEED)
    shares = np.bincount(labels, minlength=len(centres)) / len(labels)
    keep = np.nonzero(shares >= config["broad_share"])[0]
    if len(keep) == 0:
        keep = np.array([shares.argmax()])
    centres = centres[keep]
    labels = np.where(np.isin(labels, keep), np.searchsorted(keep, labels), -1)  # small groups vote for nobody
    indicators = np.stack([(labels == c).astype(np.float64) for c in range(len(centres))], axis=1)
    votes = spla.splu(l_uu.tocsc()).solve(-(l_us @ indicators))
    cols[unseen] = centres[votes.argmax(axis=1)]
    if config["hair_colour"] is None:
        return
    # A high hairline at the front leaves the vote painting the back of the head as skin: behind the head's
    # middle and above the nape it is hair, as are the sides above the ear.
    wanted = hex_to_unit(config["hair_colour"])
    gap = np.linalg.norm(centres - wanted, axis=1)
    hair = centres[gap.argmin()] if gap.min() < config["hair_match"] else wanted
    height = (v[unseen, 1] - lo[1]) / span[1]
    off_centre = np.abs(v[unseen, 0] - (lo[0] + hi[0]) / 2)
    behind = ((v[unseen, 2] < (lo[2] + hi[2]) / 2) & (height > config["nape_height"])
              & ~((off_centre > config["ear_side"] * span[0] / 2) & (height < config["ear_top"])))
    temple = (height > config["temple_height"]) & (off_centre > config["temple_side"] * span[0] / 2)
    cols[unseen[behind | temple]] = hair


def colour_working(work, image, box, config):
    """(uint8 RGB per working vertex, stats) by front projection and hidden-area fill."""
    x0, x1, y0, y1 = box
    v = work.vertices
    lo, hi = v.min(0), v.max(0)
    span = hi - lo
    u = (v[:, 0] - lo[0]) / span[0]
    t = (hi[1] - v[:, 1]) / span[1]
    px = np.clip((x0 + u * (x1 - x0)).astype(int), 0, image.shape[1] - 1)
    py = np.clip((y0 + t * (y1 - y0)).astype(int), 0, image.shape[0] - 1)
    cols = image[py, px]
    side = config["depth_resolution"]
    gx = np.clip((u * (side - 1)).astype(int), 0, side - 1)
    gy = np.clip((t * (side - 1)).astype(int), 0, side - 1)
    depth = np.full((side, side), -np.inf)
    np.maximum.at(depth, (gy, gx), v[:, 2])
    seen = (work.vertex_normals[:, 2] >= config["seen_facing"]) & (v[:, 2] >= depth[gy, gx] - config["depth_tolerance"] * span[1])
    seen_share = float(seen.mean())
    if seen_share < config["min_seen_share"]:
        raise Missed(f"{TOOL}: only {seen_share:.1%} of the working vertices are seen by the front view (needs {config['min_seen_share']:.1%})")
    level = config["background"]["tolerance"] / MAX_CHANNEL
    white = (cols >= level).all(axis=1) & seen  # seen vertices that landed on the background (silhouette, neck)
    good = np.nonzero(seen & ~white)[0]
    if white.any() and len(good):
        _, nearest = cKDTree(v[good]).query(v[white])
        cols[white] = cols[good[nearest]]
    if (~seen).any():
        hidden_fill(work, cols, seen, config, (lo, hi))
    stats = {"seen_share": round(seen_share, 3), "unseen_colours": int(len(np.unique(np.round(cols[~seen] * MAX_CHANNEL), axis=0))) if (~seen).any() else 0}
    return np.clip(np.rint(cols * MAX_CHANNEL), 0, MAX_CHANNEL).astype(np.uint8), stats


def colour(mesh, image, box, config):
    """Return (the input mesh with vertex colours, report body)."""
    work = working_copy(mesh, config["working_faces"])
    work_colours, stats = colour_working(work, image, box, config)
    _, nearest = cKDTree(work.vertices).query(mesh.vertices)
    rgba = np.concatenate([work_colours[nearest], np.full((len(nearest), 1), MAX_CHANNEL, np.uint8)], axis=1)
    out = mesh_io.build(mesh.vertices, mesh.faces, rgba, mesh.metadata)
    return out, {**stats, "faces": int(len(out.faces)), "working_faces": int(len(work.faces)),
                 "colours": int(len(np.unique(rgba[:, :3], axis=0)))}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    config, config_sha = common.load_config(args.config, SCHEMA, TOOL)
    common.require_file(args.mesh, TOOL, "input mesh")
    common.require_file(args.image, TOOL, "front image")
    try:
        image, box = prepare_image(args.image, config)
    except (OSError, ValueError) as exc:
        raise common.NormaliserError(f"{TOOL}: cannot read image {args.image}: {exc}")
    out, report = colour(mesh_io.load_mesh(args.mesh, TOOL), image, box, config)
    mesh_io.save_mesh(out, args.output)
    report.update({"tool": TOOL, "config": config, "config_sha256": config_sha})
    common.write_report(args.report, report)
    return 0


if __name__ == "__main__":
    sys.exit(common.run(TOOL, main))
