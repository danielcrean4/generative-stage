"""The stand-in's `mesh` mode: a closed solid raised from the silhouette of a picture. Standard library only.

The subject is found against the white background (or in the alpha channel), the outline is cut out of a coarse grid
with its true position found along each grid edge, and the outline's inside is inflated into a flat plate with a rounded edge: the height at a
point is a rounded profile of its distance from the outline, mirrored front and back, so the two halves meet exactly on
the outline and the surface is closed. Each vertex takes its colour from the picture (with the painter's shading divided out, as the viewer lights the solid itself). Where the picture is busy the
front is meshed three times finer, within the face budget. Nothing is learned: the same
picture always gives the same solid, and its outline from the front is the picture's outline.

Frame (the one the pipeline's mesh clean-up expects from a generator): x runs right along the picture, y up it and z
towards the viewer, so the side that was drawn faces +z. Units: the subject's longer side is 2.
"""
import math
import struct
import zlib

DEPTH_SHARE = 0.17  # half the thickness of the plate, as a share of the subject's shorter side
ROUNDING = 0.6  # the width of the rounded edge, in half-thicknesses
CELLS = 1500  # about this many coarse grid cells inside the subject, to start with
DETAIL_RANGE = 34  # a cell is split finely where the picture's brightness varies by more than this within it
MAX_FACES = 7700  # the grid is coarsened until the solid has no more faces than this (the contract's budget is 8000)
LIGHT_IN_SOLID = (-0.4508, 0.6211, 0.6411)  # the painter's light, y up (see standin_paint.LIGHT)
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
    cell = max(3.0, math.sqrt(len(inside) / CELLS))
    while True:  # the finest grid whose solid stays inside the face budget, so no later stage has to thin it
        grid = _grid(subject, left, top, right, bottom, cell)
        if grid.face_count() <= MAX_FACES:
            break
        cell *= 1.04
    positions, outline = grid.positions, grid.outline
    heights = _heights(grid, cell, right - left, bottom - top)
    scale = 2.0 / max(right - left, bottom - top)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    front = [((x - cx) * scale, (cy - y) * scale, heights[k] * scale) for k, (x, y, _) in enumerate(positions)]
    points, back = list(front), {}

    def behind(k):
        if heights[k] <= 1e-9:
            return k
        if k not in back:
            back[k] = len(points)
            points.append((front[k][0], front[k][1], -front[k][2]))
        return back[k]

    triangles = []
    for polygon in grid.front:
        for a in range(1, len(polygon) - 1):
            triangles.append((polygon[0], polygon[a], polygon[a + 1]))
    for polygon in grid.back:
        for a in range(1, len(polygon) - 1):
            triangles.append((behind(polygon[0]), behind(polygon[a + 1]), behind(polygon[a])))
    triangles = [t for t in triangles if len(set(t)) == 3]
    if _volume(points, triangles) < 0:
        triangles = [(a, c, b) for a, b, c in triangles]
    normals = _normals(points, triangles)
    colours = [None] * len(points)
    for k in range(len(front)):
        seen = subject.colour(*_inward(subject, positions[k], k in outline))
        colours[k] = _unlit(seen, normals[k], k in outline)
    for k, j in back.items():
        colours[j] = colours[k]
    return points, normals, triangles, colours


def _unlit(seen, normal, on_outline):
    """The picture's colour with the painter's shading taken out, so the viewer's own light does the shading.

    The picture was lit from the top left (standin_paint.LIGHT, seen from the front: x right, y up in the solid's frame);
    the solid's own normal gives the same light, and the colour is divided by it, within limits."""
    if on_outline:
        return seen
    lx, ly, lz = LIGHT_IN_SOLID
    shade = 0.36 + 0.82 * max(0.0, normal[0] * lx + normal[1] * ly + abs(normal[2]) * lz)
    shade = min(1.2, max(0.55, shade))
    return tuple(min(1.0, c / shade) for c in seen)


