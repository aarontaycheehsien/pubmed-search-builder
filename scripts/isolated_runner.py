#!/usr/bin/env python3
"""Run one schema-constrained task in a fresh-context, read-only child agent.

Two steps in the workflow mean something only when a reader other than the builder performs
them: the PRESS-informed critic and the independent re-screen of a screening sample. A second
reading by the context that produced the first is not a second reading. This module launches
that reader as a separate process that sees only the files staged into a temporary workspace,
cannot write or reach the network, and loads none of the user's configuration, rules, hooks,
skills, plugins, or MCP servers. It records how the child was run so validators check the
isolation claim instead of taking it on trust.

Supported runners:

* ``codex-cli`` -- ``codex exec`` with a read-only sandbox, an ephemeral session, user
  configuration and rules ignored, and optional features disabled.
* ``claude-code-cli`` -- ``claude -p`` in safe mode (no CLAUDE.md, hooks, skills, plugins, or MCP
  servers), without session persistence, with only the read-only Read/Glob/Grep tools, and with
  ``dontAsk`` permissions so any other action is refused rather than prompted.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CODEX_RUNNER = "codex-cli"
CLAUDE_RUNNER = "claude-code-cli"
RUNNERS = (CODEX_RUNNER, CLAUDE_RUNNER)
EXECUTION_MODE = "fresh-context-child-agent"

RUNNER_ENV = "PUBMED_ISOLATED_RUNNER"
EXECUTABLE_ENV = {CODEX_RUNNER: "CODEX_BIN", CLAUDE_RUNNER: "CLAUDE_BIN"}
DEFAULT_EXECUTABLE = {CODEX_RUNNER: "codex", CLAUDE_RUNNER: "claude"}

CODEX_DISABLED_FEATURES = (
    "plugins",
    "apps",
    "browser_use",
    "computer_use",
    "in_app_browser",
    "multi_agent",
    "image_generation",
)
CLAUDE_ALLOWED_TOOLS = ("Read", "Glob", "Grep")
CLAUDE_PERMISSION_MODE = "dontAsk"
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# Properties every isolated execution record must assert, whatever the runner.
COMMON_POLICY = {
    "mode": EXECUTION_MODE,
    "sandbox": "read-only",
    "ephemeral": True,
    "user_config_ignored": True,
    "rules_ignored": True,
    "network_use_authorized": False,
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class IsolatedRunnerError(ValueError):
    pass


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


CLEANUP_RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0)


@contextlib.contextmanager
def isolated_workspace(prefix: str) -> Iterator[Path]:
    """Temporary child workspace that is removed afterwards without masking the run's outcome.

    On Windows a CLI can leave a helper process holding its working directory for a moment after
    it exits, so deletion is retried briefly. A directory that still cannot be removed is left in
    the system temp folder rather than replacing the child's real result or error.
    """

    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        for delay in (*CLEANUP_RETRY_DELAYS, None):
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
            except OSError:
                if delay is None:
                    break
                time.sleep(delay)


def locate_executable(runner: str, explicit: str | None = None) -> str | None:
    """Return the runner's executable from an explicit path, its environment variable, or PATH.

    An explicitly named executable is returned as given when it cannot be resolved, so the
    operating system reports the missing program rather than a silent fallback to another one.
    """

    if explicit:
        if Path(explicit).is_file():
            return str(Path(explicit))
        return shutil.which(explicit) or explicit
    configured = os.environ.get(EXECUTABLE_ENV[runner])
    if configured:
        if Path(configured).is_file():
            return str(Path(configured))
        resolved = shutil.which(configured)
        if resolved:
            return resolved
    return shutil.which(DEFAULT_EXECUTABLE[runner])


def resolve_runner(requested: str | None = None) -> str:
    """Resolve ``auto`` to an installed runner.

    An explicit choice or ``PUBMED_ISOLATED_RUNNER`` wins. Otherwise a build running inside Claude
    Code prefers the Claude Code runner and any other host prefers Codex, falling back to whichever
    is installed.
    """

    value = str(requested or "auto").strip()
    if value == "auto":
        value = os.environ.get(RUNNER_ENV, "").strip() or "auto"
    if value != "auto":
        if value not in RUNNERS:
            raise IsolatedRunnerError(f"Unknown isolated runner {value!r}; choose one of: {', '.join(RUNNERS)}")
        return value
    preferred = (CLAUDE_RUNNER, CODEX_RUNNER) if os.environ.get("CLAUDECODE") else (CODEX_RUNNER, CLAUDE_RUNNER)
    for runner in preferred:
        if locate_executable(runner):
            return runner
    raise IsolatedRunnerError(
        "No isolated runner is installed. Install the Codex CLI or Claude Code, or set "
        f"{RUNNER_ENV} / --runner and the matching CODEX_BIN or CLAUDE_BIN."
    )


def runner_policy(runner: str) -> dict[str, Any]:
    """Runner-specific isolation settings recorded alongside the common policy."""

    if runner == CODEX_RUNNER:
        return {"disabled_features": list(CODEX_DISABLED_FEATURES)}
    if runner == CLAUDE_RUNNER:
        return {
            "allowed_tools": list(CLAUDE_ALLOWED_TOOLS),
            "permission_mode": CLAUDE_PERMISSION_MODE,
            "safe_mode": True,
            "mcp_servers": "none",
        }
    raise IsolatedRunnerError(f"Unknown isolated runner {runner!r}")


def codex_command(executable: str, workspace: Path, schema_path: Path, output_path: Path, *, model: str | None, reasoning_effort: str) -> list[str]:
    command = [
        executable,
        "exec",
        "-C",
        str(workspace),
        "-s",
        "read-only",
        "-c",
        "approval_policy=never",
        "-c",
        f"model_reasoning_effort={reasoning_effort}",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        *[value for feature in CODEX_DISABLED_FEATURES for value in ("--disable", feature)],
        "--color",
        "never",
        "--output-schema",
        str(schema_path),
        "--json",
        "-o",
        str(output_path),
        "-",
    ]
    if model:
        command[2:2] = ["-m", model]
    return command


def claude_effort(reasoning_effort: str) -> str:
    value = str(reasoning_effort or "").strip().lower()
    if value in CLAUDE_EFFORTS:
        return value
    return "low" if value in {"minimal", "none"} else "high"


def claude_command(executable: str, schema: dict[str, Any], *, model: str | None, reasoning_effort: str) -> list[str]:
    # The prompt arrives on stdin, so no positional argument can be swallowed by a variadic option.
    schema_text = json.dumps({key: value for key, value in schema.items() if key != "$schema"}, separators=(",", ":"))
    command = [
        executable,
        "-p",
        "--safe-mode",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--no-chrome",
        "--disable-slash-commands",
        "--tools",
        ",".join(CLAUDE_ALLOWED_TOOLS),
        "--permission-mode",
        CLAUDE_PERMISSION_MODE,
        "--effort",
        claude_effort(reasoning_effort),
        "--output-format",
        "json",
        "--json-schema",
        schema_text,
    ]
    if model:
        command += ["--model", model]
    return command


def parse_json_text(text: str) -> Any:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    return json.loads(stripped)


def claude_envelope(stdout: str) -> dict[str, Any]:
    """Return the final ``result`` message from ``claude -p --output-format json``."""

    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise IsolatedRunnerError(f"Claude Code child did not return JSON output: {exc}") from exc
    if isinstance(value, list):
        results = [item for item in value if isinstance(item, dict) and item.get("type") == "result"]
        value = results[-1] if results else None
    if not isinstance(value, dict):
        raise IsolatedRunnerError("Claude Code child output has no result message")
    return value


def claude_draft(envelope: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("is_error") is True:
        raise IsolatedRunnerError(f"Claude Code child reported an error: {str(envelope.get('result') or '')[:2000]}")
    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured
    result = envelope.get("result")
    if isinstance(result, str) and result.strip():
        try:
            parsed = parse_json_text(result)
        except json.JSONDecodeError as exc:
            raise IsolatedRunnerError("Claude Code child returned no structured output and its result is not JSON") from exc
        if isinstance(parsed, dict):
            return parsed
    raise IsolatedRunnerError("Claude Code child completed without a structured JSON object")


def failure_detail(process: subprocess.CompletedProcess[str]) -> str:
    details = []
    stdout = (process.stdout or "").strip()
    if stdout:
        try:
            envelope = claude_envelope(stdout)
            message = str(envelope.get("result") or "").strip()
            if message:
                details.append("result: " + message[:2000])
        except IsolatedRunnerError:
            details.append("stdout: " + stdout[-4000:])
    stderr = (process.stderr or "").strip()
    if stderr:
        details.append("stderr: " + stderr[-4000:])
    return "\n".join(details)


def run_isolated(
    *,
    runner: str,
    workspace: Path,
    prompt: str,
    schema: dict[str, Any],
    model: str | None,
    reasoning_effort: str,
    timeout_seconds: int,
    executable: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the child in ``workspace`` and return its untrusted draft plus an execution record.

    The caller stages every file the child may read into ``workspace`` beforehand and validates
    the draft afterwards; nothing the child returns is trusted until then.
    """

    if runner not in RUNNERS:
        raise IsolatedRunnerError(f"Unknown isolated runner {runner!r}")
    if timeout_seconds < 1:
        raise IsolatedRunnerError("timeout must be a positive number of seconds")
    resolved = locate_executable(runner, executable)
    if not resolved:
        env_name = EXECUTABLE_ENV[runner]
        raise IsolatedRunnerError(
            f"{runner} executable was not found; install it, set {env_name}, or pass its path explicitly"
        )
    workspace = workspace.resolve()
    raw_output = workspace / "child_response.json"
    if runner == CODEX_RUNNER:
        schema_path = workspace / "child_output.schema.json"
        schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        command = codex_command(resolved, workspace, schema_path, raw_output, model=model, reasoning_effort=reasoning_effort)
    else:
        command = claude_command(resolved, schema, model=model, reasoning_effort=reasoning_effort)
    try:
        process = subprocess.run(
            command,
            cwd=workspace,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise IsolatedRunnerError(f"Isolated {runner} child timed out after {timeout_seconds} seconds") from exc
    except OSError as exc:
        raise IsolatedRunnerError(f"Could not launch the {runner} executable {resolved!r}: {exc}") from exc
    if process.returncode != 0:
        detail = failure_detail(process)
        raise IsolatedRunnerError(
            f"Isolated {runner} child failed with return code {process.returncode}"
            + (f": {detail}" if detail else "")
            + ". If this runner is not signed in, sign in to it or choose the other with --runner."
        )
    extra: dict[str, Any] = {}
    if runner == CODEX_RUNNER:
        if not raw_output.is_file():
            raise IsolatedRunnerError("Codex child completed without a structured output artifact")
        try:
            draft = json.loads(raw_output.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise IsolatedRunnerError(f"Codex child output is not JSON: {exc}") from exc
    else:
        envelope = claude_envelope(process.stdout or "")
        draft = claude_draft(envelope)
        denials = envelope.get("permission_denials")
        extra["permission_denials"] = len(denials) if isinstance(denials, list) else 0
        if isinstance(envelope.get("total_cost_usd"), (int, float)):
            extra["reported_cost_usd"] = envelope["total_cost_usd"]
    if not isinstance(draft, dict):
        raise IsolatedRunnerError("Isolated child output must be a JSON object")
    execution = {
        **COMMON_POLICY,
        "runner": runner,
        "requested_model": model or "configured-default",
        "reasoning_effort": reasoning_effort,
        **runner_policy(runner),
        "prompt_sha256": sha256_text(prompt),
        "event_stream_sha256": sha256_text(process.stdout or ""),
        "completed_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        **extra,
    }
    return draft, execution


def execution_issues(execution: Any, label: str) -> list[str]:
    """Check an execution record against the isolation policy of the runner it names."""

    if not isinstance(execution, dict):
        return [f"{label} must be an object"]
    issues: list[str] = []
    runner = execution.get("runner")
    if runner not in RUNNERS:
        issues.append(f"{label} runner must be one of: {', '.join(RUNNERS)}")
    for key, expected in COMMON_POLICY.items():
        if execution.get(key) != expected:
            issues.append(f"{label} {key} must be {expected!r}")
    for key in ("prompt_sha256", "event_stream_sha256"):
        if not SHA256_PATTERN.fullmatch(str(execution.get(key) or "")):
            issues.append(f"{label} {key} must be a SHA-256 digest")
    for key in ("completed_utc", "requested_model", "reasoning_effort"):
        if not str(execution.get(key) or "").strip():
            issues.append(f"{label} {key} is required")
    if runner in RUNNERS:
        for key, expected in runner_policy(runner).items():
            if execution.get(key) != expected:
                issues.append(f"{label} {key} does not match the isolated runner policy")
    return issues
