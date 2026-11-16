"""The rig gate: is a rigged .glb's skin usable? Plain Python, standard library only (docs/pipeline_files.md).

    python3 -I pipeline/rig_gate.py RIGGED.glb --gate GATE.json --out DIR

GATE.json is the stage's gate block; every key is required (no defaults):

    min_weighted_share   share of vertices that must carry some bone weight (an unweighted vertex never moves)
    max_influences       the most bones one vertex may follow (game engines take 4)
    min_inside_share     share of the deforming bones whose joint must sit inside the mesh

A deforming bone is a skin joint that carries weight on some vertex. Its joint position is read from the skin's
inverse bind matrices, so it is in the mesh's own space; "inside" is an odd number of crossings on at least two of
three rays. Writes DIR/rig-validation.json: {"verdict": "pass" | "fail", "reasons": [...], "measures": {name:
{value, limit, margin, outcome}}, "facts": {...}}; exits 0 on pass, 1 on fail, 2 when the file cannot be read.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import glb_read  # noqa: E402

GATE_KEYS = ("min_weighted_share", "max_influences", "min_inside_share")
REPORT = "rig-validation.json"
WEIGHTED = 1e-6   # a total weight above this counts as weighted
RAYS = ((1.0, 0.013, 0.007), (-0.011, 1.0, 0.017), (0.019, -0.009, 1.0))  # off-axis, so a ray rarely meets an edge
EPSILON = 1e-12


def parse_gate(raw):
    """The gate block RAW checked; ValueError names the first wrong key."""
    if not isinstance(raw, dict):
        raise ValueError("the rig gate must be an object")
    missing = [key for key in GATE_KEYS if key not in raw]
    unknown = sorted(set(raw) - set(GATE_KEYS))
    if missing or unknown:
        raise ValueError(f"the rig gate needs exactly {', '.join(GATE_KEYS)}"
                         + (f"; missing {', '.join(missing)}" if missing else "")
                         + (f"; unknown {', '.join(unknown)}" if unknown else ""))
    for key in ("min_weighted_share", "min_inside_share"):
        value = raw[key]
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError(f"gate.{key} must be a number from 0 to 1")
    if type(raw["max_influences"]) is not int or not 1 <= raw["max_influences"] <= 8:
        raise ValueError("gate.max_influences must be a whole number from 1 to 8")
    return dict(raw)


def _invert(m):
    """The inverse of a 4x4 matrix given as 16 numbers in glTF's column-major order, as rows."""
    rows = [[m[c * 4 + r] for c in range(4)] + [1.0 if r == k else 0.0 for k in range(4)] for r in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < EPSILON:
            raise glb_read.GlbError("an inverse bind matrix cannot be inverted")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        lead = rows[col][col]
        rows[col] = [v / lead for v in rows[col]]
        for r in range(4):
            if r != col:
                factor = rows[r][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [row[4:] for row in rows]


def read_skin(path):
    """{"vertices": [...], "triangles": [...], "influences": [{joint: weight}], "joints": {name: position}} for the
    skinned primitives of the .glb at PATH (joint names are the skin's node names)."""
    document, binary = glb_read.load(path)
    skinned = [node for node in document.get("nodes", []) if "skin" in node and "mesh" in node]
    if not skinned:
        raise glb_read.GlbError("no skinned mesh: the file has no node with both a mesh and a skin")
    vertices, triangles, influences, joints = [], [], [], {}
    for node in skinned:
        skin = document["skins"][node["skin"]]
        names = [document["nodes"][j].get("name", f"node{j}") for j in skin["joints"]]
        if "inverseBindMatrices" in skin:
            for name, matrix in zip(names, glb_read.accessor(document, binary, skin["inverseBindMatrices"]), strict=True):
                bind = _invert(matrix)
                joints[name] = (bind[0][3], bind[1][3], bind[2][3])
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            attributes = primitive["attributes"]
            base = len(vertices)
            points = glb_read.accessor(document, binary, attributes["POSITION"])
            vertices += points
            sets = sorted(key[len("JOINTS_"):] for key in attributes if key.startswith("JOINTS_"))
            found = [dict() for _ in points]
            for number in sets:
                bones = glb_read.accessor(document, binary, attributes[f"JOINTS_{number}"])
                amounts = glb_read.accessor(document, binary, attributes[f"WEIGHTS_{number}"])
                for one, ids, weights in zip(found, bones, amounts, strict=True):
                    for bone, weight in zip(ids, weights, strict=True):
                        if weight > 0:
                            one[names[bone]] = one.get(names[bone], 0.0) + weight
            influences += found
            if primitive.get("mode", 4) != 4:
                continue
            order = glb_read.accessor(document, binary, primitive["indices"]) if "indices" in primitive \
                else list(range(len(points)))
            triangles += [(base + order[i], base + order[i + 1], base + order[i + 2]) for i in range(0, len(order) - 2, 3)]
    return {"vertices": vertices, "triangles": triangles, "influences": influences, "joints": joints}


def _crosses(origin, direction, a, b, c):
    """Möller-Trumbore: does the ray from ORIGIN along DIRECTION cross triangle ABC (in front of the origin)?"""
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    p = (direction[1] * e2[2] - direction[2] * e2[1], direction[2] * e2[0] - direction[0] * e2[2],
         direction[0] * e2[1] - direction[1] * e2[0])
    det = e1[0] * p[0] + e1[1] * p[1] + e1[2] * p[2]
    if abs(det) < EPSILON:
        return False
    s = (origin[0] - a[0], origin[1] - a[1], origin[2] - a[2])
    u = (s[0] * p[0] + s[1] * p[1] + s[2] * p[2]) / det
    if u < 0 or u > 1:
        return False
    q = (s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0])
    v = (direction[0] * q[0] + direction[1] * q[1] + direction[2] * q[2]) / det
    if v < 0 or u + v > 1:
        return False
    return (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2]) / det > 0


