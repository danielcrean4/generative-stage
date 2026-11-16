# Motion families

A **motion family** makes animation clips the way an art family makes meshes: a
script, its parameters and a seed go in; clips come out, checked automatically and reviewed on
one picture. Nothing is downloaded and no model runs. It's plain Python apart from the
filmstrip, which uses Blender.

## Run it

```bash
python3 blender/build_motions.py --motions blender/motions --manifest blender/examples/motion_manifest.json --out /tmp/motions
blender --background --factory-startup --python blender/filmstrip_motions.py -- --clips /tmp/motions --manifest blender/examples/motion_manifest.json --out /tmp/filmstrips
```

A project passes its own manifest and rigs, and may add its own families with a second
`--motions` folder. The runner exits non-zero if any clip fails a check.

## The pieces

| File | What |
|---|---|
| `blender/motion/rig.py` | Rig profiles (joints, rest offsets, limits, sites, roles, mirrored joints) and forward kinematics |
| `blender/motion/curves.py` | The `Clip` builder (`rotate`, `move`, `event`, `contact`), its JSON form, and shaping helpers (`smooth`, `envelope`, `wave`) |
| `blender/motion/ik.py` | Two-bone IK, plus `plant_legs` and `lower` for keeping feet planted while the body moves |
| `blender/motion/checks.py` | The checks below |
| `blender/build_motions.py` | The runner |
| `blender/filmstrip_motions.py` | One picture per rig: a row per clip, eight poses along it, left side blue and right orange |
| `blender/build_rigged.py` | Builds a rigged body from a rig profile and keys chosen clips on it, into one `.glb` with its animations (`blender/examples/rigged/`, shown by the 3D viewer's clip player) |
| `blender/rigging.py` | Armatures and clip keying in Blender, shared by the scripts that make rigged files; keys a clip on any armature whose bones carry the profile's joint names, whatever way its bones point |
| `blender/motion/fit.py` | Fits a rig profile to a mesh by its bounds, pulls joints inside the body, nearest-bone-segment weights (plain Python) |
| `blender/rig_standin.py`, `blender/animate_standin.py` | The `rig` and `motion` stand-in adapters ([adapters](adapters.md)): rig a generated mesh with the profile, then key named clips made for the fitted profile |
| `blender/motions/` | Generic families: `locomotion_biped`, `rolling` (wheels or tracks), `reactions` |
| `blender/examples/rigs/`, `blender/examples/motion_manifest.json` | Two sample rigs (`biped`, `wheeled`) and every clip for both, used by `pipeline/check.sh` |

## Conventions

- **Axes:** glTF and Godot: Y up, +Z forward, a character's right is -X.
- **Rotations:** Euler angles in radians, applied in Godot's default YXZ order, so a game can
  turn them straight into quaternions.
- **Roles, not names.** Families ask for `hip_l`, `elbow_r`, `body`, `wheel_l` and so on; a rig's
  `roles` map those to its own joint names. A family skips any role a rig doesn't have, so one
  reaction family serves legged and wheeled bodies alike.
- **In place.** Locomotion clips don't travel; they carry the `speed` they were made for, and
  the game moves the body and scales playback to match.
- **IK at generation time.** Feet are planted, and later two-handed grips solved, when the clip
  is made. The game only plays it back.
- **Mirrored joints.** If a game mirrors a part (scale x = -1), the rig lists the joints inside
  it. Clips stay in true space and carry the list; the game negates Y and Z rotation on those
  joints when it bakes them.
- **Seeded and reproducible.** Each clip is seeded by `rig/clip`; a rebuild is byte-identical.

## Checks

| Check | Fails when |
|---|---|
| limits | a rotation leaves its joint's limits |
| loop | a looping clip's last pose is more than about 1° from its first |
| events | a clip lacks an event its family promises (`footfall_l`, `impact`, `down`…) |
| floor | a site goes more than 5 mm below the ground (sites on wheels' contact points catch a sinking chassis) |
| slide | a planted site drifts more than 1 cm while the body moves at the clip's speed |

## Writing a family

A module in a motions folder with `CLIPS` (name → `make(rig, params, rng)` returning a
`Clip`), `DEFAULTS` (name → parameters) and optionally `EVENTS` (name → required events).
Use only the `rng` passed in. A manifest may override any parameter by name; an unknown one is
an error.
