# Head pipeline

`pipeline/pipelines/head.json` makes a coloured head from a concept bust. It is a pipeline file like the others
([pipeline files](pipeline_files.md)): it names no game and no look; the look comes from a style pack, a motif and a subject.

| Stage | Tool | What it does |
|---|---|---|
| `bust` | `concept` | draws the bust with an image adapter |
| `crop` | `crop_image` | keeps the top share of the subject's height (head and neck) and cuts the rest away |
| `matte` | `matte` | finds the subject; `allow_border` lets the cut edge touch the frame |
| `mesh` | `mesh` | image to mesh, with an image-to-mesh adapter |
| `colour` | `colour_head` | colours the mesh from the bust |
| `clean_mesh`, `decimate`, `shape_gate` | as for props | the same chain, with the head's camera ranges ([shape gate](gate_v2.md)) |

## `crop_image`

`python pipeline/crop_image.py INPUT.png OUTPUT.png --config CONFIG.json --report REPORT.json`. Config keys, all required:
`background` (a `capture.background` object, which says which pixels are the subject) and `keep_share` (above 0 up to 1: the
share of the subject's own height kept, measured from its top row, so it follows how high or low the subject sits). The image
keeps its width. An image with no subject is an error, never copied through.

## `colour_head`

Gives the mesh vertex colours from the picture; the geometry is unchanged. The vertices the front camera sees (facing it,
not hidden behind nearer geometry) take the image colour, after the image is reduced to a few flat colours. Every other vertex
takes the colour that diffuses in from the seen area across the mesh, as a vote between the broad flat colours of the seen area,
so hair meets hair and skin meets skin. With a `hair_colour`, the back and upper sides of the head take it. It exits 2 on bad
input and when the projection misses the mesh.

Config keys, all required and none with a default: `background`, `hair_colour` (`"#rrggbb"` or null), `working_faces`,
`posterize`, `seen_facing`, `depth_resolution`, `depth_tolerance`, `min_seen_share`, `horizontal_bias`, `toon_colours`,
`broad_share`, `nape_height`, `temple_height`, `temple_side`, `ear_top`, `ear_side`, `hair_match`. Each is explained in the
docstring of `pipeline/colour_head.py`. The subject file may carry `hair_colour`; a pipeline can offer it as a choice
([pipeline files](pipeline_files.md), "Choices").

## Running from saved files

`pipeline_run.py --start-at STAGE --input STAGE/FILE=PATH` starts a run from saved outputs of the earlier stages, so a mesh you
already have can go through `colour`, `clean_mesh`, `decimate` and `shape_gate` with no model. A run that starts after the last
model stage never takes the GPU lock.

## Seeds and the lock

`pipeline_batch.py` (and `pipeline_run.py --candidates N`) runs one subject for several seeds, one after another, as one job for
the GPU lock: the lock is taken at the first model stage and held until the last seed ends ([GPU lock](gpu_lock.md)). A seed
that fails or asks for review does not stop the others. `pipeline_batch.py` also draws a contact sheet of every seed's review
sheet.
