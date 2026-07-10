import importlib.util
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


if __name__ == "__main__":
    unittest.main()
