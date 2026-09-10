#!/usr/bin/env python3
"""Validate candidate-study screening and discovery/holdout role assignments."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROVENANCE = {"user-seed", "pilot-anchor", "similar", "citedin", "reference", "prior-review", "other"}
DECISIONS = {"include", "exclude", "uncertain"}
TEMPLATE_DECISIONS = DECISIONS | {"pending"}
USES = {"discovery", "development-validation", "holdout", "both", "heuristic", "neither"}
DISCOVERY_USES = {"discovery", "both"}
VALIDATION_USES = {"development-validation", "holdout", "both"}
EVIDENCE_USES = DISCOVERY_USES | {"development-validation", "holdout"}

# How a screening decision was reached, mirroring screening_tool.py.
DECIDED_BY = {"human", "model", "rule", "human_verified_model"}
ADJUDICATED_BY = {"human", "model", "human_verified_model"}


class CandidateLedgerError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateLedgerError(f"Could not read candidate ledger {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateLedgerError("Candidate ledger must be a JSON object.")
    return value


def normalize_pmid(value: Any) -> str:
    text = str(value or "").strip()
    return text if text.isdigit() else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protocol_binding_issues(data: dict[str, Any]) -> list[str]:
    """Validate protocol binding when the ledger participates in the DSL workflow.

    Legacy ledgers without an artifact envelope remain valid. Once any protocol-envelope
    field is present, the complete binding is required so downstream tools can reject stale
    scope artifacts rather than silently mixing versions.
    """
    keys = {"artifact_type", "artifact_version", "protocol_id", "dsl_version", "generated_from"}
    if not any(key in data for key in keys):
        return []
    issues: list[str] = []
    if data.get("artifact_type") not in {"candidate-ledger", "candidate-ledger-template"}:
        issues.append("artifact_type must be candidate-ledger or candidate-ledger-template")
    if data.get("artifact_version") != 1:
        issues.append("artifact_version must be 1")
    if not str(data.get("protocol_id") or "").strip():
        issues.append("protocol_id is required for protocol-bound ledgers")
    if data.get("dsl_version") != 1:
        issues.append("dsl_version must be 1")
    generated = data.get("generated_from")
    if not isinstance(generated, dict) or not str(generated.get("sha256") or "").strip():
        issues.append("generated_from.sha256 is required for protocol-bound ledgers")
    return issues


def validate_template(data: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    issues = protocol_binding_issues(data)
    if data.get("artifact_type") != "candidate-ledger-template":
        issues.append("candidate template artifact_type must be candidate-ledger-template")
    if data.get("ledger_status") != "template":
        issues.append("candidate template ledger_status must be template")
    scope_version = data.get("scope_version")
    if not isinstance(scope_version, int) or isinstance(scope_version, bool) or scope_version < 1:
        issues.append("scope_version must be a positive integer")
    records = data.get("records")
    if not isinstance(records, list):
        issues.append("records must be a list")
        records = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        prefix = f"record {index}"
        if not isinstance(record, dict):
            issues.append(f"{prefix} must be a JSON object")
            continue
        pmid = normalize_pmid(record.get("pmid"))
        if not pmid:
            issues.append(f"{prefix} pmid must contain digits only")
        elif pmid in seen:
            issues.append(f"{prefix} duplicates PMID {pmid}")
        seen.add(pmid)
        decision = str(record.get("decision") or "pending")
        if decision not in TEMPLATE_DECISIONS:
            issues.append(f"{prefix} decision must be pending, include, exclude, or uncertain")
        requested = str(record.get("requested_role") or record.get("requested_use") or "").strip()
        if requested and requested not in {"discovery-candidate", "development-validation-candidate", "holdout-candidate", "both-candidate", "heuristic"}:
            issues.append(f"{prefix} requested_role is invalid")
    summary = {
        "scope_version": scope_version,
        "protocol_id": data.get("protocol_id"),
        "protocol_sha256": (data.get("generated_from") or {}).get("sha256") if isinstance(data.get("generated_from"), dict) else None,
        "record_count": len(records),
        "pending_count": sum(1 for item in records if isinstance(item, dict) and item.get("decision", "pending") == "pending"),
    }
    return issues, summary


def instantiate_template(data: dict[str, Any], template_path: Path) -> dict[str, Any]:
    issues, _ = validate_template(data)
    if issues:
        raise CandidateLedgerError("candidate template is invalid: " + "; ".join(issues))
    ledger = copy.deepcopy(data)
    ledger["artifact_type"] = "candidate-ledger"
    ledger["ledger_status"] = "screening"
    ledger["instantiated_from"] = {"path": str(template_path), "sha256": sha256_file(template_path)}
    for record in ledger.get("records", []):
        if not isinstance(record, dict):
            continue
        record.setdefault("decision", "pending")
        record.setdefault("title_abstract_reviewed", False)
        record.setdefault("eligibility_reason", "")
        requested = str(record.get("requested_role") or record.get("requested_use") or "")
        record.setdefault("use", "heuristic" if requested == "heuristic" else "neither")
    return ledger


def screening_provenance_issues(prefix: str, record: dict[str, Any], use: str) -> list[str]:
    """Check a record's screening provenance, when it carries any.

    Records screened before ``screening_tool.py`` existed have no ``screening`` block and are
    validated as before. Once the block is present it is held to the rule that matters: a
    decision reached by a mechanical rule alone, with nobody having read the record, cannot
    supply a discovery or holdout record. Rules may triage and prioritise; they cannot be the
    final authority for the records that teach the search its vocabulary or measure its recall.
    """
    screening = record.get("screening")
    if not isinstance(screening, dict):
        return []
    issues: list[str] = []
    decided_by = str(screening.get("decided_by") or "").strip()
    if decided_by not in DECIDED_BY:
        issues.append(f"{prefix} screening.decided_by must be one of: {', '.join(sorted(DECIDED_BY))}")
    adjudicated_by = str(screening.get("adjudicated_by") or "").strip()
    if adjudicated_by and adjudicated_by not in ADJUDICATED_BY:
        issues.append(f"{prefix} screening.adjudicated_by must be one of: {', '.join(sorted(ADJUDICATED_BY))}")
    if use in EVIDENCE_USES:
        if decided_by == "rule" and not adjudicated_by:
            issues.append(
                f"{prefix} was decided by rule alone and cannot take {use} use; adjudicate it with a "
                "human or model review, or keep it as a heuristic record"
            )
        if not str(screening.get("rubric_sha256") or "").strip():
            issues.append(f"{prefix} {use} use requires screening.rubric_sha256 binding the decision to a rubric")
        if not str(screening.get("record_sha256") or "").strip():
            issues.append(f"{prefix} {use} use requires screening.record_sha256 binding the decision to record content")
    return issues


def validate_ledger(data: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = protocol_binding_issues(data)
    if data.get("artifact_type") == "candidate-ledger-template" or data.get("ledger_status") == "template":
        return issues + ["candidate-ledger templates must be instantiated before final validation"], {}
    scope_version = data.get("scope_version")
    if not isinstance(scope_version, int) or isinstance(scope_version, bool) or scope_version < 1:
        issues.append("scope_version must be a positive integer")

    records = data.get("records")
    if not isinstance(records, list) or not records:
        return issues + ["records must be a non-empty list"], {
            "scope_version": scope_version,
            "record_count": 0,
            "decision_counts": {},
            "use_counts": {},
            "eligible_discovery_pmids": [],
            "holdout_pmids": [],
            "non_independent_validation_pmids": [],
            "heuristic_pmids": [],
            "independent_holdout_available": False,
            "development_validation_available": False,
            "validation_stage": "development-validation",
            "final_test_status": "not-performed",
        }

    seen: set[str] = set()
    decision_counts: Counter[str] = Counter()
    use_counts: Counter[str] = Counter()
    decided_by_counts: Counter[str] = Counter()
    discovery_pmids: list[str] = []
    holdout_pmids: list[str] = []
    both_pmids: list[str] = []
    heuristic_pmids: list[str] = []
    unevidenced_evidence_roles: list[str] = []

    for index, record in enumerate(records, start=1):
        prefix = f"record {index}"
        if not isinstance(record, dict):
            issues.append(f"{prefix} must be a JSON object")
            continue

        pmid = normalize_pmid(record.get("pmid"))
        if not pmid:
            issues.append(f"{prefix} pmid must contain digits only")
        elif pmid in seen:
            issues.append(f"{prefix} duplicates PMID {pmid}")
        else:
            seen.add(pmid)

        provenance = str(record.get("provenance") or "").strip()
        if provenance not in PROVENANCE:
            issues.append(f"{prefix} provenance must be one of: {', '.join(sorted(PROVENANCE))}")

        decision = str(record.get("decision") or "").strip()
        if decision == "pending":
            issues.append(f"{prefix} has a pending screening decision")
        elif decision not in DECISIONS:
            issues.append(f"{prefix} decision must be one of: {', '.join(sorted(DECISIONS))}")
        else:
            decision_counts[decision] += 1

        use = str(record.get("use") or "").strip()
        if use not in USES:
            issues.append(f"{prefix} use must be one of: {', '.join(sorted(USES))}")
        else:
            use_counts[use] += 1

        reviewed = record.get("title_abstract_reviewed")
        if not isinstance(reviewed, bool):
            issues.append(f"{prefix} title_abstract_reviewed must be true or false")
        reason = str(record.get("eligibility_reason") or "").strip()

        if decision == "exclude" and use != "neither":
            issues.append(f"{prefix} excluded records must use neither")
        if decision == "uncertain" and use not in {"heuristic", "neither"}:
            issues.append(f"{prefix} uncertain records may use only heuristic or neither")
        if use in EVIDENCE_USES:
            if decision != "include":
                issues.append(f"{prefix} {use} use requires decision include")
            if reviewed is not True:
                issues.append(f"{prefix} {use} use requires title/abstract review")
            if not reason:
                issues.append(f"{prefix} {use} use requires a non-empty eligibility_reason")
        if decision in {"exclude", "uncertain"} and reviewed is True and not reason:
            issues.append(f"{prefix} screened {decision} records require an eligibility_reason")
        issues.extend(screening_provenance_issues(prefix, record, use))
        screening = record.get("screening")
        if isinstance(screening, dict):
            decided_by_counts[str(screening.get("decided_by") or "unset")] += 1
        elif pmid and use in EVIDENCE_USES:
            unevidenced_evidence_roles.append(pmid)

        if pmid and decision == "include" and reviewed is True and reason:
            if use in DISCOVERY_USES:
                discovery_pmids.append(pmid)
            if use in {"development-validation", "holdout"}:
                holdout_pmids.append(pmid)
            elif use == "both":
                both_pmids.append(pmid)
        if pmid and use == "heuristic":
            heuristic_pmids.append(pmid)

    summary = {
        "scope_version": scope_version,
        "protocol_id": data.get("protocol_id"),
        "protocol_sha256": (data.get("generated_from") or {}).get("sha256") if isinstance(data.get("generated_from"), dict) else None,
        "record_count": len(records),
        "decision_counts": dict(sorted(decision_counts.items())),
        "use_counts": dict(sorted(use_counts.items())),
        "eligible_discovery_pmids": discovery_pmids,
        "holdout_pmids": holdout_pmids,
        "non_independent_validation_pmids": both_pmids,
        "heuristic_pmids": heuristic_pmids,
        "independent_holdout_available": False,  # deprecated; development is not a final test
        "development_validation_available": bool(holdout_pmids),
        "development_validation_pmids": holdout_pmids,
        "validation_stage": "development-validation",
        "final_test_status": "not-performed",
        "screening_provenance": {
            "decided_by_counts": dict(sorted(decided_by_counts.items())),
            # Records driving vocabulary or validation that carry no screening provenance at all.
            # Legacy ledgers report a non-empty list here; the audit should say so.
            "evidence_roles_without_screening_provenance": unevidenced_evidence_roles,
            "all_evidence_roles_screened_with_evidence": not unevidenced_evidence_roles,
        },
    }
    return issues, summary


def allocate_holdout(
    data: dict[str, Any],
    *,
    seed: str = "pubmed-search-builder",
    minimum_confirmed: int = 6,
    fraction: float = 0.20,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministically freeze discovery/holdout roles for screened-in records.

    With fewer than ``minimum_confirmed`` eligible records, all records use ``both`` and validation
    is explicitly non-independent. Otherwise reserve at least two records or ``fraction`` of the set,
    whichever is larger. Hash ordering makes the split reproducible without depending on input order.
    """
    records = data.get("records")
    if not isinstance(records, list):
        raise CandidateLedgerError("records must be a list before holdout allocation")
    eligible = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("decision") == "include"
        and record.get("title_abstract_reviewed") is True
        and normalize_pmid(record.get("pmid"))
    ]
    if not eligible:
        raise CandidateLedgerError("no screened-in records are eligible for discovery/holdout allocation")
    ranked = sorted(
        eligible,
        key=lambda record: hashlib.sha256(
            f"{seed}:{normalize_pmid(record.get('pmid'))}".encode("utf-8")
        ).hexdigest(),
    )
    if len(ranked) < max(1, minimum_confirmed):
        holdout_pmids: set[str] = set()
        assignment = "non-independent-both"
        for record in ranked:
            record["use"] = "both"
    else:
        holdout_n = min(len(ranked) - 1, max(2, math.ceil(len(ranked) * max(0.0, fraction))))
        holdout_pmids = {normalize_pmid(record.get("pmid")) for record in ranked[:holdout_n]}
        assignment = "development-validation"
        for record in ranked:
            record["use"] = "development-validation" if normalize_pmid(record.get("pmid")) in holdout_pmids else "discovery"
    metadata = {
        "method": "sha256-deterministic",
        "seed": seed,
        "eligible_count": len(ranked),
        "minimum_confirmed": minimum_confirmed,
        "fraction": fraction,
        "assignment": assignment,
        "validation_stage": "development-validation",
        "final_test_status": "not-performed",
        "holdout_pmids": sorted(holdout_pmids),
    }
    data["holdout_allocation"] = metadata
    return data, metadata


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a candidate evidence screening ledger.")
    parser.add_argument("ledger", nargs="?", help="Path to candidate_ledger.json.")
    parser.add_argument("--validate-template", action="store_true", help="Validate an immutable candidate-ledger template instead of a screened ledger.")
    parser.add_argument("--instantiate-template", help="Instantiate this generated template as an editable working ledger.")
    parser.add_argument("--output", help="Optional path for the validation receipt JSON.")
    parser.add_argument("--allocate-holdout", action="store_true", help="Deterministically assign discovery/holdout roles before validation.")
    parser.add_argument("--ledger-output", help="Required with --allocate-holdout; writes the allocated ledger without overwriting the input.")
    parser.add_argument("--allocation-seed", default="pubmed-search-builder")
    parser.add_argument("--minimum-confirmed", type=int, default=6)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    allocation = None
    try:
        if args.instantiate_template:
            if args.ledger:
                raise CandidateLedgerError("do not provide a positional ledger with --instantiate-template")
            if not args.ledger_output:
                raise CandidateLedgerError("--ledger-output is required with --instantiate-template")
            template_path = Path(args.instantiate_template)
            data = instantiate_template(load_json(template_path), template_path)
            write_json(Path(args.ledger_output), data)
            receipt = {
                "operation": "candidate-ledger-instantiate",
                "ok": True,
                "template": args.instantiate_template,
                "output": args.ledger_output,
                "template_sha256": sha256_file(template_path),
                "protocol_id": data.get("protocol_id"),
                "scope_version": data.get("scope_version"),
            }
            if args.output:
                write_json(Path(args.output), receipt)
            print(json.dumps(receipt, indent=2, ensure_ascii=False))
            return 0
        if not args.ledger:
            raise CandidateLedgerError("ledger path is required")
        data = load_json(Path(args.ledger))
        if args.allocate_holdout:
            if not args.ledger_output:
                raise CandidateLedgerError("--ledger-output is required with --allocate-holdout")
            data, allocation = allocate_holdout(
                data,
                seed=args.allocation_seed,
                minimum_confirmed=max(1, args.minimum_confirmed),
                fraction=max(0.0, min(1.0, args.holdout_fraction)),
            )
            write_json(Path(args.ledger_output), data)
        issues, summary = validate_template(data) if args.validate_template else validate_ledger(data)
    except CandidateLedgerError as exc:
        issues, summary = [str(exc)], {}
    validated_path = Path(args.ledger_output if allocation is not None else args.ledger).resolve()
    receipt = {
        "operation": "candidate-ledger-validate",
        "ledger": args.ledger,
        "artifact_path": str(validated_path),
        "artifact_sha256": sha256_file(validated_path) if validated_path.is_file() else "",
        "ok": not issues,
        "issues": issues,
        "summary": summary,
    }
    if allocation is not None:
        receipt["allocation"] = allocation
        receipt["allocated_ledger"] = args.ledger_output
    if args.output:
        write_json(Path(args.output), receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
