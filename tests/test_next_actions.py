"""Gate issues become an ordered, actionable to-do list."""

import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("next_actions_test", ROOT / "scripts" / "next_actions.py")
next_actions = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(next_actions)

MANIFEST_SPEC = importlib.util.spec_from_file_location("manifest_tool_next_actions", ROOT / "scripts" / "manifest_tool.py")
manifest_tool = importlib.util.module_from_spec(MANIFEST_SPEC)
assert MANIFEST_SPEC.loader is not None
MANIFEST_SPEC.loader.exec_module(manifest_tool)


def gate_message_templates():
    """Literal issue messages in manifest_tool.py, with interpolations replaced by a placeholder."""

    source = (ROOT / "scripts" / "manifest_tool.py").read_text(encoding="utf-8")
    raw = re.findall(r'(?:issues\.append|return \[)\(?\s*f?("[^"]*"|\'[^\']*\')', source)
    templates = {re.sub(r"\{[^}]*\}", "X", item[1:-1]) for item in raw}
    # Messages led by a label placeholder are classified by their runtime label (covered below),
    # and pause-type messages come from set-run-status argument checks, not the completion gate.
    return sorted(
        text for text in templates
        if not text.startswith("X") and not text.startswith("latest X") and "pause type" not in text
    )


class ClassificationTests(unittest.TestCase):
    def test_every_gate_message_routes_to_a_workflow_stage(self):
        unrouted = [text for text in gate_message_templates() if next_actions.classify_issue(text) == "other"]
        self.assertEqual(unrouted, [], "add a pattern in next_actions.STAGES for these gate messages")

    def test_label_led_messages_route_by_their_runtime_labels(self):
        cases = {
            "candidate ledger artifact is not recorded": "candidate-screening",
            "candidate-ledger validation artifact does not exist: x.json": "candidate-screening",
            "latest critic artifact is not recorded": "critic",
            "latest critic validation artifact does not exist: v.json": "critic",
        }
        for issue, stage in cases.items():
            with self.subTest(issue=issue):
                self.assertEqual(next_actions.classify_issue(issue), stage)

    def test_specific_stages_win_over_broad_keywords(self):
        cases = {
            "critic round 2 required revision but no revision cycle is recorded": "revision",
            "final audit does not disclose waived checks: vocabulary-learning": "audit",
            "final QA was not rerun after the latest critic round": "final-qa",
            "required validation was not rerun after the latest revision cycle": "validation",
            "complete-loop gap: no PRESS-informed critic round is recorded": "critic",
        }
        for issue, stage in cases.items():
            with self.subTest(issue=issue):
                self.assertEqual(next_actions.classify_issue(issue), stage)


class PlanTests(unittest.TestCase):
    def test_actions_follow_build_order_with_commands_and_references(self):
        plan = next_actions.plan_next_actions(
            [
                "no final audit Markdown artifact is recorded",
                "no PRESS-informed critic round is recorded",
                "candidate screening is not complete or explicitly not applicable",
                "complete-loop gap: concept gate is not resolved",
            ]
        )
        self.assertEqual([item["stage"] for item in plan], ["intake", "candidate-screening", "critic", "audit"])
        self.assertEqual([item["order"] for item in plan], [1, 2, 3, 4])
        self.assertEqual(plan[0]["issues"], ["concept gate is not resolved"])
        for item in plan:
            self.assertTrue(item["action"])
            self.assertTrue(item["commands"])
            self.assertTrue(item["reference"].startswith("references/"))

    def test_unknown_issues_are_kept_rather_than_dropped(self):
        plan = next_actions.plan_next_actions(["something new the gate learned to say"])
        self.assertEqual(plan[-1]["stage"], "other")
        self.assertEqual(plan[-1]["issues"], ["something new the gate learned to say"])

    def test_no_issues_means_no_actions(self):
        self.assertEqual(next_actions.plan_next_actions([]), [])


class ManifestIntegrationTests(unittest.TestCase):
    def run_cli(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = manifest_tool.main(args)
        return rc, json.loads(out.getvalue())

    def test_report_and_check_complete_lead_with_the_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "run_manifest.json"
            self.run_cli(["init", "--manifest", str(manifest), "--topic-slug", "demo", "--allow-skill-root"])
            _rc, report = self.run_cli(["report", "--manifest", str(manifest)])
            self.assertFalse(report["handoff_ready"])
            self.assertTrue(report["next_actions"])
            self.assertEqual(report["next_actions"][0]["order"], 1)
            flattened = [issue for item in report["next_actions"] for issue in item["issues"]]
            self.assertEqual(sorted(flattened), sorted(report["complete_loop_issues"]))
            rc, check = self.run_cli(["state", "check-complete", "--manifest", str(manifest)])
            self.assertEqual(rc, 1)
            self.assertEqual(check["next_actions"][0]["stage"], report["next_actions"][0]["stage"])


if __name__ == "__main__":
    unittest.main()
