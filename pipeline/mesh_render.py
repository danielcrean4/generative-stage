"""Draw a mesh to an image on the CPU: an orthographic z-buffer renderer (tools interpreter: numpy, PIL).

One job: turn vertices and faces into a picture, correct on curved and concave surfaces. Every pixel
keeps the nearest triangle that covers it (a per-pixel depth test), so nothing hidden shows through a
gap; the painter's-sort renderer behind the 11 Nov contact sheets could not promise that. Rasterising
is vectorised: triangles are bucketed by the size of their pixel box and tested against all the pixels
of the box at once, there is no per-pixel Python loop.

Views are named relative to the contract's axes (up_axis and front_axis, as in normalize_mesh): the
front view looks at the subject's front, so the screen's right is the subject's +right where
right = up x front; back looks from behind; side looks from the left of the front view (the subject's
front points to the screen's right); top looks down with the subject's front at the bottom.

Nothing about how it looks has a default here. Colours, light, shading mode, margin and sizes arrive in
a style dict (STYLE_SCHEMA lists the keys, check_style validates them); review_sheet.py reads them from
the config's `review_sheet` block.
"""
import numpy as np

import normaliser_common as common
import normalize_mesh

VIEWS = ("front", "side", "top", "back")
EDGE_TOLERANCE = 1e-7      # barycentric slack so a pixel centre on a shared edge belongs to both triangles
MIN_DOUBLE_AREA = 1e-12    # triangles smaller than this on screen are degenerate and draw nothing
FRAGMENT_BUDGET = 1 << 22  # pixels tested per batch; bounds memory for large triangles
RGB_MAX = 255.0


def _colour(value):
    common.rgb(value)


def _unit_share(value):
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise ValueError("must be a number from 0 to 1")


def _margin(value):
    if type(value) not in (int, float) or not 0 <= value < 0.5:
        raise ValueError("must be a number from 0 up to (not including) 0.5")


def _light(value):
    if not (isinstance(value, list) and len(value) == 3 and all(type(v) in (int, float) for v in value)):
        raise ValueError("must be three numbers [right, up, toward the viewer]")
    if not np.linalg.norm(value) > 0:
        raise ValueError("must not be the zero vector")


STYLE_SCHEMA = {"size": common.positive_int, "supersample": common.positive_int, "margin": _margin,
                "shading": common.one_of("flat", "smooth"), "background": _colour, "surface": _colour,
                "ambient": _unit_share, "light": _light}


def check_style(style):
    """Raise ValueError('style.KEY must ...') for a missing, unknown or invalid style key."""
    if not isinstance(style, dict):
        raise ValueError("style must be an object")
    for key in STYLE_SCHEMA:
        if key not in style:
            raise ValueError(f"missing key {key}")
    for key in style:
        if key not in STYLE_SCHEMA:
            raise ValueError(f"unknown key {key}")
    for key, check in STYLE_SCHEMA.items():
        try:
            check(style[key])
        except ValueError as exc:
            raise ValueError(f"{key} {exc}")


def view_axes(name, up_axis, front_axis):
    """3x3 matrix, rows = the screen's right, up and toward-the-viewer axes in mesh coordinates."""
    if name not in VIEWS:
        raise ValueError(f"unknown view {name!r}; views are {', '.join(VIEWS)}")
    up, front = normalize_mesh.axis_vector(up_axis), normalize_mesh.axis_vector(front_axis)
    right = np.cross(up, front)
    toward, screen_up = {"front": (front, up), "back": (-front, up),
                         "side": (-right, up), "top": (up, -front)}[name]
    return np.array([np.cross(screen_up, toward), screen_up, toward])


def fit(vertices, size, margin):
    """(centre, scale): one pixel scale shared by every view, so the largest extent fits with MARGIN to spare."""
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    span = float((hi - lo).max())
    if not span > 0:
        raise ValueError("mesh has no extent")
    return (lo + hi) / 2, size * (1 - 2 * margin) / span


