#!/usr/bin/env python3
"""Run lightweight deterministic gates before a Codex turn stops."""

from __future__ import annotations

import subprocess
import sys

from common import (
    REPOSITORY_ROOT,
    emit,
    event_cwd,
    find_nearest_manifest,
    manifest_issue_count,
    read_event,
    relative_label,
    run_process,
)


def run_manifest_gate(manifest):
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "manifest_tool.py"),
        "show",
        "--manifest",
        str(manifest),
        "--validate",
        "--check-files",
        "--require-complete-loop",
    ]
    return run_process(command, cwd=manifest.parent, timeout=25)


def run_hygiene_gate():
    command = [sys.executable, str(REPOSITORY_ROOT / "scripts" / "repository_hygiene.py")]
    return run_process(command, cwd=REPOSITORY_ROOT, timeout=20)


def main() -> int:
    event = read_event()
    cwd = event_cwd(event)
    if cwd is None:
        emit({})
        return 0

    manifest = find_nearest_manifest(cwd)
    try:
        if manifest is not None:
            result = run_manifest_gate(manifest)
            if result.returncode != 0:
                count = manifest_issue_count(result.stdout)
                count_text = f" ({count} reported gaps)" if count is not None else ""
                emit(
                    {
                        "continue": True,
                        "systemMessage": (
                            "The active PubMed run does not yet satisfy the complete-loop handoff gate"
                            f"{count_text}. This is advisory so intake and scope questions may still pause. "
                            "Before final handoff, run `python scripts/manifest_tool.py show --manifest "
                            f"{relative_label(manifest)} --validate --check-files --require-complete-loop` "
                            "and resolve its reported gaps."
                        ),
                    }
                )
            else:
                emit({})
            return 0

        result = run_hygiene_gate()
        if result.returncode == 0:
            emit({})
            return 0
        if not bool(event.get("stop_hook_active")):
            emit(
                {
                    "decision": "block",
                    "reason": (
                        "Repository hygiene failed. Run `python scripts/repository_hygiene.py`, "
                        "fix the reported tracked-file issues, and then finish the handoff."
                    ),
                }
            )
        else:
            emit(
                {
                    "continue": True,
                    "systemMessage": (
                        "Repository hygiene is still failing after one continuation. "
                        "The hook will not create a stop loop; report the unresolved failure explicitly."
                    ),
                }
            )
    except (OSError, subprocess.SubprocessError) as exc:
        emit(
            {
                "continue": True,
                "systemMessage": (
                    "A repository hook could not run its local validation command. "
                    f"Report the hook failure before handoff ({type(exc).__name__})."
                ),
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
