"""The two commands that create build state refuse to seed it into the skill installation."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


manifest_tool = load_module("manifest_tool_workspace_test", "manifest_tool.py")
sys.modules.setdefault("manifest_tool", manifest_tool)
workflow_tool = load_module("workflow_tool_workspace_test", "workflow_tool.py")


class ManifestInitGuardTests(unittest.TestCase):
    def run_init(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = manifest_tool.main(["init", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_init_in_the_skill_root_is_refused(self):
        target = ROOT / "test_workspace_guard_should_not_exist.json"
        code, _out, err = self.run_init(["--manifest", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("skill installation directory", err)
        self.assertFalse(target.exists())

    def test_init_in_the_skill_root_is_permitted_with_the_override(self):
        with tempfile.TemporaryDirectory() as td:
            # Same guard path, exercised where a stray write cannot pollute the repository.
            target = Path(td) / "run_manifest.json"
            code, _out, _err = self.run_init(["--manifest", str(target), "--allow-skill-root"])
            self.assertEqual(code, 0)
            self.assertTrue(target.exists())

    def test_workspace_creates_the_directory_and_places_the_manifest_inside(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "runs" / "demo"
            code, out, _err = self.run_init(["--workspace", str(workspace), "--topic-slug", "demo"])
            self.assertEqual(code, 0)
            self.assertTrue((workspace / "run_manifest.json").is_file())
            self.assertEqual(Path(json.loads(out)["manifest_path"]), workspace / "run_manifest.json")

    def test_a_run_workspace_beneath_the_install_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "runs" / "topic"
            code, _out, _err = self.run_init(["--workspace", str(workspace)])
            self.assertEqual(code, 0)


class WorkflowInitGuardTests(unittest.TestCase):
    def run_init(self, argv):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
            code = workflow_tool.main(["init", *argv])
        return code, json.loads(stream.getvalue())

    def test_v2_init_in_the_skill_root_is_refused(self):
        target = ROOT / "test_workspace_guard_v2_should_not_exist.json"
        code, receipt = self.run_init(["--manifest", str(target)])
        self.assertEqual(code, 1)
        self.assertFalse(receipt["ok"])
        self.assertIn("skill installation directory", receipt["error"])
        self.assertFalse(target.exists())

    def test_v2_workspace_creates_the_directory_and_reports_it(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "runs" / "demo"
            code, receipt = self.run_init(["--workspace", str(workspace), "--topic-slug", "demo"])
            self.assertEqual(code, 0)
            self.assertTrue((workspace / "run_manifest_v2.json").is_file())
            self.assertEqual(Path(receipt["workspace"]), workspace.resolve())


if __name__ == "__main__":
    unittest.main()
