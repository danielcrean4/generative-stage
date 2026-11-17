"""The stand-in's `mesh` mode: a closed solid raised from the silhouette of a picture. Standard library only.

The subject is found against the white background (or in the alpha channel), the outline is cut out of a coarse grid
with its true position found along each grid edge, and the outline's inside is inflated into a pillow: the height at a
point is a rounded profile of its distance from the outline, mirrored front and back, so the two halves meet exactly on
the outline and the surface is closed. Each vertex takes its colour from the picture. Nothing is learned: the same
picture always gives the same solid, and its outline from the front is the picture's outline.

Frame (the one the pipeline's mesh clean-up expects from a generator): x runs right along the picture, y up it and z
towards the viewer, so the side that was drawn faces +z. Units: the subject's longer side is 2.
"""
import math
import struct
import zlib

DEPTH_SHARE = 0.18  # half the thickness, as a share of the subject's shorter side
ROUNDING = 1.4  # how far from the outline (in half-thicknesses) the top flattens out
CELLS = 1200  # about this many grid cells inside the subject
NEAR_WHITE = 240  # a pixel with every channel at least this bright is background


def read_png(data):
    """(width, height, channels, rows) of an 8-bit grey, grey+alpha, RGB or RGBA PNG; rows are bytearrays."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos, header, parts = 8, None, []
    while pos < len(data):
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            parts.append(body)
        pos += 12 + size
    width, height, depth, colour, _, _, interlace = header
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour)
    if depth != 8 or channels is None or interlace:
        raise ValueError("only 8-bit grey, RGB and alpha PNGs without interlacing are read")
    raw = zlib.decompress(b"".join(parts))
    stride = width * channels
    rows, previous = [], bytearray(stride)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if kind == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif kind == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 255
        elif kind == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = previous[i]
                c = previous[i - channels] if i >= channels else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        previous = line
    return width, height, channels, rows


class Subject:
    """The picture's pixels and the mask of what is subject."""

    def __init__(self, data):
        self.width, self.height, self.channels, self.rows = read_png(data)
        alphas = [row[self.channels - 1::self.channels] for row in self.rows] if self.channels in (2, 4) else None
        keyed = alphas is not None and any(min(a) < 255 for a in alphas)
        self.mask = []
        for y, row in enumerate(self.rows):
            if keyed:
                self.mask.append(bytearray(1 if v >= 128 else 0 for v in alphas[y]))
            else:
                step = self.channels if self.channels >= 3 else 1
                shown = 3 if self.channels >= 3 else 1
                self.mask.append(bytearray(
                    1 if min(row[x:x + shown]) < NEAR_WHITE else 0 for x in range(0, self.width * step, step)))

    def at(self, x, y):
        x, y = int(x), int(y)
        return 0 <= x < self.width and 0 <= y < self.height and self.mask[y][x] == 1

    def colour(self, x, y):
        """The picture's colour near (x, y), averaged over the subject pixels in a 3 x 3 block."""
        total, n = [0, 0, 0], 0
        for yy in range(int(y) - 1, int(y) + 2):
            for xx in range(int(x) - 1, int(x) + 2):
                if 0 <= xx < self.width and 0 <= yy < self.height and self.mask[yy][xx]:
                    row, step = self.rows[yy], self.channels
                    r = row[xx * step:xx * step + 3] if step >= 3 else bytes([row[xx * step]] * 3)
                    total[0] += r[0]
                    total[1] += r[1]
                    total[2] += r[2]
                    n += 1
        return tuple(v / n / 255 for v in total) if n else (0.6, 0.6, 0.6)


