#!/usr/bin/env python3
"""Gate the end of a turn on the run manifest, not on the assistant's prose.

The gate is conditional, not universal. An incomplete build may end a turn only when the manifest
positively records why -- a fresh, type-matched pause, a mid-run checkpoint, or an external blocker.
Anything else falls through to the complete-loop gate and is blocked.

Every failure path here fails *open*. A gate that cannot run, times out, or raises must never block:
blocking on a check that did not produce a verdict is how a stop loop starts. Three separate brakes
apply -- ``stop_hook_active`` (block at most once per cascade), a per-session block budget, and
``continue: True`` on every exception path.
"""

from __future__ import annotations

import json
import subprocess
import sys

from common import (
    REPOSITORY_ROOT,
    active_manifest,
    client_name,
    emit,
    event_cwd,
    last_user_turn,
    note_stop_block,
    read_event,
    relative_label,
    run_process,
    safe_message,
    stop_blocks_exhausted,
)


def run_stop_gate(manifest, since: str):
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "manifest_tool.py"),
        "state",
        "check-stop",
        "--manifest",
        str(manifest),
    ]
    if since:
        command += ["--since", since]
    return run_process(command, cwd=manifest.parent, timeout=25)


def run_hygiene_gate():
    command = [sys.executable, str(REPOSITORY_ROOT / "scripts" / "repository_hygiene.py")]
    return run_process(command, cwd=REPOSITORY_ROOT, timeout=20)


def verdict(stdout: str) -> dict | None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def advise(message: str) -> dict:
    return {"continue": True, "systemMessage": message}


def handle_manifest(event, client, manifest) -> dict:
    result = run_stop_gate(manifest, last_user_turn(event, client))
    payload = verdict(result.stdout)
    if payload is None:
        # No parseable verdict means the gate did not run, not that the build is complete.
        return advise(
            "The PubMed Stop gate could not produce a verdict for "
            f"{relative_label(manifest)}. Report that the handoff is unverified rather than "
            "implying the run passed its gates."
        )
    if payload.get("allow_stop") is True:
        if payload.get("basis") == "run-status":
            return advise(
                "Stopping on a recorded run status: "
                f"{safe_message(payload.get('reason'), limit=140)}. The complete-loop gate has not run; "
                "the build is not finished."
            )
        return {}

    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    summary = "; ".join(safe_message(issue, limit=160) for issue in issues[:4]) or safe_message(
        payload.get("reason"), limit=160
    )
    remaining = f"{len(issues)} unresolved gate" + ("s" if len(issues) != 1 else "")

    if bool(event.get("stop_hook_active")) or stop_blocks_exhausted(event, client):
        return advise(
            f"The PubMed handoff still has {remaining} after a continuation: {summary}. "
            "Do not retry in a loop. Either record why the run is idle with "
            "`manifest_tool.py state set-run-status ...`, or state plainly in the final response that "
            "the strategy is not validated and name the outstanding checks."
        )

    note_stop_block(event, client)
    return {
        "decision": "block",
        "reason": (
            f"The PubMed handoff is incomplete ({remaining}): {summary}. "
            "Resolve these, or -- if the run is legitimately idle -- record why with "
            "`manifest_tool.py state set-run-status <awaiting-user --type ...|checkpoint|blocked-external> "
            f"--reason ... --manifest {relative_label(manifest)}`."
        ),
    }


def handle_hygiene(event, client) -> dict:
    result = run_hygiene_gate()
    if result.returncode == 0:
        return {}
    if bool(event.get("stop_hook_active")) or stop_blocks_exhausted(event, client):
        return advise(
            "Repository hygiene is still failing after one continuation. "
            "The hook will not create a stop loop; report the unresolved failure explicitly."
        )
    note_stop_block(event, client)
    return {
        "decision": "block",
        "reason": (
            "Repository hygiene failed. Run `python scripts/repository_hygiene.py`, "
            "fix the reported tracked-file issues, and then finish the handoff."
        ),
    }


def main() -> int:
    event = read_event()
    client = client_name()
    if event_cwd(event) is None:
        emit({})
        return 0

    try:
        manifest, ambiguity = active_manifest(event, client)
        if manifest is not None:
            emit(handle_manifest(event, client, manifest))
            return 0
        response = handle_hygiene(event, client)
        if ambiguity and "decision" not in response:
            # Advisory only: refusing to guess between runs must not become a refusal to stop.
            # Already built from sanitized path labels, so it is not re-escaped here.
            response = advise(ambiguity)
        emit(response)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        emit(
            advise(
                "A repository hook could not run its local validation command. "
                f"Report the hook failure before handoff ({type(exc).__name__})."
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