class Grid:
    """The front's polygons (fine where the picture has detail), the back's polygons (coarse), and the vertices."""

    def __init__(self):
        self.positions, self.outline, self.chords = [], set(), []
        self.front, self.back, self.lattice = [], [], {}

    def face_count(self):
        return sum(len(p) - 2 for p in self.front) + sum(len(p) - 2 for p in self.back)


def _busy(subject, x0, y0, x1, y1):
    """Whether the picture changes a lot between (x0, y0) and (x1, y1): strings, pegs, a sound hole, an edge."""
    low, high = 255.0, 0.0
    for y in range(int(y0), int(y1) + 1):
        row = subject.rows[y] if 0 <= y < subject.height else None
        if row is None:
            continue
        for x in range(int(x0), int(x1) + 1):
            if 0 <= x < subject.width:
                i = x * subject.channels
                v = sum(row[i:i + 3]) / 3 if subject.channels >= 3 else row[i]
                low, high = min(low, v), max(high, v)
    return high - low > DETAIL_RANGE


def _grid(subject, left, top, right, bottom, cell):
    """The cells of a grid over the subject, each cut by the outline. Cells wholly inside where the picture is busy are
    split three ways each side on the front only; the back keeps the coarse cells, so detail costs the face budget once."""
    nx, ny = int((right - left) / cell) + 3, int((bottom - top) / cell) + 3
    x0, y0 = left - cell, top - cell
    corner_in = [[subject.at(x0 + i * cell, y0 + j * cell) for i in range(nx)] for j in range(ny)]
    grid, crossings = Grid(), {}
    positions, step = grid.positions, cell / 3.0
    full = {(i, j) for j in range(ny - 1) for i in range(nx - 1)
            if corner_in[j][i] and corner_in[j][i + 1] and corner_in[j + 1][i] and corner_in[j + 1][i + 1]}
    busy = {c for c in full if _busy(subject, x0 + c[0] * cell, y0 + c[1] * cell, x0 + (c[0] + 1) * cell,
                                     y0 + (c[1] + 1) * cell)}

    def lattice(fi, fj):
        if (fi, fj) not in grid.lattice:
            grid.lattice[(fi, fj)] = len(positions)
            positions.append((x0 + fi * step, y0 + fj * step, 0.0))
        return grid.lattice[(fi, fj)]

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
            if (i, j) in busy:
                for dj in range(3):
                    for di in range(3):
                        fi, fj = 3 * i + di, 3 * j + dj
                        grid.front.append([lattice(fi, fj), lattice(fi + 1, fj), lattice(fi + 1, fj + 1),
                                           lattice(fi, fj + 1)])
                grid.back.append([lattice(3 * a, 3 * b) for a, b in ring])
                continue
            polygon, cut, coarse = [], [], []
            for k in range(4):
                a, b = ring[k], ring[(k + 1) % 4]
                if flags[k]:
                    v = lattice(3 * a[0], 3 * a[1])
                    polygon.append(v)
                    coarse.append(v)
                    cut.append(False)
                    if flags[(k + 1) % 4] and _across(i, j, k) in busy:  # the busy cell across this edge has two points on it
                        for t in (1, 2):
                            polygon.append(lattice(3 * a[0] + (b[0] - a[0]) * t, 3 * a[1] + (b[1] - a[1]) * t))
                            cut.append(False)
                if flags[k] != flags[(k + 1) % 4]:
                    v = crossing(a, b)
                    polygon.append(v)
                    coarse.append(v)
                    cut.append(True)
            for k in range(len(polygon)):
                if cut[k] and cut[(k + 1) % len(polygon)]:
                    grid.chords.append((polygon[k], polygon[(k + 1) % len(polygon)]))
            grid.front.append(polygon)
            grid.back.append(coarse)
    grid.outline = set(crossings.values())
    return grid


