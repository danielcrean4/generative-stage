"""Quadric edge-collapse decimation through fast-simplification (MIT; tools interpreter), shared by
decimate_mesh.py, colour_head.py and gate_v2.py so the library call lives in one place.

The library carries no vertex attributes and does not protect topology, so this module adds both:
  * colours: every output vertex takes the colour of the nearest vertex of the ORIGINAL mesh (scipy KD-tree), so
    flat colour areas stay flat and nothing is blended across a colour edge;
  * topology (preserve_topology true): the library only supplies the ORDER of its collapses; each is replayed through
    `Guard`, which skips any collapse that fails the link condition (so no handle closes, no two pieces touch and
    join, the Euler characteristic and piece count stay), would create a non-manifold edge, would move a vertex on an
    open border, or would flip a face. Skipped collapses are made up by asking the library again for the mesh that is
    left. Where no legal collapse remains the result stays above the budget and the caller sees the face count.
    `topology()` measures a mesh; decimate_mesh.py puts the figures before and after in its report.
With preserve_topology false the library runs unguarded (the gate's camera proxy and colour_head's working copy).
"""
import fast_simplification
import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as csgraph
from scipy.spatial import cKDTree

MAX_PASSES = 4  # collapse can land off the target; ask again, never loop forever
ROUNDS = 8  # how many times the library is asked again for the mesh the guard left above the target
FLIP_COS = 0.2  # a face whose normal would turn to less than this cosine of its old direction is flipped
UNDERSHOOT_OK = 0.98  # a result at or under the target and at least this share of it is close enough
DEFAULT_AGG = 5.0  # the library's aggressiveness: 5 reproduced the previous library's camera in every gate case; its default 7 moved one borderline case


