#!/usr/bin/env python3
"""Validate candidate-study screening and discovery/holdout role assignments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROVENANCE = {"user-seed", "pilot-anchor", "similar", "citedin", "reference", "prior-review", "other"}
DECISIONS = {"include", "exclude", "uncertain"}
USES = {"discovery", "holdout", "both", "heuristic", "neither"}
DISCOVERY_USES = {"discovery", "both"}
VALIDATION_USES = {"holdout", "both"}


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


def validate_ledger(data: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
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
        }

    seen: set[str] = set()
    decision_counts: Counter[str] = Counter()
    use_counts: Counter[str] = Counter()
    discovery_pmids: list[str] = []
    holdout_pmids: list[str] = []
    both_pmids: list[str] = []
    heuristic_pmids: list[str] = []

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
        if decision not in DECISIONS:
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
        if use in {"discovery", "holdout", "both"}:
            if decision != "include":
                issues.append(f"{prefix} {use} use requires decision include")
            if reviewed is not True:
                issues.append(f"{prefix} {use} use requires title/abstract review")
            if not reason:
                issues.append(f"{prefix} {use} use requires a non-empty eligibility_reason")
        if decision in {"exclude", "uncertain"} and reviewed is True and not reason:
            issues.append(f"{prefix} screened {decision} records require an eligibility_reason")

        if pmid and decision == "include" and reviewed is True and reason:
            if use in DISCOVERY_USES:
                discovery_pmids.append(pmid)
            if use == "holdout":
                holdout_pmids.append(pmid)
            elif use == "both":
                both_pmids.append(pmid)
        if pmid and use == "heuristic":
            heuristic_pmids.append(pmid)

    summary = {
        "scope_version": scope_version,
        "record_count": len(records),
        "decision_counts": dict(sorted(decision_counts.items())),
        "use_counts": dict(sorted(use_counts.items())),
        "eligible_discovery_pmids": discovery_pmids,
        "holdout_pmids": holdout_pmids,
        "non_independent_validation_pmids": both_pmids,
        "heuristic_pmids": heuristic_pmids,
        "independent_holdout_available": bool(holdout_pmids),
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
        assignment = "independent-holdout"
        for record in ranked:
            record["use"] = "holdout" if normalize_pmid(record.get("pmid")) in holdout_pmids else "discovery"
    metadata = {
        "method": "sha256-deterministic",
        "seed": seed,
        "eligible_count": len(ranked),
        "minimum_confirmed": minimum_confirmed,
        "fraction": fraction,
        "assignment": assignment,
        "holdout_pmids": sorted(holdout_pmids),
    }
    data["holdout_allocation"] = metadata
    return data, metadata


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a candidate evidence screening ledger.")
    parser.add_argument("ledger", help="Path to candidate_ledger.json.")
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
        issues, summary = validate_ledger(data)
    except CandidateLedgerError as exc:
        issues, summary = [str(exc)], {}
    receipt = {
        "operation": "candidate-ledger-validate",
        "ledger": args.ledger,
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