def _project(vertices, axes, centre, scale, size):
    """Screen x, y (pixels, y downwards) and depth (larger = nearer) of every vertex."""
    local = (np.asarray(vertices, float) - centre) @ axes.T
    return local[:, 0] * scale + size / 2, size / 2 - local[:, 1] * scale, local[:, 2] * scale


def _barycentric(px, py, x, y):
    """Barycentric weights (3 arrays shaped like px/py) of points in triangles; x, y are (T,3) vertex screen coordinates."""
    shape = (-1,) + (1,) * (px.ndim - 1)
    x0, x1, x2 = (x[:, i].reshape(shape) for i in range(3))
    y0, y1, y2 = (y[:, i].reshape(shape) for i in range(3))
    double_area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    w1 = ((px - x0) * (y2 - y0) - (x2 - x0) * (py - y0)) / double_area
    w2 = ((x1 - x0) * (py - y0) - (px - x0) * (y1 - y0)) / double_area
    return 1 - w1 - w2, w1, w2


def _fragments(x, y, depth, faces, size):
    """Every (pixel index, depth, face index) whose pixel centre lies inside a triangle (not yet depth-tested)."""
    fx, fy, fz = x[faces], y[faces], depth[faces]
    double_area = (fx[:, 1] - fx[:, 0]) * (fy[:, 2] - fy[:, 0]) - (fx[:, 2] - fx[:, 0]) * (fy[:, 1] - fy[:, 0])
    first_col = np.maximum(np.ceil(fx.min(axis=1) - 0.5), 0).astype(int)
    last_col = np.minimum(np.floor(fx.max(axis=1) - 0.5), size - 1).astype(int)
    first_row = np.maximum(np.ceil(fy.min(axis=1) - 0.5), 0).astype(int)
    last_row = np.minimum(np.floor(fy.max(axis=1) - 0.5), size - 1).astype(int)
    cols, rows = last_col - first_col + 1, last_row - first_row + 1
    alive = np.nonzero((np.abs(double_area) > MIN_DOUBLE_AREA) & (cols > 0) & (rows > 0))[0]
    reach = np.maximum(cols[alive], rows[alive])
    bucket = np.ceil(np.log2(np.maximum(reach, 1))).astype(int)   # triangles whose box fits 2**bucket pixels
    found = []
    for b in np.unique(bucket):
        ids = alive[bucket == b]
        side = 1 << int(b)
        step = max(1, FRAGMENT_BUDGET // (side * side))
        offsets = np.arange(side)
        for start in range(0, len(ids), step):
            t = ids[start:start + step]
            j = first_col[t][:, None] + offsets[None, :]                     # (T, side) columns
            i = first_row[t][:, None] + offsets[None, :]                     # (T, side) rows
            px = np.broadcast_to((j + 0.5)[:, None, :], (len(t), side, side))
            py = np.broadcast_to((i + 0.5)[:, :, None], (len(t), side, side))
            w0, w1, w2 = _barycentric(px, py, fx[t], fy[t])
            inside = ((w0 >= -EDGE_TOLERANCE) & (w1 >= -EDGE_TOLERANCE) & (w2 >= -EDGE_TOLERANCE)
                      & (j <= last_col[t][:, None])[:, None, :] & (i <= last_row[t][:, None])[:, :, None])
            n, r, c = np.nonzero(inside)
            z = w0[n, r, c] * fz[t[n], 0] + w1[n, r, c] * fz[t[n], 1] + w2[n, r, c] * fz[t[n], 2]
            found.append((i[n, r] * size + j[n, c], z, t[n]))
    if not found:
        return (np.empty(0, int),) * 3
    return tuple(np.concatenate(part) for part in zip(*found))


def rasterise(vertices, faces, axes, centre, scale, size):
    """Depth test at SIZE x SIZE pixels: (depth, face) images. depth is -inf and face is -1 where nothing covers the pixel."""
    x, y, z = _project(vertices, axes, centre, scale, size)
    pixel, depth, face = _fragments(x, y, z, np.asarray(faces), size)
    depth_image = np.full(size * size, -np.inf)
    face_image = np.full(size * size, -1, dtype=int)
    if len(pixel):
        order = np.lexsort((face, -depth, pixel))        # per pixel: nearest first, lowest face index on a tie
        pixel, depth, face = pixel[order], depth[order], face[order]
        first = np.r_[True, pixel[1:] != pixel[:-1]]
        depth_image[pixel[first]], face_image[pixel[first]] = depth[first], face[first]
    return depth_image.reshape(size, size), face_image.reshape(size, size)


def _normals(vertices, faces, smooth):
    """(face normals, vertex normals or None): unit vectors, area-weighted at the vertices."""
    a, b, c = (vertices[faces[:, i]] for i in range(3))
    raw = np.cross(b - a, c - a)
    length = np.linalg.norm(raw, axis=1, keepdims=True)
    unit = np.divide(raw, length, out=np.zeros_like(raw), where=length > 0)
    if not smooth:
        return unit, None
    summed = np.zeros_like(vertices)
    for i in range(3):
        np.add.at(summed, faces[:, i], raw)               # raw length is twice the area: area weighting
    size = np.linalg.norm(summed, axis=1, keepdims=True)
    return unit, np.divide(summed, size, out=np.zeros_like(summed), where=size > 0)


def render(vertices, faces, view, up_axis, front_axis, style, colors=None, scale_from=None):
    """The mesh drawn from VIEW as an (size, size, 3) uint8 array, plus the depth image at the drawn resolution.

    Lit by one key light (style["light"], in the camera's right/up/toward axes) plus an ambient share,
    two-sided, so inconsistent winding does not matter. Vertex COLORS (uint8, N x 3 or N x 4) are used
    when given, style["surface"] otherwise. SCALE_FROM is a (centre, scale) pair at output resolution
    from fit(), to draw several views at one scale; by default the mesh fits this view alone.
    The picture is drawn at size x supersample and averaged down.
    """
    check_style(style)
    vertices, faces = np.asarray(vertices, float), np.asarray(faces)
    size = style["size"] * style["supersample"]
    centre, scale = scale_from or fit(vertices, style["size"], style["margin"])
    axes = view_axes(view, up_axis, front_axis)
    depth, face = rasterise(vertices, faces, axes, centre, scale * style["supersample"], size)
    picture = np.empty((size, size, 3))
    picture[:] = style["background"]
    covered = face >= 0
    rows, cols = np.nonzero(covered)
    tri = face[covered]
    x, y, z = _project(vertices, axes, centre, scale * style["supersample"], size)
    w0, w1, w2 = _barycentric(cols + 0.5, rows + 0.5, x[faces[tri]], y[faces[tri]])
    weights = np.stack([w0, w1, w2], axis=1)
    face_normals, vertex_normals = _normals(vertices, faces, style["shading"] == "smooth")
    if vertex_normals is None:
        normal = face_normals[tri]
    else:
        normal = np.einsum("nk,nkd->nd", weights, vertex_normals[faces[tri]])
        length = np.linalg.norm(normal, axis=1, keepdims=True)
        normal = np.divide(normal, length, out=face_normals[tri], where=length > 0)
    camera_normal = normal @ axes.T
    camera_normal *= np.where(camera_normal[:, 2:3] < 0, -1.0, 1.0)      # two-sided: face the viewer
    light = np.asarray(style["light"], float)
    shade = np.clip(camera_normal @ (light / np.linalg.norm(light)), 0, 1)
    intensity = style["ambient"] + (1 - style["ambient"]) * shade
    if colors is None:
        base = np.broadcast_to(np.asarray(style["surface"], float), (len(tri), 3))
    else:
        base = np.einsum("nk,nkd->nd", weights, np.asarray(colors, float)[faces[tri]][:, :, :3])
    picture[rows, cols] = np.clip(base * intensity[:, None], 0, RGB_MAX)
    s = style["supersample"]
    small = picture.reshape(style["size"], s, style["size"], s, 3).mean(axis=(1, 3))
    return np.rint(small).astype(np.uint8), depth
