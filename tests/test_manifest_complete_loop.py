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

    def add(self, kind, command, *, output=None, count=None, label=None, block=None):
        args = ["add", "--manifest", str(self.manifest), "--kind", kind, "--command", command]
        if output is not None:
            args += ["--output", str(output)]
        if count is not None:
            args += ["--count", str(count)]
        if label is not None:
            args += ["--label", label]
        if block is not None:
            args += ["--block", block]
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
        self.state("register-block", "condition")
        self.add("mesh", "python scripts/mesh_tool.py sweep --concept condition --output mesh.json", block="condition")
        self.add("search", "python scripts/pubmed_tool.py search --query-file condition.txt --retmax 0", count=2000, block="condition")
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

        revision = self.write_json(
            "revision_cycle_1.json",
            {
                "revision_round": 1,
                "critic_round": 1,
                "scope_version": 1,
                "trigger_finding": "Missing historical synonym",
                "classification": "lexical",
                "change": "Added legacy condition term",
                "evidence_files": ["sample.json"],
                "required_reprobe": ["condition block count"],
                "strategy_file": "strategy_v2.txt",
                "disposition": "accepted",
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
        )
        final_qa = self.write_json("final_qa.json", {"hook": "pre_final_strategy_qa", "ok": True})
        self.add("qa", "python scripts/hooks_tool.py final-qa --strategy-file strategy_v2.txt", output=final_qa)
        audit = self.dir / "audit_demo.md"
        audit.write_text("# Audit", encoding="utf-8")
        self.add("artifact", "python scripts/audit_markdown.py audit.json --output audit_demo.md", output=audit)

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
