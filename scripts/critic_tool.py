#!/usr/bin/env python3
"""Validate a PRESS-informed internal critic round artifact."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REQUIRED_DOMAINS = {
    "research-question",
    "operators",
    "subject-headings",
    "text-words",
    "syntax",
    "limits-filters",
    "hybrid-integrity",
}
SEVERITIES = {"must-fix", "should-fix", "document"}
CLASSIFICATIONS = {"lexical", "structural", "scope", "filter", "syntax", "reporting"}
STATUSES = {"open", "resolved", "accepted-risk", "not-applicable"}
OVERALL_STATUSES = {"pass", "revise"}


class CriticArtifactError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CriticArtifactError(f"Could not read critic artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CriticArtifactError("Critic artifact must be a JSON object.")
    return value


def validate_artifact(data: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    round_number = data.get("round")
    scope_version = data.get("scope_version")
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        issues.append("round must be a positive integer")
    if not isinstance(scope_version, int) or isinstance(scope_version, bool) or scope_version < 1:
        issues.append("scope_version must be a positive integer")
    if not str(data.get("strategy_file") or "").strip():
        issues.append("strategy_file is required")

    overall_status = str(data.get("overall_status") or "").strip()
    if overall_status not in OVERALL_STATUSES:
        issues.append(f"overall_status must be one of: {', '.join(sorted(OVERALL_STATUSES))}")

    domains = data.get("reviewed_domains")
    if not isinstance(domains, list):
        issues.append("reviewed_domains must be a list")
        domain_values: set[str] = set()
    else:
        domain_values = {str(value).strip() for value in domains}
        missing = sorted(REQUIRED_DOMAINS - domain_values)
        if missing:
            issues.append(f"reviewed_domains is missing: {', '.join(missing)}")

    findings = data.get("findings")
    if not isinstance(findings, list):
        issues.append("findings must be a list")
        findings = []

    severity_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    open_must_fix = 0
    open_actionable = 0
    for index, finding in enumerate(findings, start=1):
        prefix = f"finding {index}"
        if not isinstance(finding, dict):
            issues.append(f"{prefix} must be a JSON object")
            continue
        if not str(finding.get("press_element") or "").strip():
            issues.append(f"{prefix} press_element is required")
        severity = str(finding.get("severity") or "").strip()
        if severity not in SEVERITIES:
            issues.append(f"{prefix} severity must be one of: {', '.join(sorted(SEVERITIES))}")
        else:
            severity_counts[severity] += 1
        classification = str(finding.get("classification") or "").strip()
        if classification not in CLASSIFICATIONS:
            issues.append(f"{prefix} classification must be one of: {', '.join(sorted(CLASSIFICATIONS))}")
        status = str(finding.get("status") or "").strip()
        if status not in STATUSES:
            issues.append(f"{prefix} status must be one of: {', '.join(sorted(STATUSES))}")
        else:
            status_counts[status] += 1
        for field in ("affected_component", "evidence", "recommendation", "required_reprobe"):
            if not str(finding.get(field) or "").strip():
                issues.append(f"{prefix} {field} is required")
        if status == "open":
            if severity == "must-fix":
                open_must_fix += 1
            if severity in {"must-fix", "should-fix"}:
                open_actionable += 1

    if overall_status == "pass" and open_actionable:
        issues.append("overall_status pass is invalid while must-fix or should-fix findings remain open")
    if overall_status == "revise" and not open_actionable:
        issues.append("overall_status revise requires at least one open must-fix or should-fix finding")

    summary = {
        "round": round_number,
        "scope_version": scope_version,
        "overall_status": overall_status,
        "finding_count": len(findings),
        "severity_counts": dict(sorted(severity_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "open_must_fix": open_must_fix,
        "open_actionable": open_actionable,
        "reviewed_domains": sorted(domain_values),
    }
    return issues, summary


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a PRESS-informed critic round JSON artifact.")
    parser.add_argument("artifact", help="Path to critic_round_<N>.json.")
    parser.add_argument("--output", help="Optional path for the validation receipt JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_json(Path(args.artifact))
        issues, summary = validate_artifact(data)
    except CriticArtifactError as exc:
        issues, summary = [str(exc)], {}
    receipt = {
        "operation": "critic-artifact-validate",
        "artifact": args.artifact,
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
