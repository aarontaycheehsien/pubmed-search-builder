#!/usr/bin/env python3
"""Evaluate revision no-harm invariants and select the authoritative strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


CHECK_NAMES = (
    "named-defect-fixed",
    "heldout-preserved",
    "required-blocks-justified",
    "syntax-translation-stable",
    "scope-unchanged-or-explicit",
    "workload-recorded",
)


class RevisionGuardError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RevisionGuardError(f"Could not read revision guard input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RevisionGuardError("Revision guard input must be a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_file(value: object, base: Path, label: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise RevisionGuardError(f"{label} strategy_file is required")
    path = Path(text)
    if not path.is_absolute():
        path = base / path
    if not path.is_file():
        raise RevisionGuardError(f"{label} strategy file does not exist: {path}")
    return path.resolve()


def normalize_pmids(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise RevisionGuardError(f"{label} must be a list")
    pmids = [str(item).strip() for item in value]
    if any(not pmid.isdigit() for pmid in pmids):
        raise RevisionGuardError(f"{label} must contain numeric PMIDs")
    return list(dict.fromkeys(pmids))


def state(data: dict[str, Any], key: str, base: Path) -> tuple[dict[str, Any], Path]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RevisionGuardError(f"{key} must be an object")
    path = resolve_file(value.get("strategy_file"), base, key)
    expected = str(value.get("strategy_sha256") or "").strip()
    actual = sha256_file(path)
    if not expected or expected != actual:
        raise RevisionGuardError(f"{key} strategy_sha256 does not match {path}")
    return value, path


def check(name: str, passed: bool, evidence: dict[str, Any], failure: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "evidence": evidence, "failure": "" if passed else failure}


def disposition_for_checks(checks: list[dict[str, Any]], experimental: dict[str, Any] | None = None) -> tuple[bool, str]:
    passed = all(item.get("passed") is True for item in checks)
    experimental = experimental if isinstance(experimental, dict) else {}
    retain = experimental.get("retain_if_failed") is True
    labelled = bool(str(experimental.get("variant_id") or "").strip() and str(experimental.get("label") or "").strip())
    return passed, "adopt" if passed else "experimental-only" if retain and labelled else "revert-to-baseline"


def evaluate_payload(data: dict[str, Any], *, base: Path) -> dict[str, Any]:
    if data.get("guard_version") != 1:
        raise RevisionGuardError("guard_version must be 1")
    revision_id = str(data.get("revision_id") or "").strip()
    revision_kind = str(data.get("revision_kind") or "").strip()
    if not revision_id or revision_kind not in {"critic", "vocabulary"}:
        raise RevisionGuardError("revision_id and revision_kind critic|vocabulary are required")
    baseline, baseline_path = state(data, "baseline", base)
    revised, revised_path = state(data, "revised", base)

    defect = data.get("named_defect")
    if not isinstance(defect, dict):
        raise RevisionGuardError("named_defect must be an object")
    defect_id = str(defect.get("id") or "").strip()
    defect_description = str(defect.get("description") or "").strip()
    defect_evidence = defect.get("evidence")
    defect_fixed = defect.get("fixed") is True
    defect_pass = bool(defect_id and defect_description and isinstance(defect_evidence, list) and defect_evidence and defect_fixed)

    baseline_heldout = normalize_pmids(baseline.get("heldout_retrieved_pmids", []), "baseline.heldout_retrieved_pmids")
    revised_heldout = normalize_pmids(revised.get("heldout_retrieved_pmids", []), "revised.heldout_retrieved_pmids")
    lost_heldout = sorted(set(baseline_heldout) - set(revised_heldout), key=int)

    baseline_blocks = {str(value) for value in baseline.get("required_block_ids", [])}
    revised_blocks = {str(value) for value in revised.get("required_block_ids", [])}
    authorized_blocks = {str(value) for value in data.get("authorized_required_block_ids", [])}
    added_blocks = sorted(revised_blocks - baseline_blocks)
    unjustified_blocks = sorted(set(added_blocks) - authorized_blocks)

    drift = revised.get("translation_drift_issues")
    if not isinstance(drift, list):
        raise RevisionGuardError("revised.translation_drift_issues must be a list")
    syntax_pass = revised.get("syntax_ok") is True and not drift

    scope = data.get("scope_change")
    if not isinstance(scope, dict):
        raise RevisionGuardError("scope_change must be an object")
    changed = scope.get("changed") is True
    baseline_scope = baseline.get("scope_version")
    revised_scope = revised.get("scope_version")
    baseline_protocol = baseline.get("protocol_sha256")
    revised_protocol = revised.get("protocol_sha256")
    if changed:
        scope_pass = (
            scope.get("authorized") is True
            and isinstance(baseline_scope, int)
            and revised_scope == baseline_scope + 1
            and bool(str(scope.get("reason") or "").strip())
            and bool(baseline_protocol)
            and bool(revised_protocol)
            and baseline_protocol != revised_protocol
        )
    else:
        scope_pass = baseline_scope == revised_scope and baseline_protocol == revised_protocol

    baseline_count = baseline.get("result_count")
    revised_count = revised.get("result_count")
    workload_pass = (
        isinstance(baseline_count, int)
        and not isinstance(baseline_count, bool)
        and baseline_count >= 0
        and isinstance(revised_count, int)
        and not isinstance(revised_count, bool)
        and revised_count >= 0
    )
    workload = {
        "baseline_count": baseline_count,
        "revised_count": revised_count,
        "absolute_change": revised_count - baseline_count if workload_pass else None,
        "percent_change": round(((revised_count - baseline_count) / baseline_count) * 100, 2) if workload_pass and baseline_count else None,
    }

    checks = [
        check("named-defect-fixed", defect_pass, {"defect_id": defect_id, "evidence": defect_evidence}, "named defect lacks a fixed=true evidence record"),
        check("heldout-preserved", not lost_heldout, {"baseline_retrieved": baseline_heldout, "revised_retrieved": revised_heldout, "lost_pmids": lost_heldout}, "revision loses previously retrieved held-out records"),
        check("required-blocks-justified", not unjustified_blocks, {"added": added_blocks, "authorized": sorted(authorized_blocks), "unjustified": unjustified_blocks}, "revision adds an unauthorized required block"),
        check("syntax-translation-stable", syntax_pass, {"syntax_ok": revised.get("syntax_ok"), "translation_drift_issues": drift}, "revision introduces syntax or translation drift"),
        check("scope-unchanged-or-explicit", scope_pass, {"changed": changed, "authorized": scope.get("authorized"), "baseline_scope_version": baseline_scope, "revised_scope_version": revised_scope}, "revision changes scope without a valid new protocol version"),
        check("workload-recorded", workload_pass, workload, "revision lacks numeric before/after result counts"),
    ]
    experimental = data.get("experimental_variant") if isinstance(data.get("experimental_variant"), dict) else {}
    passed, disposition = disposition_for_checks(checks, experimental)
    authoritative = revised_path if disposition == "adopt" else baseline_path
    return {
        "operation": "revision-no-harm",
        "ok": True,
        "guard_version": 1,
        "revision_id": revision_id,
        "revision_kind": revision_kind,
        "scope_version": revised_scope if disposition == "adopt" else baseline_scope,
        "protocol_id": data.get("protocol_id"),
        "protocol_sha256": revised_protocol if disposition == "adopt" else baseline_protocol,
        "named_defect_id": defect_id,
        "checks": checks,
        "no_harm_passed": passed,
        "failed_checks": [item["name"] for item in checks if not item["passed"]],
        "disposition": disposition,
        # Keep these absolute because the result artifact may be written to a
        # different directory from its input. Downstream manifest validation
        # must resolve the exact file that was hashed here.
        "authoritative_strategy_file": str(authoritative),
        "authoritative_strategy_sha256": sha256_file(authoritative),
        "experimental_strategy_file": str(revised_path) if disposition == "experimental-only" else None,
        "experimental_variant": experimental if disposition == "experimental-only" else None,
        "workload_effect": workload,
        "rule": "Adopt only after every no-harm check passes; otherwise keep the baseline authoritative or retain the revision only as a labelled experimental variant.",
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="Revision no-harm input JSON")
    parser.add_argument("--output", type=Path, required=True, help="Guard result JSON")
    parser.add_argument("--selected-strategy-output", type=Path, help="Write the selected authoritative strategy content here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_json(args.artifact)
        result = evaluate_payload(data, base=args.artifact.resolve().parent)
        if args.selected_strategy_output:
            selected = Path(result["authoritative_strategy_file"])
            if not selected.is_absolute():
                selected = args.artifact.resolve().parent / selected
            args.selected_strategy_output.parent.mkdir(parents=True, exist_ok=True)
            args.selected_strategy_output.write_bytes(selected.read_bytes())
            result["selected_strategy_output"] = str(args.selected_strategy_output)
            result["selected_strategy_output_sha256"] = sha256_file(args.selected_strategy_output)
        write_json(args.output, result)
        print(json.dumps({"operation": result["operation"], "ok": True, "output": str(args.output), "no_harm_passed": result["no_harm_passed"], "disposition": result["disposition"]}, indent=2))
        return 0
    except (RevisionGuardError, OSError) as exc:
        print(json.dumps({"operation": "revision-no-harm", "ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
