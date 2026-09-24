"""The isolated runner launches a fresh-context child and records how, for either CLI."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("isolated_runner_test", ROOT / "scripts" / "isolated_runner.py")
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)

CRITIC_SPEC = importlib.util.spec_from_file_location("critic_tool_runner_test", ROOT / "scripts" / "critic_tool.py")
critic_tool = importlib.util.module_from_spec(CRITIC_SPEC)
assert CRITIC_SPEC.loader is not None
CRITIC_SPEC.loader.exec_module(critic_tool)

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
}


def claude_envelope(**fields):
    envelope = {"type": "result", "subtype": "success", "is_error": False, "result": "", "permission_denials": []}
    envelope.update(fields)
    return json.dumps(envelope)


class ClaudeRunnerTests(unittest.TestCase):
    def run_claude(self, stdout, returncode=0):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
            result = runner.run_isolated(
                runner=runner.CLAUDE_RUNNER,
                workspace=Path(tmp),
                prompt="Report the answer.",
                schema=SCHEMA,
                model=None,
                reasoning_effort="high",
                timeout_seconds=30,
                executable="claude-test",
            )
        return result, captured

    def test_child_is_launched_read_only_without_user_customisations(self):
        (_draft, _execution), captured = self.run_claude(claude_envelope(structured_output={"answer": 42}))
        command = captured["command"]
        for flag in ("-p", "--safe-mode", "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--tools") + 1], "Read,Glob,Grep")
        self.assertEqual(command[command.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(command[command.index("--output-format") + 1], "json")
        schema = json.loads(command[command.index("--json-schema") + 1])
        self.assertNotIn("$schema", schema)
        self.assertEqual(captured["kwargs"]["input"], "Report the answer.")

    def test_structured_output_is_returned_with_a_verifiable_execution_record(self):
        (draft, execution), _ = self.run_claude(claude_envelope(structured_output={"answer": 42}, total_cost_usd=0.01))
        self.assertEqual(draft, {"answer": 42})
        self.assertEqual(execution["runner"], runner.CLAUDE_RUNNER)
        self.assertEqual(execution["allowed_tools"], ["Read", "Glob", "Grep"])
        self.assertEqual(execution["permission_denials"], 0)
        self.assertEqual(runner.execution_issues(execution, "execution"), [])

    def test_json_result_text_is_accepted_when_no_structured_output_is_returned(self):
        (draft, _execution), _ = self.run_claude(claude_envelope(result='```json\n{"answer": 7}\n```'))
        self.assertEqual(draft, {"answer": 7})

    def test_an_error_result_is_raised_with_its_message(self):
        with self.assertRaisesRegex(runner.IsolatedRunnerError, "Failed to authenticate"):
            self.run_claude(claude_envelope(is_error=True, result="Failed to authenticate: OAuth session expired"), returncode=1)

    def test_a_widened_tool_policy_is_not_accepted_as_isolated(self):
        (_draft, execution), _ = self.run_claude(claude_envelope(structured_output={"answer": 1}))
        execution["allowed_tools"] = ["Read", "Glob", "Grep", "Bash"]
        self.assertTrue(any("allowed_tools" in issue for issue in runner.execution_issues(execution, "execution")))


class WorkspaceCleanupTests(unittest.TestCase):
    def test_a_briefly_locked_workspace_is_retried_and_never_masks_the_result(self):
        real_rmtree = runner.shutil.rmtree
        calls = []

        def locked_once(path):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError("[WinError 32] in use by another process")
            real_rmtree(path)

        with mock.patch.object(runner.time, "sleep"), mock.patch.object(runner.shutil, "rmtree", side_effect=locked_once):
            with runner.isolated_workspace("runner-test-") as workspace:
                (workspace / "staged.json").write_text("{}", encoding="utf-8")
        self.assertEqual(len(calls), 2)
        self.assertFalse(workspace.exists())

    def test_a_workspace_that_stays_locked_is_left_behind_without_raising(self):
        with mock.patch.object(runner.time, "sleep"), mock.patch.object(
            runner.shutil, "rmtree", side_effect=PermissionError("in use")
        ):
            with self.assertRaisesRegex(ValueError, "child result"):
                with runner.isolated_workspace("runner-test-") as workspace:
                    raise ValueError("child result")
        real_workspace = workspace
        self.assertTrue(real_workspace.exists())
        runner.shutil.rmtree(real_workspace)


class RunnerResolutionTests(unittest.TestCase):
    def test_explicit_choice_and_environment_override_win(self):
        self.assertEqual(runner.resolve_runner("codex-cli"), "codex-cli")
        with mock.patch.dict(os.environ, {runner.RUNNER_ENV: "claude-code-cli"}):
            self.assertEqual(runner.resolve_runner("auto"), "claude-code-cli")

    def test_auto_prefers_claude_code_inside_claude_code_and_codex_elsewhere(self):
        def which(name):
            return f"/bin/{name}"

        with mock.patch.object(runner.shutil, "which", side_effect=which):
            with mock.patch.dict(os.environ, {"CLAUDECODE": "1", runner.RUNNER_ENV: ""}):
                self.assertEqual(runner.resolve_runner(None), "claude-code-cli")
            environment = {key: value for key, value in os.environ.items() if key not in {"CLAUDECODE", runner.RUNNER_ENV}}
            with mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(runner.resolve_runner(None), "codex-cli")

    def test_auto_falls_back_to_whichever_runner_is_installed(self):
        with mock.patch.object(runner.shutil, "which", side_effect=lambda name: "/bin/claude" if name == "claude" else None):
            environment = {key: value for key, value in os.environ.items() if key not in {"CLAUDECODE", runner.RUNNER_ENV, "CODEX_BIN", "CLAUDE_BIN"}}
            with mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(runner.resolve_runner("auto"), "claude-code-cli")

    def test_unknown_or_missing_runners_are_errors(self):
        with self.assertRaises(runner.IsolatedRunnerError):
            runner.resolve_runner("gpt-cli")
        with mock.patch.object(runner.shutil, "which", return_value=None):
            environment = {key: value for key, value in os.environ.items() if key not in {"CLAUDECODE", runner.RUNNER_ENV, "CODEX_BIN", "CLAUDE_BIN"}}
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesRegex(runner.IsolatedRunnerError, "No isolated runner"):
                    runner.resolve_runner("auto")


def critic_payload():
    return {
        "critic_version": 2,
        "round": 1,
        "scope_version": 1,
        "strategy_file": "strategy.txt",
        "evidence_bundle": "critic_evidence.json",
        "protocol_id": None,
        "protocol_sha256": None,
        "reviewed_domains": sorted(critic_tool.REQUIRED_DOMAINS),
        "domain_verdicts": [
            {"domain": domain, "status": "pass", "evidence_refs": ["strategy"], "rationale": "Reviewed the strategy."}
            for domain in sorted(critic_tool.REQUIRED_DOMAINS)
        ],
        "overall_status": "pass",
        "findings": [],
    }


class CriticOnClaudeCodeTests(unittest.TestCase):
    def test_critic_round_produced_by_claude_code_passes_independent_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("asthma[tiab]", encoding="utf-8")
            bundle = root / "bundle.json"
            critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle)
            output = root / "critic_round_1.json"
            seen = {}

            def fake_run(command, **kwargs):
                seen["files"] = sorted(path.name for path in Path(kwargs["cwd"]).iterdir())
                return subprocess.CompletedProcess(command, 0, stdout=claude_envelope(structured_output=critic_payload()), stderr="")

            with mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
                receipt = critic_tool.run_independent_critic(
                    bundle_path=bundle,
                    output_path=output,
                    round_number=1,
                    scope_version=1,
                    model=None,
                    reasoning_effort="high",
                    timeout_seconds=30,
                    replace=False,
                    runner="claude-code-cli",
                    runner_bin="claude-test",
                )
            self.assertTrue(receipt["ok"])
            self.assertEqual(receipt["runner"], "claude-code-cli")
            self.assertEqual(seen["files"], ["critic_evidence.json", "evidence"])
            critic = json.loads(output.read_text(encoding="utf-8"))
            issues, summary = critic_tool.validate_artifact(
                critic,
                evidence_bundle={**critic_tool.validate_evidence_bundle(bundle)[1], "bundle_sha256": critic_tool.sha256_file(bundle)},
                artifact_base=root,
                require_independent=True,
            )
            self.assertEqual(issues, [])
            self.assertTrue(summary["independent_execution"])
            self.assertEqual(summary["critic_execution_runner"], "claude-code-cli")

    def test_legacy_codex_bin_argument_still_selects_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = root / "strategy.txt"
            strategy.write_text("asthma[tiab]", encoding="utf-8")
            bundle = root / "bundle.json"
            critic_tool.build_evidence_bundle([f"strategy={strategy}"], bundle)

            def fake_run(command, **kwargs):
                Path(command[command.index("-o") + 1]).write_text(json.dumps(critic_payload()), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}), mock.patch.object(runner.subprocess, "run", side_effect=fake_run):
                receipt = critic_tool.run_independent_critic(
                    bundle_path=bundle,
                    output_path=root / "critic_round_1.json",
                    round_number=1,
                    scope_version=1,
                    model=None,
                    reasoning_effort="high",
                    timeout_seconds=30,
                    codex_bin="codex-test",
                    replace=False,
                )
            self.assertEqual(receipt["runner"], "codex-cli")


if __name__ == "__main__":
    unittest.main()
