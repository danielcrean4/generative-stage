# Example configs

These files are examples of the config shape each normaliser reads, not defaults: the tools have no
built-in values, so a pipeline file or style pack supplies the real ones. Copy one and change it;
the keys are explained in [normalisers](../../../docs/normalisers.md).

`gate_v2.prop.json`, `gate_v2.head.json` and `gate_v2.thin.json` are examples of the config `mesh_gates.py --profile v2 --gate` reads (gate block, camera ranges, conventional frame, face budget). They are examples, not defaults: v2 has no built-in values and a missing key is an error. See [gate v2](../../../docs/gate_v2.md).

`finish.prop.json`, `finish.head.json` and `finish.thin.json` are examples of the one config `pipeline/mesh_finish.py` reads (contract, clean_mesh, decimate, capture and gate blocks, shaped like the stages of [pipeline files](../../../docs/pipeline_files.md)). The gate limits are the `gate_v2.*` examples'; the face budget is 8000. Examples, not defaults.

`prop.pipeline.json`, `character.pipeline.json` (the prop recipe, then rig, rig gate and motion) and `icon.pipeline.json` are examples of whole pipeline files ([pipeline files](../../../docs/pipeline_files.md)); `python3 -I pipeline/pipeline_file.py validate pipeline/pipelines/examples/*.pipeline.json` checks them. `icon.pipeline.json` carries real `chroma_key` background settings. `normalize_image.chroma.json` and `finish.prop.chroma.json` are the chroma variants of `normalize_image.json` and `finish.prop.json` (the finish one keys green and differs only in `capture.background`). Examples, not defaults.
