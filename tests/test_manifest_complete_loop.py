import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("manifest_tool_complete", ROOT / "scripts" / "manifest_tool.py")
manifest_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifest_tool)


class ManifestCompleteLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "run_manifest.json"

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = manifest_tool.main(list(args))
        text = stdout.getvalue().strip()
        return code, json.loads(text) if text else None

    def state(self, *args):
        return self.cli("state", *args, "--manifest", str(self.manifest))

    def add(self, kind, command, *, output=None, inputs=(), count=None, block=""):
        args = ["add", "--manifest", str(self.manifest), "--kind", kind, "--command", command]
        if output:
            args += ["--output", str(output)]
        for path in inputs:
            args += ["--input", str(path)]
        if count is not None:
            args += ["--count", str(count)]
        if block:
            args += ["--block", block]
        return self.cli(*args)

    def passing_no_seed(self):
        self.cli("init", "--manifest", str(self.manifest), "--topic-slug", "demo")
        for gate, value in (("framework", "PICO"), ("seed", "none"), ("concept", "resolved"), ("filter", "none")):
            self.state("resolve-gate", gate, value)
        for stage in manifest_tool.REQUIRED_COMPLETION_STAGES:
            if stage in {"pre-mesh-brainstorm", "revision"}:
                self.state("complete-stage", stage, "--disposition", "not-applicable", "--reason", "not needed")
            else:
                self.state("complete-stage", stage)
        self.state("register-block", "population")
        self.add("mesh", "mesh_tool.py sweep --concept population", block="population")
        self.add("term-rank", "pubmed_tool.py term-rank", block="population")

        strategy = self.root / "strategy.txt"
        strategy.write_text('"Population"[Mesh]', encoding="utf-8")
        search = self.root / "search.json"
        search.write_text(json.dumps({"ok": True, "count": 10}), encoding="utf-8")
        self.add(
            "search",
            "pubmed_tool.py search --query-file strategy.txt --retmax 0",
            output=search,
            inputs=[strategy],
            count=10,
            block="population",
        )
        qa = self.root / "final_qa.json"
        qa.write_text(json.dumps({"ok": True, "errors": [], "warnings": []}), encoding="utf-8")
        self.add("qa", "hooks_tool.py final-qa --strategy-file strategy.txt", output=qa, inputs=[strategy])
        audit_json = self.root / "audit.json"
        audit_json.write_text(json.dumps({"final_strategy": strategy.read_text()}), encoding="utf-8")
        audit_md = self.root / "audit_demo.md"
        audit_md.write_text("# Audit\n", encoding="utf-8")
        self.add("artifact", "audit_markdown.py audit.json", output=audit_md, inputs=[audit_json])
        self.state("resolve-recall-offer", "declined")
        self.state("resolve-unvalidated-handoff", "accepted", "--reason", "No independent benchmark exists")
        return strategy

    def test_complete_no_seed_fixture_passes(self):
        self.passing_no_seed()
        code, receipt = self.state("check-complete")
        self.assertEqual(code, 0, receipt)
        self.assertEqual(receipt["issues"], [])

    def test_show_require_complete_loop_matches_state_gate(self):
        self.passing_no_seed()
        code, receipt = self.cli(
            "show", "--manifest", str(self.manifest), "--validate", "--check-files", "--require-complete-loop"
        )
        self.assertEqual(code, 0, receipt)

    def test_each_gate_is_binding(self):
        self.passing_no_seed()
        for gate in manifest_tool.GATE_NAMES:
            with self.subTest(gate=gate):
                data = json.loads(self.manifest.read_text(encoding="utf-8"))
                original = data["build_state"]["gates"][gate]
                data["build_state"]["gates"][gate] = "pending"
                self.manifest.write_text(json.dumps(data), encoding="utf-8")
                code, receipt = self.state("check-complete")
                self.assertEqual(code, 1)
                self.assertIn(f"gate is unresolved: {gate}", receipt["issues"])
                data["build_state"]["gates"][gate] = original
                self.manifest.write_text(json.dumps(data), encoding="utf-8")

    def test_strategy_hash_change_invalidates_qa_and_search(self):
        strategy = self.passing_no_seed()
        strategy.write_text('"Different"[Mesh]', encoding="utf-8")
        code, receipt = self.state("check-complete")
        self.assertEqual(code, 1)
        self.assertTrue(any("input artifact hash no longer matches" in item for item in receipt["issues"]))

    def test_completion_requirements_are_independently_binding(self):
        self.passing_no_seed()
        original = json.loads(self.manifest.read_text(encoding="utf-8"))

        def pending_question(data):
            data["build_state"]["pending_user_question"] = "Need a protocol decision"

        def open_design_decision(data):
            data["build_state"]["open_decisions"] = [{"decision": "outcome block"}]

        def missing_stage(data):
            data["build_state"]["stage_records"].pop("block-testing")
            data["build_state"]["stages_completed"].remove("block-testing")

        def missing_blocks(data):
            data["build_state"]["blocks"] = {}

        def missing_mesh(data):
            data["entries"] = [entry for entry in data["entries"] if entry["kind"] != "mesh"]

        def missing_text_words(data):
            data["entries"] = [entry for entry in data["entries"] if entry["kind"] != "term-rank"]

        def missing_count(data):
            data["entries"] = [entry for entry in data["entries"] if entry["kind"] != "search"]

        def recall_offer_pending(data):
            data["build_state"]["recall_offer"] = "pending"

        def unvalidated_not_accepted(data):
            data["build_state"]["unvalidated_handoff"] = {"status": "pending", "reason": ""}

        def missing_qa(data):
            data["entries"] = [entry for entry in data["entries"] if entry["kind"] != "qa"]

        def missing_audit(data):
            data["entries"] = [entry for entry in data["entries"] if entry["kind"] != "artifact"]

        cases = (
            ("pending question", pending_question, "question is still pending"),
            ("open design decision", open_design_decision, "unresolved decisions"),
            ("missing stage", missing_stage, "required stage is not recorded"),
            ("missing blocks", missing_blocks, "no essential blocks are registered"),
            ("missing mesh", missing_mesh, "mesh_sweep"),
            ("missing text words", missing_text_words, "text_word_evidence"),
            ("missing count", missing_count, "block_count"),
            ("recall offer", recall_offer_pending, "recall offer unresolved"),
            ("unvalidated acceptance", unvalidated_not_accepted, "explicit acceptance"),
            ("final QA", missing_qa, "no final-qa"),
            ("audit", missing_audit, "no final audit"),
        )
        for label, mutate, expected in cases:
            with self.subTest(label=label):
                data = json.loads(json.dumps(original))
                mutate(data)
                self.manifest.write_text(json.dumps(data), encoding="utf-8")
                code, receipt = self.state("check-complete")
                self.assertEqual(code, 1)
                self.assertTrue(any(expected in issue for issue in receipt["issues"]), receipt)
        self.manifest.write_text(json.dumps(original), encoding="utf-8")

    def test_audit_must_bind_a_json_input_after_final_qa(self):
        self.passing_no_seed()
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        audit = next(entry for entry in data["entries"] if entry["kind"] == "artifact")
        audit["input_sha256"] = {}
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        code, receipt = self.state("check-complete")
        self.assertEqual(code, 1)
        self.assertTrue(any("audit JSON" in issue for issue in receipt["issues"]))

        data = json.loads(json.dumps(data))
        audit = next(entry for entry in data["entries"] if entry["kind"] == "artifact")
        qa = next(entry for entry in data["entries"] if entry["kind"] == "qa")
        audit["input_sha256"] = {str(self.root / "audit.json"): manifest_tool.sha256_file(self.root / "audit.json")}
        audit["seq"], qa["seq"] = qa["seq"], audit["seq"]
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        code, receipt = self.state("check-complete")
        self.assertEqual(code, 1)
        self.assertIn("audit Markdown was not rendered after final QA", receipt["issues"])

    def test_seeded_build_requires_validation(self):
        self.passing_no_seed()
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["build_state"]["gates"]["seed"] = "provided"
        data["build_state"]["stage_records"]["limited-seed-evidence"] = {
            "status": "complete", "reason": "", "recorded_utc": manifest_tool.utc_now()
        }
        data["build_state"]["stages_completed"].append("limited-seed-evidence")
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        code, receipt = self.state("check-complete")
        self.assertEqual(code, 1)
        self.assertIn("seeded build lacks a known-item validation entry", receipt["issues"])

        validation = self.root / "validation.json"
        validation.write_text(json.dumps({"ok": True}), encoding="utf-8")
        self.add("validate", "pubmed_tool.py validate", output=validation)
        code, receipt = self.state("check-complete")
        self.assertEqual(code, 0, receipt)

    def test_successful_no_seed_recall_does_not_require_unvalidated_acceptance(self):
        self.passing_no_seed()
        self.state("resolve-recall-offer", "done")
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["build_state"]["unvalidated_handoff"] = {"status": "pending", "reason": ""}
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        recall = self.root / "recall.json"
        recall.write_text(json.dumps({"ok": True, "benchmark_size": 12}), encoding="utf-8")
        self.add("recall", "pubmed_tool.py recall --pilot-query-file strategy.txt", output=recall)
        code, receipt = self.state("check-complete")
        self.assertEqual(code, 0, receipt)

    def test_not_applicable_stage_requires_reason(self):
        self.cli("init", "--manifest", str(self.manifest))
        code, _ = self.state("complete-stage", "revision", "--disposition", "not-applicable")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
