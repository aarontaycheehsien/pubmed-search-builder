#!/usr/bin/env python3
"""Stage-aware lifecycle dispatcher shared by Codex and Claude Code."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import (
    REPOSITORY_ROOT,
    STAGE_OPTION_RE,
    active_manifest,
    bind_manifest,
    emit,
    event_cwd,
    manifest_from_command,
    option_value,
    read_event,
    tool_command,
)

SCRIPT_DIR = str(REPOSITORY_ROOT / "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import manifest_tool
import workflow_tool


SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(?P<name>NCBI_API_KEY|MESH_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|"
    r"GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|AZURE_CLIENT_SECRET|CLIENT_SECRET|PASSWORD)\b"
    r"\s*(?:=|:)\s*[\"']?(?P<value>[^\s\"'`,;]{8,})"
)
COMMAND_SECRET_RE = re.compile(
    r"(?i)--(?P<name>api-key|token|password|secret)\s+[\"']?(?P<value>[^\s\"'`,;]{8,})"
)
TOKEN_PATTERNS = (
    ("OpenAI-style API token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")
PERSONAL_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"'`]+"),
    re.compile(r"(?i)(?:^|[\s(])/(?:Users|home)/[^/\s\"'`)]+"),
    re.compile(r"(?i)\bC" + r"--Users-[A-Za-z0-9._-]+"),
)
PLACEHOLDERS = ("example", "placeholder", "redacted", "changeme", "dummy", "yourkey", "yourtoken")
MATERIAL_RE = re.compile(
    r"(?:pubmed_tool\.py|mesh_tool\.py|hooks_tool\.py\s+final-qa|audit_markdown\.py|export_final\.py)",
    re.IGNORECASE,
)
PROTECTED_EDIT_RE = re.compile(
    r"(?:^|[\\/\s:])run_manifest(?:_v\d+)?\.json\b|"
    r"(?:^|[\\/\s:])protocol_v\d+[\\/].*(?:compile|receipt).*\.json\b",
    re.IGNORECASE,
)
MAINTENANCE_MARKERS = ("--help", " -h", "py_compile", "-m unittest", "pytest", " doctor", "selftest")


def placeholder(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return (
        not normalized
        or any(marker in normalized for marker in PLACEHOLDERS)
        or set(normalized) <= {"x", "0"}
        or value.startswith(("$", "%", "<", "{"))
        or "(" in value
    )


def secret_labels(prompt: str) -> list[str]:
    labels: set[str] = set()
    for pattern in (SECRET_ASSIGNMENT_RE, COMMAND_SECRET_RE):
        for match in pattern.finditer(prompt):
            if not placeholder(match.group("value")):
                labels.add(match.group("name").upper().replace("-", "_"))
    for label, pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(prompt):
            if not placeholder(match.group(0)):
                labels.add(label)
    if PRIVATE_KEY_RE.search(prompt):
        labels.add("private key")
    return sorted(labels)


def safe_text(value: object, limit: int = 100) -> str:
    return re.sub(r"[^A-Za-z0-9._/@+ -]+", "_", str(value or "unknown"))[:limit]


def manifest_context(path: Path) -> str:
    try:
        data = manifest_tool.load_manifest(path)
        state = manifest_tool.ensure_build_state(data)
        issues = manifest_tool.complete_loop_issues(data, manifest_path=path)
    except (OSError, ValueError, json.JSONDecodeError, manifest_tool.ManifestError):
        return "The active PubMed run manifest is unreadable; validate it before continuing."
    run_status = state.get("run_status") if isinstance(state.get("run_status"), dict) else {}
    pending = "yes" if str(state.get("pending_user_question") or "").strip() else "no"
    return " ".join(
        (
            "PubMed workflow guardrails are active.",
            f"Topic={safe_text(data.get('topic_slug'))};",
            f"stage={safe_text(state.get('current_stage'))};",
            f"run-status={safe_text(run_status.get('status'))};",
            f"pending-user-question={pending};",
            f"remaining-gates={len(issues)};",
            f"next={safe_text(issues[0], 180) if issues else 'handoff-ready'}.",
            "Use workflow_tool.py for material PubMed, MeSH, QA, and audit commands.",
        )
    )


def deny(event_name: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def handle_context(event: dict[str, Any], client: str, event_name: str) -> dict[str, Any]:
    manifest = active_manifest(event, client)
    context = (
        manifest_context(manifest)
        if manifest is not None
        else (
            "PubMed Search Builder repository hooks are active in maintenance mode. "
            "Start or attach a run with workflow_tool.py before material PubMed work."
        )
    )
    return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}


def handle_prompt(event: dict[str, Any], client: str) -> dict[str, Any] | None:
    prompt = event.get("prompt")
    if not isinstance(prompt, str):
        return None
    labels = secret_labels(prompt)
    if labels:
        response: dict[str, Any] = {
            "decision": "block",
            "reason": (
                "Potential secret material was detected "
                f"({', '.join(labels)}). Put the value in the process environment or trusted .env, "
                "then resubmit without the value. The detected value was not logged."
            ),
        }
        if client == "claude":
            response["suppressOriginalPrompt"] = True
        return response
    if any(pattern.search(prompt) for pattern in PERSONAL_PATH_PATTERNS):
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "The prompt contains a personal absolute path. It may be used for this task, "
                    "but must not be copied into tracked files."
                ),
            }
        }
    return None


def maintenance_command(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in MAINTENANCE_MARKERS)


def handle_pre_tool(event: dict[str, Any], client: str) -> dict[str, Any] | None:
    cwd = event_cwd(event)
    if cwd is None:
        return None
    command = tool_command(event)
    if not command:
        return None
    tool_name = str(event.get("tool_name") or "")
    if tool_name.lower() in {"apply_patch", "edit", "write"} and PROTECTED_EDIT_RE.search(command):
        return deny("PreToolUse", "Direct edits to run manifests and locked protocol receipts are blocked; use the workflow tools.")
    lowered = command.lower()
    if "workflow_tool.py" in lowered:
        is_run = bool(re.search(r"workflow_tool\.py[\"']?\s+run\b", command, re.IGNORECASE))
        is_export = bool(re.search(r"workflow_tool\.py[\"']?\s+export-final\b", command, re.IGNORECASE))
        if is_run or is_export:
            manifest = manifest_from_command(command, cwd)
            stage = "audit-output" if is_export else option_value(STAGE_OPTION_RE, command)
            if manifest is None or not manifest.is_file():
                return deny("PreToolUse", "Initialize or attach a valid run manifest before executing a workflow stage.")
            if not stage:
                return deny("PreToolUse", "workflow_tool.py run requires an explicit --stage.")
            try:
                data = manifest_tool.load_manifest(manifest)
                issues = workflow_tool.stage_preflight(data, stage)
            except (OSError, ValueError, json.JSONDecodeError, manifest_tool.ManifestError) as exc:
                issues = [f"manifest preflight failed: {type(exc).__name__}"]
            if issues:
                return deny("PreToolUse", "Workflow stage is out of order: " + "; ".join(issues[:3]))
        return None
    if MATERIAL_RE.search(command) and not maintenance_command(command):
        manifest = active_manifest(event, client)
        instruction = (
            "Attach the active run and execute this material command through workflow_tool.py run."
            if manifest is not None
            else "Initialize or attach a run with workflow_tool.py, then execute the command through workflow_tool.py run."
        )
        return deny("PreToolUse", "Direct material PubMed workflow commands bypass provenance. " + instruction)
    return None


def tool_failed(event: dict[str, Any]) -> bool:
    response = event.get("tool_response")
    if isinstance(response, dict):
        for key in ("exit_code", "returncode", "status_code"):
            value = response.get(key)
            if isinstance(value, int):
                return value != 0
        if response.get("is_error") is True or response.get("isError") is True:
            return True
    return False


def handle_post_tool(event: dict[str, Any], client: str) -> dict[str, Any] | None:
    cwd = event_cwd(event)
    command = tool_command(event)
    if cwd is None or "workflow_tool.py" not in command.lower() or tool_failed(event):
        return None
    manifest = manifest_from_command(command, cwd)
    if manifest is None or not manifest.is_file():
        return None
    bind_manifest(event, client, manifest)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": manifest_context(manifest),
        }
    }


def legitimate_pause(state: dict[str, object]) -> bool:
    status = state.get("run_status") if isinstance(state.get("run_status"), dict) else {}
    if status.get("status") in {"paused", "abandoned"}:
        return True
    if str(state.get("pending_user_question") or "").strip():
        return True
    stage = state.get("current_stage")
    gate = {"question-intake": "framework", "seed-intake": "seed", "concept-gate": "concept"}.get(stage)
    return bool(gate and not manifest_tool.gate_resolved((state.get("gates") or {}).get(gate)))


def hygiene_result() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scripts" / "repository_hygiene.py")],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def handle_stop(event: dict[str, Any], client: str) -> dict[str, Any]:
    manifest = active_manifest(event, client)
    active_before = bool(event.get("stop_hook_active"))
    if manifest is None:
        result = hygiene_result()
        if result.returncode == 0:
            return {}
        if not active_before:
            return {"decision": "block", "reason": "Repository hygiene failed. Run scripts/repository_hygiene.py and fix the reported tracked-file issues."}
        return {"continue": True, "systemMessage": "Repository hygiene is still failing after one continuation; report it explicitly without creating a stop loop."}
    try:
        data = manifest_tool.load_manifest(manifest)
        state = manifest_tool.ensure_build_state(data)
        if legitimate_pause(state):
            return {}
        issues = manifest_tool.complete_loop_issues(data, manifest_path=manifest)
    except (OSError, ValueError, json.JSONDecodeError, manifest_tool.ManifestError) as exc:
        issues = [f"manifest validation could not run ({type(exc).__name__})"]
    if not issues:
        return {}
    summary = "; ".join(safe_text(issue, 180) for issue in issues[:4])
    if not active_before:
        return {"decision": "block", "reason": f"PubMed handoff is incomplete ({len(issues)} gaps): {summary}"}
    return {
        "continue": True,
        "systemMessage": (
            f"PubMed handoff still has {len(issues)} unresolved gaps after one continuation: {summary}. "
            "Do not create a stop loop; disclose the unresolved checks in the final response."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", choices=("codex", "claude"), default="codex")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event = read_event()
    event_name = str(event.get("hook_event_name") or "")
    try:
        if event_cwd(event) is None:
            payload: dict[str, Any] | None = {} if event_name == "Stop" else None
        elif event_name in {"SessionStart", "SubagentStart"}:
            payload = handle_context(event, args.client, event_name)
        elif event_name == "UserPromptSubmit":
            payload = handle_prompt(event, args.client)
        elif event_name == "PreToolUse":
            payload = handle_pre_tool(event, args.client)
        elif event_name == "PostToolUse":
            payload = handle_post_tool(event, args.client)
        elif event_name == "Stop":
            payload = handle_stop(event, args.client)
        else:
            payload = None
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        payload = {
            "continue": True,
            "systemMessage": f"PubMed workflow hook failed safely ({type(exc).__name__}); report the hook failure before handoff.",
        }
    if payload is not None:
        emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