def inside(point, vertices, triangles):
    votes = 0
    for ray in RAYS:
        hits = sum(_crosses(point, ray, vertices[i], vertices[j], vertices[k]) for i, j, k in triangles)
        votes += hits % 2
    return votes >= 2


def measure(skin, gate):
    """(measures, reasons, facts) for SKIN (read_skin) against GATE (parse_gate)."""
    influences = skin["influences"]
    count = len(influences)
    weighted = sum(1 for one in influences if sum(one.values()) > WEIGHTED)
    most = max((len(one) for one in influences), default=0)
    deforming = sorted({name for one in influences for name in one} & set(skin["joints"]))
    outside = [name for name in deforming if not inside(skin["joints"][name], skin["vertices"], skin["triangles"])]
    inside_share = (len(deforming) - len(outside)) / len(deforming) if deforming else 0.0

    def at_least(value, limit):
        return {"value": round(value, 6), "limit": limit, "margin": round(value - limit, 6),
                "outcome": "pass" if value >= limit else "fail"}

    measures = {"weighted_share": at_least(weighted / count if count else 0.0, gate["min_weighted_share"]),
                "influences": {"value": most, "limit": gate["max_influences"], "margin": gate["max_influences"] - most,
                               "outcome": "pass" if most <= gate["max_influences"] else "fail"},
                "inside_share": at_least(inside_share, gate["min_inside_share"])}
    reasons = []
    if measures["weighted_share"]["outcome"] == "fail":
        reasons.append(f"{count - weighted} of {count} vertices carry no bone weight "
                       f"(weighted share {measures['weighted_share']['value']}, needs {gate['min_weighted_share']})")
    if measures["influences"]["outcome"] == "fail":
        reasons.append(f"a vertex follows {most} bones; at most {gate['max_influences']} allowed")
    if measures["inside_share"]["outcome"] == "fail":
        reasons.append(f"bones outside the mesh: {', '.join(outside) or 'none deform'} "
                       f"(inside share {measures['inside_share']['value']}, needs {gate['min_inside_share']})")
    facts = {"vertices": count, "triangles": len(skin["triangles"]), "joints": len(skin["joints"]),
             "deforming": deforming, "unused": sorted(set(skin["joints"]) - set(deforming)), "outside": outside}
    return measures, reasons, facts


def judge(path, gate):
    """The rig-validation report for the .glb at PATH under GATE (a raw gate block)."""
    gate = parse_gate(gate)
    try:
        skin = read_skin(path)
    except (glb_read.GlbError, KeyError, IndexError, ValueError) as error:
        return {"verdict": "fail", "reasons": [f"cannot read the skin: {error}"], "measures": {}, "facts": {}}
    measures, reasons, facts = measure(skin, gate)
    return {"verdict": "fail" if reasons else "pass", "reasons": reasons, "measures": measures, "facts": facts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = judge(args.mesh, json.loads(args.gate.read_text()))
    except (OSError, ValueError) as error:
        print(f"rig gate: {error}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / REPORT).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"rig gate: {report['verdict']}" + "".join(f"\n  {reason}" for reason in report["reasons"]))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
