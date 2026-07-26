import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("protocol_tool", ROOT / "scripts" / "protocol_tool.py")
protocol_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(protocol_tool)


def valid_protocol() -> dict:
    return {
        "dsl_version": 1,
        "protocol_id": "emergency-allocation",
        "scope_version": 1,
        "version_change": {
            "previous_scope_version": None,
            "reason": "Initial protocol",
            "decision_source": "Team protocol meeting",
        },
        "review": {
            "question": "Which allocation methods are used in emergency-care trials?",
            "framework": {
                "name": "Method plus setting",
                "rationale": "The method and setting define retrieval.",
                "slots": [
                    {"id": "method", "label": "Method", "description": "Allocation method"},
                    {"id": "setting", "label": "Setting", "description": "Emergency care"},
                ],
            },
        },
        "eligibility": {
            "inclusion": [
                {"id": "eligible_method", "label": "Allocation", "description": "Predictable allocation"},
                {"id": "eligible_setting", "label": "Setting", "description": "Emergency care"},
            ],
            "exclusion": [
                {"id": "exclude_simulation", "label": "Simulation", "description": "Exclude simulated trials"}
            ],
        },
        "searchable_scope": {
            "concepts": [
                {
                    "id": "allocation", "label": "Allocation method", "role": "essential",
                    "eligibility_refs": ["eligible_method"], "framework_slots": ["method"],
                    "definition": "Quasi-random or predictable allocation", "rationale": "Core review focus",
                    "provisional_fragility": "fragile", "term_families": ["quasi-random*", "alternat*"],
                },
                {
                    "id": "emergency", "label": "Emergency care", "role": "essential",
                    "eligibility_refs": ["eligible_setting"], "framework_slots": ["setting"],
                    "definition": "Emergency and prehospital care", "rationale": "Application domain",
                    "provisional_fragility": "stable",
                },
                {
                    "id": "recruitment", "label": "Recruitment", "role": "optional",
                    "eligibility_refs": [], "framework_slots": ["method"],
                    "definition": "Recruitment and consent process", "rationale": "Focused prioritization only",
                    "provisional_fragility": "very_fragile",
                },
            ]
        },
        "screening_only": {
            "properties": [
                {
                    "id": "bias_assessment", "label": "Selection bias",
                    "eligibility_refs": ["eligible_method"], "instructions": "Assess at screening or full text.",
                    "recall_rationale": "Rarely named in abstracts.",
                }
            ]
        },
        "filters_and_limits": {
            "decisions": [
                {
                    "id": "humans_filter", "type": "filter", "label": "Humans", "status": "rejected",
                    "value": "Humans[Mesh]", "validated_source": None,
                    "rationale": "Could remove incompletely indexed reports.",
                }
            ]
        },
        "date_boundaries": {
            "eligibility": {"start": None, "end": None},
            "search": {"start": None, "end": None},
            "rationale": "No date restriction.",
        },
        "seeds": {
            "records": [
                {"pmid": "12345", "role": "discovery-candidate", "rationale": "Known candidate"},
                {"pmid": "67890", "role": "holdout-candidate", "rationale": "Independent candidate"},
            ]
        },
        "priorities": {
            "recall": {"policy": "Recall-first main strategy", "minimum_heldout_recall": 1.0},
            "workload": {
                "policy": "Compare burden only after recall qualification",
                "selection_rule": "Choose the lowest burden recall-qualified strategy",
            },
        },
        "focused_variants": [
            {
                "id": "recruitment_focus", "label": "Recruitment focus",
                "optional_concept_ids": ["recruitment"], "filter_limit_ids": [],
                "excluded_concept_ids": [], "rationale": "Prioritize recruitment reports.",
            }
        ],
    }


