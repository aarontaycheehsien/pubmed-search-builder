"""Manifest integration tests for the canonical protocol DSL compile envelope."""

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("manifest_tool_protocol", ROOT / "scripts" / "manifest_tool.py")
manifest_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifest_tool)

PROTOCOL_SPEC = importlib.util.spec_from_file_location(
    "protocol_tool_manifest_integration", ROOT / "scripts" / "protocol_tool.py"
)
protocol_tool = importlib.util.module_from_spec(PROTOCOL_SPEC)
assert PROTOCOL_SPEC.loader is not None
PROTOCOL_SPEC.loader.exec_module(protocol_tool)


def canonical_hash(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManifestProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.manifest = self.directory / "run_manifest.json"

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = manifest_tool.main(args)
        text = out.getvalue().strip()
        return rc, json.loads(text) if text else None, err.getvalue()

    def state(self, action, *args):
        return self.run_cli(["state", action, "--manifest", str(self.manifest), *map(str, args)])

    def load(self):
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    def add(self, kind, command, output):
        return self.run_cli(
            [
                "add",
                "--manifest",
                str(self.manifest),
                "--kind",
                kind,
                "--command",
                command,
                "--output",
                str(output),
            ]
        )

    def compiled_protocol(
        self,
        version=1,
        *,
        protocol_id="emergency-trials",
        concepts=None,
        seed_records=None,
        filter_decisions=None,
    ):
        concepts = concepts or [
            {"id": "emergency-care", "label": "Emergency care", "role": "essential"},
            {"id": "allocation", "label": "Quasi-random allocation", "role": "essential"},
            {"id": "bias", "label": "Selection bias", "role": "optional"},
        ]
        protocol = {
            "dsl_version": 1,
            "protocol_id": protocol_id,
            "scope_version": version,
            "version_change": {"reason": "initial lock" if version == 1 else "scope revision"},
            "review": {"question": "How does quasi-randomization perform in emergency trials?", "framework": {"name": "PICO"}},
            "eligibility": {"include": [], "exclude": []},
            "searchable_scope": {"concepts": concepts},
            "screening_only": [],
            "filters_and_limits": {"decisions": filter_decisions or []},
            "date_boundaries": [],
            "seeds": {"records": seed_records or []},
            "priorities": [],
            "focused_variants": [],
        }
        protocol_path = self.directory / f"protocol_v{version}.json"
        protocol_path.write_text(json.dumps(protocol, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        protocol_sha = canonical_hash(protocol)

        artifact_specs = {
            "concept-ledger": {"essential_blocks": [item["id"] for item in concepts if item["role"] == "essential"]},
            "block-registry": {
                "blocks": [
                    {
                        "block_id": item["id"],
                        "concept_id": item["id"],
                        "label": item["label"],
                        "role": item["role"],
                    }
                    for item in concepts
                ]
            },
            "candidate-ledger-template": {"ledger_status": "template", "records": []},
            "critic-packet": {"reviewed_domains": []},
            "audit-outline": {"sections": []},
        }
        artifacts = []
        for artifact_type, payload in artifact_specs.items():
            path = self.directory / f"{artifact_type}_v{version}.json"
            envelope = {
                "artifact_type": artifact_type,
                "artifact_version": 1,
                "protocol_id": protocol_id,
                "scope_version": version,
                "dsl_version": 1,
                "generated_from": {"path": protocol_path.name, "sha256": protocol_sha},
                **payload,
            }
            path.write_text(
                json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            artifacts.append({"artifact_type": artifact_type, "path": str(path), "sha256": file_hash(path)})

        receipt = {
            "operation": "protocol-compile",
            "ok": True,
            "protocol_sha256": protocol_sha,
            "protocol_id": protocol_id,
            "scope_version": version,
            "dsl_version": 1,
            "artifacts": artifacts,
        }
        receipt_path = self.directory / f"protocol_compile_v{version}.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return protocol_path, receipt_path, protocol, receipt

    def lock_valid_protocol(self):
        protocol = protocol_tool.new_protocol()
        protocol.update(
            {
                "protocol_id": "actual-compiler",
                "version_change": {
                    "previous_scope_version": None,
                    "reason": "Initial protocol lock",
                    "decision_source": "Review protocol",
                },
                "review": {
                    "question": "Does intervention X help people with condition Y?",
                    "framework": {
                        "name": "PICO",
                        "rationale": "Intervention-effect review",
                        "slots": [
                            {"id": "population", "label": "Population", "description": "People with Y"},
                            {"id": "intervention", "label": "Intervention", "description": "Intervention X"},
                        ],
                    },
                },
                "eligibility": {
                    "inclusion": [
                        {"id": "condition_y", "label": "Condition Y", "description": "Confirmed condition Y"}
                    ],
                    "exclusion": [],
                },
                "searchable_scope": {
                    "concepts": [
                        {
                            "id": "condition",
                            "label": "Condition Y",
                            "role": "essential",
                            "eligibility_refs": ["condition_y"],
                            "framework_slots": ["population"],
                            "definition": "The target condition",
                            "rationale": "Required retrieval concept",
                            "provisional_fragility": "stable",
                            "term_families": ["condition names"],
                        },
                        {
                            "id": "intervention",
                            "label": "Intervention X",
                            "role": "essential",
                            "eligibility_refs": [],
                            "framework_slots": ["intervention"],
                            "definition": "The intervention",
                            "rationale": "Required retrieval concept",
                            "provisional_fragility": "fragile",
                            "term_families": ["generic and brand names"],
                        },
                    ]
                },
                "priorities": {
                    "recall": {"policy": "Recall-first", "minimum_heldout_recall": 1.0},
                    "workload": {
                        "policy": "Use burden after recall qualification",
                        "selection_rule": "Lowest burden among recall-qualified variants",
                    },
                },
            }
        )
        protocol_tool.require_valid(protocol, "lock")
        return protocol

    def lock(self, protocol_path, receipt_path):
        return self.state(
            "lock-protocol",
            "--protocol-file",
            protocol_path,
            "--compile-receipt",
            receipt_path,
        )

    def test_lock_protocol_derives_gates_and_registers_essential_blocks(self):
        protocol_path, receipt_path, protocol, receipt = self.compiled_protocol(
            seed_records=[{"pmid": "123", "role": "discovery-candidate", "rationale": "Known relevant report"}],
            filter_decisions=[
                {
                    "id": "language-limit",
                    "type": "limit",
                    "label": "Language",
                    "status": "selected",
                    "value": "English",
                    "validated_source": None,
                    "rationale": "Protocol decision",
                }
            ],
        )
        rc, _, error = self.lock(protocol_path, receipt_path)
        self.assertEqual(rc, 0, error)
        state = self.load()["build_state"]
        scope = state["scope"]
        self.assertEqual(scope["lock_mode"], "protocol")
        self.assertEqual(scope["artifact"], str(protocol_path))
        self.assertEqual(scope["protocol_sha256"], canonical_hash(protocol))
        self.assertEqual(scope["generated_paths"], {item["artifact_type"]: item["path"] for item in receipt["artifacts"]})
        self.assertEqual(
            state["gates"],
            {"framework": "PICO", "seed": "provided", "concept": "resolved-v1", "filter": "selected"},
        )
        self.assertEqual(set(state["blocks"]), {"emergency-care", "allocation"})
        self.assertEqual(state["blocks"]["allocation"]["display_label"], "Quasi-random allocation")
        self.assertEqual(state["blocks"]["allocation"]["protocol_sha256"], canonical_hash(protocol))
        self.assertEqual(scope["history"][-1]["lock_mode"], "protocol")
        self.assertEqual(self.load()["entries"][-1]["scope_version"], 1)

    def test_actual_compiler_nested_receipt_and_outputs_lock_end_to_end(self):
        protocol = self.lock_valid_protocol()
        source_dir = self.directory / "source"
        output_dir = self.directory / "generated" / "protocol-v1"
        receipt_path = self.directory / "receipts" / "v1" / "compile.json"
        protocol_path = source_dir / "review_protocol_v1.json"
        source_dir.mkdir(parents=True)
        protocol_path.write_bytes(protocol_tool.pretty_bytes(protocol))
        receipt = protocol_tool.compile_protocol(protocol_path, output_dir, receipt_path)
        self.manifest = self.directory / "manifests" / "run_manifest.json"

        rc, _, error = self.lock(protocol_path, receipt_path)

        self.assertEqual(rc, 0, error)
        state = self.load()["build_state"]
        self.assertEqual(set(state["blocks"]), {"condition", "intervention"})
        self.assertEqual(state["scope"]["protocol_sha256"], protocol_tool.canonical_sha256(protocol))
        self.assertTrue(all(not Path(row["path"]).is_absolute() for row in receipt["artifacts"]))

    def test_external_validation_requires_source_status_and_resolved_benchmark(self):
        protocol = self.lock_valid_protocol()
        protocol["information_source_mode"] = "pubmed-plus-external-validation"
        protocol["external_validation"] = {
            "status": "enabled",
            "purpose": "pubmed-leak-detection",
            "sources": ["clinicaltrials.gov", "who-ictrp"],
        }
        protocol_path = self.directory / "review_protocol_v1.json"
        output_dir = self.directory / "protocol-v1"
        receipt_path = self.directory / "protocol-v1" / "compile.json"
        protocol_path.write_bytes(protocol_tool.pretty_bytes(protocol))
        protocol_tool.compile_protocol(protocol_path, output_dir, receipt_path)
        rc, _, error = self.lock(protocol_path, receipt_path)
        self.assertEqual(rc, 0, error)

        issues = manifest_tool.complete_loop_readiness(self.load(), self.manifest)
        self.assertTrue(any("external registry sources lack" in issue for issue in issues))
        self.assertTrue(any("no external-pubmed-benchmark" in issue for issue in issues))

        binding = {
            "protocol_id": protocol["protocol_id"],
            "scope_version": protocol["scope_version"],
            "protocol_sha256": protocol_tool.canonical_sha256(protocol),
        }
        ctgov = self.directory / "ctgov.json"
        ctgov.write_text(json.dumps({
            "operation": "registry-search", "source": "clinicaltrials.gov", "status": "complete", **binding,
        }), encoding="utf-8")
        who = self.directory / "who.json"
        who.write_text(json.dumps({
            "operation": "registry-source-status", "source": "who-ictrp", "status": "unavailable", **binding,
        }), encoding="utf-8")
        benchmark = self.directory / "benchmark.json"
        benchmark.write_text(json.dumps({
            "operation": "external-pubmed-benchmark",
            "handoff_blocked": False,
            "summary": {"unresolved_pubmed_misses": []},
            **binding,
        }), encoding="utf-8")
        self.add("registry-search", "registry_sentinel.py clinicaltrials-search", ctgov)
        self.add("artifact", "registry_sentinel.py source-status", who)
        self.add("external-recall-validation", "registry_sentinel.py evaluate-pubmed", benchmark)

        issues = manifest_tool.complete_loop_readiness(self.load(), self.manifest)
        self.assertFalse(any("external registry sources lack" in issue for issue in issues))
        self.assertFalse(any("no external-pubmed-benchmark" in issue for issue in issues))
        self.assertFalse(any("unresolved eligible linked PMID" in issue for issue in issues))

    def test_lock_protocol_rejects_protocol_hash_mismatch(self):
        protocol_path, receipt_path, _, receipt = self.compiled_protocol()
        receipt["protocol_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        rc, _, error = self.lock(protocol_path, receipt_path)
        self.assertEqual(rc, 1)
        self.assertIn("protocol_sha256", error)
        self.assertFalse(self.manifest.exists())

    def test_lock_protocol_rejects_tampered_generated_artifact(self):
        protocol_path, receipt_path, _, receipt = self.compiled_protocol()
        Path(receipt["artifacts"][0]["path"]).write_text("{}\n", encoding="utf-8")
        rc, _, error = self.lock(protocol_path, receipt_path)
        self.assertEqual(rc, 1)
        self.assertIn("artifact hash mismatch", error)

    def test_lock_protocol_rejects_generated_from_mismatch(self):
        protocol_path, receipt_path, _, receipt = self.compiled_protocol()
        artifact_path = Path(receipt["artifacts"][0]["path"])
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["generated_from"]["sha256"] = "f" * 64
        artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt["artifacts"][0]["sha256"] = file_hash(artifact_path)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        rc, _, error = self.lock(protocol_path, receipt_path)
        self.assertEqual(rc, 1)
        self.assertIn("not bound to the current protocol", error)

    def test_lock_protocol_rejects_block_registry_drift(self):
        protocol_path, receipt_path, _, receipt = self.compiled_protocol()
        registry_row = next(item for item in receipt["artifacts"] if item["artifact_type"] == "block-registry")
        registry_path = Path(registry_row["path"])
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["blocks"][0]["block_id"] = "wrong-id"
        registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        registry_row["sha256"] = file_hash(registry_path)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        rc, _, error = self.lock(protocol_path, receipt_path)
        self.assertEqual(rc, 1)
        self.assertIn("invalid IDs", error)

    def test_protocol_reentry_requires_next_version_and_clears_dependent_state(self):
        v1, r1, _, _ = self.compiled_protocol()
        self.assertEqual(self.lock(v1, r1)[0], 0)
        data = self.load()
        state = data["build_state"]
        state["candidate_screening"] = {"status": "complete", "artifact": "old.json"}
        state["critic_rounds"] = [{"round": 1}]
        state["revision_cycles"] = [{"revision_round": 1}]
        state["recall_offer"] = "done"
        self.manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

        v2, r2, protocol2, _ = self.compiled_protocol(
            version=2,
            concepts=[{"id": "new-core", "label": "Revised core concept", "role": "essential"}],
        )
        rc, _, error = self.lock(v2, r2)
        self.assertEqual(rc, 0, error)
        state = self.load()["build_state"]
        self.assertEqual(state["scope"]["version"], 2)
        self.assertEqual(state["candidate_screening"]["status"], "pending")
        self.assertEqual(state["critic_rounds"], [])
        self.assertEqual(state["revision_cycles"], [])
        self.assertEqual(state["recall_offer"], "pending")
        self.assertEqual(set(state["blocks"]), {"new-core"})
        self.assertEqual(state["blocks"]["new-core"]["protocol_sha256"], canonical_hash(protocol2))
        self.assertEqual(len(state["scope"]["history"]), 2)

    def test_protocol_reentry_rejects_version_skip(self):
        v1, r1, _, _ = self.compiled_protocol()
        self.assertEqual(self.lock(v1, r1)[0], 0)
        v3, r3, _, _ = self.compiled_protocol(version=3)
        rc, _, error = self.lock(v3, r3)
        self.assertEqual(rc, 1)
        self.assertIn("increment scope_version by one", error)
        self.assertEqual(self.load()["build_state"]["scope"]["version"], 1)

    def test_same_protocol_lock_is_idempotent(self):
        protocol_path, receipt_path, _, _ = self.compiled_protocol()
        self.assertEqual(self.lock(protocol_path, receipt_path)[0], 0)
        self.assertEqual(self.lock(protocol_path, receipt_path)[0], 0)
        data = self.load()
        self.assertEqual(len(data["build_state"]["scope"]["history"]), 1)
        self.assertEqual(len(data["entries"]), 1)

    def test_reopened_protocol_cannot_be_relocked_at_same_version(self):
        protocol_path, receipt_path, _, _ = self.compiled_protocol()
        self.assertEqual(self.lock(protocol_path, receipt_path)[0], 0)
        self.assertEqual(self.state("reopen-scope", "--reason", "Structural scope change")[0], 0)
        rc, _, error = self.lock(protocol_path, receipt_path)
        self.assertEqual(rc, 1)
        self.assertIn("increment scope_version by one", error)

    def test_completion_rechecks_current_protocol_and_block_binding(self):
        protocol_path, receipt_path, protocol, _ = self.compiled_protocol()
        self.assertEqual(self.lock(protocol_path, receipt_path)[0], 0)
        protocol["review"]["question"] = "Tampered after compile"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        rc, receipt, _ = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertTrue(any("current protocol verification failed" in issue for issue in receipt["issues"]))

        # Restore the protocol, then demonstrate that block state is hash/scope bound too.
        protocol["review"]["question"] = "How does quasi-randomization perform in emergency trials?"
        protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
        data = self.load()
        data["build_state"]["blocks"]["allocation"]["scope_version"] = 99
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        rc, receipt, _ = self.state("check-complete")
        self.assertEqual(rc, 1)
        self.assertTrue(any("stale scope version" in issue for issue in receipt["issues"]))

    def test_completion_rejects_unbound_candidate_critic_strategy_and_audit_json(self):
        protocol_path, receipt_path, _, _ = self.compiled_protocol()
        self.assertEqual(self.lock(protocol_path, receipt_path)[0], 0)

        ledger = self.directory / "candidate_ledger.json"
        ledger.write_text(json.dumps({"scope_version": 1, "records": []}), encoding="utf-8")
        validation = self.directory / "candidate_validation.json"
        validation.write_text(
            json.dumps({"operation": "candidate-ledger-validate", "ok": True, "summary": {"scope_version": 1}}),
            encoding="utf-8",
        )
        two_strand = self.directory / "two_strand.json"
        two_strand.write_text(json.dumps({"operation": "two-strand", "ok": True, "scope_version": 1}), encoding="utf-8")
        burden = self.directory / "screening_burden.json"
        burden.write_text(json.dumps({"operation": "screening-burden", "ok": True, "scope_version": 1}), encoding="utf-8")
        audit_json = self.directory / "audit_scaffold.json"
        audit_json.write_text(json.dumps({"scope_version": 1, "audit_outline": {}}), encoding="utf-8")
        self.add("artifact", "strategy_analysis.py two-strand", two_strand)
        self.add("artifact", "screening_burden.py evaluate", burden)
        self.add("artifact", "pubmed_tool.py audit-scaffold", audit_json)

        data = self.load()
        state = data["build_state"]
        state["candidate_screening"] = {
            "status": "complete",
            "artifact": str(ledger),
            "validation_artifact": str(validation),
            "summary": {"scope_version": 1, "independent_holdout_available": False},
            "reason": "",
        }
        state["critic_rounds"] = [
            {
                "round": 1,
                "scope_version": 1,
                "critic_version": 2,
                "overall_status": "pass",
                "open_actionable": 0,
                "entry_seq": 999,
            }
        ]
        self.manifest.write_text(json.dumps(data), encoding="utf-8")

        rc, result, _ = self.state("check-complete")
        self.assertEqual(rc, 1)
        joined = "\n".join(result["issues"])
        for label in (
            "candidate-screening summary protocol_id",
            "candidate ledger protocol_id",
            "candidate-ledger validation summary protocol_id",
            "critic round 1 summary protocol_id",
            "latest two-strand artifact protocol_id",
            "latest screening-burden artifact protocol_id",
            "audit JSON artifact",
        ):
            self.assertIn(label, joined)

    def test_legacy_lock_scope_remains_supported_and_marked_legacy(self):
        scope_path = self.directory / "retrieval_scope_v1.json"
        scope_path.write_text(
            json.dumps(
                {
                    "scope_version": 1,
                    "review_question": "Legacy question",
                    "framework": "PICO",
                    "essential_blocks": ["condition"],
                    "unresolved_ambiguities": [],
                }
            ),
            encoding="utf-8",
        )
        rc, _, error = self.state("lock-scope", "--scope-file", scope_path)
        self.assertEqual(rc, 0, error)
        scope = self.load()["build_state"]["scope"]
        self.assertEqual(scope["lock_mode"], "legacy")
        self.assertEqual(scope["protocol_sha256"], "")
        self.assertEqual(manifest_tool.protocol_scope_readiness(scope, self.load()["build_state"], self.manifest), [])


if __name__ == "__main__":
    unittest.main()
