import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from pubmed_search_builder.core.io import sha256_file
from pubmed_search_builder.workflow.contracts import ArtifactReference
from pubmed_search_builder.workflow.events import append_event, artifact_event


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("workflow_tool_v2", ROOT / "scripts" / "workflow_tool.py")
workflow_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(workflow_tool)


class WorkflowV2Tests(unittest.TestCase):
    def run_cli(self, args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            code = workflow_tool.main(args)
        return code, json.loads(stream.getvalue())

    def test_migrate_v1_manifest_preserves_legacy_file_and_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "run_manifest.json"
            legacy_payload = {
                "manifest_version": "1.1",
                "skill": "pubmed-search-builder",
                "skill_version": "2.0.0",
                "topic_slug": "demo",
                "created_utc": "2026-01-01T00:00:00Z",
                "updated_utc": "2026-01-01T00:00:00Z",
                "working_dir": str(root),
                "entries": [{"seq": 1, "timestamp_utc": "2026-01-01T00:00:00Z", "kind": "search", "command": "legacy", "scope_version": 1}],
                "superseded": [{"path": "old-search.json", "superseded_by": "new-search.json", "seq": 1, "timestamp_utc": "2026-01-01T00:00:00Z"}],
                "build_state": {"gates": {"framework": "PICO"}, "pending_user_question": "Use a filter?"},
            }
            legacy.write_text(json.dumps(legacy_payload), encoding="utf-8")
            output = root / "run_manifest_v2.json"
            code, receipt = self.run_cli(["migrate", "--manifest", str(legacy), "--output", str(output)])
            self.assertEqual(code, 0, receipt)
            self.assertEqual(json.loads(legacy.read_text(encoding="utf-8")), legacy_payload)
            status_code, status = self.run_cli(["status", "--manifest", str(output)])
            self.assertEqual(status_code, 0, status)
            self.assertEqual(status["state"]["decisions"]["framework"]["value"], "PICO")
            self.assertEqual(status["state"]["decisions"]["pending-user-question"]["status"], "pending")
            migrated = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(any(item["event_type"] == "artifact-superseded" for item in migrated["events"]))
            self.assertFalse(status["handoff_ready"])
            self.assertTrue(any(item["code"] == "workflow.decision.pending" for item in status["completion_diagnostics"]))

    def test_stage_run_hash_binds_artifacts_and_status_derives_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "run_manifest_v2.json"
            protocol = root / "protocol.json"
            protocol.write_text("{}", encoding="utf-8")
            output = root / "scope.json"
            code, receipt = self.run_cli(["init", "--manifest", str(manifest), "--topic-slug", "demo"])
            self.assertEqual(code, 0, receipt)
            write = "import pathlib; pathlib.Path('scope.json').write_text('{\\\"operation\\\":\\\"protocol-compile\\\",\\\"ok\\\":true,\\\"scope_version\\\":1}')"
            code, receipt = self.run_cli([
                "run", "--manifest", str(manifest), "--stage", "scope-lock",
                "--input", "protocol=protocol.json", "--output", "scope=scope.json", "--scope-version", "1", "--cwd", str(root),
                "--", sys.executable, "-c", write,
            ])
            self.assertEqual(code, 0, receipt)
            self.assertEqual(receipt["event"]["outputs"][0]["artifact_type"], "protocol/receipt")
            code, receipt = self.run_cli(["status", "--manifest", str(manifest)])
            self.assertEqual(code, 0, receipt)
            self.assertEqual(receipt["state"]["scope_version"], 1)
            stage = next(item for item in receipt["stages"] if item["id"] == "scope-lock")
            self.assertEqual(stage["status"], "complete")
            self.assertFalse(receipt["handoff_ready"])
            self.assertTrue(any(item["code"] == "workflow.intake.question_pending" for item in receipt["completion_diagnostics"]))

    def test_stage_run_refuses_to_register_command_that_mutates_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "run_manifest_v2.json"
            input_path = root / "protocol.json"
            input_path.write_text("{}", encoding="utf-8")
            self.run_cli(["init", "--manifest", str(manifest)])
            code = "import pathlib; pathlib.Path('protocol.json').write_text('changed'); pathlib.Path('scope.json').write_text('{\\\"operation\\\":\\\"protocol-compile\\\",\\\"ok\\\":true}')"
            rc, receipt = self.run_cli([
                "run", "--manifest", str(manifest), "--stage", "scope-lock",
                "--input", "protocol=protocol.json", "--output", "scope=scope.json", "--cwd", str(root),
                "--", sys.executable, "-c", code,
            ])
            self.assertEqual(rc, 1)
            self.assertIn("modified declared input", receipt["error"])
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["events"], [])

    def test_status_rejects_non_append_only_event_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "run_manifest_v2.json"
            self.run_cli(["init", "--manifest", str(manifest)])
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["events"] = [{"seq": 2, "timestamp_utc": "x", "event_type": "decision-recorded", "decision_id": "x", "status": "resolved", "reason": "test"}]
            manifest.write_text(json.dumps(data), encoding="utf-8")
            code, receipt = self.run_cli(["status", "--manifest", str(manifest)])
            self.assertEqual(code, 1)
            self.assertIn("seq=1", receipt["error"])

    def test_new_scope_marks_prior_scope_artifacts_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "run_manifest_v2.json"
            protocol = root / "protocol.json"
            protocol.write_text("{}", encoding="utf-8")
            self.run_cli(["init", "--manifest", str(manifest)])

            def run_scope(name, version):
                code = f"import pathlib; pathlib.Path('{name}').write_text('{{\\\"operation\\\":\\\"protocol-compile\\\",\\\"ok\\\":true,\\\"scope_version\\\":{version}}}')"
                rc, receipt = self.run_cli([
                    "run", "--manifest", str(manifest), "--stage", "scope-lock", "--input", "protocol=protocol.json",
                    "--output", f"scope={name}", "--scope-version", str(version), "--cwd", str(root), "--", sys.executable, "-c", code,
                ])
                self.assertEqual(rc, 0, receipt)

            run_scope("scope_v1.json", 1)
            candidate_code = "import pathlib; pathlib.Path('candidates.json').write_text('{\\\"operation\\\":\\\"related\\\",\\\"ok\\\":true,\\\"scope_version\\\":1}')"
            rc, receipt = self.run_cli([
                "run", "--manifest", str(manifest), "--stage", "candidate-discovery", "--input", "scope=scope_v1.json",
                "--output", "candidates=candidates.json", "--scope-version", "1", "--cwd", str(root), "--", sys.executable, "-c", candidate_code,
            ])
            self.assertEqual(rc, 0, receipt)
            run_scope("scope_v2.json", 2)
            rc, receipt = self.run_cli(["status", "--manifest", str(manifest)])
            self.assertEqual(rc, 0, receipt)
            self.assertEqual(receipt["state"]["scope_version"], 2)
            self.assertGreaterEqual(receipt["state"]["stale_artifact_count"], 1)
            self.assertNotIn("candidates", receipt["state"]["artifacts"])

    def test_audit_stage_accepts_hash_bound_markdown_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "run_manifest_v2.json"
            qa = root / "qa.json"
            qa.write_text('{"operation":"hooks-pre_final_strategy_qa","ok":true,"scope_version":1}', encoding="utf-8")
            self.run_cli(["init", "--manifest", str(manifest)])
            command = "import pathlib; pathlib.Path('audit.md').write_text('# Audit')"
            code, receipt = self.run_cli([
                "run", "--manifest", str(manifest), "--stage", "audit-output", "--input", "qa=qa.json",
                "--output", "audit=audit.md", "--scope-version", "1", "--cwd", str(root), "--", sys.executable, "-c", command,
            ])
            self.assertEqual(code, 0, receipt)
            self.assertEqual(receipt["event"]["outputs"][0]["artifact_type"], "artifact/markdown")

    def test_strategy_revision_stales_transitive_downstream_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "run_manifest_v2.json"
            strategy = root / "strategy.txt"
            validation = root / "validation.json"
            strategy.write_text("first", encoding="utf-8")
            validation.write_text('{"operation":"recall","ok":true,"scope_version":1}', encoding="utf-8")
            self.run_cli(["init", "--manifest", str(manifest)])
            first_strategy = ArtifactReference("strategy", str(strategy), sha256_file(strategy), "artifact/file", 1, 1)
            validation_ref = ArtifactReference("validation", str(validation), sha256_file(validation), "pubmed/evidence", 2, 1)
            append_event(
                manifest,
                artifact_event(stage="validation", command=["test"], inputs=[first_strategy], outputs=[validation_ref], scope_version=1),
            )
            strategy.write_text("revised", encoding="utf-8")
            revised_strategy = ArtifactReference("strategy", str(strategy), sha256_file(strategy), "artifact/file", 1, 1)
            append_event(
                manifest,
                artifact_event(stage="revision", command=["test"], inputs=[], outputs=[revised_strategy], scope_version=1),
            )
            code, receipt = self.run_cli(["status", "--manifest", str(manifest)])
            self.assertEqual(code, 0, receipt)
            self.assertNotIn("validation", receipt["state"]["artifacts"])
            self.assertGreaterEqual(receipt["state"]["stale_artifact_count"], 1)

    def test_seeded_no_seed_and_review_targeted_runs_reach_offline_handoff(self):
        for no_seed in (False, True):
            for evidence_synthesis in (False, True):
                with self.subTest(no_seed=no_seed, evidence_synthesis=evidence_synthesis), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    manifest = root / "run_manifest_v2.json"
                    protocol = root / "protocol.json"
                    protocol_payload = {
                        "seeds": {"records": [] if no_seed else [{"pmid": "1"}]},
                        "searchable_scope": {"concepts": [{"role": "essential", "provisional_fragility": "stable"}]},
                    }
                    if evidence_synthesis:
                        protocol_payload["evidence_target"] = {
                            "mode": "evidence-syntheses", "eligible_types": ["systematic-review"],
                            "protocols": "exclude", "narrative_reviews": "screen", "methods_papers": "exclude",
                        }
                    protocol.write_text(json.dumps(protocol_payload), encoding="utf-8")
                    self.assertEqual(self.run_cli(["init", "--manifest", str(manifest)])[0], 0)
                    self.assertEqual(
                        self.run_cli([
                            "decision", "--manifest", str(manifest), "--id", "question", "--status", "resolved",
                            "--value", "Does X affect Y?", "--reason", "Independently supplied review question",
                        ])[0],
                        0,
                    )

                    def run(stage, inputs, outputs):
                        code_parts = ["import json,pathlib"]
                        for filename, payload in outputs.values():
                            serialized = json.dumps(payload)
                            code_parts.append(f"pathlib.Path({filename!r}).write_text({serialized!r})")
                        args = ["run", "--manifest", str(manifest), "--stage", stage, "--scope-version", "1", "--cwd", str(root)]
                        for role, filename in inputs.items():
                            args += ["--input", f"{role}={filename}"]
                        for role, (filename, _) in outputs.items():
                            args += ["--output", f"{role}={filename}"]
                        args += ["--", sys.executable, "-c", "; ".join(code_parts)]
                        rc, receipt = self.run_cli(args)
                        self.assertEqual(rc, 0, receipt)

                    run("scope-lock", {"protocol": "protocol.json"}, {"scope": ("scope.json", {"operation": "protocol-compile", "ok": True, "scope_version": 1})})
                    if evidence_synthesis:
                        run(
                            "review-discovery", {"scope": "scope.json"},
                            {
                                "review-profile": ("review_profile.json", {"operation": "review-retrieval-profile", "artifact_type": "review-retrieval/profile", "ok": True, "scope_version": 1, "profile_id": "p", "protocol_id": "demo", "eligible_types": ["systematic-review"], "branches": [{"branch_id": "systematic"}], "query": "systematic[sb]", "profile_sha256": "abc"}),
                                "review-candidates": ("review_candidates.json", {"operation": "review-discover", "artifact_type": "review-discovery/evidence", "ok": True, "scope_version": 1, "profile_sha256": "abc", "topic_query": "asthma", "records": []}),
                            },
                        )
                    discovery_outputs = {"candidates": ("candidates.json", {"operation": "related", "ok": True, "scope_version": 1})}
                    if no_seed:
                        discovery_outputs["pilot-saturation"] = ("pilot.json", {"operation": "orthogonal-pilot-adjudication", "ok": True, "scope_version": 1})
                    run("candidate-discovery", {"scope": "scope.json"}, discovery_outputs)
                    screening_outputs = {"candidate-ledger": ("ledger.json", {"operation": "candidate-ledger-validate", "ok": True, "scope_version": 1})}
                    if evidence_synthesis:
                        screening_outputs["review-classification"] = ("review_classification.json", {"operation": "review-classify", "artifact_type": "review-classification/evidence", "ok": True, "scope_version": 1, "profile_sha256": "abc", "records": [], "eligible_types": ["systematic-review"]})
                    run("candidate-screening", {"candidates": "candidates.json"}, screening_outputs)
                    run("objective-evidence", {"candidate-ledger": "ledger.json"}, {"evidence": ("evidence.json", {"operation": "fetch", "ok": True, "scope_version": 1})})
                    run("block-testing", {"evidence": "evidence.json"}, {"block-analysis": ("analysis.json", {"operation": "concept-ablation", "ok": True, "scope_version": 1})})
                    validation_outputs = {"validation": ("validation.json", {"operation": "recall", "ok": True, "scope_version": 1})}
                    if evidence_synthesis:
                        validation_outputs["review-filter-evaluation"] = ("review_evaluation.json", {"operation": "review-filter-evaluate", "artifact_type": "review-filter/evaluation", "ok": True, "scope_version": 1, "profile_sha256": "abc", "eligible_count": 0, "retrieved_count": 0})
                    run("validation", {"block-analysis": "analysis.json"}, validation_outputs)
                    run("critic-review", {"validation": "validation.json"}, {"critic": ("critic.json", {"operation": "critic-artifact-validate", "ok": True, "scope_version": 1})})
                    run("final-qa", {"critic": "critic.json"}, {"qa": ("qa.json", {"hook": "pre_final_strategy_qa", "ok": True, "scope_version": 1})})
                    run("audit-output", {"qa": "qa.json"}, {"audit": ("audit.md", "# Audit\n")})
                    run("peer-review-handoff", {"audit": "audit.md"}, {"handoff": ("handoff.md", "# Human PRESS handoff\n")})

                    code, receipt = self.run_cli(["status", "--manifest", str(manifest)])
                    self.assertEqual(code, 0, receipt)
                    self.assertTrue(receipt["handoff_ready"], receipt["completion_diagnostics"])


if __name__ == "__main__":
    unittest.main()
