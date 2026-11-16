# Normalisers

Three small scripts that put generated files into a known shape. They use no AI, give the same
answer every time, and are idempotent: running one on its own output with the same config changes
nothing beyond float noise. The pipeline runner builds their config from a pipeline file and runs them as stages
([pipeline files](pipeline_files.md)); they also run on their own. Run them under the tools interpreter (numpy, scipy,
trimesh, Pillow, fast-simplification), like the gate.

Every script is `script.py INPUT OUTPUT --config CONFIG.json --report REPORT.json`. It exits 2 with a
message on bad input and 0 on success. The report holds before/after numbers, the config itself and
`config_sha256`, the hash of the config file, so an output can always be traced to the values that
made it.

## No built-in values

Nothing about the look is in the code. Every config key is required: a missing key,
an unknown key or a bad value stops the script with a message naming the key and the config file. The
files in [pipeline/pipelines/examples](../pipeline/pipelines/examples/) show the shape; they are examples, not defaults,
and a pipeline file or style pack supplies the real values. The validation lives in one place,
`pipeline/normaliser_common.py`; each script only declares its keys.

## normalize_image.py

Finds the subject (`pipeline/subject_mask.py`: real alpha if the image has it, otherwise the
border-connected near-white flood), crops to it, scales it so its longer side fills the canvas minus
the margins, centres it and writes a PNG. Input must be RGB or RGBA.

