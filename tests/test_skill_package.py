import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_skill", ROOT / "tools" / "package_skill.py")
package_skill = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(package_skill)


class SkillPackageTests(unittest.TestCase):
    def test_shared_repository_and_junction_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repository = root / "pubmed-search-builder"
            repository.mkdir()
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repository), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                            "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
            worktree = root / "development"
            subprocess.run(["git", "-C", str(repository), "worktree", "add", "--detach", str(worktree)], check=True, capture_output=True)
            (worktree / "SKILL.md").write_text("fixture", encoding="utf-8")
            with patch.object(package_skill.shutil, "rmtree") as remove:
                with self.assertRaises(package_skill.PackageError):
                    package_skill.package_skill(worktree, repository, replace=True)
                remove.assert_not_called()
            self.assertTrue((repository / ".git").is_dir())
            link = root / "linked"
            if sys.platform == "win32":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(repository)], check=True, capture_output=True)
            else:
                link.symlink_to(repository, target_is_directory=True)
            try:
                with self.assertRaises(package_skill.PackageError):
                    package_skill.package_skill(worktree, link, replace=True)
            finally:
                if sys.platform == "win32":
                    link.rmdir()
                else:
                    link.unlink()

    def test_unmanaged_directory_and_protected_roots_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "pubmed-search-builder"
            output.mkdir()
            sentinel = output / "important.txt"
            sentinel.write_text("keep", encoding="utf-8")
            for target in (output, Path.home(), Path(ROOT.anchor)):
                with self.subTest(target=target), self.assertRaises(package_skill.PackageError):
                    package_skill.package_skill(ROOT, target, replace=True)
            self.assertEqual(sentinel.read_text(), "keep")

    def test_replace_preserves_credentials_and_recoverable_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "pubmed-search-builder"
            first = package_skill.package_skill(ROOT, output)
            self.assertTrue(first["source_commit"])
            (output / ".env").write_text("LOCAL_SETTING=fixture", encoding="utf-8")
            (output / "local-notes.txt").write_text("keep", encoding="utf-8")
            receipt = package_skill.package_skill(ROOT, output, replace=True)
            backup = Path(receipt["backup"])
            self.assertEqual((backup / "local-notes.txt").read_text(), "keep")
            self.assertEqual((output / ".env").read_text(), "LOCAL_SETTING=fixture")
            self.assertIn("SKILL.md", json.loads((output / package_skill.OWNERSHIP_FILE).read_text())["sha256"])

    def test_build_and_promotion_failures_preserve_previous_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "pubmed-search-builder"
            package_skill.package_skill(ROOT, output)
            original = (output / package_skill.OWNERSHIP_FILE).read_bytes()
            with patch.object(package_skill, "build_package", side_effect=OSError("copy failed")):
                with self.assertRaises(OSError):
                    package_skill.package_skill(ROOT, output, replace=True)
            self.assertEqual((output / package_skill.OWNERSHIP_FILE).read_bytes(), original)
            rename = Path.rename
            def fail_promotion(path, destination):
                if ".stage-" in str(path.parent):
                    raise OSError("promotion failed")
                return rename(path, destination)
            with patch.object(Path, "rename", fail_promotion):
                with self.assertRaises(package_skill.PackageError):
                    package_skill.package_skill(ROOT, output, replace=True)
            self.assertEqual((output / package_skill.OWNERSHIP_FILE).read_bytes(), original)
            self.assertFalse(output.with_name(f".{output.name}.package.lock").exists())

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
