import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOOK_DIR = ROOT / ".codex" / "hooks"
CODEX_CONFIG = ROOT / ".codex" / "hooks.json"
CLAUDE_CONFIG = ROOT / ".claude" / "settings.json"
HOOK_SCRIPTS = {
    "SessionStart": "session_context.py",
    "UserPromptSubmit": "prompt_secret_guard.py",
    "Stop": "stop_gate.py",
}
CLAUDE_HOOK_ARGS = {
    event_name: [f"${{CLAUDE_PROJECT_DIR}}/.codex/hooks/{script_name}"]
    for event_name, script_name in HOOK_SCRIPTS.items()
}
CLAUDE_HOOK_ARGS["UserPromptSubmit"].append("--claude")


def claude_event(event_name: str, *, cwd: Path | str = ROOT, **fields: object) -> dict[str, object]:
    event: dict[str, object] = {
        "session_id": "test-session",
        "transcript_path": str(ROOT / ".test-transcript.jsonl"),
        "cwd": str(cwd),
        "permission_mode": "default",
        "hook_event_name": event_name,
    }
    event.update(fields)
    return event


def run_hook(
    name: str,
    event: dict[str, object],
    *,
    script_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK_DIR / name), *(script_args or [])],
        cwd=ROOT,
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


class HookConfigurationTests(unittest.TestCase):
    def test_configuration_is_cross_platform_and_bounded(self):
        config = json.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(set(config), {"hooks"})
        self.assertEqual(set(config["hooks"]), {"SessionStart", "UserPromptSubmit", "Stop"})
        self.assertEqual(config["hooks"]["SessionStart"][0]["matcher"], "^(startup|resume|clear|compact)$")
        for groups in config["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    self.assertEqual(hook["type"], "command")
                    self.assertIn("git rev-parse --show-toplevel", hook["command"])
                    self.assertIn("commandWindows", hook)
                    self.assertNotIn('"', hook["commandWindows"])
                    self.assertIn("alias.codex=!.codex/hooks/", hook["commandWindows"])
                    self.assertLessEqual(hook["timeout"], 30)

    @unittest.skipUnless(sys.platform == "win32", "Windows command-runner regression test")
    def test_windows_session_command_runs_under_supported_shells(self):
        config = json.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        command = config["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]
        event = claude_event("SessionStart", source="startup")
        for shell in (
            ["cmd.exe", "/d", "/s", "/c"],
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"],
        ):
            with self.subTest(shell=shell[0]):
                result = subprocess.run(
                    [*shell, command],
                    cwd=ROOT,
                    input=json.dumps(event),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout)
                self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_claude_configuration_reuses_codex_hook_engine(self):
        codex = json.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        claude = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(
            claude["$schema"],
            "https://json.schemastore.org/claude-code-settings.json",
        )
        self.assertEqual(set(claude), {"$schema", "hooks"})
        self.assertEqual(set(claude["hooks"]), set(HOOK_SCRIPTS))
        self.assertEqual(
            claude["hooks"]["SessionStart"][0]["matcher"],
            "startup|resume|clear|compact|fork",
        )

        for event_name, script_name in HOOK_SCRIPTS.items():
            with self.subTest(event=event_name):
                codex_hook = codex["hooks"][event_name][0]["hooks"][0]
                claude_hook = claude["hooks"][event_name][0]["hooks"][0]
                self.assertEqual(claude_hook["type"], "command")
                self.assertEqual(claude_hook["command"], "python")
                self.assertEqual(
                    claude_hook["args"],
                    CLAUDE_HOOK_ARGS[event_name],
                )
                self.assertEqual(claude_hook["timeout"], codex_hook["timeout"])
                self.assertEqual(claude_hook["statusMessage"], codex_hook["statusMessage"])

    def test_claude_exec_form_runs_session_hook(self):
        config = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
        hook = config["hooks"]["SessionStart"][0]["hooks"][0]
        args = [argument.replace("${CLAUDE_PROJECT_DIR}", str(ROOT)) for argument in hook["args"]]
        result = subprocess.run(
            [hook["command"], *args],
            cwd=ROOT,
            input=json.dumps(claude_event("SessionStart", source="fork")),
            text=True,
            capture_output=True,
            check=False,
            timeout=hook["timeout"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "SessionStart")


class PromptSecretGuardTests(unittest.TestCase):
    def test_blocks_assignment_without_echoing_value(self):
        value = "A" * 32
        result = run_hook(
            "prompt_secret_guard.py",
            claude_event("UserPromptSubmit", prompt=f"NCBI_API_KEY={value}"),
            script_args=["--claude"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertTrue(response["suppressOriginalPrompt"])
        self.assertNotIn(value, result.stdout)

    def test_codex_block_response_omits_claude_only_field(self):
        result = run_hook(
            "prompt_secret_guard.py",
            claude_event("UserPromptSubmit", prompt="GH_TOKEN=" + "C" * 32),
        )
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertNotIn("suppressOriginalPrompt", response)

    def test_allows_obvious_placeholder(self):
        result = run_hook(
            "prompt_secret_guard.py",
            claude_event("UserPromptSubmit", prompt="NCBI_API_KEY=your-key-placeholder"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_warns_without_blocking_personal_path(self):
        path = "C:" + "\\Users\\" + "someone\\Downloads\\input.txt"
        result = run_hook(
            "prompt_secret_guard.py",
            claude_event("UserPromptSubmit", prompt=f"Review {path}"),
        )
        response = json.loads(result.stdout)
        self.assertNotIn("decision", response)
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_noops_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_hook(
                "prompt_secret_guard.py",
                claude_event("UserPromptSubmit", cwd=directory, prompt="NCBI_API_KEY=" + "B" * 32),
            )
        self.assertEqual(result.stdout, "")


class SessionContextTests(unittest.TestCase):
    def test_maintenance_context_at_repository_root(self):
        result = run_hook(
            "session_context.py",
            claude_event("SessionStart", source="startup", model="claude-sonnet-4-5"),
        )
        response = json.loads(result.stdout)
        context = response["hookSpecificOutput"]["additionalContext"]
        self.assertIn("maintenance mode", context)

    def test_active_manifest_summary_does_not_include_pending_question_text(self):
        with tempfile.TemporaryDirectory(prefix="hook-run-", dir=ROOT) as directory:
            run_dir = Path(directory)
            manifest = {
                "topic_slug": "demo-topic",
                "entries": [{"seq": 1}],
                "build_state": {
                    "current_stage": "scope",
                    "pending_user_question": "untrusted question text",
                    "scope": {"status": "locked", "version": 1},
                    "gates": {"concept": "passed"},
                },
            }
            (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = run_hook(
                "session_context.py",
                claude_event("SessionStart", cwd=run_dir, source="compact"),
            )
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("pending-user-question=yes", context)
        self.assertNotIn("untrusted question text", context)


class StopGateTests(unittest.TestCase):
    def test_repository_hygiene_passes_without_continuation(self):
        result = run_hook(
            "stop_gate.py",
            claude_event(
                "Stop",
                stop_hook_active=False,
                last_assistant_message="Completed the requested maintenance.",
                background_tasks=[],
                session_crons=[],
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})

    def test_incomplete_run_is_advisory(self):
        with tempfile.TemporaryDirectory(prefix="hook-run-", dir=ROOT) as directory:
            run_dir = Path(directory)
            manifest = {
                "manifest_version": "1.1",
                "skill": "pubmed-search-builder",
                "skill_version": "2.0.0",
                "topic_slug": "demo",
                "created_utc": "2026-01-01T00:00:00Z",
                "updated_utc": "2026-01-01T00:00:00Z",
                "working_dir": ".",
                "entries": [],
                "superseded": [],
                "build_state": {},
            }
            (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = run_hook(
                "stop_gate.py",
                claude_event(
                    "Stop",
                    cwd=run_dir,
                    stop_hook_active=False,
                    last_assistant_message="The intake needs a user decision.",
                    background_tasks=[],
                    session_crons=[],
                ),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response["continue"])
        self.assertIn("advisory", response["systemMessage"])
        self.assertNotIn("decision", response)

    def test_hygiene_failure_blocks_once_then_avoids_stop_loop(self):
        spec = importlib.util.spec_from_file_location("test_stop_gate", HOOK_DIR / "stop_gate.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(HOOK_DIR), *sys.path]):
            spec.loader.exec_module(module)

        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="failure")
        for active in (False, True):
            with self.subTest(stop_hook_active=active):
                captured: list[dict[str, object]] = []
                with (
                    mock.patch.object(
                        module,
                        "read_event",
                        return_value=claude_event("Stop", stop_hook_active=active),
                    ),
                    mock.patch.object(module, "event_cwd", return_value=ROOT),
                    mock.patch.object(module, "find_nearest_manifest", return_value=None),
                    mock.patch.object(module, "run_hygiene_gate", return_value=failed),
                    mock.patch.object(module, "emit", side_effect=captured.append),
                ):
                    self.assertEqual(module.main(), 0)

                self.assertEqual(len(captured), 1)
                if active:
                    self.assertTrue(captured[0]["continue"])
                    self.assertNotIn("decision", captured[0])
                else:
                    self.assertEqual(captured[0]["decision"], "block")


if __name__ == "__main__":
    unittest.main()