def methods_evaluation_protocol() -> dict:
    """A methods-evaluation protocol: how well do LLMs generate Boolean search strategies?"""
    return {
        "dsl_version": 1,
        "protocol_id": "llm-boolean-strategy-generation",
        "scope_version": 1,
        "version_change": {
            "previous_scope_version": None,
            "reason": "Initial protocol",
            "decision_source": "Review team scoping call",
        },
        "review": {
            "question": "How well do large language models generate Boolean search strategies for systematic reviews?",
            "framework": {
                "name": "Methods evaluation",
                "profile_id": "methods-evaluation",
                "rationale": "Task-performance question about a tool, not an intervention effect.",
                "slots": [
                    {"id": "technology_method", "label": "Technology or method", "description": "Large language models"},
                    {"id": "task_function", "label": "Task or function", "description": "Evidence-synthesis literature searching"},
                    {"id": "application_context", "label": "Application context", "description": "Boolean strategy generation"},
                    {"id": "comparator", "label": "Comparator or baseline", "description": "Human or expert searcher"},
                    {"id": "performance_outcome", "label": "Performance outcome", "description": "Recall, precision, quality, workload"},
                ],
            },
        },
        "evidence_target": {
            "mode": "primary-studies",
            "eligible_types": [],
            "protocols": "screen",
            "narrative_reviews": "exclude",
            "methods_papers": "include",
        },
        "eligibility": {
            "inclusion": [
                {"id": "eligible_model", "label": "LLM evaluated", "description": "A large language model is the method under evaluation"},
                {"id": "eligible_task", "label": "Search task", "description": "The model performs an evidence-synthesis searching task"},
            ],
            "exclusion": [
                {"id": "exclude_unevaluated", "label": "No performance data", "description": "Exclude reports with no measured task performance"}
            ],
        },
        "searchable_scope": {
            "concepts": [
                {
                    "id": "llm", "label": "Large language models", "role": "essential",
                    "eligibility_refs": ["eligible_model"], "framework_slots": ["technology_method"],
                    "definition": "Generative language models and chat assistants",
                    "rationale": "The method under evaluation",
                    "provisional_fragility": "fragile",
                    "term_families": ["large language model*", "generative pretrained*", "chatgpt"],
                },
                {
                    "id": "synthesis_workflow", "label": "Evidence-synthesis searching workflow", "role": "essential",
                    "eligibility_refs": ["eligible_task"], "framework_slots": ["task_function"],
                    "definition": "Literature searching and evidence-synthesis conduct",
                    "rationale": "Broader workflow concept keeps recall when the narrow action wording varies",
                    "provisional_fragility": "fragile",
                    "term_families": ["literature search*", "systematic review*", "search strateg*", "boolean quer*"],
                },
                {
                    "id": "boolean_generation", "label": "Boolean strategy generation", "role": "optional",
                    "eligibility_refs": [], "framework_slots": ["task_function"],
                    "definition": "Generation or translation of Boolean queries",
                    "rationale": "Narrow action wording; prioritization only, never the main block",
                    "provisional_fragility": "very_fragile",
                },
            ]
        },
        "screening_only": {
            "properties": [
                {
                    "id": "screening_purpose", "label": "Title/abstract-screening purpose",
                    "eligibility_refs": ["eligible_task"],
                    "instructions": "Confirm the generated strategy served title/abstract screening at screening.",
                    "recall_rationale": "The application context is the setting, not a searchable topic anchor.",
                },
                {
                    "id": "human_comparator", "label": "Human or expert comparator",
                    "eligibility_refs": ["eligible_model"],
                    "instructions": "Confirm a human or expert baseline at screening.",
                    "recall_rationale": "Comparisons are reported in results, not as indexed topic anchors.",
                },
                {
                    "id": "performance_metrics", "label": "Performance outcomes",
                    "eligibility_refs": ["exclude_unevaluated"],
                    "instructions": "Confirm measured recall, precision, quality, or workload at screening.",
                    "recall_rationale": "Metric wording is unbounded and often absent from abstracts.",
                },
            ]
        },
        "filters_and_limits": {
            "decisions": [
                {
                    "id": "evaluation_design_filter", "type": "filter", "label": "Evaluation study design",
                    "status": "rejected", "value": "evaluation studies[pt]", "validated_source": None,
                    "rationale": "No validated filter exists for methods-evaluation designs.",
                }
            ]
        },
        "date_boundaries": {
            "eligibility": {"start": "2019-01-01", "end": None},
            "search": {"start": "2019-01-01", "end": None},
            "rationale": "Transformer-based language models postdate 2019.",
        },
        "seeds": {"records": []},
        "priorities": {
            "recall": {"policy": "Recall-first main strategy", "minimum_heldout_recall": 1.0},
            "workload": {
                "policy": "Compare burden only after recall qualification",
                "selection_rule": "Choose the lowest burden recall-qualified strategy",
            },
        },
        "focused_variants": [
            {
                "id": "boolean_focus", "label": "Boolean-generation focus",
                "optional_concept_ids": ["boolean_generation"], "filter_limit_ids": [],
                "excluded_concept_ids": [], "rationale": "Prioritized screening for the narrow action wording.",
            }
        ],
    }


