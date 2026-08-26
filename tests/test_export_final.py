import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "export_final.py"
WORKFLOW_TOOL = ROOT / "scripts" / "workflow_tool.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExportFinalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.strategy = self.root / "strategy.txt"
        self.strategy.write_text('"Adolescent"[Mesh] AND nutrition[tiab]\n', encoding="utf-8")
        self.qa = self.root / "final_qa.json"
        self.qa.write_text(json.dumps({"ok": True, "errors": [], "warnings": []}), encoding="utf-8")
        strategy_hash = sha256(self.strategy)
        self.manifest = self.root / "run_manifest.json"
        payload = {
            "manifest_version": "1.1",
            "skill": "pubmed-search-builder",
            "skill_version": "1.0.0",
            "topic_slug": "adolescent-nutrition",
            "created_utc": "2026-01-01T00:00:00Z",
            "updated_utc": "2026-01-01T00:00:00Z",
            "working_dir": str(self.root),
            "entries": [
                {
                    "seq": 1,
                    "timestamp_utc": "2026-01-01T00:00:01Z",
                    "kind": "search",
                    "command": "pubmed_tool.py search --query-file strategy.txt --retmax 0",
                    "output_path": None,
                    "input_sha256": {str(self.strategy): strategy_hash},
                    "count": 42,
                },
                {
                    "seq": 2,
                    "timestamp_utc": "2026-01-01T00:00:02Z",
                    "kind": "qa",
                    "command": "hooks_tool.py final-qa --strategy-file strategy.txt",
                    "output_path": str(self.qa),
                    "output_sha256": sha256(self.qa),
                    "input_sha256": {str(self.strategy): strategy_hash},
                    "count": None,
                },
            ],
            "superseded": [],
        }
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")

    def run_tool(self, *, output: Path, strategy: Path | None = None):
        return subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--strategy", str(strategy or self.strategy),
                "--manifest", str(self.manifest),
                "--output", str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_export_is_deterministic_and_contains_validated_provenance(self):
        output = self.root / "final_strategy.md"
        first = self.run_tool(output=output)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_bytes = output.read_bytes()
        receipt = json.loads(first.stdout)
        self.assertEqual(receipt["strategy_sha256"], sha256(self.strategy))
        self.assertEqual(receipt["count"], 42)

        second = self.run_tool(output=output)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(output.read_bytes(), first_bytes)
        rendered = first_bytes.decode("utf-8")
        self.assertIn('"strategy_sha256": "' + sha256(self.strategy) + '"', rendered)
        self.assertIn('"final_pubmed_count": 42', rendered)
        self.assertIn(self.strategy.read_text(encoding="utf-8").strip(), rendered)
        self.assertNotIn(str(self.root), rendered)

    def test_export_rejects_strategy_not_bound_to_qa_and_count(self):
        changed = self.root / "changed.txt"
        changed.write_text('"Different"[Mesh]\n', encoding="utf-8")
        output = self.root / "final_strategy.md"
        result = self.run_tool(output=output, strategy=changed)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output.exists())
        self.assertIn("does not match the hash", json.loads(result.stdout)["error"])

    def test_export_rejects_unsuccessful_final_qa(self):
        self.qa.write_text(json.dumps({"ok": False, "errors": ["invalid"]}), encoding="utf-8")
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["entries"][1]["output_sha256"] = sha256(self.qa)
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        output = self.root / "final_strategy.md"
        result = self.run_tool(output=output)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output.exists())
        self.assertIn("unsuccessful", json.loads(result.stdout)["error"])

    def test_export_does_not_overwrite_a_different_handoff(self):
        output = self.root / "final_strategy.md"
        output.write_text("existing different handoff\n", encoding="utf-8")
        result = self.run_tool(output=output)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(output.read_text(encoding="utf-8"), "existing different handoff\n")
        self.assertIn("Refusing to replace", json.loads(result.stdout)["error"])

    def test_export_requires_canonical_filename(self):
        output = self.root / "custom.md"
        result = self.run_tool(output=output)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(output.exists())
        self.assertIn("must be named final_strategy.md", json.loads(result.stdout)["error"])

    def test_workflow_export_final_records_output_and_exact_strategy_hash(self):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        prior_stages = (
            "question-intake", "seed-intake", "concept-gate", "pre-mesh-brainstorm",
            "mesh-exploration", "text-word-expansion", "block-testing", "validation",
            "revision", "final-qa",
        )
        data["build_state"] = {
            "current_stage": "audit-output",
            "stages_completed": list(prior_stages),
            "stage_records": {
                stage: {"status": "complete", "reason": "", "recorded_utc": "2026-01-01T00:00:00Z"}
                for stage in prior_stages
            },
            "gates": {"framework": "PICO", "seed": "none", "concept": "resolved", "filter": "none"},
            "pending_user_question": "", "open_decisions": [], "blocks": {},
            "recall_offer": "pending", "unvalidated_handoff": {"status": "pending", "reason": ""},
            "run_status": {"status": "active", "reason": ""},
        }
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        output = self.root / "final_strategy.md"
        result = subprocess.run(
            [
                sys.executable, str(WORKFLOW_TOOL), "export-final",
                "--manifest", str(self.manifest),
                "--strategy", str(self.strategy),
                "--output", str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = json.loads(self.manifest.read_text(encoding="utf-8"))
        entry = updated["entries"][-1]
        self.assertIn("export_final.py", entry["command"])
        self.assertEqual(entry["output_path"], str(output))
        self.assertEqual(entry["output_sha256"], sha256(output))
        self.assertEqual(entry["input_sha256"], {str(self.strategy): sha256(self.strategy)})
        self.assertEqual(entry["count"], 42)


if __name__ == "__main__":
    unittest.main()
