import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


manifest_tool = load_module("manifest_tool_complete", "manifest_tool.py")
critic_tool = load_module("critic_tool_complete", "critic_tool.py")
revision_guard = load_module("revision_guard_complete", "revision_guard.py")


class ManifestCompleteLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.manifest = self.dir / "run_manifest.json"
        self.run_cli(["init", "--manifest", str(self.manifest), "--topic-slug", "demo"])

    def run_cli(self, args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            rc = manifest_tool.main(args)
        text = stream.getvalue().strip().splitlines()
        payload = json.loads("\n".join(text)) if text else {}
        return rc, payload

    def state(self, action, *args):
        return self.run_cli(["state", action, "--manifest", str(self.manifest), *map(str, args)])

    def add(self, kind, command, *, output=None, count=None, label=None, block=None, inputs=None, scope_version=None):
        args = ["add", "--manifest", str(self.manifest), "--kind", kind, "--command", command]
        if output is not None:
            args += ["--output", str(output)]
        if count is not None:
            args += ["--count", str(count)]
        if label is not None:
            args += ["--label", label]
        if block is not None:
            args += ["--block", block]
        if scope_version is not None:
            args += ["--scope-version", str(scope_version)]
        for input_path in inputs or []:
            args += ["--input", str(input_path)]
        return self.run_cli(args)

    def write_json(self, name, payload):
        path = self.dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def critic_receipt(self, name, payload):
        strategy = self.dir / str(payload["strategy_file"])
        strategy.parent.mkdir(parents=True, exist_ok=True)
        if not strategy.exists():
            strategy.write_text("randomized[tiab]", encoding="utf-8")
        bundle = self.dir / name.replace(".json", "_evidence.json")
        critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle)
        payload = dict(payload)
        payload["critic_version"] = 2
        payload["evidence_bundle"] = bundle.name
        payload["domain_verdicts"] = [
            {
                "domain": domain,
                "status": "finding" if payload.get("overall_status") == "revise" and domain == "text-words" else "pass",
                "evidence_refs": ["strategy"],
            }
            for domain in sorted(critic_tool.REQUIRED_DOMAINS)
        ]
        upgraded = []
        for index, item in enumerate(payload.get("findings", []), start=1):
            item = dict(item)
            item.setdefault("finding_id", f"F{index:03d}")
            item.setdefault("evidence_refs", ["strategy"])
            upgraded.append(item)
        payload["findings"] = upgraded
        artifact = self.write_json(name, payload)
        receipt = self.dir / name.replace(".json", "_validation.json")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = critic_tool.main([str(artifact), "--output", str(receipt)])
        self.assertEqual(rc, 0)
        return artifact, receipt

    def resolve_base_gates_and_scope(self):
        self.state("resolve-gate", "framework", "PICO")
        self.state("resolve-gate", "seed", "none")
        self.state("resolve-gate", "filter", "none")
        scope = self.write_json(
            "retrieval_scope_v1.json",
            {
                "scope_version": 1,
                "review_question": "Does intervention X affect condition Y?",
                "framework": "PICO",
                "essential_blocks": ["condition"],
                "within_block_terms": [],
                "screening_only": ["outcome"],
                "optional_concepts": [],
                "filters": [],
                "unresolved_ambiguities": [],
            },
        )
        rc, _ = self.state("lock-scope", "--scope-file", scope)
        self.assertEqual(rc, 0)
        self.state("resolve-candidate-screening", "not-applicable", "--reason", "No candidate records found")
        self.state("resolve-recall-offer", "declined")
        orthogonal = self.write_json(
            "orthogonal_pilot_state.json",
            {
                "operation": "orthogonal-pilot-adjudication",
                "ok": True,
                "scope_version": 1,
                "provenance_blinded": True,
                "pilot_types": [
                    "mesh-led",
                    "exact-phrase-led",
                    "operational-description-led",
                    "prior-review-led",
                    "citation-registry-led",
                    "historical-terminology-led",
                ],
                "safety_cap_reached_any": False,
                "saturation_reached": True,
                "required_saturated_rounds": 2,
                "consecutive_saturated_rounds": 2,
                "new_included_pmids": [],
                "new_vocabulary_term_count": 0,
                "stopping_rule": "Two consecutive rounds added no relevant studies or vocabulary.",
                "ledger_frozen": False,
                "stop_reason": "No included candidates after saturated orthogonal discovery",
            },
        )
        self.add("artifact", "python scripts/no_seed_discovery.py adjudicate", output=orthogonal)
        self.state("register-block", "condition")
        mesh_output = self.write_json("mesh.json", {"operation": "sweep", "status": "complete", "ok": True})
        condition_query = self.dir / "condition.txt"
        condition_query.write_text("condition[tiab]", encoding="utf-8")
        condition_count = self.write_json("condition_count.json", {"operation": "search", "ok": True, "count": 2000})
        self.add("mesh", "python scripts/mesh_tool.py sweep --concept condition --output mesh.json", output=mesh_output, block="condition", scope_version=1)
        self.add("search", "python scripts/pubmed_tool.py search --query-file condition.txt --retmax 0", output=condition_count, inputs=[condition_query], count=2000, block="condition", scope_version=1)
        self.state("waive-requirement", "condition", "bramer_gap", "Stable concept with explained layer coverage")

    def test_complete_gate_requires_revision_between_revise_and_pass_rounds(self):
        self.resolve_base_gates_and_scope()
        domains = sorted(critic_tool.REQUIRED_DOMAINS)
        revise, revise_receipt = self.critic_receipt(
            "critic_round_1.json",
            {
                "round": 1,
                "scope_version": 1,
                "strategy_file": "strategy_v1.txt",
                "reviewed_domains": domains,
                "overall_status": "revise",
                "findings": [
                    {
                        "press_element": "4. Text-word search",
                        "severity": "must-fix",
                        "classification": "lexical",
                        "affected_component": "condition",
                        "evidence": "sample.json",
                        "recommendation": "Add historical synonym",
                        "required_reprobe": "block count",
                        "status": "open",
                    }
                ],
            },
        )
        self.state("record-critic", "--critic-file", revise, "--validation-file", revise_receipt)
        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertTrue(any("latest critic round has not passed" in issue for issue in receipt["issues"]))

        strategy_v1 = self.dir / "strategy_v1.txt"
        strategy_v2 = self.dir / "strategy_v2.txt"
        strategy_v2.write_text("randomized[tiab] OR alternate[tiab]", encoding="utf-8")
        guard_input = {
            "guard_version": 1,
            "revision_id": "R001",
            "revision_kind": "critic",
            "protocol_id": None,
            "named_defect": {"id": "F001", "description": "Missing historical synonym", "fixed": True, "evidence": ["sample.json"]},
            "baseline": {"strategy_file": strategy_v1.name, "strategy_sha256": revision_guard.sha256_file(strategy_v1), "heldout_retrieved_pmids": [], "required_block_ids": ["condition"], "syntax_ok": True, "translation_drift_issues": [], "scope_version": 1, "protocol_sha256": None, "result_count": 100},
            "revised": {"strategy_file": strategy_v2.name, "strategy_sha256": revision_guard.sha256_file(strategy_v2), "heldout_retrieved_pmids": [], "required_block_ids": ["condition"], "syntax_ok": True, "translation_drift_issues": [], "scope_version": 1, "protocol_sha256": None, "result_count": 110},
            "authorized_required_block_ids": [],
            "scope_change": {"changed": False, "authorized": False, "reason": ""},
            "experimental_variant": {"retain_if_failed": False, "variant_id": None, "label": None},
        }
        guard_result = revision_guard.evaluate_payload(guard_input, base=self.dir)
        guard_file = self.write_json("revision_no_harm_1.json", guard_result)
        revision = self.write_json(
            "revision_cycle_1.json",
            {
                "revision_round": 1,
                "critic_round": 1,
                "scope_version": 1,
                "trigger_finding": "F001",
                "classification": "lexical",
                "change": "Added legacy condition term",
                "evidence_files": ["sample.json"],
                "required_reprobe": ["condition block count"],
                "strategy_file": "strategy_v2.txt",
                "disposition": "accepted",
                "no_harm_file": guard_file.name,
            },
        )
        self.state("record-revision", "--revision-file", revision)
        passed, passed_receipt = self.critic_receipt(
            "critic_round_2.json",
            {
                "round": 2,
                "scope_version": 1,
                "strategy_file": "strategy_v2.txt",
                "reviewed_domains": domains,
                "overall_status": "pass",
                "findings": [
                    {
                        "finding_id": "F001",
                        "press_element": "4. Text-word search",
                        "severity": "must-fix",
                        "classification": "lexical",
                        "affected_component": "condition",
                        "evidence": "sample.json",
                        "evidence_refs": ["strategy"],
                        "recommendation": "Add historical synonym",
                        "required_reprobe": "block count",
                        "status": "resolved",
                    }
                ],
            },
        )
        self.state("record-critic", "--critic-file", passed, "--validation-file", passed_receipt)

        final_search = self.write_json("final_search.json", {"count": 1000})
        self.add(
            "search",
            "python scripts/pubmed_tool.py search --query-file strategy_v2.txt --retmax 0 --output final_search.json",
            output=final_search,
            count=1000,
            label="final topic-only strategy",
            inputs=[strategy_v2],
            scope_version=1,
        )
        final_qa = self.write_json("final_qa.json", {
            "hook": "pre_final_strategy_qa", "ok": True,
            "unresolved_warning_codes": [],
            "strategy_sha256": manifest_tool.sha256_file(strategy_v2),
        })
        self.add("qa", "python scripts/hooks_tool.py final-qa --strategy-file strategy_v2.txt", output=final_qa, inputs=[strategy_v2], scope_version=1)
        audit_json = self.write_json("audit.json", {
            "final_strategy": strategy_v2.read_text(encoding="utf-8").strip(),
            "result_count": 1000,
            "date_searched": "2026-07-13",
            "reporting_notes": {
                "limits_filters_validated_filters_used": "none",
                "restrictions_and_justifications": "none",
                "remaining_caveats": "not peer reviewed",
            },
        })
        audit = self.dir / "audit_demo.md"
        audit.write_text("# Audit\n\n## Final PubMed strategy\n\n## Reporting notes\n\n## PRISMA-S appendix\n", encoding="utf-8")
        self.add("artifact", "python scripts/audit_markdown.py audit.json --output audit_demo.md", output=audit, inputs=[audit_json], scope_version=1)

        rc, receipt = self.run_cli(
            [
                "show",
                "--manifest",
                str(self.manifest),
                "--validate",
                "--check-files",
                "--require-complete-loop",
            ]
        )
        self.assertEqual(rc, 0, receipt.get("issues"))
        self.assertTrue(receipt["ok"])

    def test_reopen_scope_clears_stale_candidate_and_block_state(self):
        self.resolve_base_gates_and_scope()
        rc, _ = self.state("reopen-scope", "--reason", "Critic found a structural block error")
        self.assertEqual(rc, 0)
        state = json.loads(self.manifest.read_text(encoding="utf-8"))["build_state"]
        self.assertEqual(state["scope"]["status"], "reopened")
        self.assertEqual(state["gates"]["concept"], "pending")
        self.assertEqual(state["blocks"], {})
        self.assertEqual(state["candidate_screening"]["status"], "pending")

    def test_complete_gate_requires_concept_ablation_for_multiple_and_blocks(self):
        self.resolve_base_gates_and_scope()
        self.state("register-block", "intervention")
        self.add("mesh", "python scripts/mesh_tool.py sweep --concept intervention", block="intervention")
        self.add("search", "python scripts/pubmed_tool.py search intervention", count=100, block="intervention")
        self.state("waive-requirement", "intervention", "bramer_gap", "Stable concept")
        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertIn("no concept-ablation artifact covers the proposed AND blocks", receipt["issues"])

    def test_complete_gate_requires_two_strand_for_explicit_fragile_scope(self):
        self.resolve_base_gates_and_scope()
        scope_path = self.dir / "retrieval_scope_v1.json"
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        scope["fragile_topic"] = True
        scope_path.write_text(json.dumps(scope), encoding="utf-8")
        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertIn("fragile retrieval scope requires a two-strand deliverable", receipt["issues"])

    def test_complete_gate_requires_orthogonal_pilot_saturation_on_no_seed_build(self):
        self.resolve_base_gates_and_scope()
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["entries"] = [
            entry for entry in manifest["entries"]
            if not str(entry.get("output_path") or "").endswith("orthogonal_pilot_state.json")
        ]
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertIn("no-seed build lacks orthogonal-pilot saturation evidence", receipt["issues"])

    def test_final_audit_must_disclose_each_current_reduced_mesh_artifact(self):
        reduced = {
            "operation": "sweep",
            "status": "complete",
            "reduced_fidelity_present": True,
            "methods": ["eutils_batch_esearch_esummary"],
        }
        data = manifest_tool.new_manifest("demo", "1.0")
        data["entries"] = [
            {
                "seq": 1,
                "kind": "mesh",
                "returncode": 0,
                "output_path": "mesh_condition.json",
                "output_sha256": "mesh-sha",
                "scope_version": 2,
                "mesh_evidence": reduced,
            }
        ]
        data["build_state"] = {"scope": {"version": 2}}

        missing = manifest_tool.mesh_audit_disclosure_issues(data, self.manifest, {"final_strategy": "x"})
        self.assertTrue(any("lacks mesh_backend_evidence" in issue for issue in missing))

        disclosed = {
            "mesh_backend_evidence": {
                "artifacts": [
                    {
                        "artifact": "mesh_condition.json",
                        "artifact_sha256": "mesh-sha",
                        "evidence": reduced,
                    }
                ],
                "automatic_peer_review_attention_points": [
                    "Confirm mesh_condition.json against MeSH RDF before finalizing the strategy."
                ],
            }
        }
        self.assertEqual(manifest_tool.mesh_audit_disclosure_issues(data, self.manifest, disclosed), [])

        disclosed["mesh_backend_evidence"]["artifacts"][0]["evidence"] = {
            "operation": "sweep", "status": "complete", "reduced_fidelity_present": True, "methods": ["wrong-method"]
        }
        mismatch = manifest_tool.mesh_audit_disclosure_issues(data, self.manifest, disclosed)
        self.assertTrue(any("does not disclose" in issue for issue in mismatch))

    def test_superseded_or_old_scope_reduced_mesh_does_not_block_final_audit(self):
        reduced = {"operation": "sweep", "status": "complete", "reduced_fidelity_present": True}
        data = manifest_tool.new_manifest("demo", "1.0")
        data["entries"] = [
            {
                "seq": 1,
                "kind": "mesh",
                "returncode": 0,
                "output_path": "old_scope_mesh.json",
                "output_sha256": "old-sha",
                "scope_version": 1,
                "mesh_evidence": reduced,
            },
            {
                "seq": 2,
                "kind": "mesh",
                "returncode": 0,
                "output_path": "superseded_mesh.json",
                "output_sha256": "superseded-sha",
                "scope_version": 2,
                "mesh_evidence": reduced,
            },
        ]
        data["superseded"] = [{"path": "superseded_mesh.json"}]
        data["build_state"] = {"scope": {"version": 2}}

        self.assertEqual(manifest_tool.mesh_audit_disclosure_issues(data, self.manifest, {}), [])

    def test_complete_gate_requires_empirical_fragility_when_screened_records_exist(self):
        self.resolve_base_gates_and_scope()
        ledger = self.write_json("candidate_ledger.json", {"scope_version": 1, "records": []})
        validation = self.write_json("candidate_ledger_validation.json", {"operation": "candidate-ledger-validate", "ok": True})
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["build_state"]["candidate_screening"] = {
            "status": "complete",
            "artifact": str(ledger),
            "validation_artifact": str(validation),
            "summary": {"independent_holdout_available": False},
            "reason": "",
        }
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertIn("no empirical fragility-score artifact covers the registered blocks", receipt["issues"])
        self.assertIn("no active vocabulary-learning artifact follows candidate screening", receipt["issues"])
        vocabulary = self.write_json(
            "vocabulary_learning.json",
            {
                "operation": "vocabulary-learning",
                "ok": True,
                "scope_version": 1,
                "locked_concepts": ["condition"],
                "scope_reentry_required": False,
                "assignment_required": False,
                "processing_blockers": [],
                "excluded_record_diagnosis": {"used_for_proposals": False},
                "proposals": [],
                "accepted_term_count": 0,
                "experimental_term_count": 0,
                "reverted_term_count": 0,
                "all_accepted_terms_retested": True,
                "no_harm_checks_complete": True,
            },
        )
        self.add("term-rank", "python scripts/vocabulary_learning.py retest", output=vocabulary)
        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertFalse(any("vocabulary learning" in issue or "vocabulary-learning" in issue for issue in receipt["issues"]), receipt["issues"])

    def test_valid_ablation_and_two_strand_artifacts_satisfy_new_gates(self):
        self.resolve_base_gates_and_scope()
        self.state("register-block", "intervention")
        self.add("mesh", "python scripts/mesh_tool.py sweep --concept intervention", block="intervention")
        self.add("search", "python scripts/pubmed_tool.py search intervention", count=100, block="intervention")
        self.state("waive-requirement", "intervention", "bramer_gap", "Stable concept")
        scope_path = self.dir / "retrieval_scope_v1.json"
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        scope["fragile_topic"] = True
        scope_path.write_text(json.dumps(scope), encoding="utf-8")
        ablation = self.write_json(
            "concept_ablation.json",
            {
                "operation": "concept-ablation",
                "ok": True,
                "scope_version": 1,
                "analyses": [
                    {
                        "label": label,
                        "recommendation": {"disposition": "keep-as-required"},
                        "development": {},
                        "holdout": {},
                        "differential_sample": {},
                        "workload_change": {},
                    }
                    for label in ("condition", "intervention")
                ],
            },
        )
        self.add("variants", "python scripts/strategy_analysis.py concept-ablation", output=ablation)
        strands = self.write_json(
            "two_strand.json",
            {
                "operation": "two-strand",
                "ok": True,
                "scope_version": 1,
                "main": {},
                "focused": {},
                "development": {},
                "holdout": {},
                "records_unique_to_main": {},
                "records_unique_to_focused": {},
                "estimated_screening_workload": {},
                "narrowing_blocks": [{"label": "priority", "rationale": "Prioritization only"}],
                "safeguards": {"main_is_authoritative": True, "focused_cannot_replace_main": True},
            },
        )
        self.add("variants", "python scripts/strategy_analysis.py two-strand", output=strands)
        burden = self.write_json(
            "screening_burden.json",
            {
                "operation": "screening-burden",
                "ok": True,
                "scope_version": 1,
                "labels_complete": True,
                "minimum_heldout_recall": 1.0,
                "variants": [
                    {
                        "label": label,
                        "precision_estimate": precision,
                        "precision_confidence_interval_95": {"lower": 0.01, "upper": 0.5},
                        "estimated_records_screened_per_relevant_report": 1 / precision,
                        "total_count": 1000 if label == "main" else 500,
                        "heldout_recall": 1.0,
                        "recall_requirement_met": True,
                        "incremental_vs_baseline": {},
                    }
                    for label, precision in (("main", 0.1), ("focused", 0.2))
                ],
                "selection": {
                    "burden_used_for_selection": True,
                    "eligible_variant_labels": ["main", "focused"],
                    "recommended_variant_label": "focused",
                    "main_remains_authoritative": True,
                },
            },
        )
        self.add("variants", "python scripts/screening_burden.py estimate", output=burden)
        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertFalse(any("concept-ablation" in issue for issue in receipt["issues"]), receipt["issues"])
        self.assertFalse(any("two-strand" in issue for issue in receipt["issues"]), receipt["issues"])
        self.assertFalse(any("screening-burden" in issue or "multi-strand" in issue for issue in receipt["issues"]), receipt["issues"])

    def test_complete_gate_rejects_failed_final_qa_artifact(self):
        self.resolve_base_gates_and_scope()
        domains = sorted(critic_tool.REQUIRED_DOMAINS)
        critic, critic_receipt = self.critic_receipt(
            "critic_round_1.json",
            {
                "round": 1,
                "scope_version": 1,
                "strategy_file": "strategy.txt",
                "reviewed_domains": domains,
                "overall_status": "pass",
                "findings": [],
            },
        )
        self.state("record-critic", "--critic-file", critic, "--validation-file", critic_receipt)

        final_search = self.write_json("final_search.json", {"count": 1000})
        self.add(
            "search",
            "python scripts/pubmed_tool.py search --query-file strategy.txt --retmax 0 --output final_search.json",
            output=final_search,
            count=1000,
            label="final topic-only strategy",
        )
        failed_qa = self.write_json(
            "final_qa.json",
            {
                "hook": "pre_final_strategy_qa",
                "ok": False,
                "issues": [
                    {
                        "severity": "error",
                        "code": "unbalanced_parentheses",
                        "message": "Unbalanced parentheses.",
                    }
                ],
            },
        )
        self.add(
            "qa",
            "python scripts/hooks_tool.py final-qa --strategy-file strategy.txt",
            output=failed_qa,
        )
        audit = self.dir / "audit_demo.md"
        audit.write_text("# Audit", encoding="utf-8")
        self.add(
            "artifact",
            "python scripts/audit_markdown.py audit.json --output audit_demo.md",
            output=audit,
        )

        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertTrue(
            any(
                "latest final-qa output did not pass" in issue
                and "unbalanced_parentheses" in issue
                for issue in receipt["issues"]
            ),
            receipt["issues"],
        )

    def test_complete_gate_rejects_unresolved_required_validation_miss(self):
        self.resolve_base_gates_and_scope()
        self.state("resolve-gate", "seed", "provided")
        domains = sorted(critic_tool.REQUIRED_DOMAINS)
        critic, critic_receipt = self.critic_receipt(
            "critic_round_1.json",
            {
                "round": 1,
                "scope_version": 1,
                "strategy_file": "strategy.txt",
                "reviewed_domains": domains,
                "overall_status": "pass",
                "findings": [],
            },
        )
        self.state("record-critic", "--critic-file", critic, "--validation-file", critic_receipt)
        final_search = self.write_json("final_search.json", {"operation": "search", "count": 1000, "ok": True})
        self.add(
            "search",
            "python scripts/pubmed_tool.py search --query-file strategy.txt --retmax 0 --output final_search.json",
            output=final_search,
            count=1000,
            label="final topic-only strategy",
        )
        validation = self.write_json(
            "validation.json",
            {"operation": "validate", "ok": True, "retrieved_pmids": [], "missed_pmids": ["9"]},
        )
        self.add(
            "validate",
            "python scripts/pubmed_tool.py validate --query-file strategy.txt --pmids 9 --output validation.json",
            output=validation,
        )
        final_qa = self.write_json("final_qa.json", {"hook": "pre_final_strategy_qa", "ok": True})
        self.add("qa", "python scripts/hooks_tool.py final-qa --strategy-file strategy.txt", output=final_qa)
        audit = self.dir / "audit_demo.md"
        audit.write_text("# Audit", encoding="utf-8")
        self.add("artifact", "python scripts/audit_markdown.py audit.json --output audit_demo.md", output=audit)

        rc, receipt = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertTrue(
            any("unresolved missed PMIDs: 9" in issue for issue in receipt["issues"]),
            receipt["issues"],
        )


if __name__ == "__main__":
    unittest.main()
