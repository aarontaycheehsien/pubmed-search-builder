"""Headless Codex CLI driver for Phase 2 skill-generation evals.

Phase 2 evaluates the *skill itself*: it drives Codex non-interactively to build
a strategy from only the review question (+ a front-loaded protocol that
pre-resolves every gate, "approach A"), then Phase 1 (`run_eval.py`) scores the
strategy the agent produced.

Verified invocation (spike: codex-cli 0.130.0-alpha.5, model gpt-5.5):

    codex exec -C <skill_dir> -s workspace-write \\
      -c approval_policy=never \\
      -c sandbox_workspace_write.network_access=true \\
      -c model_reasoning_effort=<effort> \\
      --skip-git-repo-check --color never \\
      -o <last_message_file> --json -

Spike findings that shaped this driver:
  * Pass the prompt via STDIN with `-` as the prompt arg. Passing it as a plain
    argument makes `codex exec` block forever reading stdin for EOF in a
    non-interactive shell.
  * `sandbox_workspace_write.network_access=true` is REQUIRED. The default
    workspace-write sandbox blocks outbound sockets (WinError 10013), which
    breaks every NCBI/MeSH call the skill makes. With it enabled, the bundled
    `pubmed_tool.py doctor` returns checks.ok=true from inside the sandbox.
  * `approval_policy=never` keeps the run unattended (no confirmation prompts).
  * `--skip-git-repo-check` because the skill dir is not a git repo.
  * `-o <file>` captures the agent's final message; `--json` streams JSONL
    events to stdout, saved as the run transcript.

This module only LAUNCHES the skill and captures artifacts. Prompt construction
(question + protocol) and harvesting/scoring of `final_strategy.txt` live in the
generation/suite layer (not yet built).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from glob import glob
from pathlib import Path


def find_codex() -> str:
    """Locate the codex executable. Honors $CODEX_BIN, then PATH, then the
    default Windows install location."""
    env = os.environ.get("CODEX_BIN")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    localapp = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    for cand in glob(str(Path(localapp) / "OpenAI" / "Codex" / "bin" / "**" / "codex.exe"), recursive=True):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError(
        "codex executable not found. Set CODEX_BIN, or install Codex CLI. "
        "Default location: %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\codex.exe"
    )


# Codex sandbox runner occasionally fails to start with a transient pipe/timeout
# error (observed: "windows sandbox: timed out ... connecting runner pipe-in").
# These are infrastructure hiccups, not build failures, so a failed run carrying
# one of these signatures is safe to relaunch. Kept deliberately specific so a
# genuine build failure (e.g. the skill stalling at a gate) is never masked.
TRANSIENT_SANDBOX_SIGNATURES = (
    "connecting runner pipe-in",
    "windows sandbox: timed out",
    "sandbox: timed out",
    "runner pipe",
)


def is_transient_sandbox_failure(returncode: int, stderr: str) -> bool:
    """True only for a *failed* run whose stderr matches a known transient
    sandbox-startup signature. A returncode of 0 is never transient-failure."""
    if returncode == 0:
        return False
    low = (stderr or "").lower()
    return any(sig in low for sig in TRANSIENT_SANDBOX_SIGNATURES)


def run_skill(
    prompt: str,
    *,
    skill_dir: Path,
    run_dir: Path,
    model: str | None = None,
    reasoning_effort: str = "medium",
    timeout: int = 1800,
    codex_bin: str | None = None,
    max_attempts: int = 2,
) -> dict:
    """Drive the skill headlessly for one generation run.

    Writes ``run_dir/events.jsonl`` (JSONL transcript) and
    ``run_dir/last_message.txt`` (agent's final message). Returns a dict with
    the return code and those artifact paths. The skill is expected (per the
    prompt's protocol) to write its final strategy into ``run_dir`` so the
    scorer can pick it up.

    A failed run whose stderr matches a transient sandbox-startup signature is
    relaunched, up to ``max_attempts`` total. Successful runs and non-transient
    failures (e.g. a gate stall) are never retried. The returned dict includes
    ``attempts``.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    last_message = run_dir / "last_message.txt"
    events = run_dir / "events.jsonl"

    codex = codex_bin or find_codex()
    cmd = [
        codex, "exec",
        "-C", str(skill_dir),
        "-s", "workspace-write",
        "-c", "approval_policy=never",
        "-c", "sandbox_workspace_write.network_access=true",
        "-c", f"model_reasoning_effort={reasoning_effort}",
        "--skip-git-repo-check",
        "--color", "never",
        "--json",
        "-o", str(last_message),
        "-",
    ]
    if model:
        cmd[2:2] = ["-m", model]  # insert after "exec"

    result: dict = {}
    for attempt in range(1, max(1, max_attempts) + 1):
        with events.open("w", encoding="utf-8") as ev:
            proc = subprocess.run(
                cmd,
                input=prompt,
                stdout=ev,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        stderr = proc.stderr or ""
        result = {
            "returncode": proc.returncode,
            "events_path": str(events),
            "last_message_path": str(last_message),
            "last_message": last_message.read_text(encoding="utf-8") if last_message.exists() else "",
            "stderr": stderr,
            "attempts": attempt,
        }
        # Success, or a non-transient failure, or out of attempts: stop here.
        if not is_transient_sandbox_failure(proc.returncode, stderr) or attempt >= max(1, max_attempts):
            return result
        # Transient sandbox-startup failure with attempts left: relaunch.
    return result
