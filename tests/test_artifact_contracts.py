import ast
import json
import tempfile
import unittest
from pathlib import Path

from pubmed_search_builder.workflow.contracts import (
    ARTIFACT_ENVELOPE_VERSION,
    CONTRACTS,
    artifact_type_for_operation,
    envelope,
    reference_from_path,
)


class ArtifactContractTests(unittest.TestCase):
    def test_legacy_operations_are_assigned_stable_contract_types(self):
        self.assertEqual(artifact_type_for_operation("fetch"), "pubmed/evidence")
        self.assertEqual(artifact_type_for_operation("protocol-compile"), "protocol/receipt")
        self.assertEqual(artifact_type_for_operation("sweep"), "mesh/evidence")
        self.assertEqual(artifact_type_for_operation("unrecognised"), "legacy/unknown")
        self.assertEqual(artifact_type_for_operation("vocabulary-learning"), "strategy-analysis/evidence")
        self.assertEqual(artifact_type_for_operation("hooks-pre_final_strategy_qa"), "qa/evidence")
        self.assertEqual(artifact_type_for_operation("review-retrieval-profile"), "review-retrieval/profile")
        self.assertEqual(artifact_type_for_operation("review-filter-evaluate"), "review-filter/evaluation")
        self.assertIn("candidate-ledger", CONTRACTS)
        self.assertIn("review-discovery/evidence", CONTRACTS)

    def test_envelope_is_additive(self):
        result = envelope({"operation": "fetch", "ok": True, "records": []}, producer="pubmed_tool")
        self.assertEqual(result["records"], [])
        self.assertEqual(result["artifact_type"], "pubmed/evidence")
        self.assertEqual(result["artifact_version"], ARTIFACT_ENVELOPE_VERSION)
        self.assertEqual(result["producer"], "pubmed_tool")
        hook_result = envelope({"hook": "pre_final_strategy_qa", "ok": True}, producer="hooks_tool")
        self.assertEqual(hook_result["operation"], "hooks-pre_final_strategy_qa")
        self.assertEqual(hook_result["artifact_type"], "qa/evidence")

    def test_reference_uses_legacy_adapter_without_rewriting_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fetch.json"
            source = {"operation": "fetch", "ok": True, "scope_version": 2, "records": []}
            path.write_text(json.dumps(source), encoding="utf-8")
            reference, issues = reference_from_path("records", path)
            self.assertEqual(reference.artifact_type, "pubmed/evidence")
            self.assertEqual(reference.artifact_version, ARTIFACT_ENVELOPE_VERSION)
            self.assertEqual(reference.scope_version, 2)
            self.assertEqual(issues, [])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), source)

    def test_reference_rejects_declared_scope_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fetch.json"
            path.write_text(json.dumps({"operation": "fetch", "ok": True, "scope_version": 1}), encoding="utf-8")
            _, issues = reference_from_path("records", path, scope_version=2)
            self.assertEqual([issue.code for issue in issues], ["artifact.scope_version.mismatch"])

    def test_every_declared_script_operation_has_a_contract(self):
        root = Path(__file__).resolve().parents[1]
        operations = set()
        for path in (root / "scripts").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == "operation" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                        operations.add(value.value)
        unknown = sorted(operation for operation in operations if artifact_type_for_operation(operation) == "legacy/unknown")
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
