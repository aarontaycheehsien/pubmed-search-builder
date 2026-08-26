"""Shared, fail-safe helpers for repository-local Codex hooks."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Where this checkout's *runs* live, as opposed to where its scripts live. They are the same
# directory in normal use. Separating them lets the hook tests point the run/session side at a
# throwaway tree while still executing the real gate scripts, so a test's verdict never depends on
# which builds happen to be sitting in the developer's `runs/`. Test-only; nothing sets it in
# production, and it cannot redirect which code runs.
HOOK_ROOT_ENV = "PUBMED_SEARCH_BUILDER_HOOK_ROOT"


def _workspace_root() -> Path:
    override = os.environ.get(HOOK_ROOT_ENV, "").strip()
    if override:
        try:
            candidate = Path(override).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            return REPOSITORY_ROOT
        if candidate.is_dir():
            return candidate
    return REPOSITORY_ROOT


WORKSPACE_ROOT = _workspace_root()
# Session-scoped, untracked, and disposable: which run this session is working on, when the user last
# spoke, and how many times the Stop gate has already blocked. Losing it degrades the hooks to their
# cold-start behaviour, never to a wrong answer.
STATE_DIR = WORKSPACE_ROOT / ".codex" / "state"
MANIFEST_NAMES = ("run_manifest.json", "run_manifest_v2.json")
SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9._/@+-]+")
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
MESSAGE_UNSAFE_RE = re.compile(r"[^A-Za-z0-9 ._/@+,;:()'\"=<>%-]+")
MANIFEST_OPTION_RE = re.compile(
    r"(?:^|\s)--manifest(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))",
    re.IGNORECASE,
)
# The Stop gate blocks at most once per stop cascade via ``stop_hook_active``. This is the backstop
# for the case where that flag never arrives: past it, the gate only ever advises.
MAX_STOP_BLOCKS = 3


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


def event_cwd(event: dict[str, Any], root: Path = WORKSPACE_ROOT) -> Path | None:
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


def find_nearest_manifest(cwd: Path, root: Path = WORKSPACE_ROOT) -> Path | None:
    """Find a run manifest between a subdirectory cwd and the repository root.

    The repository root is searched *through* but never accepted as a run location. It is the skill
    installation directory, which ``core.workspace.guard_run_workspace`` already refuses to create
    build state in; a ``run_manifest.json`` sitting there is legacy debris from before that guard,
    and binding to it would validate this session against an abandoned build.

    A cwd *at* the root is no longer an early abort, though -- that is what made the manifest gate
    inert for every client that reports the project root as the cwd. It now simply finds nothing
    here, and :func:`active_manifest` continues on to the session pointer and the ``runs/`` scan.
    """

    resolved_root = root.resolve(strict=False)
    current = cwd.resolve(strict=False)
    if not is_within(current, resolved_root):
        return None
    while current != resolved_root:
        for name in MANIFEST_NAMES:
            candidate = current / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        current = current.parent
    return None


def workspace_manifests(root: Path = WORKSPACE_ROOT) -> list[Path]:
    """Every run manifest under ``runs/``, sorted, for cold-start disambiguation."""

    runs = (root / "runs").resolve(strict=False)
    if not runs.is_dir():
        return []
    found: list[Path] = []
    for name in MANIFEST_NAMES:
        for depth in ("*/", "*/*/"):
            found.extend(
                path for path in runs.glob(f"{depth}{name}") if path.is_file() and not path.is_symlink()
            )
    return sorted(set(found))


def safe_id(value: object) -> str:
    return SAFE_ID_RE.sub("_", str(value or "unknown"))[:120]


def client_name(argv: list[str] | None = None) -> str:
    values = list(argv if argv is not None else sys.argv[1:])
    if "--claude" in values:
        return "claude"
    if "--client" in values:
        index = values.index("--client")
        if index + 1 < len(values):
            return safe_id(values[index + 1])
    return "codex"


def pointer_path(event: dict[str, Any], client: str) -> Path:
    return STATE_DIR / f"{safe_id(client)}-{safe_id(event.get('session_id'))}.json"


def cleanup_stale_pointers(max_age_days: int = 14) -> None:
    if not STATE_DIR.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    for path in STATE_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def read_pointer(event: dict[str, Any], client: str) -> dict[str, Any]:
    try:
        value = json.loads(pointer_path(event, client).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_pointer(event: dict[str, Any], client: str, **updates: Any) -> dict[str, Any]:
    """Merge ``updates`` into this session's pointer. Never raises: pointer state is a convenience."""

    payload = read_pointer(event, client)
    payload.update(updates)
    payload["client"] = client
    payload["updated"] = int(time.time())
    path = pointer_path(event, client)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        return payload
    return payload


def bind_manifest(event: dict[str, Any], client: str, manifest: Path) -> None:
    """Remember which run this session is driving, so a root-level cwd still resolves it."""

    resolved = manifest.resolve(strict=False)
    resolved_root = WORKSPACE_ROOT.resolve(strict=False)
    if resolved.name not in MANIFEST_NAMES or not resolved.is_file():
        return
    if not is_within(resolved, resolved_root) or resolved.parent == resolved_root:
        # Same rule as find_nearest_manifest: the skill install root is not a run workspace.
        return
    write_pointer(event, client, manifest=str(resolved))


def pointer_manifest(event: dict[str, Any], client: str) -> Path | None:
    cleanup_stale_pointers()
    value = read_pointer(event, client).get("manifest")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).resolve(strict=False)
    return path if path.is_file() else None


