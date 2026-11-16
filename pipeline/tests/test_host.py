"""host.py, the one module that knows the operating system: capabilities, requirement messages, the network sandbox
and the rule that nothing else branches on the operating system."""
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
import host  # noqa: E402

OS_PATTERNS = re.compile(r"sys\.platform|platform\.(system|mac_ver|machine)\(|sandbox-exec|[\"']darwin[\"']|/opt/homebrew|"
                         r"os\.uname\(|RUSAGE_CHILDREN\)\.ru_maxrss \*")


class CapabilityTests(unittest.TestCase):
    def test_cpu_is_always_there_and_every_name_is_known(self):
        found = host.capabilities()
        self.assertIn("cpu", found)
        self.assertTrue(set(found) <= set(host.KNOWN))
        self.assertEqual(host.unmet(["cpu"]), [])

    def test_an_unmet_requirement_is_one_plain_sentence(self):
        with patch.object(host, "_system", return_value="Linux"), patch.object(host.shutil, "which", return_value=None):
            problems = host.unmet(["apple_silicon", "cuda", "cpu"])
        self.assertEqual(len(problems), 2)
        self.assertIn("Apple Silicon", problems[0])
        self.assertIn("nvidia-smi", problems[1])

    def test_an_unknown_requirement_is_refused_not_passed(self):
        self.assertIn("not a capability", host.unmet(["quantum"])[0])

    def test_no_network_mode_means_a_refusal_never_an_open_network(self):
        with patch.object(host, "network_modes", return_value=["allow"]):
            self.assertIn("deny a child process the network", host.unmet(["network_denied"])[0])
            with self.assertRaisesRegex(host.HostError, "refused rather than run with the network open"):
                host.sandboxed(["prog"], "deny")
        self.assertEqual(host.sandboxed(["prog", 1], "allow"), ["prog", "1"])
        with self.assertRaisesRegex(host.HostError, "unknown network mode"):
            host.sandboxed(["prog"], "open")

    @unittest.skipUnless("deny" in host.network_modes(), "this host cannot deny a child the network")
    def test_a_denied_child_cannot_reach_out_and_a_local_one_can_still_run(self):
        host.prove_network_denied("deny")
        result = subprocess.run(host.sandboxed([sys.executable, "-I", "-c", "print('ran')"], "deny"),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout.strip(), "ran")

    def test_rss_is_in_bytes(self):
        with patch.object(host, "_system", return_value="Darwin"):
            self.assertEqual(host.rss_bytes(2048), 2048)
        with patch.object(host, "_system", return_value="Linux"):
            self.assertEqual(host.rss_bytes(2048), 2048 * 1024)


class OnlyHostKnowsTheSystemTests(unittest.TestCase):
    def test_nothing_else_branches_on_the_operating_system(self):
        sources = [*sorted(ROOT.glob("*.py")), *sorted((REPO / "adapters").rglob("*.py")),
                   *sorted((REPO / "server" / "authoring").glob("*.py"))]
        found = [f"{path.relative_to(REPO)}:{number}: {line.strip()}"
                 for path in sources if path.name != "host.py"
                 for number, line in enumerate(path.read_text().splitlines(), 1) if OS_PATTERNS.search(line)]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