class ProtocolValidationTests(unittest.TestCase):
    def test_complete_protocol_passes_lock_validation(self):
        self.assertEqual(protocol_tool.validate_protocol(valid_protocol(), "lock"), [])

    def test_new_protocol_is_draft_valid_but_not_lock_ready(self):
        draft = protocol_tool.new_protocol()
        self.assertEqual(protocol_tool.validate_protocol(draft, "draft"), [])
        self.assertTrue(protocol_tool.validate_protocol(draft, "lock"))

    def test_legacy_protocol_without_mode_defaults_to_pubmed_only(self):
        protocol = valid_protocol()
        self.assertEqual(protocol_tool.validate_protocol(protocol, "lock"), [])

    def test_evidence_synthesis_target_requires_types_and_valid_screening_policy(self):
        protocol = valid_protocol()
        protocol["evidence_target"] = {
            "mode": "evidence-syntheses",
            "eligible_types": [],
            "protocols": "exclude",
            "narrative_reviews": "screen",
            "methods_papers": "screen",
        }
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("eligible_types must not be empty" in issue for issue in issues))
        protocol["evidence_target"]["eligible_types"] = ["systematic-review", "meta-analysis"]
        self.assertEqual(protocol_tool.validate_protocol(protocol, "lock"), [])

    def test_external_validation_mode_requires_enabled_source_configuration(self):
        protocol = valid_protocol()
        protocol["information_source_mode"] = "pubmed-plus-external-validation"
        protocol["external_validation"] = {
            "status": "enabled",
            "purpose": "pubmed-leak-detection",
            "sources": ["clinicaltrials.gov", "who-ictrp"],
        }
        self.assertEqual(protocol_tool.validate_protocol(protocol, "lock"), [])
        protocol["external_validation"]["status"] = "not-applicable"
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("must be enabled" in issue for issue in issues))

    def test_pubmed_only_rejects_enabled_external_validation(self):
        protocol = valid_protocol()
        protocol["information_source_mode"] = "pubmed-only"
        protocol["external_validation"] = {
            "status": "enabled",
            "purpose": "pubmed-leak-detection",
            "sources": ["clinicaltrials.gov"],
        }
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("cannot be enabled" in issue for issue in issues))

    def test_unknown_core_fields_require_x_prefix(self):
        protocol = valid_protocol()
        protocol["surprise"] = True
        protocol["x-owner"] = "team"
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("surprise is not permitted" in issue for issue in issues))
        self.assertFalse(any("x-owner" in issue for issue in issues))

    def test_semantics_reject_broken_refs_dates_duplicates_and_essential_removal(self):
        protocol = valid_protocol()
        protocol["scope_version"] = 2
        protocol["version_change"]["previous_scope_version"] = None
        protocol["date_boundaries"]["search"] = {"start": "2025-12-01", "end": "2025-01-01"}
        protocol["date_boundaries"]["rationale"] = ""
        protocol["seeds"]["records"][1]["pmid"] = "12345"
        protocol["searchable_scope"]["concepts"][0]["eligibility_refs"] = ["missing"]
        protocol["focused_variants"][0]["excluded_concept_ids"] = ["allocation"]
        issues = protocol_tool.validate_protocol(protocol, "lock")
        joined = "\n".join(issues)
        self.assertIn("previous_scope_version must be 1", joined)
        self.assertIn("start must not be after end", joined)
        self.assertIn("duplicates PMID", joined)
        self.assertIn("unknown criterion", joined)
        self.assertIn("may not exclude essential concept", joined)

    def test_selected_filter_requires_validated_source(self):
        protocol = valid_protocol()
        protocol["filters_and_limits"]["decisions"][0]["status"] = "selected"
        protocol["filters_and_limits"]["decisions"][0]["value"] = None
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("validated_source is required" in issue for issue in issues))
        self.assertTrue(any("value is required" in issue for issue in issues))

    def test_focused_variant_must_add_a_narrowing_decision(self):
        protocol = valid_protocol()
        protocol["focused_variants"][0]["optional_concept_ids"] = []
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("must add at least one optional concept" in issue for issue in issues))