def analyse(vertices, faces):
    """(topology figures, body label of every face). Pieces join through shared vertices; bodies through edges that
    exactly two faces share (a piece held by one vertex is two bodies, which is how the gate counts pieces)."""
    faces = np.asarray(faces)
    used = np.unique(faces)
    index = np.full(len(vertices), -1)
    index[used] = np.arange(len(used))
    local = index[faces]
    pairs = np.concatenate([local[:, [0, 1]], local[:, [1, 2]], local[:, [2, 0]]])
    edges, ids, uses = np.unique(np.sort(pairs, axis=1), axis=0, return_inverse=True, return_counts=True)
    ids = ids.reshape(-1)  # edge id of every face side
    graph = sp.coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(used), len(used)))
    pieces = int(csgraph.connected_components(graph, directed=False)[0])
    owners = np.tile(np.arange(len(faces)), 3)
    order = np.argsort(ids, kind="stable")
    side = order[uses[ids[order]] == 2]  # the two sides of every edge two faces share, next to each other
    joined = sp.coo_matrix((np.ones(len(side) // 2), (owners[side][0::2], owners[side][1::2])), shape=(len(faces), len(faces)))
    bodies, labels = csgraph.connected_components(joined, directed=False)
    figures = {"pieces": pieces, "bodies": int(bodies), "euler": int(len(used) - len(edges) + len(faces)),
               "non_manifold_edges": int((uses > 2).sum())}
    return figures, labels


def topology(vertices, faces):
    """{"pieces", "bodies", "euler", "non_manifold_edges"} of a triangle mesh (see analyse)."""
    return analyse(vertices, faces)[0]


def carry_colours(source_vertices, source_colours, vertices):
    """Colours for VERTICES: each takes the colour of its nearest source vertex."""
    _, nearest = cKDTree(source_vertices).query(vertices)
    return np.asarray(source_colours)[nearest]


def collapse(source, target, preserve_border, agg):
    """(vertices, faces) with at most TARGET faces when the library can get there, from SOURCE = (vertices, faces).

    A run can stall above the target (asked again from its result: each run stalls at its own point) or land well
    below it (asked again from the source for the shortfall more); the largest result at or under the target is kept."""
    best, base, ask = None, source, target
    for _ in range(MAX_PASSES):
        if len(base[1]) <= target:
            break
        out_v, out_f = fast_simplification.simplify(base[0], base[1].astype(np.int32), target_count=ask, agg=agg,
                                                    preserve_border=preserve_border)
        base_next = (out_v, np.asarray(out_f, dtype=np.int64))
        count = len(base_next[1])
        if count > target:
            base, ask = base_next, target
            continue
        if best is None or count > len(best[1]):
            best = base_next
        if count >= UNDERSHOOT_OK * target:
            break
        base, ask = source, ask + (target - count)
    return best or base


def vertex_quadrics(vertices, faces):
    """Per-vertex error quadrics (10 numbers each, the upper triangle of the 4x4 matrix) as nested lists: the sum over
    the vertex's faces of the area-weighted squared distance to the face's plane."""
    p = vertices[faces]
    normal = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    length = np.linalg.norm(normal, axis=1)
    unit = normal / np.maximum(length, 1e-300)[:, None]
    d = -(unit * p[:, 0]).sum(axis=1)
    plane = np.concatenate([unit, d[:, None]], axis=1)
    weight = 0.5 * length
    k = np.stack([plane[:, i] * plane[:, j] for i in range(4) for j in range(i, 4)], axis=1) * weight[:, None]
    quadrics = np.zeros((len(vertices), 10))
    for corner in range(3):
        np.add.at(quadrics, faces[:, corner], k)
    return quadrics.tolist()


def quadric_error(q, x, y, z):
    return (q[0] * x * x + 2 * q[1] * x * y + 2 * q[2] * x * z + 2 * q[3] * x + q[4] * y * y + 2 * q[5] * y * z
            + 2 * q[6] * y + q[7] * z * z + 2 * q[8] * z + q[9])


def optimal_point(q):
    """The point of least quadric error (Cramer's rule on the 3x3 system), or None when the system is near singular."""
    a, b, c, d, e, f, g, h, i = q[0], q[1], q[2], q[4], q[5], q[7], -q[3], -q[6], -q[8]
    det = a * (d * f - e * e) - b * (b * f - c * e) + c * (b * e - c * d)
    scale = abs(a * d * f) + 1e-300
    if abs(det) <= 1e-9 * scale:
        return None
    x = (g * (d * f - e * e) - b * (h * f - e * i) + c * (h * e - d * i)) / det
    y = (a * (h * f - e * i) - g * (b * f - c * e) + c * (b * i - c * h)) / det
    z = (a * (d * i - h * e) - b * (b * i - c * h) + g * (b * e - c * d)) / det
    return [x, y, z]


def face_normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)


class Guard:
    """An editable triangle mesh that contracts only the edges whose contraction keeps its topology.

    `contract(a, b)` merges vertex b into vertex a (moving it to the cheapest of a, b and their midpoint by error
    quadric) and returns True, or leaves the mesh alone and returns False when the contraction would:
      * touch a vertex on an open border or on a non-manifold edge (those are never moved);
      * fail the link condition (the two ends may share only the vertices opposite the edge, which is what keeps
        handles, separate pieces and the Euler characteristic);
      * collapse a tetrahedron into a pillow;
      * turn a face over (its normal would swing by more than FLIP_COS) or make it degenerate.
    Neither a handle nor two touching pieces can be joined, and no non-manifold edge can appear."""

    def __init__(self, vertices, faces):
        self.pos = np.asarray(vertices, float).tolist()
        self.faces = np.asarray(faces).tolist()
        self.alive = len(self.faces)
        self.vf = [set() for _ in self.pos]
        self.nb = [set() for _ in self.pos]
        for index, (x, y, z) in enumerate(self.faces):
            for v in (x, y, z):
                self.vf[v].add(index)
            self.nb[x].update((y, z))
            self.nb[y].update((x, z))
            self.nb[z].update((x, y))
        self.quadric = vertex_quadrics(np.asarray(vertices, float), np.asarray(faces))
        self.locked = self.locked_vertices(np.asarray(faces))

    @staticmethod
    def locked_vertices(faces):
        pairs = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
        edges, uses = np.unique(pairs, axis=0, return_counts=True)
        return set(np.unique(edges[uses != 2]).tolist())

    def contract(self, a, b):
        nb, vf, faces, pos = self.nb, self.vf, self.faces, self.pos
        if a == b or b not in nb[a] or a in self.locked or b in self.locked:
            return False
        shared = vf[a] & vf[b]
        if len(shared) != 2:
            return False
        thirds = set()
        for f in shared:
            thirds.update(v for v in faces[f] if v != a and v != b)
        if nb[a] & nb[b] != thirds or (len(nb[a]) == 3 and len(nb[b]) == 3):
            return False
        qa, qb = self.quadric[a], self.quadric[b]
        q = [x + y for x, y in zip(qa, qb)]
        pa, pb = pos[a], pos[b]
        mid = [(x + y) / 2 for x, y in zip(pa, pb)]
        candidates = [pa, pb, mid]
        best = optimal_point(q)
        if best is not None:  # the library puts the merged vertex where the error is least; so does the guard, near the edge
            reach = sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
            if sum((x - y) ** 2 for x, y in zip(best, mid)) ** 0.5 <= 2 * reach:
                candidates.append(best)
        place = min(candidates, key=lambda p: quadric_error(q, p[0], p[1], p[2]))
        for f in (vf[a] | vf[b]) - shared:
            x, y, z = faces[f]
            old = face_normal(pos[x], pos[y], pos[z])
            moved = [place if v == a or v == b else pos[v] for v in (x, y, z)]
            new = face_normal(*moved)
            dot = old[0] * new[0] + old[1] * new[1] + old[2] * new[2]
            if dot <= FLIP_COS * (sum(c * c for c in old) * sum(c * c for c in new)) ** 0.5 or dot <= 0:
                return False
        for f in shared:
            for v in faces[f]:
                vf[v].discard(f)
            faces[f] = None
        self.alive -= 2
        for f in vf[b]:
            faces[f] = [a if v == b else v for v in faces[f]]
            vf[a].add(f)
        vf[b] = set()
        for n in nb[b]:
            nb[n].discard(b)
            if n != a:
                nb[n].add(a)
                nb[a].add(n)
        nb[a].discard(b)
        nb[b] = set()
        pos[a], self.quadric[a] = list(place), q
        return True

    def result(self):
        """(vertices, faces) with only the vertices still in use."""
        kept = np.array([f for f in self.faces if f is not None], dtype=np.int64).reshape(-1, 3)
        used = np.unique(kept)
        index = np.full(len(self.pos), -1)
        index[used] = np.arange(len(used))
        return np.asarray(self.pos)[used], index[kept]


def guarded_collapse(source, target, agg):
    """(vertices, faces, stats) of SOURCE contracted towards TARGET faces without changing its topology.

    The library supplies the order (its collapse sequence for the mesh as it stands); every collapse is replayed through
    Guard, which skips the illegal ones. If skipped collapses leave the mesh above the target, the library is asked again
    for the mesh that is left, for a deeper reduction (up to ROUNDS times) while collapses are still being accepted."""
    base = source
    stats = {"rounds": 0, "accepted": 0, "skipped": 0}
    for _ in range(ROUNDS):
        if len(base[1]) <= target:
            break
        ask = max(1, target - (len(base[1]) - target) * stats["rounds"])
        _, _, sequence = fast_simplification.simplify(base[0], base[1].astype(np.int32), target_count=min(ask, len(base[1]) - 1),
                                                      agg=agg, preserve_border=True, return_collapses=True)
        guard, taken = Guard(*base), 0
        for a, b in sequence.tolist():
            if guard.alive <= target:
                break
            if guard.contract(a, b):
                taken += 1
            else:
                stats["skipped"] += 1
        stats["rounds"] += 1
        stats["accepted"] += taken
        base = guard.result()
        if not taken:
            break
    return base[0], base[1], stats


def decimate(vertices, faces, target_faces, preserve_topology, colors=None):
    """Return (vertices, faces, colors-or-None) with at most TARGET_FACES faces when reachable.

    COLORS is uint8 RGBA per vertex of the input; the output has them per output vertex (see the module text).
    A mesh already within the target is returned as it is. With PRESERVE_TOPOLOGY the collapses are guarded (see Guard),
    so Euler characteristic, pieces and non-manifold edges are as the input had them, and the result may stay above the
    target when no legal collapse is left; callers compare the face count with the budget.
    """
    target = int(target_faces)
    source = (np.asarray(vertices, float), np.asarray(faces))
    if len(source[1]) <= target:
        return source[0], source[1], (None if colors is None else np.asarray(colors, np.uint8))
    if preserve_topology:
        out_v, out_f, _ = guarded_collapse(source, target, DEFAULT_AGG)
    else:
        out_v, out_f = collapse(source, target, False, DEFAULT_AGG)
    if colors is not None:
        colors = carry_colours(source[0], np.asarray(colors, np.uint8), out_v)
    return out_v, out_f, colors
