"""The trust rule, pipeline side (docs/adapters.md): only the machine config defines a command. Every way data reaches
the runner tries to add a program, an argument, an environment variable or a working folder, and each must fail
closed: refused, or the command that runs is exactly the configured one. server/tests/test_trust_rule.py covers the
HTTP API, entity data, the project file and export bundles."""
import copy
import json
import os
import subprocess
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
import machine  # noqa: E402
import pipeline_file as pf  # noqa: E402
import pipeline_resolve as pr  # noqa: E402
import pipeline_run as run  # noqa: E402
import venv_tool  # noqa: E402
from test_adapter_config import Recorder, prop_job, stage_of  # noqa: E402

PROP = ROOT / "pipelines" / "examples" / "prop.pipeline.json"
CONFIGURED = {"id": "img", "kind": "image", "argv": ["/opt/configured/prog", "--prompt={prompt}", "--out", "{output}"],
              "sandbox": {"network": "allow"}, "licence": "MIT"}
COMMAND_SHAPES = {"command": "/bin/sh -c id", "argv": ["/bin/sh", "-c", "id"], "env": {"LD_PRELOAD": "/tmp/x.so"},
                  "cwd": "/", "adapter": {"argv": ["/bin/sh"]}, "shell": True, "runtime": "/bin/sh",
                  "model_paths": {"concept": "/tmp/weights"}}


class TrustRuleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.config = self.dir / "machine.json"
        self.config.write_text(json.dumps({"adapters": [CONFIGURED], "defaults": {"image": "img"}}))
        env = patch.dict(os.environ, {machine.CONFIG_ENV: str(self.config)})
        env.start()
        self.addCleanup(env.stop)

    def spawned(self, stage):
        """The command the concept runner would start for STAGE (nothing is started)."""
        recorder, folder = Recorder(), self.dir / "concept"
        folder.mkdir(exist_ok=True)
        (folder / "step.log").write_text("")
        with patch.object(adapter_run.local_run, "execute", recorder):
            run.default_runners()["concept"].run(stage, {}, folder, 5)
        return recorder.calls[0]

    def test_a_pipeline_file_cannot_hold_a_command(self):
        raw = json.loads(PROP.read_text())
        for key, value in COMMAND_SHAPES.items():
            for target in (raw, raw["stages"][0], raw["stages"][0]["params"]):
                changed = copy.deepcopy(raw)
                where = changed if target is raw else changed["stages"][0] if target is raw["stages"][0] \
                    else changed["stages"][0]["params"]
                where[key] = value
                file = self.dir / "p.json"
                file.write_text(json.dumps(changed))
                with self.subTest(key=key, at=id(target)), self.assertRaises(pf.PipelineError):
                    pf.load(file)
        for value in COMMAND_SHAPES.values():
            changed = copy.deepcopy(raw)
            changed["stages"][0]["model"] = value
            file = self.dir / "p.json"
            file.write_text(json.dumps(changed))
            with self.subTest(model=value), self.assertRaisesRegex(pf.PipelineError, "adapter id"):
                pf.load(file)

    def test_a_resolved_job_chooses_by_id_and_its_extra_keys_never_reach_the_command(self):
        stage = stage_of(prop_job(), "concept")
        expected = self.spawned(dict(stage))
        self.assertEqual(expected["argv"][0], "/opt/configured/prog")
        tampered = {**stage, **COMMAND_SHAPES, "params": {**stage["params"], **COMMAND_SHAPES}}
        self.assertEqual(self.spawned(tampered)["argv"], expected["argv"])
        self.assertEqual(self.spawned(tampered)["env"], {})
        for value in COMMAND_SHAPES.values():
            job = prop_job()
            job["stages"][0]["model"] = value
            with self.subTest(model=value), self.assertRaisesRegex(run.RunError, "must be an adapter id"):
                run.run_job(job, self.dir / "out", run.default_runners(job, {}), log=lambda m: None)

    def test_a_prompt_is_one_argument_whatever_it_holds(self):
        stage = stage_of(prop_job(), "concept")
        stage["prompt"] = "x --out /etc/passwd; rm -rf ~ $(id) {python} {{repo}}"
        argv = self.spawned(stage)["argv"]
        self.assertEqual(len(argv), len(CONFIGURED["argv"]))
        self.assertEqual(argv[1], "--prompt=" + stage["prompt"])

    def test_an_unknown_id_never_falls_back_to_another_adapter(self):
        stage = {**stage_of(prop_job(), "concept"), "model": "standin-mesh"}
        with self.assertRaisesRegex(run.RunError, "is of kind 'image-to-mesh'"):
            self.spawned(stage)
        with self.assertRaisesRegex(run.RunError, "no adapter 'other' is configured"):
            self.spawned({**stage, "model": "other"})

    def test_icon_jobs_hold_no_command(self):
        jobs = json.dumps([{"prompt": "a drill", "output": str(self.dir / "d.png"), "argv": ["/bin/sh"]}])
        venv_tool.require_venv(self)  # icon_batch.py imports Pillow
        result = subprocess.run([str(venv_tool.interpreter()), "-I", str(ROOT / "icon_batch.py"), "--validate-only",
                                 "--jobs-json", jobs], capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only prompt, output and seed", result.stderr)

    def test_only_the_machine_config_defines_a_command(self):
        """The adapters a run can use are the built-in stand-ins and the machine config's; nothing else is read."""
        found = ac.from_machine()
        self.assertEqual({e.origin for e in found.entries.values()}, {"built in", f"{self.config}: adapters[0]"})


if __name__ == "__main__":
    unittest.main()
