"""Append-only v2 run manifests and deterministic state reduction."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pubmed_search_builder.core.io import atomic_write_json, load_json_object
from pubmed_search_builder.workflow.contracts import ArtifactReference, artifact_type_for_operation


MANIFEST_VERSION = "2.0"
SKILL_NAME = "pubmed-search-builder"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_manifest(topic_slug: str = "", *, skill_version: str = "2.0.0") -> dict[str, Any]:
    now = utc_now()
    return {
        "manifest_version": MANIFEST_VERSION,
        "skill": SKILL_NAME,
        "skill_version": skill_version,
        "topic_slug": topic_slug,
        "created_utc": now,
        "updated_utc": now,
        "working_dir": str(Path.cwd()),
        "events": [],
    }


def is_v2(data: dict[str, Any]) -> bool:
    return str(data.get("manifest_version")) == MANIFEST_VERSION and isinstance(data.get("events"), list)


def validation_issues(data: dict[str, Any]) -> list[str]:
    required = {"manifest_version", "skill", "skill_version", "topic_slug", "created_utc", "updated_utc", "working_dir", "events"}
    issues = [f"missing top-level key: {key}" for key in sorted(required - set(data))]
    if data.get("manifest_version") != MANIFEST_VERSION:
        issues.append(f"manifest_version must be {MANIFEST_VERSION}")
    if data.get("skill") != SKILL_NAME:
        issues.append(f"skill must be {SKILL_NAME}")
    events = data.get("events")
    if not isinstance(events, list):
        return issues + ["events must be an array"]
    allowed_types = {"artifact-recorded", "artifact-superseded", "decision-recorded"}
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            issues.append(f"event {index} must be an object")
            continue
        if event.get("seq") != index:
            issues.append(f"event {index} must have seq={index}")
        if not isinstance(event.get("timestamp_utc"), str) or not event["timestamp_utc"]:
            issues.append(f"event {index} lacks timestamp_utc")
        event_type = event.get("event_type")
        if event_type not in allowed_types:
            issues.append(f"event {index} has unknown event_type: {event_type!r}")
        if event_type == "artifact-recorded":
            for key in ("stage", "command", "inputs", "outputs"):
                if key not in event:
                    issues.append(f"artifact event {index} lacks {key}")
        if event_type == "decision-recorded":
            for key in ("decision_id", "status", "reason"):
                if not str(event.get(key) or "").strip():
                    issues.append(f"decision event {index} lacks {key}")
    return issues


def load_v2(path: Path) -> dict[str, Any]:
    data = load_json_object(path)
    if not is_v2(data):
        raise ValueError(f"Manifest is not v{MANIFEST_VERSION}: {path}. Run workflow_tool.py migrate first.")
    issues = validation_issues(data)
    if issues:
        raise ValueError("Invalid v2 manifest:\n- " + "\n- ".join(issues))
    return data


def append_event(path: Path, event: dict[str, Any]) -> dict[str, Any]:
    data = load_v2(path)
    events = data["events"]
    next_event = dict(event)
    next_event.setdefault("seq", len(events) + 1)
    next_event.setdefault("timestamp_utc", utc_now())
    if next_event["seq"] != len(events) + 1:
        raise ValueError("Manifest event sequence must append exactly once.")
    if not isinstance(next_event.get("event_type"), str):
        raise ValueError("Manifest event requires event_type.")
    events.append(next_event)
    data["updated_utc"] = next_event["timestamp_utc"]
    atomic_write_json(path, data)
    return next_event


def artifact_event(
    *,
    stage: str,
    command: list[str],
    inputs: Iterable[ArtifactReference],
    outputs: Iterable[ArtifactReference],
    scope_version: int | None,
    returncode: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_type": "artifact-recorded",
        "stage": stage,
        "scope_version": scope_version,
        "command": list(command),
        "returncode": returncode,
        "inputs": [item.as_dict() for item in inputs],
        "outputs": [item.as_dict() for item in outputs],
        "metadata": metadata or {},
    }


def reduce_events(data: dict[str, Any]) -> dict[str, Any]:
    """Derive current state from event order without mutating the manifest."""

    if not is_v2(data):
        raise ValueError("State reduction requires a v2 manifest.")
    decisions: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    stages: set[str] = set()
    scope_version = 0
    stale_artifacts = 0
    workflow_context: dict[str, Any] = {}
    for event in data["events"]:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        if event_type == "decision-recorded":
            decision_id = str(event.get("decision_id") or "")
            if decision_id:
                decisions[decision_id] = dict(event)
        elif event_type == "artifact-recorded":
            version = event.get("scope_version")
            if isinstance(version, int) and version > scope_version:
                scope_version = version
            stage = event.get("stage")
            if isinstance(stage, str) and stage:
                stages.add(stage)
            for output in event.get("outputs", []):
                if isinstance(output, dict) and isinstance(output.get("role"), str):
                    artifacts[output["role"]] = (dict(output), event)
            metadata = event.get("metadata")
            context = metadata.get("workflow_context") if isinstance(metadata, dict) else None
            if isinstance(context, dict):
                workflow_context.update(context)
        elif event_type == "artifact-superseded":
            role = event.get("role")
            if isinstance(role, str):
                artifacts.pop(role, None)
            else:
                superseded_path = str(event.get("path") or "")
                for active_role, (artifact, _) in list(artifacts.items()):
                    if superseded_path and artifact.get("path") == superseded_path:
                        artifacts.pop(active_role, None)
    latest_hash_by_path: dict[str, str] = {}
    for artifact, _ in artifacts.values():
        path = str(artifact.get("path") or "")
        digest = str(artifact.get("sha256") or "")
        if path and digest:
            latest_hash_by_path[path] = digest

    current_events: dict[int, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for artifact, event in artifacts.values():
        sequence = int(event.get("seq") or 0)
        if sequence not in current_events:
            current_events[sequence] = (event, [])
        current_events[sequence][1].append(artifact)

    stale_event_sequences: set[int] = set()
    stale_references: set[tuple[str, str]] = set()
    changed = True
    while changed:
        changed = False
        for sequence, (event, outputs) in current_events.items():
            if sequence in stale_event_sequences:
                continue
            event_scope = event.get("scope_version")
            stale = isinstance(event_scope, int) and scope_version and event_scope < scope_version
            for item in event.get("inputs", []):
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "")
                digest = str(item.get("sha256") or "")
                if path and digest and latest_hash_by_path.get(path, digest) != digest:
                    stale = True
                if (path, digest) in stale_references:
                    stale = True
            if stale:
                stale_event_sequences.add(sequence)
                stale_references.update(
                    (str(output.get("path") or ""), str(output.get("sha256") or ""))
                    for output in outputs
                )
                changed = True

    active: dict[str, dict[str, Any]] = {}
    for role, (artifact, event) in artifacts.items():
        if int(event.get("seq") or 0) in stale_event_sequences:
            stale_artifacts += 1
            continue
        active[role] = artifact
    return {
        "manifest_version": MANIFEST_VERSION,
        "scope_version": scope_version or None,
        "decisions": decisions,
        "artifacts": active,
        "completed_stages": sorted(stages),
        "stale_artifact_count": stale_artifacts,
        "event_count": len(data["events"]),
        "workflow_context": workflow_context,
    }


def _legacy_reference(role: str, path_value: str, sha256: str, scope_version: int | None, operation: str) -> ArtifactReference:
    return ArtifactReference(
        role=role,
        path=path_value,
        sha256=sha256,
        artifact_type=artifact_type_for_operation(operation),
        artifact_version=1,
        scope_version=scope_version,
    )


def migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
    """Translate a v1.1 manifest into a standalone v2 event log.

    The original file is intentionally untouched.  Missing legacy files remain
    represented by their recorded path/hash so the new status command can flag
    them rather than silently erasing provenance.
    """

    if is_v2(data):
        return data
    migrated = new_manifest(str(data.get("topic_slug") or ""), skill_version=str(data.get("skill_version") or "2.0.0"))
    migrated["working_dir"] = str(data.get("working_dir") or migrated["working_dir"])
    events: list[dict[str, Any]] = []
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        command_text = str(entry.get("command") or "")
        output_path = str(entry.get("output_path") or "")
        scope = entry.get("scope_version")
        scope_version = scope if isinstance(scope, int) and not isinstance(scope, bool) else None
        outputs = []
        if output_path:
            outputs.append(
                _legacy_reference(
                    str(entry.get("label") or entry.get("kind") or "output"),
                    output_path,
                    str(entry.get("output_sha256") or ""),
                    scope_version,
                    str(entry.get("kind") or ""),
                ).as_dict()
            )
        inputs = [
            _legacy_reference("input", str(path), str(digest), scope_version, "").as_dict()
            for path, digest in (entry.get("input_sha256") or {}).items()
        ] if isinstance(entry.get("input_sha256"), dict) else []
        events.append({
            "seq": len(events) + 1,
            "timestamp_utc": str(entry.get("timestamp_utc") or migrated["created_utc"]),
            "event_type": "artifact-recorded",
            "stage": "legacy",
            "scope_version": scope_version,
            "command": [command_text] if command_text else [],
            "returncode": int(entry.get("returncode") or 0),
            "inputs": inputs,
            "outputs": outputs,
            "metadata": {"legacy_kind": entry.get("kind"), "legacy_seq": entry.get("seq")},
        })
    state = data.get("build_state") if isinstance(data.get("build_state"), dict) else {}
    gates = state.get("gates") if isinstance(state.get("gates"), dict) else {}
    for decision_id, value in gates.items():
        events.append({
            "seq": len(events) + 1,
            "timestamp_utc": migrated["created_utc"],
            "event_type": "decision-recorded",
            "decision_id": str(decision_id),
            "status": "resolved" if str(value).strip() and str(value).strip() != "pending" else "pending",
            "value": value,
            "reason": "migrated from v1 build_state",
        })
    pending = str(state.get("pending_user_question") or "").strip()
    if pending:
        events.append({
            "seq": len(events) + 1,
            "timestamp_utc": migrated["created_utc"],
            "event_type": "decision-recorded",
            "decision_id": "pending-user-question",
            "status": "pending",
            "value": pending,
            "reason": "migrated from v1 build_state",
        })
    for superseded in data.get("superseded", []):
        if not isinstance(superseded, dict):
            continue
        events.append({
            "seq": len(events) + 1,
            "timestamp_utc": str(superseded.get("timestamp_utc") or migrated["created_utc"]),
            "event_type": "artifact-superseded",
            "path": str(superseded.get("path") or ""),
            "superseded_by": str(superseded.get("superseded_by") or ""),
            "reason": str(superseded.get("reason") or "migrated from v1 superseded index"),
        })
    migrated["events"] = events
    migrated["updated_utc"] = utc_now()
    return migrated