def build(data):
    """(points, normals, triangles, colours) of the solid raised from the picture in DATA."""
    subject = Subject(data)
    inside = [(x, y) for y, row in enumerate(subject.mask) for x, v in enumerate(row) if v]
    if len(inside) < 16:
        raise ValueError("no subject found in the picture")
    left, right = min(p[0] for p in inside), max(p[0] for p in inside) + 1
    top, bottom = min(p[1] for p in inside), max(p[1] for p in inside) + 1
    cell = max(2.0, math.sqrt(len(inside) / CELLS))
    nx, ny = int((right - left) / cell) + 3, int((bottom - top) / cell) + 3
    x0, y0 = left - cell, top - cell
    corner_in = [[subject.at(x0 + i * cell, y0 + j * cell) for i in range(nx)] for j in range(ny)]

    positions, tints = [], []  # the front half's vertices, then the layout of ids
    crossings, corner_id, chords, polygons = {}, {}, [], []

    def corner(i, j):
        if (i, j) not in corner_id:
            corner_id[(i, j)] = len(positions)
            positions.append((x0 + i * cell, y0 + j * cell, 0.0))
        return corner_id[(i, j)]

    def crossing(a, b):
        """The vertex where the outline cuts the grid edge from corner A (inside) to B (outside)."""
        key = (min(a, b), max(a, b))
        if key not in crossings:
            (ia, ja), (ib, jb) = (a, b) if corner_in[a[1]][a[0]] else (b, a)
            ax, ay = x0 + ia * cell, y0 + ja * cell
            bx, by = x0 + ib * cell, y0 + jb * cell
            lo, hi = 0.0, 1.0
            for _ in range(5):
                mid = (lo + hi) / 2
                if subject.at(ax + (bx - ax) * mid, ay + (by - ay) * mid):
                    lo = mid
                else:
                    hi = mid
            t = min(0.92, max(0.08, (lo + hi) / 2))
            crossings[key] = len(positions)
            positions.append((ax + (bx - ax) * t, ay + (by - ay) * t, 0.0))
        return crossings[key]

    for j in range(ny - 1):
        for i in range(nx - 1):
            ring = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            flags = [corner_in[b][a] for a, b in ring]
            if not any(flags):
                continue
            polygon, cut = [], []
            for k in range(4):
                a, b = ring[k], ring[(k + 1) % 4]
                if flags[k]:
                    polygon.append(corner(*a))
                    cut.append(False)
                if flags[k] != flags[(k + 1) % 4]:
                    polygon.append(crossing(a, b))
                    cut.append(True)
            for k in range(len(polygon)):
                if cut[k] and cut[(k + 1) % len(polygon)]:
                    chords.append((polygon[k], polygon[(k + 1) % len(polygon)]))
            polygons.append(polygon)

    outline = set(crossings.values())
    heights = _heights(positions, outline, chords, cell, right - left, bottom - top)
    count = len(positions)
    scale = 2.0 / max(right - left, bottom - top)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    points, colours = [], []
    for k in range(count):
        x, y, _ = positions[k]
        points.append(((x - cx) * scale, (cy - y) * scale, heights[k] * scale))  # the drawn side faces +z
        colours.append(subject.colour(*_inward(subject, positions[k], k in outline)))
    back = {}
    for k in range(count):
        if heights[k] <= 1e-9:
            back[k] = k
        else:
            back[k] = len(points)
            points.append((points[k][0], points[k][1], -points[k][2]))
            colours.append(colours[k])
    triangles = []
    for polygon in polygons:
        for a in range(1, len(polygon) - 1):
            triangles.append((polygon[0], polygon[a], polygon[a + 1]))
            triangles.append((back[polygon[0]], back[polygon[a + 1]], back[polygon[a]]))
    triangles = [t for t in triangles if len(set(t)) == 3]
    if _volume(points, triangles) < 0:
        triangles = [(a, c, b) for a, b, c in triangles]
    return points, _normals(points, triangles), triangles, colours


def _inward(subject, position, on_outline):
    """Where to read the colour for a vertex: on the outline, a little way inside it (the edge pixels are blended)."""
    x, y, _ = position
    if not on_outline:
        return x, y
    best = None
    for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2), (2, 2), (-2, -2), (2, -2), (-2, 2), (3, 0), (-3, 0), (0, 3), (0, -3)):
        if subject.at(x + dx, y + dy) and subject.at(x + dx * 0.5, y + dy * 0.5):
            best = (x + dx, y + dy)
            break
    return best or (x, y)


def _heights(positions, outline, chords, cell, width, height):
    """Half-thickness at each front vertex: a rounded profile of the distance to the outline's segments."""
    depth = DEPTH_SHARE * min(width, height)
    reach = ROUNDING * depth
    buckets = {}
    size = max(reach, cell * 2)
    for a, b in chords:
        (ax, ay, _), (bx, by, _) = positions[a], positions[b]
        for kx in range(int((min(ax, bx) - reach) // size), int((max(ax, bx) + reach) // size) + 1):
            for ky in range(int((min(ay, by) - reach) // size), int((max(ay, by) + reach) // size) + 1):
                buckets.setdefault((kx, ky), []).append((ax, ay, bx, by))
    heights = []
    for k, (x, y, _) in enumerate(positions):
        if k in outline:
            heights.append(0.0)
            continue
        best = reach
        for ax, ay, bx, by in buckets.get((int(x // size), int(y // size)), ()):
            ex, ey = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * ex + (y - ay) * ey) / (ex * ex + ey * ey or 1e-9)))
            best = min(best, math.hypot(x - ax - ex * t, y - ay - ey * t))
        f = best / reach
        heights.append(depth * math.sqrt(max(0.0, 1 - (1 - f) ** 2)) + 1e-6)
    return heights


def _volume(points, triangles):
    total = 0.0
    for a, b, c in triangles:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = points[a], points[b], points[c]
        total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return total / 6


def _normals(points, triangles):
    sums = [[0.0, 0.0, 0.0] for _ in points]
    for a, b, c in triangles:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = points[a], points[b], points[c]
        ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        for i in (a, b, c):
            sums[i][0] += n[0]
            sums[i][1] += n[1]
            sums[i][2] += n[2]
    out = []
    for x, y, z in sums:
        length = math.sqrt(x * x + y * y + z * z) or 1.0
        out.append((x / length, y / length, z / length))
    return out
