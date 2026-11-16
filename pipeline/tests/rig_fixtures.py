"""Bodies and known-bad rigs for the rig stages' tests, made at test time with the standard library.

    humanoid(scale)          an unrigged box body in the example biped's proportions (.glb bytes): something a rigger
                             can fit, standing in for a generated character mesh
    skinned()                the same body rigged by hand (each box at full weight on one joint): a rig that passes
    MUTANTS[name](data)      a rigged .glb's bytes made wrong in one way the rig gate must catch

Every mutant takes and returns .glb bytes, so it works on the hand-made rig and on the stand-in rigger's output alike.
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "adapters" / "standin"))
import glb_read  # noqa: E402
import standin  # noqa: E402

PROFILE = REPO / "blender" / "examples" / "rigs" / "biped.json"
# (joint the box follows, low corner, high corner) in the biped profile's metres: separate closed boxes, none touching,
# each holding its joint (and the joints below it on the same limb)
BOXES = (
    ("hip_l", (0.04, 0.0, -0.08), (0.22, 0.5, 0.12)),
    ("hip_r", (-0.22, 0.0, -0.08), (-0.04, 0.5, 0.12)),
    ("body", (-0.24, 0.505, -0.12), (0.24, 0.98, 0.12)),
    ("shoulder_l", (0.255, 0.46, -0.06), (0.42, 0.93, 0.1)),
    ("shoulder_r", (-0.42, 0.46, -0.06), (-0.255, 0.93, 0.1)),
    ("head", (-0.12, 0.985, -0.12), (0.12, 1.26, 0.12)),
)
CORNERS = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
FACES = ((0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
         (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3))  # outward, counter-clockwise
GREY = (180, 176, 168)


def _boxes(scale):
    points, normals, triangles, owners = [], [], [], []
    for joint, lo, hi in BOXES:
        base = len(points)
        for corner in CORNERS:
            point = tuple((hi[i] if corner[i] else lo[i]) * scale for i in range(3))
            centre = tuple((lo[i] + hi[i]) / 2 * scale for i in range(3))
            offset = [p - c for p, c in zip(point, centre, strict=True)]
            length = sum(v * v for v in offset) ** 0.5
            points.append(point)
            normals.append(tuple(v / length for v in offset))
            owners.append(joint)
        triangles += [(base + a, base + b, base + c) for a, b, c in FACES]
    return points, normals, triangles, owners


def humanoid(scale=1.0):
    points, normals, triangles, _ = _boxes(scale)
    return standin.glb(points, normals, triangles, GREY)


def _profile_world():
    sys.path.insert(0, str(REPO / "blender"))
    from motion import rig as rigs  # noqa: E402  (plain Python)
    rig = rigs.load(PROFILE)
    world = {}
    for name, joint in rig.joints.items():
        world[name] = rigs.add(world[joint.parent], joint.offset) if joint.parent else joint.offset
    return world


def skinned(scale=1.0):
    """The box body with a skin: every joint of the profile is a node, each box follows one joint at full weight."""
    points, normals, triangles, owners = _boxes(scale)
    document, binary = glb_read.parse(standin.glb(points, normals, triangles, GREY))
    world = _profile_world()
    names = list(world)
    joints = b"".join(struct.pack("<4B", names.index(owner), 0, 0, 0) for owner in owners)
    weights = b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in owners)
    inverse = b"".join(struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0,
                                   *(-v * scale for v in world[name]), 1) for name in names)
    first_node = len(document["nodes"])
    document["nodes"] += [{"name": name, "translation": [v * scale for v in world[name]]} for name in names]
    document["scenes"][0]["nodes"] += list(range(first_node, first_node + len(names)))
    document["nodes"][0]["skin"] = 0
    document["skins"] = [{"joints": list(range(first_node, first_node + len(names))), "inverseBindMatrices": None}]
    binary, joints_at = _append(document, binary, joints, 5121, "VEC4", len(owners))
    binary, weights_at = _append(document, binary, weights, 5126, "VEC4", len(owners))
    binary, inverse_at = _append(document, binary, inverse, 5126, "MAT4", len(names))
    document["skins"][0]["inverseBindMatrices"] = inverse_at
    document["meshes"][0]["primitives"][0]["attributes"].update(JOINTS_0=joints_at, WEIGHTS_0=weights_at)
    return glb_read.pack(document, binary)


def _append(document, binary, blob, component, kind, count):
    """BINARY with BLOB added as a new buffer view and accessor; (binary, accessor index)."""
    binary += b"\0" * (-len(binary) % 4)
    document["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(blob)})
    document["accessors"].append({"bufferView": len(document["bufferViews"]) - 1, "componentType": component,
                                  "count": count, "type": kind})
    binary += blob
    document["buffers"][0]["byteLength"] = len(binary)
    return binary, len(document["accessors"]) - 1


def _rewrite(document, binary, index, values):
    """BINARY with accessor INDEX's values replaced (same type and layout)."""
    meta = document["accessors"][index]
    view = document["bufferViews"][meta["bufferView"]]
    code = glb_read.COMPONENTS[meta["componentType"]] * glb_read.WIDTH[meta["type"]]
    stride = view.get("byteStride") or struct.calcsize("<" + code)
    start = view.get("byteOffset", 0) + meta.get("byteOffset", 0)
    scale = glb_read.NORMALISED.get(meta["componentType"]) if meta.get("normalized") else None
    out = bytearray(binary)
    for i, value in enumerate(values):
        value = value if isinstance(value, tuple) else (value,)
        if scale:
            value = tuple(round(v * scale) for v in value)
        struct.pack_into("<" + code, out, start + i * stride, *value)
    return bytes(out)


