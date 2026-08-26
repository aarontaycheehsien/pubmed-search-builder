#!/usr/bin/env python3
"""Run PubMed workflow commands with stage checks and manifest provenance."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import manifest_tool


COUNT_FIELDS = ("count", "search_count", "benchmark_size", "candidate_count")


class WorkflowError(ValueError):
    pass


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def load_run(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise WorkflowError(f"Run manifest does not exist: {path}")
    data = manifest_tool.load_manifest(path)
    if data.get("skill") != manifest_tool.SKILL_NAME:
        raise WorkflowError(f"Not a {manifest_tool.SKILL_NAME} manifest: {path}")
    structural = manifest_tool.validate_manifest(data, manifest_path=path)
    if structural:
        raise WorkflowError("Manifest validation failed: " + "; ".join(structural[:5]))
    return data


def read_json_object(path: Path | None, stdout: str = "") -> dict[str, Any] | None:
    raw = ""
    if path is not None and path.is_file() and path.suffix.lower() == ".json":
        raw = path.read_text(encoding="utf-8-sig")
    elif stdout.strip():
        raw = stdout
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def infer_count(payload: dict[str, Any] | None) -> int | None:
    if payload:
        for field in COUNT_FIELDS:
            value = payload.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def stage_preflight(data: dict[str, object], stage: str) -> list[str]:
    if stage not in manifest_tool.STAGE_NAMES:
        return [f"unknown workflow stage: {stage}"]
    state_value = data.get("build_state")
    if not isinstance(state_value, dict):
        return ["build_state is not initialized"]
    state = manifest_tool.ensure_build_state(data)
    issues: list[str] = []
    if state.get("current_stage") != stage:
        issues.append(f"manifest current_stage is {state.get('current_stage')!r}, not {stage!r}")
    seed_value = str((state.get("gates") or {}).get("seed", "")).strip().lower()
    index = manifest_tool.STAGE_NAMES.index(stage)
    for prior in manifest_tool.STAGE_NAMES[:index]:
        if prior == "limited-seed-evidence" and seed_value not in manifest_tool.PROVIDED_SEED_GATE_VALUES:
            continue
        if prior == "peer-review-handoff":
            continue
        if manifest_tool.stage_disposition(state, prior) not in manifest_tool.STAGE_DISPOSITIONS:
            issues.append(f"prior stage is not recorded: {prior}")
    if index >= manifest_tool.STAGE_NAMES.index("mesh-exploration"):
        for gate in ("framework", "seed", "concept"):
            if not manifest_tool.gate_resolved((state.get("gates") or {}).get(gate)):
                issues.append(f"gate is unresolved: {gate}")
        if str(state.get("pending_user_question") or "").strip():
            issues.append("a user/protocol question is still pending")
    return issues


def register_entry(
    args: argparse.Namespace,
    command: list[str],
    output: Path | None,
    inputs: list[Path],
    count: int | None,
) -> dict[str, Any]:
    values = [
        "add",
        "--manifest", str(args.manifest),
        "--kind", args.kind,
        "--stage", args.stage,
        "--command", subprocess.list2cmdline(command),
    ]
    if output is not None:
        values += ["--output", str(output)]
    for path in inputs:
        values += ["--input", str(path)]
    if count is not None:
        values += ["--count", str(count)]
    if args.label:
        values += ["--label", args.label]
    if args.block:
        values += ["--block", args.block]
    if args.note:
        values += ["--note", args.note]
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        code = manifest_tool.main(values)
    if code != 0:
        raise WorkflowError(stream.getvalue().strip() or "manifest registration failed")
    return json.loads(stream.getvalue())


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    path = args.manifest.resolve()
    with manifest_tool.manifest_lock(path):
        if path.exists():
            raise WorkflowError(f"Refusing to overwrite existing manifest: {path}")
        data = manifest_tool.new_manifest(args.topic_slug, args.skill_version)
        data["working_dir"] = str(path.parent)
        manifest_tool.ensure_build_state(data)
        manifest_tool.save_manifest(path, data)
    return {"ok": True, "operation": "workflow-init", "manifest": str(path)}


def command_attach(args: argparse.Namespace) -> dict[str, Any]:
    data = load_run(args.manifest)
    state = manifest_tool.ensure_build_state(data)
    return {
        "ok": True,
        "operation": "workflow-attach",
        "manifest": str(args.manifest.resolve()),
        "topic_slug": data.get("topic_slug", ""),
        "current_stage": state.get("current_stage"),
    }


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    data = load_run(args.manifest)
    state = manifest_tool.ensure_build_state(data)
    issues = manifest_tool.complete_loop_issues(data, manifest_path=args.manifest)
    return {
        "ok": True,
        "operation": "workflow-status",
        "manifest": str(args.manifest.resolve()),
        "topic_slug": data.get("topic_slug", ""),
        "current_stage": state.get("current_stage"),
        "run_status": state.get("run_status"),
        "complete": not issues,
        "next_unmet_gate": issues[0] if issues else None,
        "issue_count": len(issues),
    }


def command_run(args: argparse.Namespace) -> dict[str, Any]:
    data = load_run(args.manifest)
    preflight = stage_preflight(data, args.stage)
    if preflight:
        raise WorkflowError("Stage preflight failed: " + "; ".join(preflight[:5]))
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise WorkflowError("A command is required after --")
    cwd = args.cwd.resolve() if args.cwd else args.manifest.parent.resolve()
    inputs = [(path if path.is_absolute() else cwd / path).resolve() for path in args.input]
    input_hashes: dict[Path, str] = {}
    for path in inputs:
        if not path.is_file():
            raise WorkflowError(f"Input artifact does not exist: {path}")
        input_hashes[path] = manifest_tool.sha256_file(path)
    output = None
    old_output_hash = None
    if args.output:
        output = (args.output if args.output.is_absolute() else cwd / args.output).resolve()
        if output.is_file():
            old_output_hash = manifest_tool.sha256_file(output)

    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        return {
            "ok": False,
            "operation": "workflow-run",
            "returncode": result.returncode,
            "manifest_updated": False,
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        }
    for path, expected in input_hashes.items():
        if not path.is_file() or manifest_tool.sha256_file(path) != expected:
            raise WorkflowError(f"Command modified declared input artifact: {path}")
    if output is not None:
        if not output.is_file():
            raise WorkflowError(f"Command succeeded but expected output does not exist: {output}")
        if (
            old_output_hash is not None
            and manifest_tool.sha256_file(output) == old_output_hash
            and not args.allow_unchanged_output
        ):
            raise WorkflowError("Command succeeded but the expected output was unchanged")
    payload = read_json_object(output, result.stdout)
    if payload is not None and payload.get("ok") is False:
        raise WorkflowError("Command output reports ok=false")
    count = args.count if args.count is not None else infer_count(payload)
    receipt = register_entry(args, command, output, inputs, count)
    return {
        "ok": True,
        "operation": "workflow-run",
        "returncode": 0,
        "manifest_updated": True,
        "output": str(output) if output else None,
        "count": count,
        "manifest": receipt,
        "stdout_tail": result.stdout[-2000:] if result.stdout.strip() else "",
        "stderr_tail": result.stderr[-2000:] if result.stderr.strip() else "",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run PubMed workflow commands with manifest provenance.")
    commands = parser.add_subparsers(dest="action", required=True)

    init = commands.add_parser("init")
    init.add_argument("--manifest", type=Path, default=Path("run_manifest.json"))
    init.add_argument("--topic-slug", default="")
    init.add_argument("--skill-version", default=manifest_tool.DEFAULT_SKILL_VERSION)

    for name in ("attach", "status"):
        sub = commands.add_parser(name)
        sub.add_argument("--manifest", type=Path, default=Path("run_manifest.json"))

    run = commands.add_parser("run")
    run.add_argument("--manifest", type=Path, default=Path("run_manifest.json"))
    run.add_argument("--stage", required=True, choices=manifest_tool.STAGE_NAMES)
    run.add_argument("--kind", required=True, choices=manifest_tool.ENTRY_KINDS)
    run.add_argument("--input", action="append", type=Path, default=[])
    run.add_argument("--output", type=Path)
    run.add_argument("--count", type=int)
    run.add_argument("--cwd", type=Path)
    run.add_argument("--label", default="")
    run.add_argument("--block", default="")
    run.add_argument("--note", default="")
    run.add_argument("--allow-unchanged-output", action="store_true")
    run.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.action == "init":
            payload = command_init(args)
        elif args.action == "attach":
            payload = command_attach(args)
        elif args.action == "status":
            payload = command_status(args)
        else:
            payload = command_run(args)
    except (OSError, ValueError, json.JSONDecodeError, manifest_tool.ManifestError, WorkflowError) as exc:
        payload = {"ok": False, "operation": f"workflow-{args.action}", "error": str(exc)}
    emit(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
