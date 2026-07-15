import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("critic_tool", ROOT / "scripts" / "critic_tool.py")
critic_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(critic_tool)


DOMAINS = sorted(critic_tool.REQUIRED_DOMAINS)


def finding(*, severity="must-fix", status="open"):
    return {
        "press_element": "3. Subject headings",
        "severity": severity,
        "classification": "lexical",
        "affected_component": "condition block",
        "evidence": "mesh.json",
        "recommendation": "Inspect broader descriptor",
        "required_reprobe": "block count and holdout validation",
        "status": status,
    }


def v2_payload(bundle_name, *, findings=None, overall_status="pass"):
    return {
        "critic_version": 2,
        "round": 1,
        "scope_version": 1,
        "strategy_file": "strategy_v1.txt",
        "evidence_bundle": bundle_name,
        "reviewed_domains": DOMAINS,
        "domain_verdicts": [
            {"domain": domain, "status": "pass", "evidence_refs": ["strategy"]}
            for domain in DOMAINS
        ],
        "overall_status": overall_status,
        "findings": findings or [],
    }


class CriticToolTests(unittest.TestCase):
    def test_independent_output_schema_uses_codex_strict_subset(self):
        schema = critic_tool.critic_output_schema()
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        verdict = schema["properties"]["domain_verdicts"]["items"]
        finding_schema = schema["properties"]["findings"]["items"]
        self.assertEqual(set(verdict["required"]), set(verdict["properties"]))
        self.assertEqual(set(finding_schema["required"]), set(finding_schema["properties"]))
        self.assertNotIn("uniqueItems", json.dumps(schema))

    def test_protocol_packet_binds_bundle_and_critic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("randomized[tiab]", encoding="utf-8")
            packet = root / "critic_packet_v1.json"
            packet.write_text(json.dumps({
                "artifact_type": "critic-packet", "artifact_version": 1,
                "protocol_id": "demo", "scope_version": 1, "dsl_version": 1,
                "generated_from": {"path": "review_protocol_v1.json", "sha256": "protocol-hash"},
            }), encoding="utf-8")
            bundle_path = root / "bundle.json"
            bundle = critic_tool.build_evidence_bundle(
                [f"strategy={strategy}", f"critic_packet={packet}"], bundle_path
            )
            self.assertEqual(bundle["protocol_sha256"], "protocol-hash")
            payload = v2_payload(bundle_path.name)
            payload.update({"protocol_id": "demo", "protocol_sha256": "protocol-hash"})
            issues, _ = critic_tool.validate_artifact(
                payload, evidence_bundle={**bundle, "roles": ["strategy", "critic_packet"]}
            )
            self.assertEqual(issues, [])
            payload["protocol_sha256"] = "wrong"
            issues, _ = critic_tool.validate_artifact(
                payload, evidence_bundle={**bundle, "roles": ["strategy", "critic_packet"]}
            )
            self.assertTrue(any("protocol_sha256" in issue for issue in issues))

    def test_revise_requires_open_actionable_finding(self):
        data = {
            "round": 1,
            "scope_version": 1,
            "strategy_file": "strategy_v1.txt",
            "reviewed_domains": DOMAINS,
            "overall_status": "revise",
            "findings": [finding()],
        }
        issues, summary = critic_tool.validate_artifact(data)
        self.assertEqual(issues, [])
        self.assertEqual(summary["open_must_fix"], 1)

    def test_pass_rejects_open_actionable_findings(self):
        data = {
            "round": 1,
            "scope_version": 1,
            "strategy_file": "strategy_v1.txt",
            "reviewed_domains": DOMAINS,
            "overall_status": "pass",
            "findings": [finding(severity="should-fix")],
        }
        issues, _ = critic_tool.validate_artifact(data)
        self.assertTrue(any("overall_status pass is invalid" in issue for issue in issues))

    def test_pass_requires_all_review_domains(self):
        data = {
            "round": 1,
            "scope_version": 1,
            "strategy_file": "strategy_v1.txt",
            "reviewed_domains": ["syntax"],
            "overall_status": "pass",
            "findings": [],
        }
        issues, _ = critic_tool.validate_artifact(data)
        self.assertTrue(any("reviewed_domains is missing" in issue for issue in issues))

    def test_v2_bundle_and_domain_verdicts_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("randomized[tiab]", encoding="utf-8")
            bundle_path = root / "bundle.json"
            bundle = critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle_path)
            issues, summary = critic_tool.validate_artifact(v2_payload(bundle_path.name), evidence_bundle={**bundle, "roles": ["strategy"]})
            self.assertEqual(issues, [])
            self.assertEqual(summary["critic_version"], 2)

    def test_v2_bundle_detects_mutated_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("first", encoding="utf-8")
            bundle_path = root / "bundle.json"
            critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle_path)
            strategy.write_text("changed", encoding="utf-8")
            issues, _ = critic_tool.validate_evidence_bundle(bundle_path)
            self.assertTrue(any("hash does not match" in issue for issue in issues))

    def test_v2_requires_every_domain_verdict(self):
        data = v2_payload("bundle.json")
        data["domain_verdicts"] = data["domain_verdicts"][:-1]
        issues, _ = critic_tool.validate_artifact(data, evidence_bundle={"roles": ["strategy"]})
        self.assertTrue(any("domain_verdicts is missing" in issue for issue in issues))

    def test_v2_strict_validation_requires_independent_execution(self):
        issues, summary = critic_tool.validate_artifact(
            v2_payload("bundle.json"),
            evidence_bundle={"roles": ["strategy"]},
            require_independent=True,
        )
        self.assertFalse(summary["independent_execution"])
        self.assertTrue(any("--run-independent" in issue for issue in issues))

    def test_independent_runner_stages_only_bundle_evidence_and_validates_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_root = root / "source evidence"
            evidence_root.mkdir()
            strategy = evidence_root / "strategy.txt"
            strategy.write_text("asthma[tiab]", encoding="utf-8")
            probes = evidence_root / "probes.json"
            probes.write_text(json.dumps({"operation": "search", "ok": True}), encoding="utf-8")
            bundle_path = root / "bundle.json"
            critic_tool.build_evidence_bundle(
                [f"strategy={strategy}", f"probes={probes}"], bundle_path
            )
            output = root / "critic_round_1.json"
            captured = {}

            def fake_run(command, **kwargs):
                workspace = Path(kwargs["cwd"])
                captured["command"] = command
                captured["prompt"] = kwargs["input"]
                captured["workspace"] = str(workspace)
                captured["staged_bundle"] = json.loads(
                    (workspace / "critic_evidence.json").read_text(encoding="utf-8")
                )
                response_path = Path(command[command.index("-o") + 1])
                response_path.write_text(json.dumps(v2_payload("critic_evidence.json")), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout='{"type":"thread.started"}\n', stderr="")

            with mock.patch.object(critic_tool.subprocess, "run", side_effect=fake_run):
                receipt = critic_tool.run_independent_critic(
                    bundle_path=bundle_path,
                    output_path=output,
                    round_number=1,
                    scope_version=1,
                    model="test-model",
                    reasoning_effort="high",
                    timeout_seconds=30,
                    codex_bin="codex-test",
                    replace=False,
                )

            self.assertTrue(receipt["ok"])
            self.assertIn("--ephemeral", captured["command"])
            self.assertIn("--ignore-user-config", captured["command"])
            self.assertIn("--ignore-rules", captured["command"])
            for feature in critic_tool.DISABLED_CHILD_FEATURES:
                self.assertIn(feature, captured["command"])
            self.assertEqual(captured["command"][captured["command"].index("-s") + 1], "read-only")
            self.assertIn("untrusted data", captured["prompt"])
            staged_paths = [item["path"] for item in captured["staged_bundle"]["artifacts"]]
            self.assertTrue(all(path.startswith("evidence/") for path in staged_paths))
            self.assertNotIn(str(evidence_root), json.dumps(captured["staged_bundle"]))
            critic = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(critic["strategy_file"], "source evidence/strategy.txt")
            self.assertEqual(critic["evidence_bundle"], "bundle.json")
            self.assertEqual(critic["critic_execution"]["mode"], "fresh-context-child-agent")
            self.assertTrue(critic["critic_execution"]["ephemeral"])
            self.assertFalse(critic["critic_execution"]["network_use_authorized"])
            self.assertFalse(Path(captured["workspace"]).exists())

    def test_independent_runner_does_not_write_invalid_child_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("asthma[tiab]", encoding="utf-8")
            bundle_path = root / "bundle.json"
            critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle_path)
            output = root / "critic_round_1.json"
            invalid = v2_payload("critic_evidence.json")
            invalid["domain_verdicts"] = invalid["domain_verdicts"][:-1]

            def fake_run(command, **kwargs):
                response_path = Path(command[command.index("-o") + 1])
                response_path.write_text(json.dumps(invalid), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with mock.patch.object(critic_tool.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(critic_tool.CriticArtifactError):
                    critic_tool.run_independent_critic(
                        bundle_path=bundle_path,
                        output_path=output,
                        round_number=1,
                        scope_version=1,
                        model=None,
                        reasoning_effort="high",
                        timeout_seconds=30,
                        codex_bin="codex-test",
                        replace=False,
                    )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