def _skinned_primitive(document):
    node = next(n for n in document["nodes"] if "skin" in n and "mesh" in n)
    return node, document["meshes"][node["mesh"]]["primitives"][0]


def unweighted_lower_half(data):
    """Every vertex below the middle of the body loses its weight: those parts would never move."""
    document, binary = glb_read.parse(data)
    _, primitive = _skinned_primitive(document)
    points = glb_read.accessor(document, binary, primitive["attributes"]["POSITION"])
    middle = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
    index = primitive["attributes"]["WEIGHTS_0"]
    weights = glb_read.accessor(document, binary, index)
    weights = [(0.0, 0.0, 0.0, 0.0) if p[1] < middle else w for p, w in zip(points, weights, strict=True)]
    return glb_read.pack(document, _rewrite(document, binary, index, weights))


def bone_outside(data, joint="head"):
    """One deforming joint's bind position moved well above the body."""
    document, binary = glb_read.parse(data)
    node, primitive = _skinned_primitive(document)
    skin = document["skins"][node["skin"]]
    names = [document["nodes"][j].get("name") for j in skin["joints"]]
    points = glb_read.accessor(document, binary, primitive["attributes"]["POSITION"])
    height = max(p[1] for p in points) - min(p[1] for p in points)
    matrices = glb_read.accessor(document, binary, skin["inverseBindMatrices"])
    at = names.index(joint)
    moved = list(matrices[at])
    moved[13] -= height  # the bind position is minus the translation for an unrotated bone: up by one body height
    matrices[at] = tuple(moved)
    return glb_read.pack(document, _rewrite(document, binary, skin["inverseBindMatrices"], matrices))


def too_many_influences(data):
    """Every vertex follows five bones: a second set of four joints and weights is added."""
    document, binary = glb_read.parse(data)
    _, primitive = _skinned_primitive(document)
    count = document["accessors"][primitive["attributes"]["POSITION"]]["count"]
    first = glb_read.accessor(document, binary, primitive["attributes"]["WEIGHTS_0"])
    bones = glb_read.accessor(document, binary, primitive["attributes"]["JOINTS_0"])
    spread = [(0.2, 0.2, 0.2, 0.2)] * count
    joints = b"".join(struct.pack("<4B", *[(b[0] + k) % 8 + 1 for k in range(4)]) for b in bones)
    binary = _rewrite(document, binary, primitive["attributes"]["WEIGHTS_0"],
                      [(0.2, 0.0, 0.0, 0.0) for _ in first])
    weights = b"".join(struct.pack("<4f", *w) for w in spread)
    binary, joints_at = _append(document, binary, joints, 5121, "VEC4", count)
    binary, weights_at = _append(document, binary, weights, 5126, "VEC4", count)
    primitive["attributes"].update(JOINTS_1=joints_at, WEIGHTS_1=weights_at)
    return glb_read.pack(document, binary)


MUTANTS = {"unweighted_lower_half": unweighted_lower_half, "bone_outside": bone_outside,
           "too_many_influences": too_many_influences}
