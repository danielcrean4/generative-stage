"""adapter_run.py and the whole pipeline on the stand-in: requirements are checked before a run, the sandbox and GPU
lock follow the entry, the reported identity is recorded, and the prop pipeline runs end to end with no model."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import adapter_config as ac  # noqa: E402
import adapter_run  # noqa: E402
import host  # noqa: E402
import machine  # noqa: E402
import pipeline_run as run  # noqa: E402
import venv_tool  # noqa: E402

DATA = HERE / "fixtures" / "pipeline_files"
EXAMPLES = ROOT / "pipelines" / "examples"
ENTRY = {"id": "probe", "kind": "text", "sandbox": {"network": "allow"}, "licence": "MIT"}


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def test_the_stand_in_runs_and_reports_its_identity(self):
        entry = ac.parse({}, "none").entries["standin-text"]
        seconds = adapter_run.run(entry, {"prompt": "a lamp", "seed": 1, "output": self.dir / "text.txt",
                                          "out_dir": self.dir}, self.dir)
        self.assertLess(seconds, 1.0)
        self.assertEqual(adapter_run.reported(self.dir)["name"], "standin")

    def test_an_unmet_requirement_is_refused_before_anything_runs(self):
        entry = ac.parse_entry({**ENTRY, "argv": ["/no/such/program"], "requires": ["cuda"]}, "machine.json")
        with patch.object(host, "accelerators", return_value=["cpu"]), \
                self.assertRaisesRegex(adapter_run.Refused, "adapter 'probe' cannot run on this computer: needs an NVIDIA"):
            adapter_run.run(entry, {}, self.dir)
        with patch.object(host, "network_modes", return_value=["allow"]), \
                self.assertRaisesRegex(adapter_run.Refused, "deny a child process the network"):
            adapter_run.run(ac.parse_entry({**ENTRY, "argv": ["/x"], "sandbox": {"network": "deny"}}, "m"), {}, self.dir)

    def test_a_gpu_entry_needs_the_job_session(self):
        entry = ac.parse_entry({**ENTRY, "argv": ["/no/such/program"], "gpu": True}, "machine.json")
        with self.assertRaisesRegex(adapter_run.Refused, "no GPU session"):
            adapter_run.run(entry, {}, self.dir)

    @unittest.skipUnless("deny" in host.network_modes(), "this host cannot deny a child the network")
    def test_a_denied_entry_really_has_no_network(self):
        probe = "import socket; socket.create_connection(('1.1.1.1', 443), 1)"
        entry = ac.parse_entry({**ENTRY, "argv": ["{python}", "-I", "-c", probe], "sandbox": {"network": "deny"}}, "m")
        with self.assertRaises(RuntimeError):
            adapter_run.run(entry, {}, self.dir)
        self.assertIn("1.1.1.1", (self.dir / "step.log").read_text())


class StandinPipelineTests(unittest.TestCase):
    """The prop pipeline, unchanged, on a machine config that names no model: every stage runs (the real tidy,
    matte, clean, decimate and shape gate under the tools interpreter), the gates pass and the attempt records which
    adapter made each file and what it reported."""

    def test_the_prop_pipeline_runs_end_to_end_on_the_stand_in(self):
        venv_tool.require_venv(self)
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            config = temp / "machine.json"
            config.write_text(json.dumps({"tools_python": str(venv_tool.interpreter())}))
            out, errors = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {machine.CONFIG_ENV: str(config), "HOME": str(temp),
                                         "GENSTAGE_IDENTITY_CACHE": str(temp / "cache.json")}), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(errors):
                code = run.main(["--pipeline", str(EXAMPLES / "prop.pipeline.json"), "--subject", str(DATA / "subject.json"),
                                 "--motif", str(DATA / "motif.json"), "--style", str(DATA / "styles" / "clay"),
                                 "--contract", str(DATA / "contract.json"), "--seed", "7", "--out-root", str(temp / "out"),
                                 "--review-sheet", str(EXAMPLES / "finish.prop.json")])
            self.assertEqual(code, 0, errors.getvalue() + out.getvalue())
            record = json.loads(next((temp / "out" / "attempts").glob("*/attempt.json")).read_text())
            self.assertEqual(record["status"], "generated")
            self.assertEqual(record["stages"]["concept"]["model"]["adapter"], "standin-image")
            self.assertEqual(record["stages"]["mesh"]["model"]["adapter"], "standin-mesh")
            self.assertEqual(record["stages"]["mesh"]["model_reported"]["name"], "standin")
            self.assertNotIn("identity.json", record["stages"]["mesh"]["outputs"])
            self.assertTrue((temp / "out" / record["final"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
