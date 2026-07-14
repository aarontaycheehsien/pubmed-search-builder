"""Stage-aware command execution and v1-to-v2 manifest migration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterable

from pubmed_search_builder.core.diagnostics import Diagnostic
from pubmed_search_builder.core.io import atomic_write_json, load_json_object, sha256_file
from pubmed_search_builder.domain.protocol import workflow_context
from pubmed_search_builder.workflow.contracts import ArtifactReference, reference_from_path
from pubmed_search_builder.workflow.events import append_event, artifact_event, load_v2, migrate_v1, reduce_events
from pubmed_search_builder.workflow.stages import canonical_stage, completion_diagnostics, stage_statuses


def parse_role_paths(values: Iterable[str], *, label: str, cwd: Path) -> list[tuple[str, Path]]:
    rows: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for value in values:
        if "=" not in value:
            raise ValueError(f"{label} must use role=path, got {value!r}")
        role, raw_path = value.split("=", 1)
        role = role.strip()
        if not role or not raw_path.strip() or role in seen:
            raise ValueError(f"{label} roles must be non-empty and unique, got {value!r}")
        seen.add(role)
        path = Path(raw_path)
        rows.append((role, (path if path.is_absolute() else cwd / path).resolve()))
    return rows


def redact_argv(command: list[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for item in command:
        if redact_next:
            result.append("***")
            redact_next = False
        elif item.casefold() in {"--api-key", "--token", "--access-token"}:
            result.append(item)
            redact_next = True
        elif "api_key=" in item.casefold() or "token=" in item.casefold():
            key = item.split("=", 1)[0]
            result.append(f"{key}=***")
        else:
            result.append(item)
    return result


def migrate_manifest(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError(f"Refusing to overwrite migration output: {output}")
    data = migrate_v1(load_json_object(source))
    atomic_write_json(output, data)
    return {
        "ok": True,
        "operation": "workflow-manifest-migrate",
        "source": str(source),
        "output": str(output),
        "event_count": len(data["events"]),
        "manifest_version": data["manifest_version"],
    }


def status(path: Path) -> dict[str, Any]:
    data = load_v2(path)
    state = reduce_events(data)
    diagnostics = completion_diagnostics(state)
    return {
        "ok": True,
        "operation": "workflow-status",
        "manifest": str(path),
        "state": state,
        "stages": stage_statuses(state),
        "handoff_ready": not diagnostics,
        "completion_diagnostics": [item.as_dict() for item in diagnostics],
    }


def run_stage(
    *,
    manifest: Path,
    stage_name: str,
    inputs: Iterable[str],
    outputs: Iterable[str],
    command: list[str],
    cwd: Path,
    scope_version: int | None,
) -> dict[str, Any]:
    spec = canonical_stage(stage_name)
    data = load_v2(manifest)
    command = list(command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("A command is required after --")
    input_rows = parse_role_paths(inputs, label="--input", cwd=cwd)
    output_rows = parse_role_paths(outputs, label="--output", cwd=cwd)
    missing_inputs = set(spec.required_input_roles) - {role for role, _ in input_rows}
    if missing_inputs:
        raise ValueError(f"Stage {spec.id} requires input roles: {', '.join(sorted(missing_inputs))}")
    missing_outputs = set(spec.required_output_roles) - {role for role, _ in output_rows}
    if missing_outputs:
        raise ValueError(f"Stage {spec.id} requires output roles: {', '.join(sorted(missing_outputs))}")
    before = {path: sha256_file(path) for _, path in input_rows if path.is_file()}
    absent = [str(path) for _, path in input_rows if not path.is_file()]
    if absent:
        raise ValueError("Declared input artifacts do not exist: " + ", ".join(absent))
    input_refs: list[ArtifactReference] = []
    for role, path in input_rows:
        try:
            reference, _ = reference_from_path(role, path, scope_version=scope_version)
        except ValueError:
            reference = ArtifactReference(role, str(path), sha256_file(path), "input/file", 1, scope_version)
        allowed = spec.accepted_input_types.get(role, ())
        if allowed and reference.artifact_type not in allowed:
            raise ValueError(
                f"Stage {spec.id} input role {role!r} requires one of {', '.join(allowed)}, "
                f"got {reference.artifact_type}"
            )
        input_refs.append(reference)
    context: dict[str, Any] = {}
    for role, path in input_rows:
        if role != "protocol":
            continue
        try:
            context = workflow_context(load_json_object(path))
        except ValueError:
            pass
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return {
            "ok": False,
            "operation": "workflow-stage-run",
            "stage": spec.id,
            "returncode": proc.returncode,
            "manifest_updated": False,
            "diagnostics": [Diagnostic("workflow.command.failed", "Stage command failed.", stage=spec.id).as_dict()],
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    changed_inputs = [str(path) for path, digest in before.items() if not path.is_file() or sha256_file(path) != digest]
    if changed_inputs:
        raise ValueError("Stage command modified declared input artifacts: " + ", ".join(changed_inputs))
    output_refs: list[ArtifactReference] = []
    diagnostics: list[Diagnostic] = []
    for role, path in output_rows:
        if not path.is_file():
            raise ValueError(f"Stage succeeded but output artifact is missing: {path}")
        reference, issues = reference_from_path(role, path, scope_version=scope_version)
        allowed = spec.accepted_output_types.get(role, ())
        if allowed and reference.artifact_type not in allowed:
            raise ValueError(
                f"Stage {spec.id} output role {role!r} requires one of {', '.join(allowed)}, "
                f"got {reference.artifact_type}"
            )
        output_refs.append(reference)
        diagnostics.extend(issues)
    errors = [issue for issue in diagnostics if issue.severity == "error"]
    if errors:
        return {
            "ok": False,
            "operation": "workflow-stage-run",
            "stage": spec.id,
            "returncode": 0,
            "manifest_updated": False,
            "diagnostics": [issue.as_dict() for issue in diagnostics],
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    event = append_event(
        manifest,
        artifact_event(
            stage=spec.id,
            command=redact_argv(command),
            inputs=input_refs,
            outputs=output_refs,
            scope_version=scope_version,
            metadata={
                "stdout_tail": proc.stdout[-2000:],
                "stderr_tail": proc.stderr[-2000:],
                "workflow_context": context,
            },
        ),
    )
    return {
        "ok": True,
        "operation": "workflow-stage-run",
        "stage": spec.id,
        "event": event,
        "manifest": str(manifest),
        "diagnostics": [issue.as_dict() for issue in diagnostics],
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
        "state": reduce_events(load_v2(manifest)),
    }
