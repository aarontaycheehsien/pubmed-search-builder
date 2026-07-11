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


class ProtocolValidationTests(unittest.TestCase):
    def test_complete_protocol_passes_lock_validation(self):
        self.assertEqual(protocol_tool.validate_protocol(valid_protocol(), "lock"), [])

    def test_new_protocol_is_draft_valid_but_not_lock_ready(self):
        draft = protocol_tool.new_protocol()
        self.assertEqual(protocol_tool.validate_protocol(draft, "draft"), [])
        self.assertTrue(protocol_tool.validate_protocol(draft, "lock"))

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
            audit = json.loads((directory / "audit_outline_v1.json").read_text(encoding="utf-8"))
            self.assertTrue(all({"id", "title", "required", "source_refs"} <= set(row) for row in audit["sections"]))
            section_ids = {row["id"] for row in audit["sections"]}
            self.assertIn("concept-allocation", section_ids)
            self.assertIn("concept-recruitment", section_ids)
            self.assertIn("focused-variant-recruitment_focus", section_ids)
            result = protocol_tool.verify_protocol(source, receipt_path)
            self.assertTrue(result["ok"])
            self.assertEqual(result["artifact_count"], 5)

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

    def test_protocol_identity_ignores_source_whitespace(self):
        left = valid_protocol()
        right = copy.deepcopy(left)
        self.assertEqual(protocol_tool.canonical_sha256(left), protocol_tool.canonical_sha256(right))


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
