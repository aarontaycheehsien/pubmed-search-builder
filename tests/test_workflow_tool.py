import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


manifest_tool = load_module("manifest_tool_workflow_test", "manifest_tool.py")
sys.modules["manifest_tool"] = manifest_tool
workflow_tool = load_module("workflow_tool_test", "workflow_tool.py")


class WorkflowToolTests(unittest.TestCase):
    def run_main(self, argv):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            code = workflow_tool.main(argv)
        return code, json.loads(stream.getvalue())

    def test_successful_stage_records_hashes_and_detects_stale_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "run_manifest.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(manifest_tool.main(["init", "--manifest", str(manifest), "--topic-slug", "x"]), 0)
            input_file = root / "query.txt"
            input_file.write_text("x[tiab]", encoding="utf-8")
            code = "import json,pathlib; pathlib.Path('out.json').write_text(json.dumps({'count': 42}), encoding='utf-8')"
            rc, receipt = self.run_main(
                [
                    "--manifest", str(manifest),
                    "--kind", "search",
                    "--label", "final topic-only strategy",
                    "--output", "out.json",
                    "--input", "query.txt",
                    "--cwd", str(root),
                    "--", sys.executable, "-c", code,
                ]
            )
            self.assertEqual(rc, 0, receipt)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            entry = data["entries"][0]
            self.assertEqual(entry["count"], 42)
            self.assertTrue(entry["output_sha256"])
            self.assertTrue(entry["input_sha256"])
            (root / "out.json").write_text(json.dumps({"count": 43}), encoding="utf-8")
            issues = manifest_tool.validate_manifest(data, check_files=True, manifest_path=manifest)
            self.assertTrue(any("output artifact hash no longer matches" in issue for issue in issues))

    def test_failed_stage_does_not_update_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "run_manifest.json"
            with contextlib.redirect_stdout(io.StringIO()):
                manifest_tool.main(["init", "--manifest", str(manifest), "--topic-slug", "x"])
            rc, receipt = self.run_main(
                ["--manifest", str(manifest), "--kind", "search", "--", sys.executable, "-c", "raise SystemExit(7)"]
            )
            self.assertEqual(rc, 1)
            self.assertFalse(receipt["manifest_updated"])
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["entries"], [])

    def test_rejects_stage_that_mutates_declared_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "run_manifest.json"
            with contextlib.redirect_stdout(io.StringIO()):
                manifest_tool.main(["init", "--manifest", str(manifest), "--topic-slug", "x"])
            source = root / "query.txt"
            source.write_text("before", encoding="utf-8")
            code = "import pathlib; pathlib.Path('query.txt').write_text('after'); pathlib.Path('out.json').write_text('{}')"
            rc, receipt = self.run_main([
                "--manifest", str(manifest), "--kind", "search", "--input", "query.txt",
                "--output", "out.json", "--cwd", str(root), "--", sys.executable, "-c", code,
            ])
            self.assertEqual(rc, 1)
            self.assertIn("modified declared input", receipt["error"])
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["entries"], [])

    def test_rejects_unchanged_preexisting_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "run_manifest.json"
            with contextlib.redirect_stdout(io.StringIO()):
                manifest_tool.main(["init", "--manifest", str(manifest), "--topic-slug", "x"])
            (root / "out.json").write_text('{"ok": true}', encoding="utf-8")
            rc, receipt = self.run_main([
                "--manifest", str(manifest), "--kind", "search", "--output", "out.json",
                "--cwd", str(root), "--", sys.executable, "-c", "pass",
            ])
            self.assertEqual(rc, 1)
            self.assertIn("unchanged", receipt["error"])


if __name__ == "__main__":
    unittest.main()
