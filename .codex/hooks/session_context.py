#!/usr/bin/env python3
"""Restore concise repository or active-run context at Codex session start."""

from __future__ import annotations

from common import REPOSITORY_ROOT, emit, event_cwd, find_nearest_manifest, load_manifest_context, read_event


def main() -> int:
    event = read_event()
    cwd = event_cwd(event)
    if cwd is None:
        emit({})
        return 0

    manifest = find_nearest_manifest(cwd)
    if manifest is None:
        context = (
            "PubMed Search Builder repository hooks are active in maintenance mode. "
            "Keep generated run artifacts and personal absolute paths out of source control, "
            "and satisfy the repository hygiene check before handoff."
        )
    else:
        context = load_manifest_context(manifest, REPOSITORY_ROOT)

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
