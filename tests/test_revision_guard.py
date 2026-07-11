import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("revision_guard_test", ROOT / "scripts" / "revision_guard.py")
guard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(guard)


class RevisionGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.baseline = self.root / "baseline.txt"
        self.revised = self.root / "revised.txt"
        self.baseline.write_text("asthma[tiab]", encoding="utf-8")
        self.revised.write_text("asthma[tiab] OR wheez*[tiab]", encoding="utf-8")

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def payload(self):
        common = {"scope_version": 1, "protocol_sha256": "p1", "required_block_ids": ["condition"], "syntax_ok": True, "translation_drift_issues": []}
        return {
            "guard_version": 1,
            "revision_id": "R001",
            "revision_kind": "critic",
            "protocol_id": "demo",
            "named_defect": {"id": "F001", "description": "Missing wheeze synonym", "fixed": True, "evidence": ["differential.json"]},
            "baseline": {**common, "strategy_file": self.baseline.name, "strategy_sha256": self.digest(self.baseline), "heldout_retrieved_pmids": ["1", "2"], "result_count": 100},
            "revised": {**common, "strategy_file": self.revised.name, "strategy_sha256": self.digest(self.revised), "heldout_retrieved_pmids": ["1", "2"], "result_count": 125},
            "authorized_required_block_ids": [],
            "scope_change": {"changed": False, "authorized": False, "reason": ""},
            "experimental_variant": {"retain_if_failed": False, "variant_id": None, "label": None},
        }

    def test_passing_revision_is_adopted_with_workload_effect(self):
        result = guard.evaluate_payload(self.payload(), base=self.root)
        self.assertTrue(result["no_harm_passed"])
        self.assertEqual(result["disposition"], "adopt")
        self.assertEqual(result["workload_effect"]["absolute_change"], 25)
        self.assertEqual(result["authoritative_strategy_sha256"], self.digest(self.revised))
        self.assertEqual(Path(result["authoritative_strategy_file"]), self.revised.resolve())

    def test_heldout_loss_automatically_reverts_to_baseline(self):
        payload = self.payload()
        payload["revised"]["heldout_retrieved_pmids"] = ["1"]
        result = guard.evaluate_payload(payload, base=self.root)
        self.assertFalse(result["no_harm_passed"])
        self.assertIn("heldout-preserved", result["failed_checks"])
        self.assertEqual(result["disposition"], "revert-to-baseline")
        self.assertEqual(result["authoritative_strategy_sha256"], self.digest(self.baseline))

    def test_failed_revision_can_be_retained_only_as_labelled_experimental(self):
        payload = self.payload()
        payload["revised"]["translation_drift_issues"] = ["unrecognized field"]
        payload["experimental_variant"] = {"retain_if_failed": True, "variant_id": "exp-wheeze", "label": "Experimental wheeze expansion"}
        result = guard.evaluate_payload(payload, base=self.root)
        self.assertEqual(result["disposition"], "experimental-only")
        self.assertEqual(result["authoritative_strategy_sha256"], self.digest(self.baseline))
        self.assertEqual(result["experimental_variant"]["variant_id"], "exp-wheeze")

    def test_unjustified_block_and_silent_scope_change_fail(self):
        payload = self.payload()
        payload["revised"]["required_block_ids"] = ["condition", "outcome"]
        payload["revised"]["protocol_sha256"] = "silently-changed"
        result = guard.evaluate_payload(payload, base=self.root)
        self.assertIn("required-blocks-justified", result["failed_checks"])
        self.assertIn("scope-unchanged-or-explicit", result["failed_checks"])

    def test_cli_writes_selected_baseline_on_failure(self):
        payload = self.payload()
        payload["named_defect"]["fixed"] = False
        artifact = self.root / "input.json"
        output = self.root / "guard.json"
        selected = self.root / "selected.txt"
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(guard.main([str(artifact), "--output", str(output), "--selected-strategy-output", str(selected)]), 0)
        self.assertEqual(selected.read_text(encoding="utf-8"), self.baseline.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["disposition"], "revert-to-baseline")


if __name__ == "__main__":
    unittest.main()
