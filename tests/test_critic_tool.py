import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("critic_tool", ROOT / "scripts" / "critic_tool.py")
critic_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(critic_tool)


DOMAINS = sorted(critic_tool.REQUIRED_DOMAINS)


def finding(*, severity="must-fix", status="open"):
    return {
        "press_element": "3. Subject headings",
        "severity": severity,
        "classification": "lexical",
        "affected_component": "condition block",
        "evidence": "mesh.json",
        "recommendation": "Inspect broader descriptor",
        "required_reprobe": "block count and holdout validation",
        "status": status,
    }


def v2_payload(bundle_name, *, findings=None, overall_status="pass"):
    return {
        "critic_version": 2,
        "round": 1,
        "scope_version": 1,
        "strategy_file": "strategy_v1.txt",
        "evidence_bundle": bundle_name,
        "reviewed_domains": DOMAINS,
        "domain_verdicts": [
            {"domain": domain, "status": "pass", "evidence_refs": ["strategy"]}
            for domain in DOMAINS
        ],
        "overall_status": overall_status,
        "findings": findings or [],
    }


class CriticToolTests(unittest.TestCase):
    def test_revise_requires_open_actionable_finding(self):
        data = {
            "round": 1,
            "scope_version": 1,
            "strategy_file": "strategy_v1.txt",
            "reviewed_domains": DOMAINS,
            "overall_status": "revise",
            "findings": [finding()],
        }
        issues, summary = critic_tool.validate_artifact(data)
        self.assertEqual(issues, [])
        self.assertEqual(summary["open_must_fix"], 1)

    def test_pass_rejects_open_actionable_findings(self):
        data = {
            "round": 1,
            "scope_version": 1,
            "strategy_file": "strategy_v1.txt",
            "reviewed_domains": DOMAINS,
            "overall_status": "pass",
            "findings": [finding(severity="should-fix")],
        }
        issues, _ = critic_tool.validate_artifact(data)
        self.assertTrue(any("overall_status pass is invalid" in issue for issue in issues))

    def test_pass_requires_all_review_domains(self):
        data = {
            "round": 1,
            "scope_version": 1,
            "strategy_file": "strategy_v1.txt",
            "reviewed_domains": ["syntax"],
            "overall_status": "pass",
            "findings": [],
        }
        issues, _ = critic_tool.validate_artifact(data)
        self.assertTrue(any("reviewed_domains is missing" in issue for issue in issues))

    def test_v2_bundle_and_domain_verdicts_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("randomized[tiab]", encoding="utf-8")
            bundle_path = root / "bundle.json"
            bundle = critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle_path)
            issues, summary = critic_tool.validate_artifact(v2_payload(bundle_path.name), evidence_bundle={**bundle, "roles": ["strategy"]})
            self.assertEqual(issues, [])
            self.assertEqual(summary["critic_version"], 2)

    def test_v2_bundle_detects_mutated_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("first", encoding="utf-8")
            bundle_path = root / "bundle.json"
            critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle_path)
            strategy.write_text("changed", encoding="utf-8")
            issues, _ = critic_tool.validate_evidence_bundle(bundle_path)
            self.assertTrue(any("hash does not match" in issue for issue in issues))

    def test_v2_requires_every_domain_verdict(self):
        data = v2_payload("bundle.json")
        data["domain_verdicts"] = data["domain_verdicts"][:-1]
        issues, _ = critic_tool.validate_artifact(data, evidence_bundle={"roles": ["strategy"]})
        self.assertTrue(any("domain_verdicts is missing" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
