#!/usr/bin/env python3
"""Discover, classify, and evaluate PubMed evidence-synthesis reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pubmed_tool
from pubmed_search_builder.core.io import atomic_write_json, load_json_object
from pubmed_search_builder.domain.review_profiles import SOURCES, compile_review_profile
from pubmed_search_builder.domain.review_types import SYNTHESIS_TYPES


DECISIONS = frozenset({"include", "exclude", "uncertain"})
RECORD_KINDS = frozenset({"completed-synthesis", "protocol", "narrative-review", "methods-paper", "update", "correction", "other"})


class ReviewDiscoveryError(ValueError):
    """Raised for invalid review-discovery inputs and classifications."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_receipt(data: dict[str, Any], output: Path | None) -> None:
    if output is not None:
        atomic_write_json(output, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _chunks(values: list[str], size: int = 200) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _load_pmid_list(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewDiscoveryError(f"Could not read PMID input: {exc}") from exc
    values = data.get("pmids") if isinstance(data, dict) else data
    if not isinstance(values, list):
        raise ReviewDiscoveryError("PMID input must be a JSON list or an object containing a 'pmids' list")
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _profile(profile_path: Path | None, protocol_path: Path | None) -> dict[str, Any]:
    if profile_path is not None:
        profile = load_json_object(profile_path)
    elif protocol_path is not None:
        profile = compile_review_profile(load_json_object(protocol_path))
    else:
        raise ReviewDiscoveryError("Provide --profile or --protocol")
    if profile.get("artifact_type") != "review-retrieval/profile":
        raise ReviewDiscoveryError("Profile must be a review-retrieval/profile artifact")
    return profile


def discover(
    client: pubmed_tool.NcbiClient,
    *,
    profile: dict[str, Any],
    topic_query: str,
    retmax_per_branch: int = 200,
) -> dict[str, Any]:
    """Run every profile branch and retain its provenance for each candidate."""

    if not topic_query.strip():
        raise ReviewDiscoveryError("Topic query is empty")
    branches = profile.get("branches")
    if not isinstance(branches, list) or not branches:
        raise ReviewDiscoveryError("Profile has no retrieval branches")
    by_pmid: dict[str, dict[str, Any]] = {}
    branch_results: list[dict[str, Any]] = []
    capped = False
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        branch_id = str(branch.get("branch_id") or "")
        branch_query = str(branch.get("query") or "")
        if not branch_id or not branch_query:
            raise ReviewDiscoveryError("Every profile branch needs branch_id and query")
        query = f"({topic_query}) AND ({branch_query})"
        result = pubmed_tool.esearch(client, query, retmax=max(1, retmax_per_branch), retstart=0, sort=None)
        pmids = [str(value) for value in result.get("pmids", []) if str(value)]
        count = int(result.get("count", 0) or 0)
        capped = capped or count > len(pmids)
        branch_results.append(
            {
                "branch_id": branch_id,
                "query": query,
                "query_sha256": _sha256(query),
                "count": count,
                "retrieved_count": len(pmids),
                "capped": count > len(pmids),
                "query_translation": result.get("query_translation", ""),
                "query_translation_hook": result.get("query_translation_hook", {}),
            }
        )
        for pmid in pmids:
            candidate = by_pmid.setdefault(pmid, {"pmid": pmid, "retrieved_by": []})
            candidate["retrieved_by"].append(branch_id)
    ordered_pmids = list(by_pmid)
    fetched: dict[str, dict[str, Any]] = {}
    for batch in _chunks(ordered_pmids):
        for record in pubmed_tool.efetch(client, batch).get("records", []):
            if isinstance(record, dict) and record.get("pmid"):
                fetched[str(record["pmid"])] = record
    records = []
    for pmid in ordered_pmids:
        record = fetched.get(pmid, {"pmid": pmid})
        records.append(
            {
                "pmid": pmid,
                "title": record.get("title", ""),
                "abstract": record.get("abstract", ""),
                "year": record.get("year", ""),
                "journal": record.get("journal", ""),
                "publication_types": record.get("publication_types", []),
                "mesh_headings": record.get("mesh_headings", []),
                "retrieved_by": by_pmid[pmid]["retrieved_by"],
                "decision": "",
                "title_abstract_reviewed": False,
                "eligibility_reason": "",
                "record_kind": "",
                "declared_synthesis_type": "",
            }
        )
    return {
        "operation": "review-discover",
        "artifact_type": "review-discovery/evidence",
        "artifact_version": 1,
        "ok": True,
        "protocol_id": profile.get("protocol_id"),
        "scope_version": profile.get("scope_version"),
        "profile_id": profile.get("profile_id"),
        "profile_sha256": profile.get("profile_sha256"),
        "topic_query": topic_query,
        "topic_query_sha256": _sha256(topic_query),
        "retmax_per_branch": retmax_per_branch,
        "retrieval_capped": capped,
        "branch_results": branch_results,
        "candidate_count": len(records),
        "records": records,
        "note": "Classify every candidate against the locked protocol. Branch provenance is discovery evidence, not eligibility evidence.",
    }


def _records_by_pmid(data: dict[str, Any], *, label: str) -> dict[str, dict[str, Any]]:
    rows = data.get("records")
    if not isinstance(rows, list):
        raise ReviewDiscoveryError(f"{label} must contain a records list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReviewDiscoveryError(f"{label} records must be objects")
        pmid = str(row.get("pmid") or "").strip()
        if not pmid or not pmid.isdigit():
            raise ReviewDiscoveryError(f"{label} record has invalid PMID")
        if pmid in result:
            raise ReviewDiscoveryError(f"{label} duplicates PMID {pmid}")
        result[pmid] = row
    return result


def classify(*, candidates: dict[str, Any], decisions: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Bind human review decisions to discovered candidates without auto-inclusion."""

    candidate_rows = _records_by_pmid(candidates, label="Candidate artifact")
    decision_rows = _records_by_pmid(decisions, label="Decision artifact")
    missing = sorted(set(candidate_rows) - set(decision_rows))
    extra = sorted(set(decision_rows) - set(candidate_rows))
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing decisions for " + ", ".join(missing))
        if extra:
            detail.append("unknown candidate PMIDs " + ", ".join(extra))
        raise ReviewDiscoveryError("Classification does not cover the discovered set: " + "; ".join(detail))
    eligible_types = set(profile.get("eligible_types") or [])
    records = []
    for pmid, candidate in candidate_rows.items():
        decision = decision_rows[pmid]
        value = str(decision.get("decision") or "").casefold()
        kind = str(decision.get("record_kind") or "").casefold()
        synthesis_type = str(decision.get("declared_synthesis_type") or "").casefold()
        reviewed = decision.get("title_abstract_reviewed") is True
        reason = str(decision.get("eligibility_reason") or "").strip()
        if value not in DECISIONS:
            raise ReviewDiscoveryError(f"PMID {pmid} decision must be include, exclude, or uncertain")
        if not reviewed or not reason:
            raise ReviewDiscoveryError(f"PMID {pmid} requires title_abstract_reviewed=true and eligibility_reason")
        if kind not in RECORD_KINDS:
            raise ReviewDiscoveryError(f"PMID {pmid} has unsupported record_kind {kind!r}")
        if synthesis_type and synthesis_type not in SYNTHESIS_TYPES:
            raise ReviewDiscoveryError(f"PMID {pmid} has unsupported declared_synthesis_type {synthesis_type!r}")
        if value == "include" and (kind != "completed-synthesis" or synthesis_type not in eligible_types):
            raise ReviewDiscoveryError(
                f"Included PMID {pmid} must be a completed-synthesis with an eligible declared_synthesis_type"
            )
        records.append(
            {
                **candidate,
                "decision": value,
                "title_abstract_reviewed": reviewed,
                "eligibility_reason": reason,
                "record_kind": kind,
                "declared_synthesis_type": synthesis_type,
            }
        )
    included = [row["pmid"] for row in records if row["decision"] == "include"]
    return {
        "operation": "review-classify",
        "artifact_type": "review-classification/evidence",
        "artifact_version": 1,
        "ok": True,
        "protocol_id": profile.get("protocol_id"),
        "scope_version": profile.get("scope_version"),
        "profile_sha256": profile.get("profile_sha256"),
        "candidate_artifact_sha256": _sha256(json.dumps(candidates, sort_keys=True, separators=(",", ":"))),
        "eligible_types": sorted(eligible_types),
        "records": records,
        "included_pmids": included,
        "counts": {decision: sum(row["decision"] == decision for row in records) for decision in sorted(DECISIONS)},
        "note": "Only human-screened include records can become target evidence. Prior-review benchmark sources remain separate artifacts.",
    }


def evaluate(
    *,
    profile: dict[str, Any],
    classification: dict[str, Any],
    retrieved_pmids: list[str],
    topic_only_count: int | None = None,
) -> dict[str, Any]:
    """Evaluate known-item retrieval overall and by declared synthesis type."""

    records = _records_by_pmid(classification, label="Classification artifact")
    expected = [pmid for pmid, row in records.items() if row.get("decision") == "include"]
    retrieved = set(str(value) for value in retrieved_pmids)
    hits = [pmid for pmid in expected if pmid in retrieved]
    misses = [pmid for pmid in expected if pmid not in retrieved]
    by_type: dict[str, dict[str, Any]] = {}
    for pmid in expected:
        synthesis_type = str(records[pmid].get("declared_synthesis_type") or "unspecified")
        row = by_type.setdefault(synthesis_type, {"eligible": 0, "retrieved": 0, "missed_pmids": []})
        row["eligible"] += 1
        if pmid in retrieved:
            row["retrieved"] += 1
        else:
            row["missed_pmids"].append(pmid)
    for row in by_type.values():
        row["relative_recall"] = row["retrieved"] / row["eligible"] if row["eligible"] else None
    return {
        "operation": "review-filter-evaluate",
        "artifact_type": "review-filter/evaluation",
        "artifact_version": 1,
        "ok": not misses,
        "protocol_id": profile.get("protocol_id"),
        "scope_version": profile.get("scope_version"),
        "profile_sha256": profile.get("profile_sha256"),
        "topic_only_count": topic_only_count,
        "eligible_count": len(expected),
        "retrieved_count": len(hits),
        "relative_recall": len(hits) / len(expected) if expected else None,
        "retrieved_pmids": hits,
        "missed_pmids": misses,
        "per_synthesis_type": by_type,
        "branch_count": len(profile.get("branches") or []),
        "note": "Relative recall is only against screened-in eligible evidence-synthesis records; resolve every miss before handoff.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    profile = sub.add_parser("profile", help="Compile a scope-bound review retrieval profile.")
    profile.add_argument("--protocol", type=Path, required=True)
    profile.add_argument("--output", type=Path, required=True)
    discover_cmd = sub.add_parser("discover", help="Run every review profile branch against a topic query.")
    group = discover_cmd.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile", type=Path)
    group.add_argument("--protocol", type=Path)
    discover_cmd.add_argument("--topic-query-file", type=Path, required=True)
    discover_cmd.add_argument("--retmax-per-branch", type=int, default=200)
    discover_cmd.add_argument("--output", type=Path, required=True)
    classify_cmd = sub.add_parser("classify", help="Validate reviewed classifications for every discovered candidate.")
    classify_cmd.add_argument("--candidates", type=Path, required=True)
    classify_cmd.add_argument("--decisions", type=Path, required=True)
    group = classify_cmd.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile", type=Path)
    group.add_argument("--protocol", type=Path)
    classify_cmd.add_argument("--output", type=Path, required=True)
    evaluate_cmd = sub.add_parser("evaluate", help="Evaluate final retrieval against included review candidates.")
    evaluate_cmd.add_argument("--profile", type=Path, required=True)
    evaluate_cmd.add_argument("--classification", type=Path, required=True)
    evaluate_cmd.add_argument("--retrieved-pmids-file", type=Path, required=True)
    evaluate_cmd.add_argument("--topic-only-count", type=int)
    evaluate_cmd.add_argument("--output", type=Path, required=True)
    sources = sub.add_parser("sources", help="Emit the bundled official source snapshot used by profiles.")
    sources.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "profile":
        value = compile_review_profile(load_json_object(args.protocol))
        _write_receipt(value, args.output)
        return 0
    if args.command == "discover":
        profile = _profile(args.profile, args.protocol)
        topic_query = args.topic_query_file.read_text(encoding="utf-8-sig").strip()
        value = discover(pubmed_tool.NcbiClient(), profile=profile, topic_query=topic_query, retmax_per_branch=max(1, args.retmax_per_branch))
        _write_receipt(value, args.output)
        return 0
    if args.command == "classify":
        profile = _profile(args.profile, args.protocol)
        value = classify(candidates=load_json_object(args.candidates), decisions=load_json_object(args.decisions), profile=profile)
        _write_receipt(value, args.output)
        return 0
    if args.command == "evaluate":
        value = evaluate(
            profile=load_json_object(args.profile),
            classification=load_json_object(args.classification),
            retrieved_pmids=_load_pmid_list(args.retrieved_pmids_file),
            topic_only_count=args.topic_only_count,
        )
        _write_receipt(value, args.output)
        return 0
    if args.command == "sources":
        _write_receipt(
            {"operation": "review-retrieval-sources", "artifact_type": "review-retrieval/sources", "artifact_version": 1, "ok": True, "sources": list(SOURCES)},
            args.output,
        )
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