class ProtocolCompilationTests(unittest.TestCase):
    def write_protocol(self, directory: Path, protocol: dict | None = None) -> Path:
        path = directory / "review_protocol_v1.json"
        path.write_text(json.dumps(protocol or valid_protocol(), indent=2), encoding="utf-8")
        return path

    def test_compile_emits_bound_artifacts_and_verify_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.write_protocol(directory)
            receipt_path = directory / "protocol_compile_v1.json"
            receipt = protocol_tool.compile_protocol(source, directory, receipt_path)
            self.assertEqual(receipt["operation"], "protocol-compile")
            self.assertEqual(len(receipt["artifacts"]), 5)
            self.assertEqual(
                {item["artifact_type"] for item in receipt["artifacts"]},
                {"concept-ledger", "candidate-ledger-template", "block-registry", "critic-packet", "audit-outline"},
            )
            candidate = json.loads((directory / "candidate_ledger_template_v1.json").read_text(encoding="utf-8"))
            self.assertEqual(candidate["ledger_status"], "template")
            self.assertEqual(candidate["records"][0]["requested_role"], "discovery-candidate")
            self.assertEqual(candidate["records"][0]["decision"], "pending")
            concept_ledger = json.loads((directory / "concept_ledger_v1.json").read_text(encoding="utf-8"))
            self.assertEqual(concept_ledger["screening_only_properties"][0]["id"], "bias_assessment")
            blocks = json.loads((directory / "block_registry_v1.json").read_text(encoding="utf-8"))
            self.assertEqual(blocks["blocks"][0]["block_id"], "allocation")
            critic = json.loads((directory / "critic_packet_v1.json").read_text(encoding="utf-8"))
            self.assertIn("required_domains", critic)
            self.assertIn("protocol_summary", critic)
            self.assertEqual(critic["protocol_summary"]["information_source_mode"], "pubmed-only")
            audit = json.loads((directory / "audit_outline_v1.json").read_text(encoding="utf-8"))
            self.assertTrue(all({"id", "title", "required", "source_refs"} <= set(row) for row in audit["sections"]))
            section_ids = {row["id"] for row in audit["sections"]}
            self.assertIn("concept-allocation", section_ids)
            self.assertIn("concept-recruitment", section_ids)
            self.assertIn("focused-variant-recruitment_focus", section_ids)
            result = protocol_tool.verify_protocol(source, receipt_path)
            self.assertTrue(result["ok"])
            self.assertEqual(result["artifact_count"], 5)

    def test_evidence_synthesis_protocol_compile_keeps_profile_separate(self):
        for mode in ("evidence-syntheses", "mixed"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                protocol = valid_protocol()
                protocol["evidence_target"] = {
                    "mode": mode,
                    "eligible_types": ["systematic-review", "meta-analysis", "scoping-review"],
                    "protocols": "exclude",
                    "narrative_reviews": "screen",
                    "methods_papers": "exclude",
                }
                source = self.write_protocol(directory, protocol)
                receipt_path = directory / "protocol_compile_v1.json"
                receipt = protocol_tool.compile_protocol(source, directory, receipt_path)

                self.assertEqual(len(receipt["artifacts"]), 5)
                self.assertEqual(
                    {item["artifact_type"] for item in receipt["artifacts"]},
                    protocol_tool.CORE_DERIVATIVE_TYPES,
                )
                self.assertFalse((directory / "review_retrieval_profile_v1.json").exists())
                audit = json.loads((directory / "audit_outline_v1.json").read_text(encoding="utf-8"))
                self.assertIn("evidence-synthesis-retrieval", {section["id"] for section in audit["sections"]})
                self.assertTrue(protocol_tool.verify_protocol(source, receipt_path)["ok"])

    def test_compile_is_deterministic_and_refuses_different_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.write_protocol(directory)
            receipt_path = directory / "protocol_compile_v1.json"
            protocol_tool.compile_protocol(source, directory, receipt_path)
            before = {path.name: path.read_bytes() for path in directory.glob("*.json")}
            protocol_tool.compile_protocol(source, directory, receipt_path)
            self.assertEqual(before, {path.name: path.read_bytes() for path in directory.glob("*.json")})
            changed = valid_protocol()
            changed["review"]["question"] = "A changed question"
            source.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(protocol_tool.ProtocolError):
                protocol_tool.compile_protocol(source, directory, receipt_path)

    def test_verify_detects_manual_artifact_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.write_protocol(directory)
            receipt_path = directory / "protocol_compile_v1.json"
            protocol_tool.compile_protocol(source, directory, receipt_path)
            artifact = directory / "concept_ledger_v1.json"
            value = json.loads(artifact.read_text(encoding="utf-8"))
            value["concepts"][0]["label"] = "Edited"
            artifact.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(protocol_tool.ProtocolError, "hash mismatch"):
                protocol_tool.verify_protocol(source, receipt_path)

    def test_verify_rebuilds_derivative_even_if_receipt_hash_is_forged(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = self.write_protocol(directory)
            receipt_path = directory / "protocol_compile_v1.json"
            protocol_tool.compile_protocol(source, directory, receipt_path)
            artifact = directory / "concept_ledger_v1.json"
            value = json.loads(artifact.read_text(encoding="utf-8"))
            value["concepts"][0]["label"] = "Forged derivative"
            artifact.write_text(json.dumps(value), encoding="utf-8")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            item = next(row for row in receipt["artifacts"] if row["artifact_type"] == "concept-ledger")
            item["sha256"] = protocol_tool.file_sha256(artifact)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(protocol_tool.ProtocolError, "does not match the derivative compiled"):
                protocol_tool.verify_protocol(source, receipt_path)

    def test_protocol_identity_ignores_source_whitespace(self):
        left = valid_protocol()
        right = copy.deepcopy(left)
        self.assertEqual(protocol_tool.canonical_sha256(left), protocol_tool.canonical_sha256(right))


class MethodsEvaluationProfileTests(unittest.TestCase):
    def compile_profile(self, directory: Path, protocol: dict) -> dict[str, dict]:
        source = directory / "review_protocol_v1.json"
        source.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
        receipt_path = directory / "protocol_compile_v1.json"
        protocol_tool.compile_protocol(source, directory, receipt_path)
        self.assertTrue(protocol_tool.verify_protocol(source, receipt_path)["ok"])
        return {
            name: json.loads((directory / f"{name}_v1.json").read_text(encoding="utf-8"))
            for name in ("critic_packet", "audit_outline", "block_registry")
        }

    def test_valid_methods_evaluation_protocol_locks_and_compiles(self):
        protocol = methods_evaluation_protocol()
        self.assertEqual(protocol_tool.validate_protocol(protocol, "lock"), [])
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self.compile_profile(Path(tmp), protocol)
        essential = [row["block_id"] for row in artifacts["block_registry"]["blocks"] if row["role"] == "essential"]
        self.assertEqual(essential, ["llm", "synthesis_workflow"])

    def test_missing_canonical_slot_fails_lock_validation(self):
        for dropped in ("technology_method", "task_function", "application_context", "comparator", "performance_outcome"):
            with self.subTest(slot=dropped):
                protocol = methods_evaluation_protocol()
                slots = protocol["review"]["framework"]["slots"]
                protocol["review"]["framework"]["slots"] = [row for row in slots if row["id"] != dropped]
                for concept in protocol["searchable_scope"]["concepts"]:
                    concept["framework_slots"] = [ref for ref in concept["framework_slots"] if ref != dropped] or ["technology_method"]
                issues = protocol_tool.validate_protocol(protocol, "lock")
                self.assertTrue(
                    any(f"canonical methods-evaluation slot '{dropped}'" in issue for issue in issues),
                    issues,
                )

    def test_profile_requires_an_explicit_evidence_target(self):
        protocol = methods_evaluation_protocol()
        del protocol["evidence_target"]
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("evidence_target is required" in issue for issue in issues), issues)
        # Draft authoring may still be in progress.
        self.assertFalse(any("evidence_target is required" in issue for issue in protocol_tool.validate_protocol(protocol, "draft")))

    def test_unknown_profile_id_is_rejected(self):
        protocol = methods_evaluation_protocol()
        protocol["review"]["framework"]["profile_id"] = "diagnostic-accuracy"
        issues = protocol_tool.validate_protocol(protocol, "lock")
        self.assertTrue(any("profile_id must be one of" in issue for issue in issues), issues)

    def test_evidence_synthesis_context_does_not_trigger_the_review_retrieval_gate(self):
        protocol = methods_evaluation_protocol()
        self.assertEqual(protocol["evidence_target"]["mode"], "primary-studies")
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self.compile_profile(Path(tmp), protocol)
        section_ids = {row["id"] for row in artifacts["audit_outline"]["sections"]}
        self.assertNotIn("evidence-synthesis-retrieval", section_ids)
        self.assertIn("methods-evaluation-framework", section_ids)

        # The gate still activates when completed syntheses really are the target records.
        review_of_reviews = methods_evaluation_protocol()
        review_of_reviews["evidence_target"] = {
            "mode": "evidence-syntheses",
            "eligible_types": ["systematic-review", "umbrella-review"],
            "protocols": "exclude",
            "narrative_reviews": "exclude",
            "methods_papers": "screen",
        }
        with tempfile.TemporaryDirectory() as tmp:
            gated = self.compile_profile(Path(tmp), review_of_reviews)
        gated_ids = {row["id"] for row in gated["audit_outline"]["sections"]}
        self.assertIn("evidence-synthesis-retrieval", gated_ids)
        self.assertIn("methods-evaluation-framework", gated_ids)

    def test_comparator_and_performance_outcomes_default_to_screening_only(self):
        protocol = methods_evaluation_protocol()
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self.compile_profile(Path(tmp), protocol)
        profile = artifacts["critic_packet"]["framework_profile"]
        self.assertEqual(profile["screening_only_by_default"], ["comparator", "performance_outcome"])
        by_slot = {row["slot_id"]: row for row in profile["slots"]}
        self.assertEqual(by_slot["comparator"]["assigned_concepts"], [])
        self.assertEqual(by_slot["performance_outcome"]["assigned_concepts"], [])
        self.assertEqual(profile["required_blocks_on_screening_default_slots"], [])
        screening_ids = {row["id"] for row in protocol["screening_only"]["properties"]}
        self.assertEqual(screening_ids, {"screening_purpose", "human_comparator", "performance_metrics"})
        # The application context is named as a slot but searched by nobody: it is screened, not blocked.
        self.assertEqual(by_slot["application_context"]["assigned_concepts"], [])

        # Promoting either default to a required block is compiled as a role-safety flag.
        promoted = methods_evaluation_protocol()
        promoted["searchable_scope"]["concepts"].append({
            "id": "recall_outcome", "label": "Retrieval recall", "role": "essential",
            "eligibility_refs": [], "framework_slots": ["performance_outcome"],
            "definition": "Measured recall of the generated strategy",
            "rationale": "Protocol requires a measured outcome",
            "provisional_fragility": "very_fragile",
        })
        self.assertEqual(protocol_tool.validate_protocol(promoted, "lock"), [])
        with tempfile.TemporaryDirectory() as tmp:
            flagged = self.compile_profile(Path(tmp), promoted)
        self.assertEqual(
            flagged["critic_packet"]["framework_profile"]["required_blocks_on_screening_default_slots"],
            ["performance_outcome"],
        )

    def test_narrow_task_language_is_carried_as_a_focused_variant(self):
        protocol = methods_evaluation_protocol()
        concepts = {row["id"]: row for row in protocol["searchable_scope"]["concepts"]}
        self.assertEqual(concepts["synthesis_workflow"]["role"], "essential")
        self.assertEqual(concepts["boolean_generation"]["role"], "optional")
        self.assertEqual(
            protocol["focused_variants"][0]["optional_concept_ids"], ["boolean_generation"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self.compile_profile(Path(tmp), protocol)
        by_slot = {row["slot_id"]: row for row in artifacts["critic_packet"]["framework_profile"]["slots"]}
        # The breadth decision lives inside task_function: broad concept blocks, narrow wording prioritizes.
        self.assertEqual(
            by_slot["task_function"]["assigned_concepts"],
            [
                {"concept_id": "synthesis_workflow", "role": "essential"},
                {"concept_id": "boolean_generation", "role": "optional"},
            ],
        )
        self.assertIn("focused-variant-boolean_focus", {row["id"] for row in artifacts["audit_outline"]["sections"]})

        # A focused variant may never drop the broad workflow block it is meant to narrow.
        replacing = methods_evaluation_protocol()
        replacing["focused_variants"][0]["excluded_concept_ids"] = ["synthesis_workflow"]
        issues = protocol_tool.validate_protocol(replacing, "lock")
        self.assertTrue(any("may not exclude essential concept" in issue for issue in issues), issues)

    def test_compiled_critic_and_audit_carry_the_profile_qa_domain(self):
        protocol = methods_evaluation_protocol()
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = self.compile_profile(Path(tmp), protocol)
        critic = artifacts["critic_packet"]
        self.assertIn("methods-evaluation-role-safety", critic["required_domains"])
        self.assertEqual(critic["framework_profile"]["profile_id"], "methods-evaluation")
        self.assertEqual(
            [check["id"] for check in critic["framework_profile"]["checks"]],
            [
                "comparator-outcome-not-required",
                "task-language-breadth",
                "context-vs-publication-type",
                "evaluation-terminology-filter",
                "focused-variant-cannot-replace-main",
            ],
        )
        self.assertTrue(critic["framework_profile"]["focused_variants_cannot_replace_main_strategy"])
        section = next(
            row for row in artifacts["audit_outline"]["sections"] if row["id"] == "methods-evaluation-framework"
        )
        self.assertEqual(section["title"], "Methods-evaluation framework decisions")
        self.assertEqual(section["source_refs"], ["review.framework"])

    def test_protocols_without_a_profile_are_unchanged(self):
        for framework_name in ("PICO", "PECO", "PCC", "Method plus setting"):
            with self.subTest(framework=framework_name), tempfile.TemporaryDirectory() as tmp:
                protocol = valid_protocol()
                protocol["review"]["framework"]["name"] = framework_name
                self.assertEqual(protocol_tool.validate_protocol(protocol, "lock"), [])
                self.assertIsNone(protocol_tool.framework_profile_packet(protocol))
                artifacts = self.compile_profile(Path(tmp), protocol)
                self.assertNotIn("framework_profile", artifacts["critic_packet"])
                self.assertNotIn("methods-evaluation-role-safety", artifacts["critic_packet"]["required_domains"])
                self.assertNotIn(
                    "methods-evaluation-framework",
                    {row["id"] for row in artifacts["audit_outline"]["sections"]},
                )

    def test_protocols_without_a_profile_do_not_require_an_evidence_target(self):
        protocol = valid_protocol()
        self.assertNotIn("evidence_target", protocol)
        self.assertEqual(protocol_tool.validate_protocol(protocol, "lock"), [])


class ProtocolMigrationAndCliTests(unittest.TestCase):
    def test_legacy_migration_maps_known_fields_and_requires_resolution(self):
        legacy = {
            "scope_version": 1,
            "review_question": "A legacy review?",
            "framework": "Custom",
            "essential_blocks": ["Emergency care"],
            "screening_only": [{"concept": "Bias", "reason": "Not reliably reported"}],
            "filters": "No filters",
        }
        protocol, report = protocol_tool.migrate_scope(legacy, Path("retrieval_scope_v1.json"))
        self.assertEqual(protocol["searchable_scope"]["concepts"][0]["id"], "emergency_care")
        self.assertFalse(report["lock_ready"])
        self.assertTrue(report["unresolved"])
        self.assertEqual(protocol_tool.validate_protocol(protocol, "draft"), [])
        self.assertTrue(any("x-migration.unresolved" in issue for issue in protocol_tool.validate_protocol(protocol, "lock")))

    def test_cli_new_validate_and_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            draft = directory / "draft.json"
            command = [sys.executable, str(ROOT / "scripts" / "protocol_tool.py"), "new", "--output", str(draft)]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            validate = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "protocol_tool.py"), "validate", str(draft), "--mode", "draft"],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)
            draft.write_text(json.dumps(valid_protocol()), encoding="utf-8")
            receipt = directory / "protocol_compile_v1.json"
            compile_result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "protocol_tool.py"), "compile", str(draft),
                 "--output-dir", str(directory), "--receipt", str(receipt)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)


if __name__ == "__main__":
    unittest.main()
