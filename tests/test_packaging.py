import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_skill_frontmatter_contains_only_trigger_fields(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        end = text.index("\n---", 4)
        keys = []
        for line in text[4:end].splitlines():
            if line and not line.startswith(" "):
                keys.append(line.split(":", 1)[0])
        self.assertEqual(keys, ["name", "description"])

    def test_required_skill_assets_exist(self):
        required = [
            "SKILL.md",
            "agents/openai.yaml",
            "references/workflow.md",
            "references/framework-selection.md",
            "references/anti-patterns.md",
            "references/audit-json-schema.md",
            "references/audit-example.json",
            "scripts/pubmed_tool.py",
            "scripts/mesh_tool.py",
            "scripts/hooks_tool.py",
            "scripts/audit_markdown.py",
            "scripts/manifest_tool.py",
            "examples/build_audit.py",
            "examples/build_queries.py",
            "evals/run_eval.py",
            "evals/run_suite.py",
            "LICENSE",
        ]
        missing = [path for path in required if not (ROOT / path).exists()]
        self.assertEqual(missing, [])

    def test_generated_artifacts_are_not_tracked(self):
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        tracked = {Path(line).as_posix() for line in proc.stdout.splitlines() if line.strip()}
        forbidden = []
        for path in tracked:
            name = Path(path).name
            if path == "run_manifest.json":
                forbidden.append(path)
            if path.startswith("evals/results/") or path.startswith("evals/.cache/"):
                forbidden.append(path)
            if "/" not in path and (path.startswith("pubmed_") or name.startswith("audit_")):
                forbidden.append(path)
            if "__pycache__" in path or ".pytest_cache" in path:
                forbidden.append(path)
            if name == ".env":
                forbidden.append(path)
        self.assertEqual(sorted(forbidden), [])


if __name__ == "__main__":
    unittest.main()
