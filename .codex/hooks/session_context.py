#!/usr/bin/env python3
"""Restore concise repository or active-run context at Codex session start."""

from __future__ import annotations

from common import REPOSITORY_ROOT, active_manifest, client_name, emit, event_cwd, load_manifest_context, read_event


def main() -> int:
    event = read_event()
    cwd = event_cwd(event)
    if cwd is None:
        emit({})
        return 0

    manifest, ambiguity = active_manifest(event, client_name())
    if manifest is not None:
        context = load_manifest_context(manifest, REPOSITORY_ROOT)
    elif ambiguity:
        context = ambiguity
    else:
        context = (
            "PubMed Search Builder repository hooks are active in maintenance mode. "
            "Keep generated run artifacts and personal absolute paths out of source control, "
            "and satisfy the repository hygiene check before handoff."
        )

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
