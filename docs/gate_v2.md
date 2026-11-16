# Shape gate (v2)

The shape gate compares a finished 3D mesh with the picture it was made from and says `pass`, `review` or `fail`, with
every measure, its limit and its margin written down. It is a check that informs a person, not a judge of quality: a
`review` is never installed automatically, and what to do with any verdict is the person's choice.

Code: `pipeline/gate_v2.py` (measures, camera search, verdict), `pipeline/gate_v2_config.py` (the one place that validates
the config), `pipeline/mesh_gates.py` (the command line; `--profile v1` runs the first, simpler gate),
`pipeline/mesh_finish.py` (the whole finishing chain). In a pipeline it is the `shape_gate` stage.

    python3 -I pipeline/mesh_gates.py MESH.glb IMAGE.png --out mesh-validation.json --profile v2 --gate gate_v2.prop.json

**Exit codes:** 0 pass, 1 fail (also "could not measure"), 2 usage or config error (no report is written), 3 review.

## Where it sits

`mesh` → `normalize_mesh` (orientation, weld, drop small pieces, scale, origin) → `decimate_mesh` → **gate**. The gate judges
the file that would ship. Nothing the gate finds is fed back into the mesh. The generator's frame is fixed (which axis the
picture is drawn from, and any flips), so the mesh's orientation is known by convention and is not searched for.

## Camera tolerance

Concept pictures are often drawn at a three-quarter angle, so an upright, correct mesh can score poorly from straight ahead.
The gate may turn the **camera** within a range given in the config (`capture.view.camera`: yaw and elevation, each a first,
last and step) and keeps the best score. A kind whose pictures are drawn straight on sets both ranges to zero. The angles
chosen are written to the report and are never applied to the mesh. The search runs on a proxy of about 3,000 faces within
`search_seconds`; the final measures are then taken once on the full mesh. If the time runs out the verdict cannot be `pass`.
Turning the camera changes the apparent height, so a wide range weakens the detection of a missing top: keep ranges small and
set them per kind.

## Measures

| Measure | Meaning | Limit key |
|---|---|---|
| `silhouette_iou` | overlap of the mesh's and the subject's outlines, each fitted to its own box | `min_silhouette_iou` |
| `aspect_error` | relative difference between the outline's width:height and the subject's, before fitting | `max_aspect_error` |
| `deficit` | share of the subject's outline the mesh does not cover | `max_deficit` |
| `excess` | share of the mesh's outline outside the subject | `max_excess` |
| `depth_ratio` | extent along the view axis divided by the smaller of the other two | `min_depth_ratio` |
| `thin_sheet_share` | largest share of the surface lying on one plane and a nearly coincident opposite plane (a flat sheet) | `max_thin_sheet_share` |
| `pieces` | connected pieces in the file | `max_pieces` |
| `faces` | face count | the contract's face budget |
| `orientation_gain` | how much better another axis matches than the conventional one | `orientation_margin` |

- Every limit is a required key. None has a default in code, and a missing key is an error naming the file and the key.
- `deficit` and `excess` register the outlines with the mesh's proportions kept (scaled uniformly to the subject's width or
  height, aligned at start, middle or end, best overlap wins), so a missing top is not stretched away.
- `depth_ratio` can only send a mesh to `review` for kinds marked `thin` in the config (tools, signs); for other kinds it can
  fail. It is measured in the conventional frame, with no camera turn.
- `pieces` and `faces` are counted on the file as given: small pieces are removed by the normaliser before the gate.
- The face budget has one owner, the contract for the kind. The decimate stage and the gate both read it.
- Scale is set by the normaliser to the contract's size, so no measure is needed. A mirrored mesh cannot be detected from an
  outline; the review sheet places the concept beside the front view so a person can see it.

## Three outcomes

- **Ratio measures** have a `review_margin` in the same units. Breaking a limit by more than the margin is `fail`; being within
  the margin on either side is `review`.
- **Counts** have no margin. `faces` over budget is `fail`. `pieces` over `max_pieces` is `review`, because a second real
  piece is sometimes the subject and a person decides.
- Otherwise `pass`.

## The config

The standalone `--gate` file holds the `gate` block (`profile`, `thin`, the limits above, `review_margin`, `orientation_margin`,
`search_seconds`), `capture.view.camera`, the conventional `frame` (`drop_axis`, `transpose`, `flip_x`, `flip_y`) and
`face_budget`. Examples: `pipeline/pipelines/examples/gate_v2.prop.json`, `.head.json` and `.thin.json`. They are examples, not
defaults. `capture.background` is either `{"tolerance": N}` (near white) or a full background object with a `method`
(`chroma_key` for a flat key colour; see [normalisers](normalisers.md)).

The report, `mesh-validation.json`, has `profile`, `verdict`, `reasons`, `frame`, `camera_ranges`, `camera` (the angles used and
how many poses were tried), `orientation`, and `measures`, each with `value`, `limit`, `limit_key`, `margin` (distance inside the
limit, negative when broken) and `outcome`.

