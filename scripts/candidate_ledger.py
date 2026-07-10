#!/usr/bin/env python3
"""Validate candidate-study screening and discovery/holdout role assignments."""

from __future__ import annotations

import argparse
import json
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


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a candidate evidence screening ledger.")
    parser.add_argument("ledger", help="Path to candidate_ledger.json.")
    parser.add_argument("--output", help="Optional path for the validation receipt JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_json(Path(args.ledger))
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
    if args.output:
        write_json(Path(args.output), receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
