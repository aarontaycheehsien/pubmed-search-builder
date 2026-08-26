#!/usr/bin/env python3
"""Render a deterministic final PubMed strategy handoff from validated inputs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import manifest_tool


class ExportError(ValueError):
    pass


def final_binding(
    data: dict[str, object], *, manifest_path: Path, strategy_path: Path
) -> tuple[str, dict[str, object], dict[str, object]]:
    structural = manifest_tool.validate_manifest(data, check_files=True, manifest_path=manifest_path)
    if structural:
        raise ExportError("Manifest validation failed: " + "; ".join(structural[:5]))
    entries = [entry for entry in data.get("entries", []) if isinstance(entry, dict)]
    final_qa = manifest_tool.latest_final_qa(entries)
    final_search = manifest_tool.latest_final_search(entries)
    if final_qa is None:
        raise ExportError("No final-QA entry is recorded")
    if final_search is None:
        raise ExportError("No hash-bound final PubMed count is recorded")
    qa_payload = manifest_tool.entry_output_json(final_qa, manifest_path=manifest_path, data=data)
    if not final_qa.get("output_sha256") or qa_payload is None or qa_payload.get("ok") is not True:
        raise ExportError("The latest final-QA artifact is missing, unhashed, or unsuccessful")
    shared = manifest_tool.strategy_hashes(final_qa) & manifest_tool.strategy_hashes(final_search)
    if len(shared) != 1:
        raise ExportError("Final QA and the final PubMed count must share exactly one strategy hash")
    actual_hash = manifest_tool.sha256_file(strategy_path)
    expected_hash = next(iter(shared))
    if actual_hash != expected_hash:
        raise ExportError("The supplied strategy does not match the hash used by final QA and the final PubMed count")
    return actual_hash, final_qa, final_search


def markdown_fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(4, longest + 1)


def render_markdown(
    *, data: dict[str, object], strategy_path: Path, strategy_text: str,
    strategy_hash: str, final_qa: dict[str, object], final_search: dict[str, object]
) -> str:
    metadata = {
        "topic_slug": str(data.get("topic_slug") or ""),
        "strategy_file": strategy_path.name,
        "strategy_sha256": strategy_hash,
        "final_pubmed_count": final_search.get("count"),
        "final_count_manifest_seq": final_search.get("seq"),
        "final_qa_manifest_seq": final_qa.get("seq"),
        "manifest_version": data.get("manifest_version"),
    }
    fence = markdown_fence(strategy_text)
    strategy_body = strategy_text if strategy_text.endswith(("\n", "\r")) else strategy_text + "\n"
    return (
        "# Final PubMed Strategy\n\n"
        "This handoff was rendered deterministically from the hash-validated strategy file.\n\n"
        "## Provenance\n\n"
        "```json\n"
        + json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n```\n\n"
        "## Strategy\n\n"
        f"{fence}text\n{strategy_body}{fence}\n"
    )


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.resolve()
    strategy_path = args.strategy.resolve()
    output_path = args.output.resolve()
    if not manifest_path.is_file():
        raise ExportError(f"Manifest does not exist: {manifest_path}")
    if not strategy_path.is_file():
        raise ExportError(f"Strategy does not exist: {strategy_path}")
    if output_path.name.lower() != "final_strategy.md":
        raise ExportError("Deterministic handoff output must be named final_strategy.md")
    if output_path in {manifest_path, strategy_path}:
        raise ExportError("Output must not overwrite the manifest or source strategy")
    data = manifest_tool.load_manifest(manifest_path)
    strategy_hash, final_qa, final_search = final_binding(
        data, manifest_path=manifest_path, strategy_path=strategy_path
    )
    try:
        strategy_text = strategy_path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExportError("Strategy must be UTF-8 text") from exc
    rendered = render_markdown(
        data=data,
        strategy_path=strategy_path,
        strategy_text=strategy_text,
        strategy_hash=strategy_hash,
        final_qa=final_qa,
        final_search=final_search,
    )
    rendered_bytes = rendered.encode("utf-8")
    if output_path.is_file():
        if output_path.read_bytes() != rendered_bytes:
            raise ExportError(
                "Refusing to replace a different final_strategy.md; use a new run directory "
                "or archive the prior completed run"
            )
    else:
        atomic_write(output_path, rendered_bytes)
    return {
        "ok": True,
        "operation": "export-final",
        "output": str(output_path),
        "output_sha256": manifest_tool.sha256_file(output_path),
        "strategy_sha256": strategy_hash,
        "count": final_search.get("count"),
        "final_count_manifest_seq": final_search.get("seq"),
        "final_qa_manifest_seq": final_qa.get("seq"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a deterministic, hash-validated final PubMed strategy.")
    parser.add_argument("--strategy", type=Path, required=True, help="Exact final strategy text file.")
    parser.add_argument("--manifest", type=Path, default=Path("run_manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("final_strategy.md"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = export(args)
    except (OSError, ValueError, json.JSONDecodeError, manifest_tool.ManifestError, ExportError) as exc:
        payload = {"ok": False, "operation": "export-final", "error": str(exc)}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
