import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK_DIR = ROOT / ".codex" / "hooks"


def run_hook(name: str, event: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK_DIR / name)],
        cwd=ROOT,
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


class HookConfigurationTests(unittest.TestCase):
    def test_configuration_is_cross_platform_and_bounded(self):
        config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
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
                    self.assertIn("alias.codex=!python${IFS}", hook["commandWindows"])
                    self.assertLessEqual(hook["timeout"], 30)

    @unittest.skipUnless(sys.platform == "win32", "Windows command-runner regression test")
    def test_windows_session_command_survives_codex_cmd_wrapping(self):
        config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        command = config["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]
        event = {"cwd": str(ROOT), "hook_event_name": "SessionStart", "source": "startup"}
        result = subprocess.run(
            f'cmd.exe /d /s /c "{command}"',
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


class PromptSecretGuardTests(unittest.TestCase):
    def test_blocks_assignment_without_echoing_value(self):
        value = "A" * 32
        result = run_hook(
            "prompt_secret_guard.py",
            {"cwd": str(ROOT), "hook_event_name": "UserPromptSubmit", "prompt": f"NCBI_API_KEY={value}"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["decision"], "block")
        self.assertNotIn(value, result.stdout)

    def test_allows_obvious_placeholder(self):
        result = run_hook(
            "prompt_secret_guard.py",
            {
                "cwd": str(ROOT),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "NCBI_API_KEY=your-key-placeholder",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_warns_without_blocking_personal_path(self):
        path = "C:" + "\\Users\\" + "someone\\Downloads\\input.txt"
        result = run_hook(
            "prompt_secret_guard.py",
            {"cwd": str(ROOT), "hook_event_name": "UserPromptSubmit", "prompt": f"Review {path}"},
        )
        response = json.loads(result.stdout)
        self.assertNotIn("decision", response)
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_noops_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_hook(
                "prompt_secret_guard.py",
                {"cwd": directory, "hook_event_name": "UserPromptSubmit", "prompt": "NCBI_API_KEY=" + "B" * 32},
            )
        self.assertEqual(result.stdout, "")


class SessionContextTests(unittest.TestCase):
    def test_maintenance_context_at_repository_root(self):
        result = run_hook(
            "session_context.py",
            {"cwd": str(ROOT), "hook_event_name": "SessionStart", "source": "startup"},
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
                {"cwd": str(run_dir), "hook_event_name": "SessionStart", "source": "compact"},
            )
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("pending-user-question=yes", context)
        self.assertNotIn("untrusted question text", context)


class StopGateTests(unittest.TestCase):
    def test_repository_hygiene_passes_without_continuation(self):
        result = run_hook(
            "stop_gate.py",
            {"cwd": str(ROOT), "hook_event_name": "Stop", "stop_hook_active": False},
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
                {"cwd": str(run_dir), "hook_event_name": "Stop", "stop_hook_active": False},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response["continue"])
        self.assertIn("advisory", response["systemMessage"])
        self.assertNotIn("decision", response)


if __name__ == "__main__":
    unittest.main()
