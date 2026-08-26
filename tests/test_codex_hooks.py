"""Lifecycle-hook behaviour.

Hook subprocesses run the *real* gate scripts but are pointed at a throwaway workspace via
``PUBMED_SEARCH_BUILDER_HOOK_ROOT``, so no assertion here depends on which builds happen to be
sitting in the developer's ``runs/`` directory.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOOK_DIR = ROOT / ".codex" / "hooks"
CODEX_CONFIG = ROOT / ".codex" / "hooks.json"
CLAUDE_CONFIG = ROOT / ".claude" / "settings.json"
HOOK_SCRIPTS = {
    "SessionStart": "session_context.py",
    "UserPromptSubmit": "prompt_secret_guard.py",
    "PreToolUse": "tool_guard.py",
    "PostToolUse": "tool_guard.py",
    "Stop": "stop_gate.py",
}
# Every Claude entry passes --claude so the two clients keep separate session pointers.
CLAUDE_HOOK_ARGS = {
    event_name: [f"${{CLAUDE_PROJECT_DIR}}/.codex/hooks/{script_name}", "--claude"]
    for event_name, script_name in HOOK_SCRIPTS.items()
}


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
    workspace: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    if workspace is not None:
        environment["PUBMED_SEARCH_BUILDER_HOOK_ROOT"] = str(workspace)
    return subprocess.run(
        [sys.executable, str(HOOK_DIR / name), *(script_args or [])],
        cwd=ROOT,
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env=environment,
    )


def response_of(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout) if result.stdout.strip() else {}


@contextmanager
def hook_workspace():
    """A disposable stand-in for the repository, holding only ``runs/`` and hook state."""

    with tempfile.TemporaryDirectory(prefix="pmsb-hooks-") as directory:
        root = Path(directory).resolve()
        (root / "runs").mkdir()
        yield root


def make_run(workspace: Path, slug: str, **build_state: object) -> Path:
    """Create a real, structurally valid run manifest with an optional build state."""

    run_dir = workspace / "runs" / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = run_dir / "run_manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "manifest_tool.py"),
            "init",
            "--manifest",
            str(manifest),
            "--topic-slug",
            slug,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    if build_state:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data.setdefault("build_state", {}).update(build_state)
        manifest.write_text(json.dumps(data), encoding="utf-8")
    return manifest


def manifest_state(manifest: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "manifest_tool.py"), "state", *args, "--manifest", str(manifest)],
        capture_output=True,
        text=True,
        check=False,
    )


def bind(workspace: Path, manifest: Path, session: str = "test-session") -> None:
    """Drive the PostToolUse hook the way a real `--manifest` command would."""

    result = run_hook(
        "tool_guard.py",
        claude_event(
            "PostToolUse",
            cwd=workspace,
            session_id=session,
            tool_name="Bash",
            tool_input={"command": f'python scripts/manifest_tool.py state show --manifest "{manifest}"'},
            tool_response={"exit_code": 0},
        ),
        script_args=["--claude"],
        workspace=workspace,
    )
    assert result.returncode == 0, result.stderr


def stop(workspace: Path, *, session: str = "test-session", active: bool = False) -> dict[str, object]:
    return response_of(
        run_hook(
            "stop_gate.py",
            claude_event("Stop", cwd=workspace, session_id=session, stop_hook_active=active),
            script_args=["--claude"],
            workspace=workspace,
        )
    )


def user_turn(workspace: Path, *, session: str = "test-session", prompt: str = "carry on") -> None:
    run_hook(
        "prompt_secret_guard.py",
        claude_event("UserPromptSubmit", cwd=workspace, session_id=session, prompt=prompt),
        script_args=["--claude"],
        workspace=workspace,
    )


class HookConfigurationTests(unittest.TestCase):
    def test_configuration_is_cross_platform_and_bounded(self):
        config = json.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(set(config), {"hooks"})
        self.assertEqual(set(config["hooks"]), set(HOOK_SCRIPTS))
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

    def test_every_configured_script_exists(self):
        for script_name in set(HOOK_SCRIPTS.values()):
            with self.subTest(script=script_name):
                self.assertTrue((HOOK_DIR / script_name).is_file())
                self.assertTrue((HOOK_DIR / f"{Path(script_name).stem}_hook").is_file())

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
        self.assertEqual(claude["$schema"], "https://json.schemastore.org/claude-code-settings.json")
        self.assertEqual(set(claude), {"$schema", "hooks"})
        self.assertEqual(set(claude["hooks"]), set(HOOK_SCRIPTS))
        self.assertEqual(claude["hooks"]["SessionStart"][0]["matcher"], "startup|resume|clear|compact|fork")

        for event_name in HOOK_SCRIPTS:
            with self.subTest(event=event_name):
                codex_hook = codex["hooks"][event_name][0]["hooks"][0]
                claude_hook = claude["hooks"][event_name][0]["hooks"][0]
                self.assertEqual(claude_hook["type"], "command")
                self.assertEqual(claude_hook["command"], "python")
                self.assertEqual(claude_hook["args"], CLAUDE_HOOK_ARGS[event_name])
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

    def test_user_turn_is_stamped_even_when_the_prompt_is_blocked(self):
        with hook_workspace() as workspace:
            run_hook(
                "prompt_secret_guard.py",
                claude_event("UserPromptSubmit", cwd=workspace, prompt="GH_TOKEN=" + "D" * 32),
                script_args=["--claude"],
                workspace=workspace,
            )
            pointers = list((workspace / ".codex" / "state").glob("*.json"))
            self.assertEqual(len(pointers), 1)
            payload = json.loads(pointers[0].read_text(encoding="utf-8"))
            self.assertTrue(payload["last_user_turn_utc"])
            self.assertEqual(payload["stop_blocks"], 0)


class SessionContextTests(unittest.TestCase):
    def test_maintenance_context_when_no_run_exists(self):
        with hook_workspace() as workspace:
            result = run_hook(
                "session_context.py",
                claude_event("SessionStart", cwd=workspace, source="startup"),
                script_args=["--claude"],
                workspace=workspace,
            )
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("maintenance mode", context)

    def test_active_manifest_summary_does_not_include_pending_question_text(self):
        with hook_workspace() as workspace:
            make_run(
                workspace,
                "demo-topic",
                current_stage="scope-lock",
                pending_user_question="untrusted question text",
                scope={"status": "locked", "version": 1},
                gates={"concept": "passed"},
            )
            result = run_hook(
                "session_context.py",
                claude_event("SessionStart", cwd=workspace, source="compact"),
                script_args=["--claude"],
                workspace=workspace,
            )
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("pending-user-question=yes", context)
        self.assertIn("run-status=active", context)
        self.assertNotIn("untrusted question text", context)

    def test_multiple_unattached_runs_report_ambiguity_instead_of_guessing(self):
        with hook_workspace() as workspace:
            make_run(workspace, "topic-a")
            make_run(workspace, "topic-b")
            result = run_hook(
                "session_context.py",
                claude_event("SessionStart", cwd=workspace, source="startup"),
                script_args=["--claude"],
                workspace=workspace,
            )
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("2 run workspaces exist", context)
        self.assertIn("topic-a", context)
        self.assertIn("topic-b", context)


class ToolGuardTests(unittest.TestCase):
    def pre_tool(self, workspace: Path, **fields: object) -> dict[str, object]:
        return response_of(
            run_hook(
                "tool_guard.py",
                claude_event("PreToolUse", cwd=workspace, **fields),
                script_args=["--claude"],
                workspace=workspace,
            )
        )

    def decision(self, response: dict[str, object]) -> str:
        return str(response.get("hookSpecificOutput", {}).get("permissionDecision", "allow"))

    def test_direct_manifest_and_receipt_edits_are_denied(self):
        with hook_workspace() as workspace:
            for target in (
                "runs/topic/run_manifest.json",
                "runs/topic/run_manifest_v2.json",
                "runs/topic/protocol_v1/protocol_compile_v1.json",
            ):
                with self.subTest(target=target):
                    response = self.pre_tool(
                        workspace,
                        tool_name="Edit",
                        tool_input={"file_path": target, "new_string": "{}"},
                    )
                    self.assertEqual(self.decision(response), "deny")

    def test_read_only_tools_are_never_denied(self):
        """Reading a protected file is not writing it, and reading a script is not running it.

        Both denials key off a *shell command*; a tool that executes nothing has none, so its
        path arguments must never be interpreted as one.
        """

        with hook_workspace() as workspace:
            for tool_name, tool_input in (
                ("Read", {"file_path": "scripts/audit_markdown.py"}),
                ("Read", {"file_path": "runs/topic/run_manifest.json"}),
                ("Grep", {"pattern": "sweep", "path": "scripts/pubmed_tool.py"}),
                ("Glob", {"pattern": "scripts/*_tool.py"}),
            ):
                with self.subTest(tool=tool_name, target=tool_input):
                    self.assertEqual(
                        self.pre_tool(workspace, tool_name=tool_name, tool_input=tool_input), {}
                    )

    def test_ordinary_source_edits_are_untouched(self):
        with hook_workspace() as workspace:
            response = self.pre_tool(
                workspace,
                tool_name="Edit",
                tool_input={"file_path": "scripts/pubmed_tool.py", "new_string": "x"},
            )
            self.assertEqual(response, {})

    def test_direct_material_command_is_denied_but_maintenance_is_allowed(self):
        with hook_workspace() as workspace:
            denied = self.pre_tool(
                workspace,
                tool_name="Bash",
                tool_input={"command": "python scripts/pubmed_tool.py search --query-file q.txt"},
            )
            self.assertEqual(self.decision(denied), "deny")
            for allowed_command in (
                "python scripts/pubmed_tool.py --help",
                "python -m unittest tests.test_query_guards",
                "python scripts/workflow_tool.py --manifest m.json --kind search -- python scripts/pubmed_tool.py search",
                "git status",
            ):
                with self.subTest(command=allowed_command):
                    self.assertEqual(
                        self.pre_tool(workspace, tool_name="Bash", tool_input={"command": allowed_command}),
                        {},
                    )

    def test_only_actual_invocations_are_material(self):
        """Naming a script is not running it.

        A substring test would deny `sed -n '1,5p' scripts/audit_markdown.py`, which reads a file
        and produces no evidence. Only the executable position of each shell segment counts.
        """

        module = _load_tool_guard()
        reads_only = (
            "sed -n '1,5p' scripts/audit_markdown.py",
            "grep -n 'foo' scripts/pubmed_tool.py",
            "cat scripts/mesh_tool.py | head -20",
            "wc -l scripts/vocabulary_learning.py",
            "python scripts/hooks_tool.py list",
            "python scripts/manifest_tool.py state show",
        )
        invocations = (
            "python scripts/pubmed_tool.py search --query-file q.txt",
            "python3 scripts/mesh_tool.py sweep --concept x",
            "py -3 scripts/critic_tool.py --run-independent",
            "uv run scripts/screening_tool.py screen",
            "NCBI_API_KEY=x python scripts/pubmed_tool.py search",
            "git status && python scripts/audit_markdown.py --input a.json",
            "./scripts/pubmed_tool.py search",
            "python scripts/hooks_tool.py final-qa --strategy s.txt",
        )
        for command in reads_only:
            with self.subTest(allowed=command):
                self.assertFalse(module.material_invocation(command))
        for command in invocations:
            with self.subTest(denied=command):
                self.assertTrue(module.material_invocation(command))

    def test_post_tool_binds_the_named_run(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "bound-topic")
            bind(workspace, manifest)
            pointer = json.loads(next((workspace / ".codex" / "state").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(Path(pointer["manifest"]), manifest)

    def test_failed_commands_do_not_bind(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "unbound-topic")
            run_hook(
                "tool_guard.py",
                claude_event(
                    "PostToolUse",
                    cwd=workspace,
                    tool_name="Bash",
                    tool_input={"command": f'python scripts/manifest_tool.py state show --manifest "{manifest}"'},
                    tool_response={"exit_code": 1},
                ),
                script_args=["--claude"],
                workspace=workspace,
            )
            self.assertEqual(list((workspace / ".codex" / "state").glob("*.json")), [])

    def test_separate_sessions_keep_separate_bindings(self):
        with hook_workspace() as workspace:
            first = make_run(workspace, "topic-one")
            second = make_run(workspace, "topic-two")
            bind(workspace, first, session="session-one")
            bind(workspace, second, session="session-two")
            pointers = {
                path.name: json.loads(path.read_text(encoding="utf-8"))["manifest"]
                for path in (workspace / ".codex" / "state").glob("*.json")
            }
            self.assertEqual(len(pointers), 2)
            self.assertEqual(set(map(Path, pointers.values())), {first, second})


class StopGateTests(unittest.TestCase):
    def test_repository_hygiene_passes_without_continuation(self):
        with hook_workspace() as workspace:
            self.assertEqual(stop(workspace), {})

    def test_incomplete_run_blocks_once_then_refuses_to_loop(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "incomplete-topic")
            bind(workspace, manifest)

            first = stop(workspace)
            self.assertEqual(first["decision"], "block")
            self.assertIn("incomplete", first["reason"])
            # The remedy has to be actionable, not just a verdict.
            self.assertIn("set-run-status", first["reason"])

            second = stop(workspace, active=True)
            self.assertNotIn("decision", second)
            self.assertTrue(second["continue"])

    def test_block_budget_stops_blocking_even_without_the_active_flag(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "budget-topic")
            bind(workspace, manifest)
            decisions = [stop(workspace).get("decision", "advise") for _ in range(5)]
            self.assertEqual(decisions[:3], ["block", "block", "block"])
            self.assertEqual(decisions[3:], ["advise", "advise"])

    def test_fresh_matching_pause_allows_an_incomplete_stop(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "paused-topic", current_stage="intake", gates={"seed": "pending"})
            bind(workspace, manifest)
            user_turn(workspace)
            recorded = manifest_state(
                manifest, "set-run-status", "awaiting-user", "--type", "seed-intake", "--reason", "need seed PMIDs"
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)

            response = stop(workspace)
            self.assertNotIn("decision", response)
            self.assertIn("seed-intake", response["systemMessage"])
            # An excused stop must not read as a finished build.
            self.assertIn("not finished", response["systemMessage"])

    def test_pause_that_does_not_match_build_state_is_refused_at_source(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "mismatch-topic", current_stage="critic-review", gates={"seed": "provided"})
            refused = manifest_state(
                manifest, "set-run-status", "awaiting-user", "--type", "seed-intake", "--reason", "pretend"
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("requires", refused.stderr)

    def test_unknown_pause_type_is_refused(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "bogus-topic")
            refused = manifest_state(
                manifest, "set-run-status", "awaiting-user", "--type", "made-up-reason", "--reason", "pretend"
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("unknown pause type", refused.stderr)

    def test_pause_goes_stale_once_the_user_speaks_again(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "stale-topic", current_stage="intake", gates={"seed": "pending"})
            bind(workspace, manifest)
            user_turn(workspace)
            manifest_state(
                manifest, "set-run-status", "awaiting-user", "--type", "seed-intake", "--reason", "need seed PMIDs"
            )
            self.assertNotIn("decision", stop(workspace))

            # The user answered; the pause describes a finished exchange and no longer excuses a stop.
            _advance_clock(manifest)
            user_turn(workspace, prompt="no seeds, carry on")
            self.assertEqual(stop(workspace).get("decision"), "block")

    def test_external_blocker_allows_an_explanatory_stop(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "blocked-topic")
            bind(workspace, manifest)
            user_turn(workspace)
            recorded = manifest_state(
                manifest, "set-run-status", "blocked-external", "--reason", "PubMed E-utilities returned 503"
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            response = stop(workspace)
            self.assertNotIn("decision", response)

    def test_checkpoint_allows_a_mid_run_progress_report(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "checkpoint-topic", current_stage="block-testing")
            bind(workspace, manifest)
            user_turn(workspace)
            manifest_state(manifest, "set-run-status", "checkpoint", "--reason", "reporting block counts so far")
            self.assertNotIn("decision", stop(workspace))

    def test_reasonless_pause_is_refused(self):
        with hook_workspace() as workspace:
            manifest = make_run(workspace, "reasonless-topic")
            for status in ("checkpoint", "blocked-external"):
                with self.subTest(status=status):
                    self.assertEqual(manifest_state(manifest, "set-run-status", status).returncode, 1)

    def test_ambiguous_workspaces_advise_and_never_block(self):
        with hook_workspace() as workspace:
            make_run(workspace, "topic-a")
            make_run(workspace, "topic-b")
            response = stop(workspace)
            self.assertNotIn("decision", response)
            self.assertIn("2 run workspaces exist", response["systemMessage"])

    def test_unparseable_gate_output_advises_instead_of_blocking(self):
        module = _load_stop_gate()
        unparseable = subprocess.CompletedProcess(args=[], returncode=1, stdout="not json", stderr="")
        with mock.patch.object(module, "run_stop_gate", return_value=unparseable):
            response = module.handle_manifest(
                claude_event("Stop", stop_hook_active=False), "claude", ROOT / "run_manifest.json"
            )
        self.assertNotIn("decision", response)
        self.assertTrue(response["continue"])
        self.assertIn("unverified", response["systemMessage"])

    def test_hygiene_failure_blocks_once_then_avoids_stop_loop(self):
        module = _load_stop_gate()
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="failure")
        for active in (False, True):
            with self.subTest(stop_hook_active=active):
                captured: list[dict[str, object]] = []
                with (
                    mock.patch.object(
                        module, "read_event", return_value=claude_event("Stop", stop_hook_active=active)
                    ),
                    mock.patch.object(module, "event_cwd", return_value=ROOT),
                    mock.patch.object(module, "active_manifest", return_value=(None, "")),
                    mock.patch.object(module, "run_hygiene_gate", return_value=failed),
                    mock.patch.object(module, "stop_blocks_exhausted", return_value=False),
                    mock.patch.object(module, "note_stop_block", return_value=1),
                    mock.patch.object(module, "emit", side_effect=captured.append),
                ):
                    self.assertEqual(module.main(), 0)

                self.assertEqual(len(captured), 1)
                if active:
                    self.assertTrue(captured[0]["continue"])
                    self.assertNotIn("decision", captured[0])
                else:
                    self.assertEqual(captured[0]["decision"], "block")

    def test_gate_exception_fails_open(self):
        module = _load_stop_gate()
        captured: list[dict[str, object]] = []
        with (
            mock.patch.object(module, "read_event", return_value=claude_event("Stop")),
            mock.patch.object(module, "event_cwd", return_value=ROOT),
            mock.patch.object(module, "active_manifest", side_effect=OSError("disk gone")),
            mock.patch.object(module, "emit", side_effect=captured.append),
        ):
            self.assertEqual(module.main(), 0)
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0]["continue"])
        self.assertNotIn("decision", captured[0])


def _advance_clock(manifest: Path) -> None:
    """Push the recorded pause a second into the past.

    ``utc_now`` has one-second resolution, so a test that records a pause and then simulates the
    user's reply inside the same second would compare two equal timestamps and read as fresh.
    """

    data = json.loads(manifest.read_text(encoding="utf-8"))
    status = data["build_state"]["run_status"]
    status["recorded_utc"] = "2000-01-01T00:00:00Z"
    manifest.write_text(json.dumps(data), encoding="utf-8")


def _load_hook_module(script_name: str):
    spec = importlib.util.spec_from_file_location(f"test_{Path(script_name).stem}", HOOK_DIR / script_name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "path", [str(HOOK_DIR), *sys.path]):
        spec.loader.exec_module(module)
    return module


def _load_stop_gate():
    return _load_hook_module("stop_gate.py")


def _load_tool_guard():
    return _load_hook_module("tool_guard.py")


if __name__ == "__main__":
    unittest.main()
