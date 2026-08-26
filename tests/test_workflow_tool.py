import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "workflow_tool.py"
MANIFEST_TOOL = ROOT / "scripts" / "manifest_tool.py"


class WorkflowToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "run_manifest.json"

    def run_tool(self, *args):
        result = subprocess.run(
            [sys.executable, str(TOOL), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode, json.loads(result.stdout)

    def state(self, *args):
        return subprocess.run(
            [sys.executable, str(MANIFEST_TOOL), "state", *map(str, args), "--manifest", str(self.manifest)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def initialize_stage(self):
        code, receipt = self.run_tool("init", "--manifest", self.manifest, "--topic-slug", "demo")
        self.assertEqual(code, 0, receipt)
        self.state("set-stage", "question-intake")

    def test_init_attach_and_status(self):
        self.initialize_stage()
        code, attach = self.run_tool("attach", "--manifest", self.manifest)
        self.assertEqual(code, 0)
        self.assertEqual(attach["current_stage"], "question-intake")
        code, status = self.run_tool("status", "--manifest", self.manifest)
        self.assertEqual(code, 0)
        self.assertFalse(status["complete"])
        self.assertGreater(status["issue_count"], 0)

    def test_successful_run_records_hashes(self):
        self.initialize_stage()
        source = self.root / "input.txt"
        output = self.root / "output.json"
        source.write_text("input", encoding="utf-8")
        script = f"import pathlib; pathlib.Path(r'{output}').write_text('{{\"ok\": true, \"count\": 7}}')"
        code, receipt = self.run_tool(
            "run", "--manifest", self.manifest, "--stage", "question-intake", "--kind", "artifact",
            "--input", source, "--output", output, "--", sys.executable, "-c", script,
        )
        self.assertEqual(code, 0, receipt)
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = data["entries"][0]
        self.assertEqual(entry["count"], 7)
        self.assertEqual(entry["stage"], "question-intake")
        self.assertTrue(entry["output_sha256"])
        self.assertTrue(entry["input_sha256"])

    def test_failed_command_does_not_update_manifest(self):
        self.initialize_stage()
        code, receipt = self.run_tool(
            "run", "--manifest", self.manifest, "--stage", "question-intake", "--kind", "artifact",
            "--", sys.executable, "-c", "raise SystemExit(3)",
        )
        self.assertEqual(code, 1)
        self.assertFalse(receipt["manifest_updated"])
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["entries"], [])

    def test_unchanged_output_is_rejected(self):
        self.initialize_stage()
        output = self.root / "output.json"
        output.write_text('{"ok": true}', encoding="utf-8")
        code, receipt = self.run_tool(
            "run", "--manifest", self.manifest, "--stage", "question-intake", "--kind", "artifact",
            "--output", output, "--", sys.executable, "-c", "pass",
        )
        self.assertEqual(code, 1)
        self.assertIn("unchanged", receipt["error"])

    def test_out_of_order_stage_is_rejected(self):
        self.initialize_stage()
        self.state("set-stage", "final-qa")
        code, receipt = self.run_tool(
            "run", "--manifest", self.manifest, "--stage", "final-qa", "--kind", "qa",
            "--", sys.executable, "-c", "pass",
        )
        self.assertEqual(code, 1)
        self.assertIn("prior stage", receipt["error"])


if __name__ == "__main__":
    unittest.main()
