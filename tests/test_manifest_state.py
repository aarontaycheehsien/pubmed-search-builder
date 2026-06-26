"""Tests for the `state` subcommand family added in Phase 4.

The build-state block externalises stage/gate tracking into run_manifest.json so the agent
reads it from a file instead of reconstructing it from conversation prose each turn. These
tests confirm it is lazily created (init/add-only manifests are unchanged), mutated under the
existing lock, read without mutation, and that the final-handoff readiness check works.
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "manifest_tool.py"
SPEC = importlib.util.spec_from_file_location("manifest_tool", MODULE_PATH)
manifest_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifest_tool)


class ManifestStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.manifest = str(self.dir / "run_manifest.json")

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = manifest_tool.main(args)
        text = out.getvalue().strip()
        return rc, (json.loads(text) if text else None)

    def load(self):
        return json.loads(Path(self.manifest).read_text(encoding="utf-8"))

    def state(self, *args):
        return self.run_cli(["state", *args, "--manifest", self.manifest])

    # --- lazy creation / non-interference -------------------------------------------------

    def test_add_only_manifest_has_no_build_state(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "1"])
        self.assertNotIn("build_state", self.load())  # init/add path is byte-for-byte unchanged

    def test_state_command_auto_creates_manifest_with_build_state(self):
        rc, receipt = self.state("set-stage", "concept-gate")
        self.assertEqual(rc, 0)
        self.assertTrue(Path(self.manifest).exists())
        data = self.load()
        self.assertEqual(data["build_state"]["current_stage"], "concept-gate")
        self.assertEqual(data["build_state"]["gates"], {g: "pending" for g in manifest_tool.GATE_NAMES})
        # The full standard manifest scaffold is still present.
        for key in manifest_tool.TOP_LEVEL_KEYS:
            self.assertIn(key, data)

    # --- mutating actions -----------------------------------------------------------------

    def test_set_and_complete_stage(self):
        self.state("set-stage", "seed-intake")
        self.state("complete-stage", "question-intake")
        self.state("complete-stage", "question-intake")  # idempotent
        bs = self.load()["build_state"]
        self.assertEqual(bs["current_stage"], "seed-intake")
        self.assertEqual(bs["stages_completed"], ["question-intake"])

    def test_unknown_stage_rejected_without_writing(self):
        rc, _ = self.state("set-stage", "not-a-stage")
        self.assertEqual(rc, 1)
        self.assertFalse(Path(self.manifest).exists())

    def test_resolve_gate_and_unknown_gate_rejected(self):
        rc, _ = self.state("resolve-gate", "framework", "PECO")
        self.assertEqual(rc, 0)
        self.assertEqual(self.load()["build_state"]["gates"]["framework"], "PECO")

        rc, _ = self.state("resolve-gate", "nonsense", "x")
        self.assertEqual(rc, 1)

    def test_set_and_clear_question(self):
        self.state("set-question", "Promote outcome to an AND block?")
        self.assertEqual(self.load()["build_state"]["pending_user_question"], "Promote outcome to an AND block?")
        self.state("clear-question")
        self.assertEqual(self.load()["build_state"]["pending_user_question"], "")

    # --- read-only actions ----------------------------------------------------------------

    def test_show_is_read_only_and_reports_defaults(self):
        self.run_cli(["init", "--manifest", self.manifest, "--topic-slug", "demo"])
        before = Path(self.manifest).read_text(encoding="utf-8")
        rc, receipt = self.state("show")
        self.assertEqual(rc, 0)
        self.assertEqual(receipt["build_state"]["current_stage"], None)  # default reported in memory
        self.assertEqual(Path(self.manifest).read_text(encoding="utf-8"), before)  # not written to disk
        self.assertNotIn("build_state", self.load())

    def test_check_ready_blocks_then_passes(self):
        # Build started: concept gate pending -> not ready (exit 1).
        self.state("set-stage", "question-intake")
        rc, receipt = self.state("check-ready")
        self.assertEqual(rc, 1)
        self.assertFalse(receipt["ok"])
        self.assertTrue(any("concept gate" in issue for issue in receipt["issues"]))

        # Resolve the concept gate but leave a pending question -> still not ready.
        self.state("resolve-gate", "concept", "resolved")
        self.state("set-question", "keep zero-hit term?")
        rc, receipt = self.state("check-ready")
        self.assertEqual(rc, 1)
        self.assertTrue(any("unresolved user question" in issue for issue in receipt["issues"]))

        # Clear the question -> ready (exit 0).
        self.state("clear-question")
        rc, receipt = self.state("check-ready")
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["issues"], [])

    def test_banner_prints_canonical_full_stage_report_without_writing_manifest(self):
        rc, receipt = self.state("banner", "concept-gate")
        self.assertEqual(rc, 0)
        self.assertEqual(receipt["operation"], "state-banner")
        self.assertEqual(receipt["level"], "full")
        self.assertIn("references/framework-selection.md", receipt["references"])
        self.assertIn("Stage: Concept gate", receipt["text"])
        self.assertIn("User decision needed:", receipt["text"])
        self.assertFalse(Path(self.manifest).exists())

    def test_banner_can_emit_marker_or_override_decision_text(self):
        rc, marker = self.state("banner", "mesh-exploration", "--level", "marker")
        self.assertEqual(rc, 0)
        self.assertEqual(marker["level"], "marker")
        self.assertIn("References in force:", marker["text"])
        self.assertNotIn("Allowed now:", marker["text"])

        rc, full = self.state(
            "banner",
            "final-qa",
            "--level",
            "full",
            "--decision-needed",
            "Whether to keep intentional zero-hit future-proofing terms",
        )
        self.assertEqual(rc, 0)
        self.assertIn("intentional zero-hit", full["text"])

    # --- interop with existing validation -------------------------------------------------

    def test_show_validate_still_passes_with_build_state_present(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "5"])
        self.state("set-stage", "block-testing")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["issues"], [])

    # --- binding final-handoff gate (show --require-ready) --------------------------------

    def test_require_ready_blocks_until_concept_gate_resolved(self):
        self.state("set-stage", "block-testing")  # build_state present, concept gate still pending
        rc, receipt = self.run_cli(
            ["show", "--manifest", self.manifest, "--validate", "--check-files", "--require-ready"]
        )
        self.assertEqual(rc, 1)
        self.assertFalse(receipt["ok"])
        self.assertTrue(any("not ready for handoff" in i and "concept gate" in i for i in receipt["issues"]))

        self.state("resolve-gate", "concept", "resolved")
        rc, receipt = self.run_cli(
            ["show", "--manifest", self.manifest, "--validate", "--check-files", "--require-ready"]
        )
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["issues"], [])

    def test_require_ready_fails_when_state_never_tracked(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "1"])
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate", "--require-ready"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("build_state not initialized" in i for i in receipt["issues"]))

    def test_validate_without_require_ready_ignores_readiness(self):
        self.state("set-stage", "block-testing")  # concept gate pending
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 0)  # structural validation only; readiness not checked
        self.assertTrue(receipt["ok"])

    def test_ensure_build_state_backfills_partial_block(self):
        partial = manifest_tool.new_manifest("demo", "1.0.0")
        partial["build_state"] = {"current_stage": "validation"}  # missing gates/lists
        state = manifest_tool.ensure_build_state(partial)
        self.assertEqual(state["current_stage"], "validation")
        self.assertEqual(state["gates"], {g: "pending" for g in manifest_tool.GATE_NAMES})
        self.assertEqual(state["stages_completed"], [])


if __name__ == "__main__":
    unittest.main()
