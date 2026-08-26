#!/usr/bin/env python3
"""Keep material PubMed work inside the provenance path, and bind the run it belongs to.

Two events, one concern.

``PreToolUse`` refuses the two ways evidence loses its provenance: editing a run manifest or a locked
protocol receipt by hand, and calling a material tool directly instead of through ``workflow_tool.py``,
which is what hashes inputs and outputs and appends the manifest entry.

``PostToolUse`` binds the run named by a successful ``--manifest`` command to this session, so later
hooks resolve the right build even when the client reports the repository root as the cwd.

Deliberately not ported from the sibling branch: stage-order preflight. This branch's
``workflow_tool.py`` has no ``stage_preflight``, and a denial derived from a guess is worse than a
check that is absent.
"""

from __future__ import annotations

import re

from common import (
    bind_manifest,
    client_name,
    emit,
    event_cwd,
    load_manifest_context,
    manifest_from_command,
    read_event,
    shell_command,
    tool_command,
    tool_target_path,
)


# Scripts whose output is evidence: they must be run through workflow_tool.py so the manifest entry,
# the input hashes, and the output hash are written in the same atomic step.
MATERIAL_SCRIPTS = frozenset(
    {
        "pubmed_tool.py",
        "mesh_tool.py",
        "critic_tool.py",
        "screening_tool.py",
        "candidate_ledger.py",
        "strategy_analysis.py",
        "vocabulary_learning.py",
        "no_seed_discovery.py",
        "registry_sentinel.py",
        "screening_burden.py",
        "review_discovery.py",
        "audit_markdown.py",
        "hooks_tool.py",
    }
)
INTERPRETER_RE = re.compile(r"^(?:[^\s]*[\\/])?(?:python[\d.]*(?:\.exe)?|py|uv|uvx|poetry)$", re.IGNORECASE)
# Shell metacharacters that start a fresh command; each segment is examined on its own so a material
# script hidden after a pipe or `&&` is still seen.
SEGMENT_RE = re.compile(r"[;&|]+|\n")
ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
TOKEN_RE = re.compile(r"\"([^\"]*)\"|'([^']*)'|(\S+)")
# Invocations that produce no evidence and must stay callable, or the guard blocks its own maintenance.
MAINTENANCE_MARKERS = ("--help", " -h", "py_compile", "-m unittest", "pytest", "--version", "selftest", " doctor")
# Hand-editing these is how a build's provenance silently stops matching its artifacts.
PROTECTED_PATH_RE = re.compile(
    r"(?:^|[\\/\s:\"'])run_manifest(?:_v\d+)?(?:\.backup)?\.json\b"
    r"|(?:^|[\\/\s:\"'])protocol_v\d+[\\/][^\s\"']*(?:compile|receipt)[^\s\"']*\.json\b",
    re.IGNORECASE,
)
EDIT_TOOLS = {"edit", "write", "apply_patch", "notebookedit", "multiedit"}


def maintenance_command(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in MAINTENANCE_MARKERS)


def through_workflow_tool(command: str) -> bool:
    return "workflow_tool.py" in command.lower()


def tokenize(segment: str) -> list[str]:
    return [next(group for group in match.groups() if group is not None) for match in TOKEN_RE.finditer(segment)]


def invoked_scripts(command: str) -> list[str]:
    """Scripts this command actually *runs*, ignoring ones it merely names.

    Matching the bare filename anywhere in the command string is too blunt: `sed -n '1,5p'
    scripts/audit_markdown.py` reads a file and produces no evidence, but would be denied by a
    substring test. Only the executable position of each shell segment counts -- the first
    non-assignment token, or the first script argument once an interpreter is in front.
    """

    found: list[str] = []
    for segment in SEGMENT_RE.split(command):
        tokens = [token for token in tokenize(segment) if not ENV_ASSIGNMENT_RE.match(token)]
        index = 0
        # Step over an interpreter and its own switches (`python -X utf8 script.py`).
        while index < len(tokens) and INTERPRETER_RE.match(tokens[index]):
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            # `uv run script.py`, `poetry run script.py`
            if index < len(tokens) and tokens[index].lower() in {"run", "python", "python3"}:
                index += 1
        if index < len(tokens):
            name = tokens[index].replace("\\", "/").rsplit("/", 1)[-1]
            if name.lower().endswith(".py"):
                found.append(name.lower())
    return found


def material_invocation(command: str) -> bool:
    scripts = invoked_scripts(command)
    if not any(script in MATERIAL_SCRIPTS for script in scripts):
        return False
    if "hooks_tool.py" in scripts and not re.search(r"\b(?:final-qa|low-count-review)\b", command, re.IGNORECASE):
        # hooks_tool.py has read-only diagnostics too; only its evidence-producing modes are gated.
        return any(script in MATERIAL_SCRIPTS - {"hooks_tool.py"} for script in scripts)
    return True


def deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def handle_pre_tool(event: dict) -> dict | None:
    tool_name = str(event.get("tool_name") or "").strip().lower()

    # A write is judged by what it targets; anything else only by what it would execute. Tools that
    # execute nothing -- Read, Grep, Glob -- reach neither branch and are never denied.
    if tool_name in EDIT_TOOLS:
        target = tool_target_path(event) or tool_command(event)
        if target and PROTECTED_PATH_RE.search(target):
            return deny(
                "Run manifests and locked protocol receipts are provenance records, not editable files. "
                "Use `manifest_tool.py state ...` / `workflow_tool.py` so the change is validated and "
                "timestamped instead of hand-written."
            )
        return None

    command = shell_command(event)
    if not command or through_workflow_tool(command) or maintenance_command(command):
        return None
    if material_invocation(command):
        return deny(
            "This command produces evidence, so running it directly would leave the manifest without "
            "the hashes that bind the artifact to this run. Re-run it through "
            "`python scripts/workflow_tool.py --manifest <run_manifest.json> --kind <kind> "
            "--output <artifact> -- <command>`."
        )
    return None


def handle_post_tool(event: dict, client: str) -> dict | None:
    cwd = event_cwd(event)
    if cwd is None or tool_failed(event):
        return None
    command = tool_command(event)
    if not command:
        return None
    manifest = manifest_from_command(command, cwd)
    if manifest is None or not manifest.is_file():
        return None
    bind_manifest(event, client, manifest)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": load_manifest_context(manifest),
        }
    }


def tool_failed(event: dict) -> bool:
    response = event.get("tool_response")
    if not isinstance(response, dict):
        return False
    for key in ("exit_code", "returncode", "status_code"):
        value = response.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value != 0
    return bool(response.get("is_error") or response.get("isError"))


def main() -> int:
    event = read_event()
    if event_cwd(event) is None:
        return 0
    client = client_name()
    try:
        name = str(event.get("hook_event_name") or "")
        if name == "PostToolUse":
            payload = handle_post_tool(event, client)
        else:
            payload = handle_pre_tool(event)
    except (OSError, ValueError):
        # A guard that cannot evaluate a command must let it through, never deny by accident.
        payload = None
    if payload is not None:
        emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
