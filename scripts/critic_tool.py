#!/usr/bin/env python3
"""Validate a PRESS-informed internal critic round artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
DOMAIN_VERDICTS = {"pass", "finding", "not-applicable"}


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_evidence_bundle(items: list[str], output: Path) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    roles: set[str] = set()
    for item in items:
        if "=" not in item:
            raise CriticArtifactError("--evidence values must use role=path")
        role, path_text = item.split("=", 1)
        role = role.strip()
        path = Path(path_text).resolve()
        if not role or role in roles:
            raise CriticArtifactError(f"Evidence role is empty or duplicated: {role!r}")
        if not path.is_file():
            raise CriticArtifactError(f"Evidence file does not exist: {path}")
        roles.add(role)
        output_parent = output.resolve().parent
        portable_path = os.path.relpath(path, output_parent)
        artifacts.append({"role": role, "path": portable_path, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    if "strategy" not in roles:
        raise CriticArtifactError("Evidence bundle requires a strategy=<path> item")
    bundle = {"bundle_version": 1, "artifacts": artifacts}
    write_json(output, bundle)
    return bundle


def validate_evidence_bundle(path: Path) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    try:
        bundle = load_json(path)
    except CriticArtifactError as exc:
        return [str(exc)], {}
    artifacts = bundle.get("artifacts")
    if bundle.get("bundle_version") != 1:
        issues.append("evidence bundle_version must be 1")
    if not isinstance(artifacts, list) or not artifacts:
        return issues + ["evidence bundle artifacts must be a non-empty list"], bundle
    roles: set[str] = set()
    for index, item in enumerate(artifacts, start=1):
        if not isinstance(item, dict):
            issues.append(f"evidence artifact {index} must be an object")
            continue
        role = str(item.get("role") or "").strip()
        file_path = Path(str(item.get("path") or ""))
        if not file_path.is_absolute():
            file_path = path.parent / file_path
        expected = str(item.get("sha256") or "")
        if not role or role in roles:
            issues.append(f"evidence artifact {index} has an empty or duplicate role")
        roles.add(role)
        if not file_path.is_file():
            issues.append(f"evidence artifact {role!r} does not exist: {file_path}")
        elif not expected or sha256_file(file_path) != expected:
            issues.append(f"evidence artifact {role!r} hash does not match")
    if "strategy" not in roles:
        issues.append("evidence bundle lacks the strategy role")
    bundle["roles"] = sorted(roles)
    return issues, bundle


def validate_artifact(
    data: dict[str, Any],
    *,
    evidence_bundle: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
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
    finding_ids: set[str] = set()
    finding_statuses: dict[str, str] = {}
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
        if severity == "must-fix" and status == "accepted-risk":
            issues.append(f"{prefix} must-fix findings cannot be accepted-risk")

        if data.get("critic_version") == 2:
            finding_id = str(finding.get("finding_id") or "").strip()
            if not finding_id or finding_id in finding_ids:
                issues.append(f"{prefix} finding_id is required and must be unique")
            finding_ids.add(finding_id)
            if finding_id:
                finding_statuses[finding_id] = status
            refs = finding.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                issues.append(f"{prefix} evidence_refs must be a non-empty list")
            elif evidence_bundle is not None:
                unknown = sorted({str(ref) for ref in refs} - set(evidence_bundle.get("roles", [])))
                if unknown:
                    issues.append(f"{prefix} references unknown evidence roles: {', '.join(unknown)}")

    if overall_status == "pass" and open_actionable:
        issues.append("overall_status pass is invalid while must-fix or should-fix findings remain open")
    if overall_status == "revise" and not open_actionable:
        issues.append("overall_status revise requires at least one open must-fix or should-fix finding")

    critic_version = data.get("critic_version", 1)
    domain_verdict_counts: Counter[str] = Counter()
    if critic_version == 2:
        if not str(data.get("evidence_bundle") or "").strip():
            issues.append("critic_version 2 requires evidence_bundle")
        verdicts = data.get("domain_verdicts")
        if not isinstance(verdicts, list):
            issues.append("critic_version 2 requires domain_verdicts list")
            verdicts = []
        verdict_domains: set[str] = set()
        available_roles = set(evidence_bundle.get("roles", [])) if isinstance(evidence_bundle, dict) else set()
        for index, verdict in enumerate(verdicts, start=1):
            if not isinstance(verdict, dict):
                issues.append(f"domain verdict {index} must be an object")
                continue
            domain = str(verdict.get("domain") or "").strip()
            status = str(verdict.get("status") or "").strip()
            if domain not in REQUIRED_DOMAINS or domain in verdict_domains:
                issues.append(f"domain verdict {index} has an invalid or duplicate domain")
            verdict_domains.add(domain)
            if status not in DOMAIN_VERDICTS:
                issues.append(f"domain verdict {index} status must be one of: {', '.join(sorted(DOMAIN_VERDICTS))}")
            else:
                domain_verdict_counts[status] += 1
            refs = verdict.get("evidence_refs")
            rationale = str(verdict.get("rationale") or "").strip()
            if status == "not-applicable":
                if not rationale:
                    issues.append(f"domain verdict {index} not-applicable status requires rationale")
            elif not isinstance(refs, list) or not refs:
                issues.append(f"domain verdict {index} requires evidence_refs")
            if isinstance(refs, list) and available_roles:
                unknown = sorted({str(ref) for ref in refs} - available_roles)
                if unknown:
                    issues.append(f"domain verdict {index} references unknown evidence roles: {', '.join(unknown)}")
        missing_verdicts = sorted(REQUIRED_DOMAINS - verdict_domains)
        if missing_verdicts:
            issues.append(f"domain_verdicts is missing: {', '.join(missing_verdicts)}")
        if open_actionable and not domain_verdict_counts.get("finding"):
            issues.append("open actionable findings require at least one domain verdict with status finding")
    elif critic_version != 1:
        issues.append("critic_version must be 1 or 2")

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
        "critic_version": critic_version,
        "evidence_bundle": data.get("evidence_bundle"),
        "domain_verdict_counts": dict(sorted(domain_verdict_counts.items())),
        "finding_ids": sorted(finding_ids),
        "finding_statuses": finding_statuses,
    }
    return issues, summary


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a PRESS-informed critic round JSON artifact.")
    parser.add_argument("artifact", nargs="?", help="Path to critic_round_<N>.json.")
    parser.add_argument("--output", help="Optional path for the validation receipt JSON.")
    parser.add_argument("--build-bundle", action="store_true", help="Build a hashed evidence bundle instead of validating a critic artifact.")
    parser.add_argument("--evidence", action="append", default=[], help="Evidence item role=path; repeatable and must include strategy=path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.build_bundle:
        if not args.output:
            print(json.dumps({"operation": "critic-bundle-build", "ok": False, "issues": ["--output is required"]}, indent=2))
            return 1
        try:
            bundle = build_evidence_bundle(args.evidence, Path(args.output))
            receipt = {"operation": "critic-bundle-build", "ok": True, "output": args.output, "artifact_count": len(bundle["artifacts"])}
        except CriticArtifactError as exc:
            receipt = {"operation": "critic-bundle-build", "ok": False, "issues": [str(exc)]}
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return 0 if receipt["ok"] else 1
    if not args.artifact:
        print(json.dumps({"operation": "critic-artifact-validate", "ok": False, "issues": ["artifact path is required"]}, indent=2))
        return 1
    data: dict[str, Any] = {}
    try:
        artifact_path = Path(args.artifact)
        data = load_json(artifact_path)
        bundle_data = None
        bundle_issues: list[str] = []
        if data.get("critic_version") == 2 and data.get("evidence_bundle"):
            bundle_path = Path(str(data["evidence_bundle"]))
            if not bundle_path.is_absolute():
                bundle_path = artifact_path.parent / bundle_path
            bundle_issues, bundle_data = validate_evidence_bundle(bundle_path)
        issues, summary = validate_artifact(data, evidence_bundle=bundle_data)
        issues = bundle_issues + issues
    except CriticArtifactError as exc:
        issues, summary = [str(exc)], {}
    receipt = {
        "operation": "critic-artifact-validate",
        "artifact": args.artifact,
        "artifact_sha256": sha256_file(Path(args.artifact)) if Path(args.artifact).is_file() else None,
        "ok": not issues,
        "issues": issues,
        "summary": summary,
    }
    if data.get("critic_version") == 2 and data.get("evidence_bundle"):
        bundle_path = Path(str(data["evidence_bundle"]))
        if not bundle_path.is_absolute():
            bundle_path = Path(args.artifact).parent / bundle_path
        receipt["evidence_bundle_sha256"] = sha256_file(bundle_path) if bundle_path.is_file() else None
    if args.output:
        write_json(Path(args.output), receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
