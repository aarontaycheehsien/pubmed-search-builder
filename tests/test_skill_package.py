import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_skill", ROOT / "tools" / "package_skill.py")
package_skill = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(package_skill)


class SkillPackageTests(unittest.TestCase):
    def test_package_contains_runtime_files_and_excludes_repository_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "pubmed-search-builder"
            receipt = package_skill.package_skill(ROOT, output)
            self.assertEqual(receipt["skill"], "pubmed-search-builder")
            self.assertTrue((output / "SKILL.md").is_file())
            self.assertTrue((output / "agents" / "openai.yaml").is_file())
            self.assertTrue((output / "references" / "workflow.md").is_file())
            self.assertTrue((output / "references" / "protocol-dsl.md").is_file())
            self.assertTrue((output / "schemas" / "review-protocol.schema.json").is_file())
            self.assertTrue((output / "schemas" / "run-manifest-v2.schema.json").is_file())
            self.assertTrue((output / "scripts" / "manifest_tool.py").is_file())
            self.assertTrue((output / "scripts" / "revision_guard.py").is_file())
            self.assertTrue((output / "references" / "no-harm-revisions.md").is_file())
            self.assertTrue((output / "references" / "external-trial-registry-validation.md").is_file())
            self.assertTrue((output / "references" / "evidence-synthesis-retrieval.md").is_file())
            self.assertTrue((output / "references" / "methods-evaluation-framework.md").is_file())
            self.assertTrue((output / "scripts" / "registry_sentinel.py").is_file())
            self.assertTrue((output / "scripts" / "review_discovery.py").is_file())
            self.assertTrue((output / "pubmed_search_builder" / "workflow" / "events.py").is_file())
            self.assertTrue((output / "pubmed_search_builder" / "infrastructure" / "transport.py").is_file())
            self.assertFalse((output / "README.md").exists())
            self.assertFalse((output / "tests").exists())
            self.assertFalse((output / "evals").exists())
            self.assertFalse((output / "tools").exists())
            manifest = Path(tmp) / "run_manifest_v2.json"
            completed = subprocess.run(
                [sys.executable, str(output / "scripts" / "workflow_tool.py"), "init", "--manifest", str(manifest)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["manifest_version"], "2.0")

    def test_replace_refuses_wrong_destination_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "wrong-name"
            output.mkdir()
            with self.assertRaises(package_skill.PackageError):
                package_skill.package_skill(ROOT, output, replace=True)

    def test_output_cannot_be_inside_source_repository(self):
        with self.assertRaises(package_skill.PackageError):
            package_skill.package_skill(ROOT, ROOT / "pubmed-search-builder")


if __name__ == "__main__":
    unittest.main()