def _across(i, j, k):
    """The cell across side K of cell (I, J); the sides run top, right, bottom, left."""
    return [(i, j - 1), (i + 1, j), (i, j + 1), (i - 1, j)][k]


def _inward(subject, position, on_outline):
    """Where to read the colour for a vertex: on the outline, a little way inside it (the edge pixels are blended)."""
    x, y, _ = position
    if not on_outline:
        return x, y
    for dx, dy in ((4, 0), (-4, 0), (0, 4), (0, -4), (3, 3), (-3, -3), (3, -3), (-3, 3), (2, 0), (-2, 0), (0, 2), (0, -2)):
        if subject.at(x + dx, y + dy) and subject.at(x + dx * 0.5, y + dy * 0.5):
            return x + dx, y + dy
    return x, y


def _heights(grid, cell, width, height):
    """Half-thickness at each front vertex: a flat plate with a rounded edge, thinner where the shape is narrow.

    A vertex's distance to the outline is measured to the outline's segments. The plate's thickness is the full depth
    only where the shape is wide (the widest distance to the outline within reach); a neck or a peg gets a thickness
    that fits its own width, so thin parts do not swell. Two passes of smoothing even out the steps."""
    positions, outline = grid.positions, grid.outline
    depth = DEPTH_SHARE * min(width, height)
    reach = 1.3 * depth  # distances beyond this are not needed
    buckets = {}
    size = max(reach, cell * 2)
    for a, b in grid.chords:
        (ax, ay, _), (bx, by, _) = positions[a], positions[b]
        for kx in range(int((min(ax, bx) - reach) // size), int((max(ax, bx) + reach) // size) + 1):
            for ky in range(int((min(ay, by) - reach) // size), int((max(ay, by) + reach) // size) + 1):
                buckets.setdefault((kx, ky), []).append((ax, ay, bx, by))
    dist = []
    for k, (x, y, _) in enumerate(positions):
        if k in outline:
            dist.append(0.0)
            continue
        best = reach
        for ax, ay, bx, by in buckets.get((int(x // size), int(y // size)), ()):
            ex, ey = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * ex + (y - ay) * ey) / (ex * ex + ey * ey or 1e-9)))
            best = min(best, math.hypot(x - ax - ex * t, y - ay - ey * t))
        dist.append(best)
    ids = grid.lattice
    span = max(1, int(depth / cell))
    widest = {}
    coarse = {(i // 3, j // 3): k for (i, j), k in ids.items() if i % 3 == 0 and j % 3 == 0}
    for (i, j), k in coarse.items():
        best = dist[k]
        for di in range(-span, span + 1):
            for dj in range(-span, span + 1):
                n = coarse.get((i + di, j + dj))
                if n is not None and dist[n] > best and di * di + dj * dj <= span * span:
                    best = dist[n]
        widest[(i, j)] = best
    near = {}
    for (i, j), k in ids.items():
        c = (round(i / 3), round(j / 3))
        near[k] = widest.get(c, widest.get((i // 3, j // 3), dist[k]))
    widest = near
    heights = []
    for k in range(len(positions)):
        if k in outline:
            heights.append(0.0)
            continue
        local = min(depth, 0.9 * max(widest.get(k, 0.0), dist[k]))
        rim = max(cell, ROUNDING * local)
        f = min(1.0, dist[k] / rim)
        heights.append(local * math.sqrt(max(0.0, 1 - (1 - f) ** 2)) + 1e-6)
    for _ in range(2):
        smoothed = list(heights)
        for (i, j), k in ids.items():
            if k in outline or heights[k] <= 1e-6:
                continue
            around = [heights[n] for n in (ids.get((i + 1, j)), ids.get((i - 1, j)), ids.get((i, j + 1)), ids.get((i, j - 1)))
                      if n is not None]
            if around:
                smoothed[k] = 0.5 * heights[k] + 0.5 * sum(around) / len(around)
        heights = smoothed
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
