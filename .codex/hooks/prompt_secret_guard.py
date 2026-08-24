#!/usr/bin/env python3
"""Block high-confidence secrets and warn about personal paths in prompts."""

from __future__ import annotations

import re
import sys

from common import emit, event_cwd, read_event


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
    re.compile(r"(?i)\bC--Users-[A-Za-z0-9._-]+"),
)
PLACEHOLDER_MARKERS = ("example", "placeholder", "redacted", "changeme", "dummy", "yourkey", "yourtoken")


def looks_like_placeholder(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    if not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS):
        return True
    if set(normalized) <= {"x", "0"}:
        return True
    return value.startswith(("$", "%", "<", "{")) or "(" in value


def secret_labels(prompt: str) -> list[str]:
    labels: set[str] = set()
    for pattern in (SECRET_ASSIGNMENT_RE, COMMAND_SECRET_RE):
        for match in pattern.finditer(prompt):
            if not looks_like_placeholder(match.group("value")):
                labels.add(match.group("name").upper().replace("-", "_"))
    for label, pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(prompt):
            if not looks_like_placeholder(match.group(0)):
                labels.add(label)
    if PRIVATE_KEY_RE.search(prompt):
        labels.add("private key")
    return sorted(labels)


def contains_personal_path(prompt: str) -> bool:
    return any(pattern.search(prompt) for pattern in PERSONAL_PATH_PATTERNS)


def main() -> int:
    event = read_event()
    if event_cwd(event) is None:
        return 0
    prompt = event.get("prompt")
    if not isinstance(prompt, str):
        return 0

    labels = secret_labels(prompt)
    if labels:
        response = {
            "decision": "block",
            "reason": (
                "Potential secret material was detected in the prompt "
                f"({', '.join(labels)}). Put the value in the process environment or trusted "
                "skill-root .env, then resubmit without the value. The detected value was not logged."
            ),
        }
        if "--claude" in sys.argv[1:]:
            response["suppressOriginalPrompt"] = True
        emit(response)
        return 0

    if contains_personal_path(prompt):
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": (
                        "The user prompt contains a personal absolute path. It may be used for the current task, "
                        "but do not copy it into tracked files; use a workspace-relative path or neutral placeholder."
                    ),
                }
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
