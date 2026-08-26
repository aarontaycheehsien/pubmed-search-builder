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

    # --- no-seed recall offer (opt-in handoff gate for no-seed builds) ---------------------

    def test_recall_offer_defaults_pending(self):
        self.state("set-stage", "validation")
        self.assertEqual(self.load()["build_state"]["recall_offer"], "pending")

    def test_resolve_recall_offer_valid_values(self):
        for value in manifest_tool.RECALL_OFFER_VALUES:
            rc, _ = self.state("resolve-recall-offer", value)
            self.assertEqual(rc, 0)
            self.assertEqual(self.load()["build_state"]["recall_offer"], value)

    def test_resolve_recall_offer_rejects_unknown_value(self):
        rc, _ = self.state("resolve-recall-offer", "maybe")
        self.assertEqual(rc, 1)
        self.assertFalse(Path(self.manifest).exists())  # rejected before any write

    def test_require_recall_offer_blocks_then_passes(self):
        self.state("set-stage", "validation")  # recall_offer still pending
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-recall-offer"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("no-seed recall offer unresolved" in i for i in receipt["issues"]))

        self.state("resolve-recall-offer", "declined")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-recall-offer"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["issues"], [])

    def test_require_recall_offer_fails_when_state_never_tracked(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "1"])
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-recall-offer"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("build_state not initialized" in i for i in receipt["issues"]))

    def test_require_ready_ignores_pending_recall_offer(self):
        # The no-seed recall offer must stay separate from --require-ready: a resolved concept gate
        # with no pending question is handoff-ready even while recall_offer is still pending.
        self.state("resolve-gate", "concept", "resolved")
        rc, receipt = self.run_cli(
            ["show", "--manifest", self.manifest, "--validate", "--check-files", "--require-ready"]
        )
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(self.load()["build_state"]["recall_offer"], "pending")

    def test_ensure_build_state_backfills_recall_offer(self):
        legacy = manifest_tool.new_manifest("demo", "1.0.0")
        legacy["build_state"] = {"current_stage": "validation"}  # pre-recall_offer manifest
        state = manifest_tool.ensure_build_state(legacy)
        self.assertEqual(state["recall_offer"], "pending")

    # --- no-seed auto-detection + reminder (Task 8a) --------------------------------------

    def test_no_seed_gate_triggers_recall_offer_reminder(self):
        self.state("resolve-gate", "seed", "none")
        _, receipt = self.state("show")
        self.assertIn("reminders", receipt)
        self.assertTrue(any("--require-recall-offer" in r for r in receipt["reminders"]))

    def test_reminder_clears_after_resolving_offer(self):
        self.state("resolve-gate", "seed", "none")
        self.state("resolve-recall-offer", "declined")
        _, receipt = self.state("show")
        self.assertNotIn("reminders", receipt)

    def test_seeded_gate_has_no_recall_reminder(self):
        self.state("resolve-gate", "seed", "provided")
        _, receipt = self.state("show")
        self.assertNotIn("reminders", receipt)

    def test_no_seed_synonyms_are_detected(self):
        for value in ["none", "no", "no-seeds", "No-Seed"]:
            state = {"gates": {"seed": value}, "recall_offer": "pending"}
            self.assertTrue(manifest_tool.seed_gate_is_no_seed(state), value)
        self.assertFalse(manifest_tool.seed_gate_is_no_seed({"gates": {"seed": "provided"}}))

    def test_show_command_surfaces_reminder(self):
        self.state("resolve-gate", "seed", "none")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest])
        self.assertEqual(rc, 0)
        self.assertIn("reminders", receipt)