| Key | Meaning |
|---|---|
| `background_tolerance` | Either this or `background`, exactly one. 0..255. Border-connected pixels with every channel at or above this are background (the matte stage's rule, the `near_white` method). |
| `background` | Either this or `background_tolerance`. A background settings object, the same as `capture.background` in a pipeline file (below). With `chroma_key` and `output_mode` `"rgba"` the output alpha is the soft alpha (edges keep partial transparency) and the colours are despilled. |
| `canvas_size` | Output is this many pixels square. |
| `margin` | Empty pixels kept on every side; `2 * margin` must be below `canvas_size`. |
| `output_mode` | `"rgba"` (alpha 0 or 255 from the mask) or `"flat"` (subject over `background_color`, RGB). |
| `background_color` | `[r, g, b]`: the flat background, and the colour under alpha 0 in rgba mode. |

The report has `subject_bbox`, `coverage` (subject share of the input), `scale`, `touched_border`,
`placed_bbox` and `output_coverage`. With `background_tolerance` edges are hard because the mask is
thresholded, which keeps a rerun stable; with a `chroma_key` `background` in rgba mode they are soft, and
a rerun on the output reads its alpha (a real matte) instead of the key. **Chroma rgba output is therefore not rerun-stable**: the rerun thresholds the soft alpha at 127, so the box and scale can shift slightly. The idempotence promised at the top of this page holds for `background_tolerance` configs only. In flat mode a rerun can turn an enclosed pixel that was within
`255 - background_tolerance` of white into background; nothing else moves.

    python3 -I pipeline/normalize_image.py in.png out.png --config pipeline/pipelines/examples/normalize_image.json --report out.report.json

    python3 -I pipeline/normalize_image.py in.png out.png --config pipeline/pipelines/examples/normalize_image.chroma.json --report out.report.json

## Background separation

`pipeline/subject_mask.py` is the one owner of "which pixels are the subject"; `pipeline/background_spec.py` is
the one validator of its settings object (the same object as `capture.background` in a pipeline file;
[keys per method](pipeline_files.md)). `matte.py` (`--background FILE.json`, or `--tolerance N` for
`near_white`), `normalize_image.py` (`background`), `mesh_gates.py` v2 (optional `capture.background` in
the gate config; `--tolerance N` is `near_white` and may not be combined with it) and `mesh_finish.py`
(`capture.background`, either the older `{"tolerance": N}` meaning `near_white`, or a full object) all go
through it. An image with a real alpha channel uses its alpha whatever the method.

- **`near_white`** is unchanged, bit for bit (a test compares it with a frozen copy of the old mask on the
  gate fixtures).
- **`chroma_key`**: the background is one flat key colour.
  - *Distance.* Each pixel is converted to BT.601 Y, Cb, Cr and its distance to the key is
    `sqrt((luma_weight * dY)^2 + dCb^2 + dCr^2)`. Why: the generator's backgrounds drift a little in
    brightness and carry noise that mostly moves Y, so Y is down-weighted and hue and saturation decide.
    A per-channel rule such as `min(r, b) - g` is right for magenta only. A subject that shares a channel
    with the key (red or blue on magenta) is still far away, because Cb and Cr mix all three channels.
    The limit: a subject whose colour is within `tolerance` of the key (dark magenta on magenta) is lost,
    so choose a key colour the subject does not use. Because the distance is linear in the colour, a
    `tolerance` of about half the subject's distance from the key puts the hard edge at half coverage.
  - *Alpha.* `alpha = clip((distance - tolerance) / feather, 0, 1)`. The hard mask the gates use is
    `alpha > 0` of the same computation, so mask and alpha cannot disagree; it includes the feather band,
    so keep `feather` small when the outline matters.
  - *Border and holes.* Key-like pixels (alpha 0) that connect to the image border are background. Key-like
    pixels enclosed by the subject are background only if `holes` is true; otherwise they are subject
    (alpha 1). A subject touching the border is fine.
  - *Despill.* A pixel with 0 < alpha < 1 is pushed along the line away from the key to the distance where
    alpha reaches 1, by `despill` of the way (0 leaves colours alone). Opaque pixels never change.
  - All settings are required; there are no defaults.

### Matching the icon routine
`pipeline/icon_batch.py` keys magenta with `min(r, b) - g` (transparent from 100, ramp from 45). Settings that
track it on a `#ff00ff` background: `tolerance` 75, `feather` 35, `luma_weight` 0.25, `holes` true
(it keys every pixel, with no border test); `icon.pipeline.json` carries them. `tests/test_subject_mask.py`
feeds the same images through `icon_batch.prepare`'s own keying (not a copy) and the new key. On five real
magenta generations the mean alpha difference was 0.0002 to 0.0012, the largest single difference 0.23 to
0.45, and 0.08% to 0.4% of pixels differed by more than 0.1 (all of those pixels had a partial alpha in one of the two results, that is, they sit on an edge; measured). The settings were fitted on those same five images, and the comparison is alpha only with `despill` 0 (the icon routine does not despill). The two differ at the edge (different
measures) and for strong pinks, which both treat as partly see-through by different amounts.


Reads a `.glb` (geometry, and vertex colours if present; texture materials are not carried and the
report says so). Steps in this order:

1. Orientation (below), if configured.
2. Merge vertices closer than the weld distance (the first vertex of a cluster stays); faces that
   collapse are removed.
3. Drop connected pieces below the small-piece area share. The largest piece is always kept.
4. Fix winding and normals (`trimesh.repair.fix_normals`).
5. Scale so the chosen extent equals the target size.
6. Move the origin to the base centre: the base touches 0 on the up axis and the mesh is centred on
   the other two.

| Key | Meaning |
|---|---|
| `orientation` | `null`, `{"matrix": 3x3}` or `{"view": {...}}`; see below. |
| `up_axis`, `front_axis` | Signed axes such as `"+y"`, `"-z"`, on different axes. The pose of the output. |
| `weld_distance_share` | Merge distance as a share of the bounding-box diagonal (0 merges identical points only). A share keeps it independent of the mesh's arbitrary scale. |
| `small_piece_area_share` | Pieces with less than this share of the total surface area are removed. |
| `target_size` | Length of the scaled extent, in output units. |
| `scale_axis` | `"largest"` (longest extent) or `"x"`, `"y"`, `"z"`. |

The report has `before` and `after` (faces, pieces, largest piece share, watertight, bounds),
`pieces_dropped`, `dropped_area_share`, `vertices_merged`, `faces_rewound`, `scale_applied`, the
orientation applied and whether vertex colours were kept.

### How the gate's view feeds this script

`pipeline/mesh_gates.py` finds which way the mesh best matches the input image and writes it in its report
as `measures.view`: `{"drop_axis", "transpose", "flip_x", "flip_y"}`. The gate discards the view after
scoring (a rotated mesh passes it), so this script is where it is applied: paste that dict into
`"orientation": {"view": ...}`.

The gate draws the two mesh axes other than `drop_axis` as image column then row, swaps them if
`transpose`, mirrors columns for `flip_x` and rows for `flip_y`. The script reads that back: image
right is +X, image up is the row axis reversed, and toward the viewer is X cross Y, so the third axis
is the `drop_axis` with whichever sign gives a proper rotation (never a mirror). That "viewer" frame
(X right, Y up, Z toward the viewer) is then carried onto `up_axis` and `front_axis`. Front versus
back cannot be told from a silhouette, so a mesh may come out facing away; the review sheet is where
that is caught.

A `matrix` is used as given (it must be a rotation: orthonormal, determinant +1).

Orientation is the one step that is not idempotent by itself, so the output records a hash of the
orientation block and the two axes in the file; a rerun with the same ones skips the rotation.

    python3 -I pipeline/normalize_mesh.py in.glb out.glb --config pipeline/pipelines/examples/normalize_mesh.json --report out.report.json

## decimate_mesh.py

Quadric edge-collapse decimation with fast-simplification (MIT; the call lives in `pipeline/mesh_decimate.py`, shared with
`pipeline/colour_head.py`, and the gate's camera search). If the collapse stops above the budget it is
retried from the result a few times; if it lands well below, it is asked again from the input for the shortfall more.

The library has no topology switch and no vertex attributes, so `mesh_decimate.py` adds what it can. With
`preserve_topology` true it never collapses an edge on an open border, runs the collapse at several settings of the library's
aggressiveness and keeps the result within the budget that changed the mesh's topology least (bodies gained, then
non-manifold edges gained, then the Euler characteristic, then pieces), and drops the tiny slivers (16 faces or fewer) the collapse split off; a larger fragment is never removed, since that would cut a hole. It does **not** refuse a collapse that closes a thin handle or pinches two
sheets together, which the previous library did; a very detailed mesh (the head fixtures, with fine hair-like detail) can still change
topology, so the report holds the topology before and after.

| Key | Meaning |
|---|---|
| `face_budget` | The most faces the output may have. |
| `preserve_topology` | True keeps open borders and picks the setting that changes the topology least (see above); false is one plain collapse. |

A mesh already within the budget is copied unchanged and the report says `"changed": false`. Vertex
colours survive: each new vertex takes the colour of the nearest vertex of the input (a KD-tree lookup), so flat colour areas
stay flat; the report's `vertex_colors` says whether they were present and preserved, and its `topology` block holds `pieces`, `bodies`,
`euler` and `non_manifold_edges` before and after.

    python3 -I pipeline/decimate_mesh.py in.glb out.glb --config pipeline/pipelines/examples/decimate_mesh.json --report out.report.json

## Tests

`tests/test_normalisers.py` runs the real commands on the three gate fixtures: the happy path,
idempotence (geometry within a tolerance, never byte equality), a missing key per script, and bad
input. It also normalises the `on_side` mutant using the view from the gate's own report, the
`scatter` mutant (which then passes the gate; it failed by 0.007 before), and decimates the
`subdivided` mutant back to the budget. It prints `NORMALISERS cases=<n> ok=<n>`.

How these configs fold into one pipeline file per kind is defined in [pipeline files](pipeline_files.md).

`pipeline/mesh_finish.py` chains `normalize_mesh`, `decimate_mesh` and the v2 gate from one config; see "Finishing chain" in [gate v2](gate_v2.md).
