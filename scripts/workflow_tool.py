#!/usr/bin/env python3
"""Execute one workflow command and register its evidence atomically in the run manifest."""

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

ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import manifest_tool
from pubmed_search_builder.core.io import atomic_write_json
from pubmed_search_builder.workflow.events import append_event, load_v2, new_manifest
from pubmed_search_builder.workflow.service import migrate_manifest, run_stage as run_v2_stage, status as v2_status


COUNT_FIELDS = ("count", "search_count", "relevant_record_count", "candidate_count", "benchmark_size")


class WorkflowRunError(ValueError):
    pass


def read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def infer_count(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    for field in COUNT_FIELDS:
        value = payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def locked_scope_version(manifest: Path) -> int | None:
    if not manifest.is_file():
        return None
    data = manifest_tool.load_manifest(manifest)
    state = data.get("build_state")
    scope = state.get("scope") if isinstance(state, dict) else None
    version = scope.get("version") if isinstance(scope, dict) else None
    return version if isinstance(version, int) and version > 0 else None


def register_entry(args: argparse.Namespace, command_text: str, count: int | None) -> dict[str, Any]:
    add_args = [
        "add",
        "--manifest", str(args.manifest),
        "--kind", args.kind,
        "--command", command_text,
        "--returncode", "0",
    ]
    if args.output:
        add_args += ["--output", args.output]
    if args.label:
        add_args += ["--label", args.label]
    if args.block:
        add_args += ["--block", args.block]
    if args.note:
        add_args += ["--note", args.note]
    if count is not None:
        add_args += ["--count", str(count)]
    if args.scope_version is not None:
        add_args += ["--scope-version", str(args.scope_version)]
    for path in args.input:
        add_args += ["--input", path]
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        code = manifest_tool.main(add_args)
    if code != 0:
        raise WorkflowRunError(stream.getvalue().strip() or "manifest registration failed")
    return json.loads(stream.getvalue())


def run_stage(args: argparse.Namespace) -> dict[str, Any]:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise WorkflowRunError("A command is required after --")
    manifest = Path(args.manifest).resolve()
    cwd = Path(args.cwd).resolve() if args.cwd else manifest.parent
    inferred_scope = locked_scope_version(manifest)
    if args.scope_version is None:
        args.scope_version = inferred_scope
    elif inferred_scope is not None and args.scope_version != inferred_scope:
        raise WorkflowRunError(
            f"Requested scope version {args.scope_version} does not match locked scope version {inferred_scope}"
        )
    resolved_inputs = [
        (Path(path) if Path(path).is_absolute() else cwd / path).resolve()
        for path in args.input
    ]
    input_hashes_before: dict[Path, str] = {}
    for input_path in resolved_inputs:
        if not input_path.is_file():
            raise WorkflowRunError(f"Input artifact does not exist: {input_path}")
        input_hashes_before[input_path] = manifest_tool.sha256_file(input_path)
    output_path = None
    output_hash_before = None
    if args.output:
        candidate = Path(args.output)
        output_path = (candidate if candidate.is_absolute() else cwd / candidate).resolve()
        if output_path.is_file():
            output_hash_before = manifest_tool.sha256_file(output_path)
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return {
            "ok": False,
            "operation": "workflow-run-stage",
            "returncode": proc.returncode,
            "command": subprocess.list2cmdline(command),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
            "manifest_updated": False,
        }
    for input_path, expected_hash in input_hashes_before.items():
        if not input_path.is_file() or manifest_tool.sha256_file(input_path) != expected_hash:
            raise WorkflowRunError(f"Command modified declared input artifact: {input_path}")
    if output_path is not None:
        if not output_path.is_file():
            raise WorkflowRunError(f"Command succeeded but expected output does not exist: {output_path}")
        output_hash_after = manifest_tool.sha256_file(output_path)
        if (
            output_hash_before is not None
            and output_hash_after == output_hash_before
            and not args.allow_unchanged_output
        ):
            raise WorkflowRunError(
                "Command succeeded but the expected output was unchanged; use "
                "--allow-unchanged-output only for an intentional, documented reuse"
            )
    payload = read_json_object(output_path) if output_path else None
    if payload is None:
        try:
            parsed_stdout = json.loads(proc.stdout)
            payload = parsed_stdout if isinstance(parsed_stdout, dict) else None
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise WorkflowRunError("Command output reports ok=false and cannot be registered as successful evidence")
    count = args.count if args.count is not None else infer_count(payload)
    command_text = subprocess.list2cmdline(command)
    if output_path is not None:
        args.output = str(output_path)
    args.input = [str(path) for path in resolved_inputs]
    manifest_receipt = register_entry(args, command_text, count)
    return {
        "ok": True,
        "operation": "workflow-run-stage",
        "returncode": 0,
        "command": command_text,
        "output": str(output_path) if output_path else None,
        "count": count,
        "scope_version": args.scope_version,
        "manifest": manifest_receipt,
        "stdout_tail": proc.stdout[-2000:] if proc.stdout.strip() else "",
        "stderr_tail": proc.stderr[-2000:] if proc.stderr.strip() else "",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one tool stage and record hashes/provenance in run_manifest.json.")
    parser.add_argument("--manifest", default="run_manifest.json")
    parser.add_argument("--kind", required=True, choices=manifest_tool.ENTRY_KINDS)
    parser.add_argument("--label", default="")
    parser.add_argument("--block", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--output", help="Expected command output path, relative to --cwd.")
    parser.add_argument(
        "--allow-unchanged-output",
        action="store_true",
        help="Allow intentional reuse of a pre-existing identical output artifact.",
    )
    parser.add_argument("--input", action="append", default=[], help="Input artifact to hash; repeatable.")
    parser.add_argument("--scope-version", type=int)
    parser.add_argument("--count", type=int, help="Explicit result count; otherwise inferred from output JSON.")
    parser.add_argument("--cwd", help="Command working directory; defaults to manifest directory.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command and arguments after --.")
    return parser


def build_v2_parser() -> argparse.ArgumentParser:
    """Build the contract-driven workflow-v2 interface.

    The historical no-subcommand interface remains in ``build_parser`` and is
    selected whenever the invocation starts with an option such as
    ``--manifest``.  This lets existing agents and runbooks keep working.
    """

    parser = argparse.ArgumentParser(description="Contract-driven workflow v2 controls.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create an empty append-only v2 run manifest.")
    init.add_argument("--manifest", default="run_manifest_v2.json")
    init.add_argument("--topic-slug", default="")
    init.add_argument("--skill-version", default="2.0.0")

    migrate = subparsers.add_parser("migrate", help="Write a v2 sibling from a v1.1 manifest without altering it.")
    migrate.add_argument("--manifest", required=True, help="Existing v1.1 or v2 manifest.")
    migrate.add_argument("--output", required=True, help="New v2 manifest path; must not exist.")

    status = subparsers.add_parser("status", help="Derive workflow state and stage status from a v2 event log.")
    status.add_argument("--manifest", default="run_manifest_v2.json")

    decision = subparsers.add_parser("decision", help="Append a structured workflow decision to a v2 manifest.")
    decision.add_argument("--manifest", default="run_manifest_v2.json")
    decision.add_argument("--id", required=True, help="Stable decision identifier, for example framework or filter.")
    decision.add_argument("--status", choices=["pending", "resolved", "declined"], required=True)
    decision.add_argument("--value", default="")
    decision.add_argument("--reason", required=True)

    run = subparsers.add_parser("run", help="Run one declared stage and append validated artifact references.")
    run.add_argument("--manifest", default="run_manifest_v2.json")
    run.add_argument("--stage", required=True)
    run.add_argument("--input", action="append", default=[], metavar="ROLE=PATH")
    run.add_argument("--output", action="append", default=[], metavar="ROLE=PATH")
    run.add_argument("--scope-version", type=int)
    run.add_argument("--cwd", default=".")
    run.add_argument("command_args", nargs=argparse.REMAINDER, help="Command and arguments after --.")
    return parser


def main_v2(argv: list[str]) -> int:
    args = build_v2_parser().parse_args(argv)
    try:
        if args.command == "init":
            path = Path(args.manifest)
            if path.exists():
                raise WorkflowRunError(f"Refusing to overwrite existing v2 manifest: {path}")
            atomic_write_json(path, new_manifest(args.topic_slug, skill_version=args.skill_version))
            receipt: dict[str, Any] = {
                "ok": True,
                "operation": "workflow-manifest-init",
                "manifest": str(path),
                "manifest_version": "2.0",
            }
        elif args.command == "migrate":
            receipt = migrate_manifest(Path(args.manifest), Path(args.output))
        elif args.command == "status":
            receipt = v2_status(Path(args.manifest))
        elif args.command == "decision":
            event = append_event(
                Path(args.manifest),
                {
                    "event_type": "decision-recorded",
                    "decision_id": args.id,
                    "status": args.status,
                    "value": args.value,
                    "reason": args.reason,
                },
            )
            receipt = {"ok": True, "operation": "workflow-decision-record", "event": event}
        else:
            receipt = run_v2_stage(
                manifest=Path(args.manifest),
                stage_name=args.stage,
                inputs=args.input,
                outputs=args.output,
                command=args.command_args,
                cwd=Path(args.cwd).resolve(),
                scope_version=args.scope_version,
            )
    except (OSError, ValueError, WorkflowRunError, json.JSONDecodeError) as exc:
        receipt = {"ok": False, "operation": f"workflow-{args.command}", "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    values = list(argv) if argv is not None else sys.argv[1:]
    if values and values[0] in {"init", "migrate", "status", "decision", "run"}:
        return main_v2(values)
    args = build_parser().parse_args(values)
    try:
        receipt = run_stage(args)
    except (WorkflowRunError, manifest_tool.ManifestError, OSError, json.JSONDecodeError) as exc:
        receipt = {"ok": False, "operation": "workflow-run-stage", "error": str(exc), "manifest_updated": False}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