def active_manifest(event: dict[str, Any], client: str) -> tuple[Path | None, str]:
    """Resolve this session's run manifest.

    Returns ``(manifest, note)``. ``note`` is non-empty only when the run could not be resolved but
    candidates exist -- an ambiguity the hooks report rather than guess through, since binding the
    wrong run would validate one build's handoff against another's evidence.
    """

    pointer = pointer_manifest(event, client)
    if pointer is not None:
        return pointer, ""
    cwd = event_cwd(event)
    if cwd is not None:
        nearest = find_nearest_manifest(cwd)
        if nearest is not None:
            return nearest, ""
    candidates = workspace_manifests()
    if len(candidates) == 1:
        return candidates[0], ""
    if candidates:
        names = ", ".join(relative_label(path) for path in candidates[:6])
        return None, (
            f"{len(candidates)} run workspaces exist and none is attached to this session ({names}). "
            "Run a workflow_tool.py or manifest_tool.py command with --manifest to attach one before "
            "material PubMed work."
        )
    return None, ""


def record_user_turn(event: dict[str, Any], client: str) -> str:
    """Stamp the user's turn and reset the per-turn block budget."""

    stamp = utc_now()
    write_pointer(event, client, last_user_turn_utc=stamp, stop_blocks=0)
    return stamp


def last_user_turn(event: dict[str, Any], client: str) -> str:
    value = read_pointer(event, client).get("last_user_turn_utc")
    return value if isinstance(value, str) else ""


def note_stop_block(event: dict[str, Any], client: str) -> int:
    payload = read_pointer(event, client)
    count = payload.get("stop_blocks")
    count = count + 1 if isinstance(count, int) and not isinstance(count, bool) else 1
    write_pointer(event, client, stop_blocks=count)
    return count


def stop_blocks_exhausted(event: dict[str, Any], client: str) -> bool:
    count = read_pointer(event, client).get("stop_blocks")
    return isinstance(count, int) and not isinstance(count, bool) and count >= MAX_STOP_BLOCKS


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def shell_command(event: dict[str, Any]) -> str:
    """The shell command a tool call will execute, or empty for tools that execute nothing.

    Kept strictly separate from :func:`tool_target_path`. Collapsing the two lets a *path* argument
    be read as a *command*, which turns an innocent `Read scripts/pubmed_tool.py` into an apparent
    invocation of it.
    """

    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "commands", "script"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            parts = [item for item in value if isinstance(item, str)]
            if parts:
                return " ".join(parts)
    return ""


def tool_command(event: dict[str, Any]) -> str:
    """A command or path identifying what a tool call is about, for binding and logging only.

    Never use this for an allow/deny decision -- it deliberately blurs commands and paths so
    PostToolUse can spot a ``--manifest`` reference wherever it appears.
    """

    command = shell_command(event)
    if command:
        return command
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    for key in ("patch", "content", "new_string", "file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def tool_target_path(event: dict[str, Any]) -> str:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def option_value(pattern: re.Pattern[str], command: str) -> str:
    match = pattern.search(command)
    if not match:
        return ""
    return next((value for value in match.groups() if value is not None), "")


def manifest_from_command(command: str, cwd: Path) -> Path | None:
    value = option_value(MANIFEST_OPTION_RE, command)
    if not value:
        return None
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else cwd / candidate).resolve(strict=False)
    return resolved if resolved.name in MANIFEST_NAMES else None


def safe_label(value: object, *, limit: int = 100) -> str:
    """Render untrusted artifact metadata without turning it into instructions."""

    text = SAFE_LABEL_RE.sub("_", str(value or "").strip())
    return text[:limit] or "unknown"


def safe_message(value: object, *, limit: int = 180) -> str:
    """Render gate text for a human to act on: readable, but never able to forge hook structure.

    ``safe_label`` collapses spaces, which is right for an identifier and wrong for a sentence the
    assistant has to follow. This keeps ordinary punctuation and drops newlines and control
    characters, so a manifest string cannot inject a second instruction line.
    """

    text = MESSAGE_UNSAFE_RE.sub(" ", str(value or "").strip())
    text = " ".join(text.split())
    return text[:limit] or "unspecified"


def relative_label(path: Path, root: Path = WORKSPACE_ROOT) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return "outside-repository"
    return safe_label(relative.as_posix(), limit=180)


def load_manifest_context(manifest: Path, root: Path = WORKSPACE_ROOT) -> str:
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
    run_status = state.get("run_status") if isinstance(state.get("run_status"), dict) else {}
    status_text = safe_label(run_status.get("status") or "active", limit=30)
    if str(run_status.get("type") or "").strip():
        status_text += f"/{safe_label(run_status.get('type'), limit=40)}"
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    return " ".join(
        (
            f"Active PubMed run manifest: {relative_label(manifest, root)}.",
            f"Topic={safe_label(data.get('topic_slug'))};",
            f"stage={safe_label(state.get('current_stage'))};",
            f"run-status={status_text};",
            f"scope={safe_label(scope.get('status'))}-v{safe_label(scope.get('version'), limit=20)};",
            f"pending-user-question={pending};",
            f"entries={len(entries)};",
            f"gates={gate_summary}.",
            "Ending a turn before the complete-loop gate passes requires a recorded run status: "
            "`manifest_tool.py state set-run-status <awaiting-user|checkpoint|blocked-external> ...`.",
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
