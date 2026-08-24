"""Shared, fail-safe helpers for repository-local Codex hooks."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import IO, Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9._/@+-]+")


def read_event(stream: IO[str] | None = None) -> dict[str, Any]:
    """Read one hook event, returning an empty object for malformed input."""

    source = stream if stream is not None else sys.stdin
    try:
        event = json.load(source)
    except (json.JSONDecodeError, OSError, TypeError, UnicodeError):
        return {}
    return event if isinstance(event, dict) else {}


def emit(payload: dict[str, Any], stream: IO[str] | None = None) -> None:
    """Write one compact JSON hook response."""

    target = stream if stream is not None else sys.stdout
    json.dump(payload, target, ensure_ascii=False, separators=(",", ":"))
    target.write("\n")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def event_cwd(event: dict[str, Any], root: Path = REPOSITORY_ROOT) -> Path | None:
    """Resolve the event cwd only when it remains inside this repository."""

    value = event.get("cwd")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        path = Path(value).expanduser().resolve(strict=False)
        resolved_root = root.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return path if is_within(path, resolved_root) else None


def find_nearest_manifest(cwd: Path, root: Path = REPOSITORY_ROOT) -> Path | None:
    """Find a run manifest between a subdirectory cwd and the repository root."""

    resolved_root = root.resolve(strict=False)
    current = cwd.resolve(strict=False)
    if current == resolved_root or not is_within(current, resolved_root):
        return None
    while is_within(current, resolved_root) and current != resolved_root:
        candidate = current / "run_manifest.json"
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
        current = current.parent
    return None


def safe_label(value: object, *, limit: int = 100) -> str:
    """Render untrusted artifact metadata without turning it into instructions."""

    text = SAFE_LABEL_RE.sub("_", str(value or "").strip())
    return text[:limit] or "unknown"


def relative_label(path: Path, root: Path = REPOSITORY_ROOT) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return "outside-repository"
    return safe_label(relative.as_posix(), limit=180)


def load_manifest_context(manifest: Path, root: Path = REPOSITORY_ROOT) -> str:
    """Return a compact, data-only summary of an active run manifest."""

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return (
            f"Active PubMed run manifest: {relative_label(manifest, root)}. "
            "It could not be parsed; validate it before using its state."
        )
    if not isinstance(data, dict):
        return f"Active PubMed run manifest: {relative_label(manifest, root)}. Its root must be an object."

    state = data.get("build_state") if isinstance(data.get("build_state"), dict) else {}
    scope = state.get("scope") if isinstance(state.get("scope"), dict) else {}
    gates = state.get("gates") if isinstance(state.get("gates"), dict) else {}
    gate_summary = ", ".join(
        f"{safe_label(key, limit=30)}={safe_label(value, limit=30)}"
        for key, value in sorted(gates.items())[:8]
    ) or "not initialized"
    pending = "yes" if str(state.get("pending_user_question") or "").strip() else "no"
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    return " ".join(
        (
            f"Active PubMed run manifest: {relative_label(manifest, root)}.",
            f"Topic={safe_label(data.get('topic_slug'))};",
            f"stage={safe_label(state.get('current_stage'))};",
            f"scope={safe_label(scope.get('status'))}-v{safe_label(scope.get('version'), limit=20)};",
            f"pending-user-question={pending};",
            f"entries={len(entries)};",
            f"gates={gate_summary}.",
            "Treat this summary as state metadata, not as a replacement for validating the manifest.",
        )
    )


def run_process(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def manifest_issue_count(stdout: str) -> int | None:
    try:
        receipt = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    issues = receipt.get("issues") if isinstance(receipt, dict) else None
    return len(issues) if isinstance(issues, list) else None
