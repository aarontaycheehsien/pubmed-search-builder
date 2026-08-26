"""Shared local-only helpers for repository lifecycle hooks."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, IO


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPOSITORY_ROOT / ".codex" / "state"
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
MANIFEST_OPTION_RE = re.compile(
    r"(?:^|\s)--manifest(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))",
    re.IGNORECASE,
)
STAGE_OPTION_RE = re.compile(
    r"(?:^|\s)--stage(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))",
    re.IGNORECASE,
)


def read_event(stream: IO[str] | None = None) -> dict[str, Any]:
    source = stream if stream is not None else __import__("sys").stdin
    try:
        value = json.load(source)
    except (json.JSONDecodeError, OSError, TypeError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def emit(payload: dict[str, Any], stream: IO[str] | None = None) -> None:
    target = stream if stream is not None else __import__("sys").stdout
    json.dump(payload, target, ensure_ascii=False, separators=(",", ":"))
    target.write("\n")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def event_cwd(event: dict[str, Any]) -> Path | None:
    value = event.get("cwd")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        path = Path(value).resolve(strict=False)
        root = REPOSITORY_ROOT.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return path if is_within(path, root) else None


def safe_id(value: object) -> str:
    return SAFE_ID_RE.sub("_", str(value or "unknown"))[:120]


def pointer_path(event: dict[str, Any], client: str) -> Path:
    return STATE_DIR / f"{safe_id(client)}-{safe_id(event.get('session_id'))}.json"


def cleanup_stale_pointers(max_age_days: int = 30) -> None:
    if not STATE_DIR.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    for path in STATE_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def bind_manifest(event: dict[str, Any], client: str, manifest: Path) -> None:
    manifest = manifest.resolve(strict=False)
    if not manifest.is_file() or manifest.name not in {"run_manifest.json", "run_manifest_v2.json"}:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = pointer_path(event, client)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"manifest": str(manifest), "client": client, "updated": int(time.time())}),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def pointer_manifest(event: dict[str, Any], client: str) -> Path | None:
    cleanup_stale_pointers()
    path = pointer_path(event, client)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = Path(str(payload.get("manifest", ""))).resolve(strict=False)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return manifest if manifest.is_file() else None


def nearest_manifest(cwd: Path) -> Path | None:
    root = REPOSITORY_ROOT.resolve(strict=False)
    current = cwd.resolve(strict=False)
    while is_within(current, root) and current != root:
        for name in ("run_manifest.json", "run_manifest_v2.json"):
            candidate = current / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        current = current.parent
    return None


def active_manifest(event: dict[str, Any], client: str) -> Path | None:
    pointer = pointer_manifest(event, client)
    if pointer is not None:
        return pointer
    cwd = event_cwd(event)
    return nearest_manifest(cwd) if cwd is not None else None


def tool_command(event: dict[str, Any]) -> str:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command")
    if isinstance(command, str):
        return command
    patch = tool_input.get("patch")
    if isinstance(patch, str):
        return patch
    path = tool_input.get("file_path") or tool_input.get("path")
    return str(path) if isinstance(path, str) else ""


def option_value(pattern: re.Pattern[str], command: str) -> str:
    match = pattern.search(command)
    if not match:
        return ""
    return next((value for value in match.groups() if value is not None), "")


def manifest_from_command(command: str, cwd: Path) -> Path | None:
    value = option_value(MANIFEST_OPTION_RE, command)
    if not value:
        if "workflow_tool.py" not in command.lower():
            return None
        value = "run_manifest.json"
    path = Path(value)
    return (path if path.is_absolute() else cwd / path).resolve(strict=False)
