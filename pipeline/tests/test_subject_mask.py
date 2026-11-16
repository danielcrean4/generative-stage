"""Background separation (pipeline/subject_mask.py, pipeline/background_spec.py): ground-truth cases, the callers' CLIs.

The ground-truth cases live in tests/subject_mask_cases.py and run under the tools interpreter; the
callers (matte, normalize_image, mesh_gates v1 and v2, mesh_finish) are run as real CLIs with a
chroma_key config. Ends with one line `SUBJECT_MASK cases=<n> ok=<n>`; the numbers behind
docs/normalisers.md (icon equivalence, white on white) are printed as `SUBJECT_MASK_REPORT {json}`.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import venv_tool

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
EXAMPLES = HERE.parent / "pipelines" / "examples"
FIXTURES = HERE / "fixtures" / "gates"
sys.path.insert(0, str(TOOLS))
import gate_v2_config  # noqa: E402

CHROMA = {"method": "chroma_key", "color": [255, 0, 255], "tolerance": 75, "feather": 35, "luma_weight": 0.25,
          "holes": False, "despill": 1}
GREEN = {**CHROMA, "color": [0, 255, 0]}
MATTE_SIZE = 128
FEATHER_ERROR = "feather is required for method 'chroma_key'"
DISC_ON_KEY = """
import sys
from PIL import Image, ImageDraw
out, size = sys.argv[1], int(sys.argv[2])
image = Image.new("RGB", (size, size), (255, 0, 255))
ImageDraw.Draw(image).ellipse([size // 2 - 30, size // 2 - 30, size // 2 + 30, size // 2 + 30], fill=(40, 120, 200))
image.save(out)
"""
REKEY = """
import sys
sys.path.insert(0, sys.argv[1])
import numpy as np
from PIL import Image
import subject_mask
image = Image.open(sys.argv[2]).convert("RGB")
subject = subject_mask.subject_from_image(image, {"method": "near_white", "tolerance": 236})
pixels = np.asarray(image).copy()
pixels[~subject] = [0, 255, 0]
Image.fromarray(pixels).save(sys.argv[3])
"""
OUTPUT_INFO = """
import json, sys
import numpy as np
from PIL import Image
image = Image.open(sys.argv[1])
alpha = np.asarray(image)[:, :, 3]
ys, xs = np.nonzero(alpha > 127)
print(json.dumps({"mode": image.mode, "size": image.size, "centre": int(alpha[image.size[1] // 2, image.size[0] // 2]),
                  "corner": int(alpha[0, 0]), "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                  "partial": int(((alpha > 0) & (alpha < 255)).sum())}))
"""


class SubjectMaskTests(unittest.TestCase):
    cases = 0
    passed = 0

    @classmethod
    def setUpClass(cls):
        venv_tool.require_venv(cls)
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
        print(f"SUBJECT_MASK cases={SubjectMaskTests.cases} ok={SubjectMaskTests.passed}")

    def case(self, label, body):
        """Run one named check; count it, and re-raise so the failure names the label."""
        SubjectMaskTests.cases += 1
        try:
            body()
        except Exception as exc:
            raise AssertionError(f"{label}: {exc}") from exc
        SubjectMaskTests.passed += 1

    def write_json(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return path

    def disc_image(self, name="disc.png"):
        path = self.root / name
        venv_tool.run_code(DISC_ON_KEY, path, MATTE_SIZE)
        return path

    @venv_tool.needs_gate_meshes
    def test_ground_truth_cases(self):
        result = json.loads(venv_tool.run_code((HERE / "subject_mask_cases.py").read_text(), TOOLS, FIXTURES))
        for item in result["cases"]:
            self.case(item["label"], lambda item=item: self.assertTrue(item["ok"], item["error"]))
        print("SUBJECT_MASK_REPORT " + json.dumps(result["reports"], sort_keys=True))

    def test_matte_with_a_chroma_background(self):
        image, config = self.disc_image(), self.write_json("chroma.json", CHROMA)

        def chroma():
            result = venv_tool.run_tool("matte.py", image, "--out", self.root / "matte", "--background", config)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((self.root / "matte" / "matte.json").read_text())
            self.assertEqual(report["background"], CHROMA)
            self.assertNotIn("tolerance", report)
            self.assertEqual(report["component_count"], 1)
            venv_tool.run_code("import sys; from PIL import Image; import numpy as np; a = np.asarray(Image.open(sys.argv[1]))[:, :, 3];"
                               "assert a[64, 64] == 255 and a[0, 0] == 0 and a[:, 0].max() == 0", self.root / "matte" / "matte.png")
        self.case("matte --background chroma_key keys the disc", chroma)

        def near_white():
            white = self.root / "white.png"
            venv_tool.write_discs(white, MATTE_SIZE, [(64, 64, 30)])
            result = venv_tool.run_tool("matte.py", white, "--out", self.root / "nw", "--tolerance", 240)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((self.root / "nw" / "matte.json").read_text())
            self.assertEqual((report["tolerance"], report["background"]), (240, {"method": "near_white", "tolerance": 240}))
        self.case("matte --tolerance still means near_white", near_white)

        def bad_file():
            broken = self.write_json("broken.json", {k: v for k, v in CHROMA.items() if k != "feather"})
            result = venv_tool.run_tool("matte.py", image, "--out", self.root / "bad", "--background", broken)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, f"matte: background {broken}: {FEATHER_ERROR}\n")
        self.case("matte rejects a background file with a missing key", bad_file)

        def both():
            result = venv_tool.run_tool("matte.py", image, "--out", self.root / "both", "--background", config, "--tolerance", 200)
            self.assertEqual(result.returncode, 2)
            self.assertIn("not allowed with argument", result.stderr)
        self.case("matte refuses --tolerance together with --background", both)

    def test_normalize_image_with_a_chroma_config(self):
        image = self.disc_image()
        config = {"background": CHROMA, "canvas_size": 256, "margin": 16, "output_mode": "rgba", "background_color": [0, 0, 0]}
        path = self.write_json("norm.json", config)

        def run():
            out = self.root / "norm.png"
            result = venv_tool.run_tool("normalize_image.py", image, out, "--config", path, "--report", self.root / "norm.report.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(venv_tool.run_code(OUTPUT_INFO, out))
            self.assertEqual((info["mode"], info["size"], info["centre"], info["corner"]), ("RGBA", [256, 256], 255, 0))
            self.assertEqual(info["bbox"][:2], [16, 16])
            self.assertGreater(info["partial"], 0, "the soft edge should survive")
            report = json.loads((self.root / "norm.report.json").read_text())
            self.assertEqual(report["config"]["background"], CHROMA)
        self.case("normalize_image keys a chroma background and keeps a soft edge", run)

        def icon_pipeline():
            icon = json.loads((EXAMPLES / "icon.pipeline.json").read_text())
            params = next(stage["params"] for stage in icon["stages"] if stage["id"] == "tidy_image")
            config = self.write_json("icon.norm.json", {"background": icon["capture"]["background"], **params,
                                                         "background_color": [0, 0, 0]})
            out = self.root / "icon.png"
            result = venv_tool.run_tool("normalize_image.py", image, out, "--config", config, "--report", self.root / "icon.report.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(venv_tool.run_code(OUTPUT_INFO, out))
            self.assertEqual((info["size"], info["centre"], info["corner"], info["bbox"][:2]), ([256, 256], 255, 0, [16, 16]))
        self.case("icon.pipeline.json's own capture.background and tidy_image params key a magenta image", icon_pipeline)

        def run_example():
            example = json.loads((EXAMPLES / "normalize_image.chroma.json").read_text())
            self.assertEqual(example["background"]["method"], "chroma_key")
            result = venv_tool.run_tool("normalize_image.py", image, self.root / "ex.png", "--config",
                                        EXAMPLES / "normalize_image.chroma.json", "--report", self.root / "ex.report.json")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.case("the chroma example config runs", run_example)

        def errors():
            for label, data, message in (
                    ("both keys", {**config, "background_tolerance": 236}, "needs exactly one of 'background_tolerance' or 'background'"),
                    ("neither key", {k: v for k, v in config.items() if k != "background"},
                     "needs exactly one of 'background_tolerance' or 'background'"),
                    ("missing feather", {**config, "background": {k: v for k, v in CHROMA.items() if k != "feather"}},
                     f"key 'background' {FEATHER_ERROR}"),
                    ("not an object", {**config, "background": 5}, "key 'background' must be an object")):
                bad = self.write_json("bad.json", data)
                result = venv_tool.run_tool("normalize_image.py", image, self.root / "bad.png", "--config", bad,
                                            "--report", self.root / "bad.report.json")
                self.assertEqual(result.returncode, 2, label)
                self.assertEqual(result.stderr, f"normalize_image: config {bad} {message}\n", label)
        self.case("normalize_image config errors have exact messages", errors)

    def gate_config(self, background=None):
        config = json.loads((EXAMPLES / "gate_v2.prop.json").read_text())
        if background:
            config["capture"]["background"] = background
        return config

    @venv_tool.needs_gate_meshes
    def test_gates_and_finish_with_a_chroma_background(self):
        green = self.root / "cabinet.green.png"
        venv_tool.run_code(REKEY, TOOLS, FIXTURES / "cabinet.png", green)
        mesh = FIXTURES / "cabinet.glb"

        def v2():
            plain = venv_tool.run_tool("mesh_gates.py", mesh, FIXTURES / "cabinet.png", "--out", self.root / "plain.json",
                                       "--profile", "v2", "--gate", self.write_json("plain.gate.json", self.gate_config()))
            keyed = venv_tool.run_tool("mesh_gates.py", mesh, green, "--out", self.root / "keyed.json", "--profile", "v2",
                                       "--gate", self.write_json("keyed.gate.json", self.gate_config(GREEN)))
            self.assertEqual(keyed.returncode, plain.returncode, keyed.stderr)
            before, after = (json.loads((self.root / f"{n}.json").read_text()) for n in ("plain", "keyed"))
            self.assertEqual(after["verdict"], before["verdict"])
            self.assertAlmostEqual(after["measures"]["silhouette_iou"], before["measures"]["silhouette_iou"], delta=0.005)
        self.case("gate v2 reads capture.background from the gate config (same verdict on a re-keyed image)", v2)

        def conflict():
            gate = self.write_json("both.gate.json", self.gate_config(GREEN))
            result = venv_tool.run_tool("mesh_gates.py", mesh, green, "--out", self.root / "both.json", "--profile", "v2",
                                        "--gate", gate, "--tolerance", 200)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, "mesh_gates: the gate config has capture.background; do not also pass --tolerance\n")
        self.case("gate v2 refuses --tolerance together with capture.background", conflict)

        def bad_gate():
            gate = self.write_json("bad.gate.json", self.gate_config({k: v for k, v in GREEN.items() if k != "feather"}))
            result = venv_tool.run_tool("mesh_gates.py", mesh, green, "--out", self.root / "bad.json", "--profile", "v2", "--gate", gate)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, f"mesh_gates: {gate}: capture.background.{FEATHER_ERROR}\n")
        self.case("gate v2 config error names the file and key", bad_gate)

        def v1():
            result = venv_tool.run_tool("mesh_gates.py", mesh, FIXTURES / "cabinet.png", "--out", self.root / "v1.json", "--tolerance", 236)
            default = venv_tool.run_tool("mesh_gates.py", mesh, FIXTURES / "cabinet.png", "--out", self.root / "v1d.json")
            self.assertEqual(result.returncode, default.returncode)
            self.assertEqual((self.root / "v1.json").read_text(), (self.root / "v1d.json").read_text())
        self.case("gate v1 --tolerance 236 equals the default (near_white)", v1)

        def finish():
            outs = {}
            for name, config, image in (("plain", "finish.prop.json", FIXTURES / "cabinet.png"), ("chroma", "finish.prop.chroma.json", green)):
                out = self.root / f"finish-{name}"
                result = venv_tool.run_tool("mesh_finish.py", mesh, image, out, "--config", EXAMPLES / config)
                outs[name] = (result.returncode, json.loads((out / "finish.json").read_text())["verdict"])
            self.assertEqual(outs["chroma"], outs["plain"])
        self.case("mesh_finish with the chroma example gives the verdict of the near_white one on a re-keyed image", finish)

        def finish_error():
            config = json.loads((EXAMPLES / "finish.prop.chroma.json").read_text())
            del config["capture"]["background"]["feather"]
            path = self.write_json("finish.bad.json", config)
            result = venv_tool.run_tool("mesh_finish.py", mesh, green, self.root / "finish-bad", "--config", path)
            self.assertEqual(result.returncode, 2)
            self.assertIn(f"{path}: capture.background.{FEATHER_ERROR}", result.stderr)
            self.assertFalse((self.root / "finish-bad").exists())
        self.case("mesh_finish config error names the file and key", finish_error)

    def test_plain_python_config_pieces(self):
        def examples_differ_only_in_the_background():
            plain = json.loads((EXAMPLES / "finish.prop.json").read_text())
            chroma = json.loads((EXAMPLES / "finish.prop.chroma.json").read_text())
            self.assertEqual(plain["capture"]["background"], {"tolerance": 236})
            plain["capture"]["background"] = chroma["capture"]["background"]
            self.assertEqual(plain, chroma)
        self.case("the chroma finish example differs from finish.prop.json only in capture.background", examples_differ_only_in_the_background)

        def gate_config_parse():
            config = self.gate_config(GREEN)
            parsed = gate_v2_config.parse(config, "g.json")
            self.assertEqual(parsed["background"], GREEN)
            self.assertIsNone(gate_v2_config.parse(self.gate_config(), "g.json")["background"])
            config["capture"]["background"]["holes"] = 1
            with self.assertRaises(gate_v2_config.ConfigError) as ctx:
                gate_v2_config.parse(config, "g.json")
            self.assertEqual(str(ctx.exception), "g.json: capture.background.holes must be true or false")
        self.case("gate_v2_config takes an optional capture.background", gate_config_parse)


if __name__ == "__main__":
    unittest.main()