class RunStatusTests(ManifestStateTests):
    """Why a run is idle, and when that excuses ending a turn on an incomplete build.

    The Stop gate is hard on `active`; these tests pin the only ways past it. A pause has to name a
    decision that is genuinely outstanding *and* have been raised for the current exchange, so
    neither a plausible-sounding label nor a pause left over from an earlier turn is enough.
    """

    def run_status(self):
        return self.load()["build_state"]["run_status"]

    def test_default_run_status_is_active(self):
        self.state("set-stage", "intake")
        self.assertEqual(self.run_status()["status"], "active")

    def test_backfilled_into_a_manifest_written_before_the_field_existed(self):
        self.run_cli(["init", "--manifest", self.manifest, "--topic-slug", "legacy"])
        data = self.load()
        data["build_state"] = {"current_stage": "revision", "gates": {"concept": "resolved"}}
        Path(self.manifest).write_text(json.dumps(data), encoding="utf-8")
        _, receipt = self.state("show")
        self.assertEqual(receipt["build_state"]["run_status"]["status"], "active")

    def test_pause_requires_a_type_that_matches_build_state(self):
        self.state("set-stage", "intake")
        self.state("resolve-gate", "seed", "pending")
        rc, _ = self.state("set-run-status", "awaiting-user", "--type", "seed-intake", "--reason", "need seeds")
        self.assertEqual(rc, 0)
        self.assertEqual(self.run_status()["type"], "seed-intake")

        # Same label, but the gate it claims to be waiting on is now resolved.
        self.state("resolve-gate", "seed", "none")
        rc, _ = self.state("set-run-status", "awaiting-user", "--type", "seed-intake", "--reason", "need seeds")
        self.assertEqual(rc, 1)

    def test_every_pause_type_is_refused_when_its_condition_is_absent(self):
        # A fully-resolved build has no outstanding decision, so only the unconditional
        # user-requested pause may be recorded.
        self.state("set-stage", "audit-output")
        for gate in manifest_tool.GATE_NAMES:
            self.state("resolve-gate", gate, "resolved")
        self.state("resolve-recall-offer", "declined")
        self.state("resolve-unvalidated-handoff", "accepted", "--reason", "user accepted")
        for pause_type in sorted(manifest_tool.PAUSE_TYPE_CONDITIONS):
            with self.subTest(pause_type=pause_type):
                rc, _ = self.state("set-run-status", "awaiting-user", "--type", pause_type, "--reason", "x")
                self.assertEqual(rc, 0 if pause_type == "user-requested" else 1)

    def test_a_fresh_build_only_admits_intake_pauses(self):
        """The stage half of each condition is load-bearing.

        `recall_offer`, `unvalidated_handoff`, and every gate start out unresolved, so a
        condition that checked the field alone would be satisfied by any brand-new manifest and
        the pause type would be a label rather than a claim about where the build is.
        """

        self.state("set-stage", "intake")
        admitted = set()
        for pause_type in sorted(manifest_tool.PAUSE_TYPE_CONDITIONS):
            rc, _ = self.state("set-run-status", "awaiting-user", "--type", pause_type, "--reason", "x")
            if rc == 0:
                admitted.add(pause_type)
        self.assertEqual(
            admitted,
            {"seed-intake", "framework-decision", "scope-clarification", "concept-gate", "user-requested"},
        )

    def test_late_stage_pauses_need_their_stage_as_well_as_their_field(self):
        # A no-seed build with both decisions outstanding, but parked at block-testing.
        self.state("set-stage", "block-testing")
        self.state("resolve-gate", "seed", "none")
        for pause_type in ("recall-offer", "thin-evidence-decision"):
            with self.subTest(pause_type=pause_type, stage="block-testing"):
                self.assertEqual(self.state("set-run-status", "awaiting-user", "--type", pause_type, "--reason", "x")[0], 1)
        self.state("set-stage", "validation")
        for pause_type in ("recall-offer", "thin-evidence-decision"):
            with self.subTest(pause_type=pause_type, stage="validation"):
                self.assertEqual(self.state("set-run-status", "awaiting-user", "--type", pause_type, "--reason", "x")[0], 0)

    def test_no_seed_pauses_are_refused_on_a_seeded_build(self):
        self.state("set-stage", "validation")
        self.state("resolve-gate", "seed", "provided")
        for pause_type in ("recall-offer", "thin-evidence-decision"):
            with self.subTest(pause_type=pause_type):
                self.assertEqual(self.state("set-run-status", "awaiting-user", "--type", pause_type, "--reason", "x")[0], 1)

    def test_unknown_type_and_missing_reason_are_refused(self):
        self.state("set-stage", "intake")
        self.assertEqual(self.state("set-run-status", "awaiting-user", "--type", "invented", "--reason", "x")[0], 1)
        self.assertEqual(self.state("set-run-status", "awaiting-user", "--reason", "x")[0], 1)
        self.assertEqual(self.state("set-run-status", "checkpoint")[0], 1)
        self.assertEqual(self.state("set-run-status", "blocked-external")[0], 1)
        # --type is meaningless outside a pause and must not be silently accepted.
        self.assertEqual(self.state("set-run-status", "checkpoint", "--type", "seed-intake", "--reason", "x")[0], 1)

    def test_check_stop_prefers_a_fresh_status_over_the_complete_loop_gate(self):
        self.state("set-stage", "block-testing")
        self.state("set-run-status", "checkpoint", "--reason", "reporting progress")
        rc, receipt = self.state("check-stop", "--since", "2000-01-01T00:00:00Z")
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["allow_stop"])
        self.assertEqual(receipt["basis"], "run-status")
        self.assertEqual(receipt["issues"], [])

    def test_check_stop_ignores_a_status_older_than_the_users_last_turn(self):
        self.state("set-stage", "block-testing")
        self.state("set-run-status", "checkpoint", "--reason", "reporting progress")
        rc, receipt = self.state("check-stop", "--since", "2099-01-01T00:00:00Z")
        self.assertEqual(rc, 1)
        self.assertFalse(receipt["allow_stop"])
        self.assertEqual(receipt["basis"], "complete-loop")
        self.assertIn("stale", receipt["reason"])

    def test_active_and_complete_never_excuse_an_incomplete_stop(self):
        self.state("set-stage", "final-qa")
        for status in ("active", "complete"):
            with self.subTest(status=status):
                self.state("set-run-status", status)
                _, receipt = self.state("check-stop")
                self.assertFalse(receipt["allow_stop"])
                self.assertEqual(receipt["basis"], "complete-loop")

    def test_check_stop_reports_structural_damage_as_well_as_gate_gaps(self):
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "1"]
        )
        self.state("set-stage", "final-qa")
        data = self.load()
        del data["working_dir"]
        Path(self.manifest).write_text(json.dumps(data), encoding="utf-8")
        _, receipt = self.state("check-stop")
        self.assertFalse(receipt["allow_stop"])
        self.assertTrue(any(issue.startswith("structural:") for issue in receipt["issues"]))

    def test_every_status_change_is_appended_to_history(self):
        self.state("set-stage", "block-testing")
        self.state("set-run-status", "checkpoint", "--reason", "first report")
        self.state("set-run-status", "active")
        self.state("set-run-status", "checkpoint", "--reason", "second report")
        history = self.load()["build_state"]["run_status_history"]
        self.assertEqual([item["status"] for item in history], ["checkpoint", "active", "checkpoint"])
        self.assertEqual(history[0]["reason"], "first report")
        self.assertEqual(history[0]["stage"], "block-testing")
        _, receipt = self.state("check-stop")
        self.assertEqual(receipt["idle_events"], 3)

    def test_history_is_bounded(self):
        self.state("set-stage", "block-testing")
        limit = manifest_tool.RUN_STATUS_HISTORY_LIMIT
        data = None
        for index in range(limit + 5):
            self.state("set-run-status", "checkpoint", "--reason", f"report {index}")
        data = self.load()["build_state"]["run_status_history"]
        self.assertEqual(len(data), limit)
        # Truncation drops the oldest, so the most recent idle events are the ones retained.
        self.assertEqual(data[-1]["reason"], f"report {limit + 4}")

    def test_report_surfaces_run_status(self):
        self.state("set-stage", "revision")
        self.state("set-run-status", "blocked-external", "--reason", "E-utilities 503")
        _, receipt = self.run_cli(["report", "--manifest", self.manifest])
        self.assertEqual(receipt["run_status"]["status"], "blocked-external")
        self.assertEqual(len(receipt["run_status_history"]), 1)

    def test_check_stop_is_read_only(self):
        self.state("set-stage", "final-qa")
        before = Path(self.manifest).read_text(encoding="utf-8")
        self.state("check-stop")
        self.assertEqual(Path(self.manifest).read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
