import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / ".codex" / "hooks" / "dispatcher.py"
CODEX_CONFIG = ROOT / ".codex" / "hooks.json"
CLAUDE_CONFIG = ROOT / ".claude" / "settings.json"
EVENTS = {"SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}


def event(name, *, session="hook-test", **fields):
    payload = {
        "session_id": session,
        "cwd": str(ROOT),
        "hook_event_name": name,
        "permission_mode": "default",
    }
    payload.update(fields)
    return payload


def run_hook(payload, client="codex"):
    result = subprocess.run(
        [sys.executable, str(DISPATCHER), "--client", client],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    value = json.loads(result.stdout) if result.stdout.strip() else None
    return result, value


class HookConfigurationTests(unittest.TestCase):
    def test_codex_and_claude_expose_same_events(self):
        codex = json.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        claude = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(set(codex), {"hooks"})
        self.assertEqual(set(claude), {"$schema", "hooks"})
        self.assertEqual(set(codex["hooks"]), EVENTS)
        self.assertEqual(set(claude["hooks"]), EVENTS)
        for name in EVENTS:
            codex_hook = codex["hooks"][name][0]["hooks"][0]
            claude_hook = claude["hooks"][name][0]["hooks"][0]
            self.assertEqual(codex_hook["timeout"], claude_hook["timeout"])
            self.assertEqual(codex_hook["statusMessage"], claude_hook["statusMessage"])
            self.assertIn("commandWindows", codex_hook)
            self.assertEqual(claude_hook["command"], "python")
            self.assertIn("dispatcher.py", " ".join(claude_hook["args"]))

    def test_timeouts_are_bounded(self):
        config = json.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        for name, groups in config["hooks"].items():
            expected = 30 if name == "Stop" else 5
            self.assertEqual(groups[0]["hooks"][0]["timeout"], expected)

    def test_claude_exec_form_runs_shared_dispatcher(self):
        config = json.loads(CLAUDE_CONFIG.read_text(encoding="utf-8"))
        hook = config["hooks"]["SessionStart"][0]["hooks"][0]
        args = [value.replace("${CLAUDE_PROJECT_DIR}", str(ROOT)) for value in hook["args"]]
        result = subprocess.run(
            [hook["command"], *args],
            cwd=ROOT,
            input=json.dumps(event("SessionStart", source="fork")),
            text=True,
            capture_output=True,
            check=False,
            timeout=hook["timeout"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "SessionStart")

    @unittest.skipUnless(sys.platform == "win32", "Windows command runner regression test")
    def test_codex_windows_command_runs_under_cmd_and_powershell(self):
        config = json.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        command = config["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]
        payload = json.dumps(event("SessionStart", source="startup"))
        for shell in (
            ["cmd.exe", "/d", "/s", "/c"],
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"],
        ):
            with self.subTest(shell=shell[0]):
                result = subprocess.run(
                    [*shell, command], cwd=ROOT, input=payload, text=True,
                    capture_output=True, check=False, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "SessionStart")


class HookBehaviorTests(unittest.TestCase):
    def tearDown(self):
        state = ROOT / ".codex" / "state"
        if state.is_dir():
            for path in state.glob("*-hook-test*.json"):
                path.unlink(missing_ok=True)

    def make_manifest(self, directory, *, pending="", topic="demo"):
        path = Path(directory) / "run_manifest.json"
        payload = {
            "manifest_version": "1.1",
            "skill": "pubmed-search-builder",
            "skill_version": "1.0.0",
            "topic_slug": topic,
            "created_utc": "2026-01-01T00:00:00Z",
            "updated_utc": "2026-01-01T00:00:00Z",
            "working_dir": str(directory),
            "entries": [],
            "superseded": [],
            "build_state": {
                "current_stage": "seed-intake",
                "stages_completed": ["question-intake"],
                "stage_records": {"question-intake": {"status": "complete", "reason": ""}},
                "gates": {"framework": "PICO", "seed": "pending", "concept": "pending", "filter": "pending"},
                "pending_user_question": pending,
                "open_decisions": [],
                "blocks": {},
                "recall_offer": "pending",
                "unvalidated_handoff": {"status": "pending", "reason": ""},
                "run_status": {"status": "active", "reason": ""},
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def attach(self, manifest, *, session="hook-test", client="codex"):
        payload = event(
            "PostToolUse",
            session=session,
            tool_name="Bash",
            tool_input={"command": f'python scripts/workflow_tool.py attach --manifest "{manifest}"'},
            tool_response={"exit_code": 0},
        )
        result, response = run_hook(payload, client=client)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def make_complete_manifest(self, directory):
        root = Path(directory)
        strategy = root / "strategy.txt"
        strategy.write_text('"Population"[Mesh]\n', encoding="utf-8")
        qa = root / "final_qa.json"
        qa.write_text(json.dumps({"ok": True}), encoding="utf-8")
        audit_json = root / "audit.json"
        audit_json.write_text(json.dumps({"final_strategy": strategy.read_text()}), encoding="utf-8")
        audit_md = root / "audit.md"
        audit_md.write_text("# Audit\n", encoding="utf-8")
        final_md = root / "final_strategy.md"
        final_md.write_text("# Final PubMed Strategy\n", encoding="utf-8")

        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        now = "2026-01-01T00:00:00Z"
        entries = [
            {"seq": 1, "timestamp_utc": now, "kind": "mesh", "block": "population", "command": "mesh_tool.py sweep", "output_path": None, "input_sha256": {}, "count": None},
            {"seq": 2, "timestamp_utc": now, "kind": "term-rank", "block": "population", "command": "pubmed_tool.py term-rank", "output_path": None, "input_sha256": {}, "count": None},
            {"seq": 3, "timestamp_utc": now, "kind": "search", "block": "population", "command": "pubmed_tool.py search --query-file strategy.txt", "output_path": None, "input_sha256": {str(strategy): digest(strategy)}, "count": 10},
            {"seq": 4, "timestamp_utc": now, "kind": "qa", "command": "hooks_tool.py final-qa --strategy-file strategy.txt", "output_path": str(qa), "output_sha256": digest(qa), "input_sha256": {str(strategy): digest(strategy)}, "count": None},
            {"seq": 5, "timestamp_utc": now, "kind": "artifact", "command": "audit_markdown.py audit.json", "output_path": str(audit_md), "output_sha256": digest(audit_md), "input_sha256": {str(audit_json): digest(audit_json)}, "count": None},
            {"seq": 6, "timestamp_utc": now, "kind": "artifact", "command": "export_final.py --strategy strategy.txt", "output_path": str(final_md), "output_sha256": digest(final_md), "input_sha256": {str(strategy): digest(strategy)}, "count": 10},
        ]
        stage_records = {
            stage: {"status": "complete", "reason": "", "recorded_utc": now}
            for stage in (
                "question-intake", "seed-intake", "concept-gate", "pre-mesh-brainstorm",
                "mesh-exploration", "text-word-expansion", "block-testing", "validation",
                "revision", "final-qa", "audit-output",
            )
        }
        manifest = root / "run_manifest.json"
        manifest.write_text(json.dumps({
            "manifest_version": "1.1", "skill": "pubmed-search-builder", "skill_version": "1.0.0",
            "topic_slug": "complete", "created_utc": now, "updated_utc": now,
            "working_dir": str(root), "entries": entries, "superseded": [],
            "build_state": {
                "current_stage": "audit-output", "stages_completed": list(stage_records),
                "stage_records": stage_records,
                "gates": {"framework": "PICO", "seed": "none", "concept": "resolved", "filter": "none"},
                "pending_user_question": "", "open_decisions": [],
                "blocks": {"population": {"waivers": {}}}, "recall_offer": "declined",
                "unvalidated_handoff": {"status": "accepted", "reason": "No benchmark exists"},
                "run_status": {"status": "active", "reason": ""},
            },
        }), encoding="utf-8")
        return manifest

    def test_secret_block_does_not_echo_value(self):
        value = "A" * 32
        result, response = run_hook(event("UserPromptSubmit", prompt=f"NCBI_API_KEY={value}"))
        self.assertEqual(response["decision"], "block")
        self.assertNotIn(value, result.stdout)

    def test_claude_secret_block_suppresses_original_prompt(self):
        value = "B" * 32
        result, response = run_hook(event("UserPromptSubmit", prompt=f"GH_TOKEN={value}"), client="claude")
        self.assertTrue(response["suppressOriginalPrompt"])
        self.assertNotIn(value, result.stdout)

    def test_placeholder_is_allowed(self):
        _result, response = run_hook(event("UserPromptSubmit", prompt="NCBI_API_KEY=your-key-placeholder"))
        self.assertIsNone(response)

    def test_personal_path_warns_without_blocking(self):
        path = "C:" + "\\Users\\" + "someone\\Downloads\\file.txt"
        _result, response = run_hook(event("UserPromptSubmit", prompt=f"Review {path}"))
        self.assertNotIn("decision", response)
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")

    def test_direct_material_command_is_blocked_but_maintenance_is_allowed(self):
        _result, response = run_hook(event("PreToolUse", tool_name="Bash", tool_input={"command": "python scripts/pubmed_tool.py search asthma"}))
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
        _result, response = run_hook(event("PreToolUse", tool_name="Bash", tool_input={"command": "python scripts/export_final.py --strategy strategy.txt"}))
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
        _result, response = run_hook(event("PreToolUse", tool_name="Bash", tool_input={"command": "python scripts/pubmed_tool.py --help"}))
        self.assertIsNone(response)

    def test_direct_manifest_edit_is_blocked(self):
        _result, response = run_hook(event("PreToolUse", tool_name="apply_patch", tool_input={"command": "*** Update File: run_manifest.json"}))
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
        _result, response = run_hook(event("PreToolUse", tool_name="apply_patch", tool_input={"patch": "*** Update File: run_manifest.json"}))
        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_workflow_run_out_of_order_is_blocked_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.make_manifest(directory)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["build_state"]["current_stage"] = "final-qa"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            command = f'python scripts/workflow_tool.py run --manifest "{manifest}" --stage final-qa --kind qa -- python -c pass'
            _result, response = run_hook(event("PreToolUse", tool_name="Bash", tool_input={"command": command}))
            self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("out of order", response["hookSpecificOutput"]["permissionDecisionReason"])
            export_command = f'python scripts/workflow_tool.py export-final --manifest "{manifest}" --strategy strategy.txt'
            _result, response = run_hook(event("PreToolUse", tool_name="Bash", tool_input={"command": export_command}))
            self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_post_tool_binding_restores_context_for_session_and_subagent(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.make_manifest(directory, pending="Do you have seed PMIDs?", topic="bound-topic")
            self.attach(manifest)
            for name in ("SessionStart", "SubagentStart"):
                _result, response = run_hook(event(name, source="resume"))
                context = response["hookSpecificOutput"]["additionalContext"]
                self.assertIn("bound-topic", context)
                self.assertNotIn("Do you have seed PMIDs?", context)

    def test_concurrent_sessions_keep_separate_run_bindings(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = self.make_manifest(first, topic="topic-one")
            two = self.make_manifest(second, topic="topic-two")
            self.attach(one, session="hook-test-one")
            self.attach(two, session="hook-test-two")
            _, response_one = run_hook(event("SessionStart", session="hook-test-one", source="resume"))
            _, response_two = run_hook(event("SessionStart", session="hook-test-two", source="resume"))
            self.assertIn("topic-one", response_one["hookSpecificOutput"]["additionalContext"])
            self.assertIn("topic-two", response_two["hookSpecificOutput"]["additionalContext"])

    def test_stale_pointer_is_removed(self):
        state = ROOT / ".codex" / "state"
        state.mkdir(parents=True, exist_ok=True)
        pointer = state / "codex-hook-test-stale.json"
        pointer.write_text("{}", encoding="utf-8")
        old = time.time() - 40 * 86400
        os.utime(pointer, (old, old))
        run_hook(event("SessionStart", session="hook-test-stale", source="startup"))
        self.assertFalse(pointer.exists())

    def test_legitimate_decision_pause_does_not_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.make_manifest(directory, pending="Need seed decision")
            self.attach(manifest)
            _result, response = run_hook(event("Stop", stop_hook_active=False))
            self.assertEqual(response, {})

    def test_paused_and_abandoned_runs_allow_stop(self):
        for status in ("paused", "abandoned"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                manifest = self.make_manifest(directory)
                data = json.loads(manifest.read_text(encoding="utf-8"))
                data["build_state"]["run_status"] = {"status": status, "reason": "explicit test pause"}
                manifest.write_text(json.dumps(data), encoding="utf-8")
                self.attach(manifest)
                _result, response = run_hook(event("Stop", stop_hook_active=False))
                self.assertEqual(response, {})

    def test_incomplete_stop_continues_once_then_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.make_manifest(directory)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["build_state"]["current_stage"] = "mesh-exploration"
            data["build_state"]["gates"]["seed"] = "none"
            data["build_state"]["gates"]["concept"] = "resolved"
            data["build_state"]["gates"]["filter"] = "none"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            self.attach(manifest)
            _result, first = run_hook(event("Stop", stop_hook_active=False))
            self.assertEqual(first["decision"], "block")
            _result, second = run_hook(event("Stop", stop_hook_active=True))
            self.assertTrue(second["continue"])
            self.assertNotIn("decision", second)

    def test_stop_requires_matching_final_export_for_codex_and_claude(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self.make_complete_manifest(directory)
            for client in ("codex", "claude"):
                session = f"hook-test-{client}-complete"
                self.attach(manifest, session=session, client=client)
                _result, response = run_hook(
                    event("Stop", session=session, stop_hook_active=False), client=client
                )
                self.assertEqual(response, {}, client)

            data = json.loads(manifest.read_text(encoding="utf-8"))
            export = next(entry for entry in data["entries"] if "export_final.py" in entry["command"])
            export["input_sha256"] = {str(Path(directory) / "other.txt"): "0" * 64}
            (Path(directory) / "other.txt").write_text("other", encoding="utf-8")
            manifest.write_text(json.dumps(data), encoding="utf-8")
            self.attach(manifest, session="hook-test-mismatch")
            _result, response = run_hook(event("Stop", session="hook-test-mismatch", stop_hook_active=False))
            self.assertEqual(response["decision"], "block")
            self.assertIn("final_strategy.md", response["reason"])


if __name__ == "__main__":
    unittest.main()