## The finishing chain

`pipeline/mesh_finish.py MESH IMAGE OUT_DIR --config CONFIG.json` runs normalise, decimate and the gate on one mesh in one
process, through the same functions the three command-line tools use, so it cannot drift from them. It writes `clean/`,
`decimate/`, `gate/mesh-validation.json`, `gate/review-sheet.png` and `finish.json` (verdict, reasons, each step's seconds,
pieces and faces before and after, the config's hash). Its exit codes are the gate's.

The one config has the blocks of the stages in [pipeline files](pipeline_files.md), so it folds into a pipeline file without
renaming (`pipeline/pipelines/examples/finish.prop.json`, `.head.json`, `.thin.json`):

| Block | Keys | Read by |
|---|---|---|
| `contract` | `up_axis`, `front_axis`, `target_size`, `scale_axis`, `face_budget` | normalise (axes, size), decimate and gate (`face_budget`) |
| `clean_mesh` | `weld_distance_share`, `small_piece_area_share`, `orientation` = `{"view": frame}` | normalise; the gate takes the same frame |
| `decimate` | `preserve_topology` | decimate |
| `capture` | `background`, `view.camera` | gate (subject mask, camera tolerance) |
| `gate` | the gate block, without `face_budget` | gate |
| `review_sheet` | the look of the sheet | review sheet |

- `contract.face_budget` goes to decimate and to the gate; a `face_budget` inside `gate` is an error.
- The gate's frame is `clean_mesh.orientation.view`, used as is. The normaliser rotates the mesh so the contract's up and front
  axes match that frame, and the chain refuses a config where they disagree. A model whose frame is not the contract's pose is
  not covered yet.

## The review sheet

A PNG written for every verdict, also when the chain stopped early: the concept image, then the front, side, top and back views of
the final mesh drawn on the CPU (`pipeline/mesh_render.py`, an orthographic z-buffer), with the verdict, every measure with its
value, limit, margin and outcome, the reasons, and pieces and faces before and after. Views are named from the contract's axes and
share one pixel scale. The look (tile size, colours, light, padding) is the config's `review_sheet` block; the renderer has no look
default. The sheet shows the shipped mesh only, never the subject mask.

## What it is tested against

`pipeline/tests/fixtures/gates/` holds three fixtures: `cabinet` (a boxy prop with a neck and two side lugs), `tool` (a thin handle
and blade) and `head` (a bust: an ellipsoid skull, jaw, nose, ears and a neck, with a painted picture). All three are made from
formulas by `pipeline/make_gate_fixtures.py shapes`, with no random numbers, so the files are the same every time. Each has ten mutants (`pipeline/tests/gate_mutants.py`): `box`, `cut_20`, `cut_33` (the top fifth
or third removed), `mirrored`, `on_side`, `relief_15` (flattened to 15% depth), `scatter` (loose small spheres added), `scaled_3x`,
`subdivided` (16 times the faces) and the original. The tests pin the verdict and the deciding measures of every case in
`expected_v1.json`, `expected_v2.json` and `expected_finish.json`; `GATE_MUTANTS_REGENERATE=1` rewrites the tables after a change.

Gate alone, no normaliser first (`expected_v2.json`; 8 pass, 6 review, 16 fail of 30):

| Case | cabinet | head | tool (thin) |
|---|---|---|---|
| original | pass | pass | pass |
| box | fail | fail | fail |
| cut_20 | review | review | review |
| cut_33 | fail | fail | review |
| relief_15 | fail | fail | fail |
| on_side | fail | fail | fail |
| scatter | review | fail (pieces) | review |
| mirrored | pass | pass | fail |
| subdivided | fail (faces) | fail (faces) | fail (faces) |
| scaled_3x | pass | pass | pass |

Through the finishing chain (`expected_finish.json`; 14 pass, 4 review, 12 fail of 30): every original, `scatter`, `scaled_3x`,
`subdivided` and `mirrored` (except the tool) pass, because the normaliser removes the loose pieces, rescales and decimates first;
`box`, `cut_33`, `relief_15` and `on_side` fail on every fixture but the tool's `cut_33`, which is reviewed; `cut_20` is reviewed.

Known gaps these tables show rather than hide: a mirrored mesh of a symmetric subject (the cabinet and the head) cannot be told from
the original, and a uniform scale changes no measure; the review band sends the mild cuts to a person rather than failing them.

## How well it agrees with a person

On 19 real meshes that one person had judged usable by eye, with the example limits, the gate failed 14 and passed none, and sent
all four meshes judged bad to review. The labels are provisional (one person's view at small size) and no limit was changed. The
main cause seen was a white subject on a white background, where the near-white matte loses part of the subject's outline; a
chroma-key background (`capture.background.method: chroma_key`) fixes the matte when the concept is generated on a key colour.
Treat the limits as starting points to tune per kind, and the verdict as information.
