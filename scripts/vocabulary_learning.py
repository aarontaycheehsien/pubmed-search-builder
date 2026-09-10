#!/usr/bin/env python3
"""Active vocabulary learning constrained to a locked PubMed retrieval scope."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pubmed_tool
import candidate_ledger as candidate_ledger_tool
import revision_guard


class VocabularyLearningError(ValueError):
    pass


# Candidate generation enumerates every phrase, acronym, keyword, and MeSH heading in every newly
# included record, for every concept the record is assigned to. On a real build that is six figures
# of candidates -- an artifact no human or critic can review, which makes a per-proposal disposition
# gate satisfiable only by a bulk reason. Ranking and capping produces a shortlist that a reviewer
# can actually work through; the remainder is retained compactly as measurements, not decisions.
REVIEW_TERMS_PER_CONCEPT_DEFAULT = 60

BELOW_THRESHOLD_NOTE = (
    "Candidates that did not reach the per-concept review shortlist. Falling below a mechanical "
    "ranking threshold is not a relevance judgement: nothing here has been reviewed, accepted, or "
    "rejected. Normalized fingerprints are retained so later rounds do not re-propose the same tail "
    "and so shortlist/threshold counts reconcile against total generated candidates."
)


def read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VocabularyLearningError(f"Could not read JSON {path}: {exc}") from exc


def write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def records_from_file(path: str) -> list[dict[str, Any]]:
    raw = read_json(path)
    if isinstance(raw, dict):
        raw = raw.get("records")
    if not isinstance(raw, list):
        raise VocabularyLearningError("Records file must contain a records list or be a list")
    return [item for item in raw if isinstance(item, dict) and str(item.get("pmid") or "").isdigit()]


def load_scope_labels(path: str, expected_version: int) -> tuple[dict[str, Any], dict[str, str]]:
    scope = read_json(path)
    if not isinstance(scope, dict) or scope.get("scope_version") != expected_version:
        raise VocabularyLearningError("Scope artifact is not an object or its scope_version does not match")
    labels: dict[str, str] = {}
    if scope.get("dsl_version") == 1:
        searchable = scope.get("searchable_scope") if isinstance(scope.get("searchable_scope"), dict) else {}
        essential = [
            item for item in searchable.get("concepts", [])
            if isinstance(item, dict) and item.get("role") == "essential"
        ]
    else:
        essential = scope.get("essential_blocks")
    if not isinstance(essential, list) or not essential:
        raise VocabularyLearningError("Scope artifact requires at least one essential searchable concept")
    for index, item in enumerate(essential, start=1):
        label = str(item.get("label") or item.get("name") or "") if isinstance(item, dict) else str(item)
        label = " ".join(label.split())
        if not label:
            raise VocabularyLearningError(f"Essential block {index} has no label")
        labels[label.casefold()] = label
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            labels[str(item["id"]).casefold()] = label
    return scope, labels


def load_ledger(
    path: str,
    expected_version: int,
    *,
    expected_protocol_id: str | None = None,
    expected_protocol_sha256: str | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    raw = read_json(path)
    if not isinstance(raw, dict) or raw.get("scope_version") != expected_version:
        raise VocabularyLearningError("Candidate ledger is not an object or its scope_version does not match")
    records = raw.get("records")
    if not isinstance(records, list):
        raise VocabularyLearningError("Candidate ledger lacks records")
    issues, _summary = candidate_ledger_tool.validate_ledger(raw)
    if issues:
        raise VocabularyLearningError("Candidate ledger is invalid: " + "; ".join(issues))
    generated = raw.get("generated_from") if isinstance(raw.get("generated_from"), dict) else {}
    if expected_protocol_id is not None and raw.get("protocol_id") != expected_protocol_id:
        raise VocabularyLearningError("Candidate ledger protocol_id does not match the review protocol")
    if expected_protocol_sha256 is not None and generated.get("sha256") != expected_protocol_sha256:
        raise VocabularyLearningError("Candidate ledger protocol binding does not match the review protocol")
    by_pmid = {str(item.get("pmid")): item for item in records if isinstance(item, dict) and str(item.get("pmid") or "").isdigit()}
    discovery = [pmid for pmid, item in by_pmid.items() if item.get("decision") == "include" and item.get("use") in {"discovery", "both"}]
    holdout = [pmid for pmid, item in by_pmid.items() if item.get("decision") == "include" and item.get("use") in {"development-validation", "holdout"}]
    return by_pmid, discovery, holdout


def load_config(path: str, scope_labels: dict[str, str], expected_version: int) -> tuple[dict[str, list[str]], dict[str, set[str]], list[dict[str, Any]]]:
    raw = read_json(path)
    if not isinstance(raw, dict) or raw.get("scope_version") != expected_version:
        raise VocabularyLearningError("Vocabulary config is not an object or its scope_version does not match")
    assignments_raw = raw.get("record_concept_assignments")
    if not isinstance(assignments_raw, dict):
        raise VocabularyLearningError("Vocabulary config requires record_concept_assignments")
    assignments: dict[str, list[str]] = {}
    challenges: list[dict[str, Any]] = []
    for pmid, values in assignments_raw.items():
        labels = values if isinstance(values, list) else [values]
        normalized: list[str] = []
        for value in labels:
            requested = " ".join(str(value).split())
            locked = scope_labels.get(requested.casefold())
            if not locked:
                challenges.append(
                    {
                        "type": "new-concept",
                        "pmid": str(pmid),
                        "requested_concept": requested,
                        "required_action": "reopen retrieval scope and issue a new scope version before vocabulary use",
                    }
                )
            else:
                normalized.append(locked)
        assignments[str(pmid)] = normalized
    existing: dict[str, set[str]] = {label: set() for label in scope_labels.values()}
    concepts = raw.get("concepts") if isinstance(raw.get("concepts"), list) else []
    for item in concepts:
        if not isinstance(item, dict):
            continue
        requested = " ".join(str(item.get("label") or "").split())
        locked = scope_labels.get(requested.casefold())
        if not locked:
            challenges.append(
                {
                    "type": "new-concept",
                    "requested_concept": requested,
                    "required_action": "reopen retrieval scope and issue a new scope version before vocabulary use",
                }
            )
            continue
        existing[locked].update(
            pubmed_tool.normalize_for_match(str(term))
            for term in item.get("existing_terms", [])
            if pubmed_tool.normalize_for_match(str(term))
        )
    return assignments, existing, challenges


def candidate_terms(record: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    values.extend((term, "phrase") for term in pubmed_tool.record_phrase_set(record))
    values.extend((term, "acronym") for term in pubmed_tool.record_acronym_set(record))
    values.extend((term, "keyword") for term in pubmed_tool.record_keyword_set(record))
    values.extend((term, "mesh") for term in pubmed_tool.record_mesh_set(record))
    return [
        (" ".join(str(term).split()), source)
        for term, source in values
        if term and not pubmed_tool.term_rank_noise_reason(str(term), "mesh" if source == "mesh" else "tiab")
    ]


def proposal_bucket(proposal: dict[str, Any]) -> str:
    """Extraction layer a candidate is charged against, matching term-rank's bucket names."""
    if proposal.get("field") == "mesh":
        return "mesh"
    sources = set(proposal.get("sources") or [])
    return next((name for name in ("keyword", "acronym", "phrase") if name in sources), "phrase")


def rank_and_bound_proposals(
    proposals: list[dict[str, Any]],
    coverage_denominators: dict[str, int],
    max_terms_per_concept: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Split generated candidates into a bounded review shortlist and a compact retained tail.

    Selection runs per locked concept through ``select_diverse_term_candidates``, which allocates
    the budget round-robin across the MeSH, keyword, acronym, and phrase layers and prefers terms
    covering records not yet represented. One concept or one phrase class therefore cannot consume
    the whole allowance. Scoring is local document-frequency coverage only -- PubMed lift costs a
    query per term and belongs on the bounded shortlist, via ``pubmed_tool.py term-rank``.
    """
    by_concept: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposal in proposals:
        denominator = max(1, int(coverage_denominators.get(str(proposal["concept"]), 0)))
        proposal["relevant_df"] = len(proposal["supporting_pmids"])
        proposal["coverage"] = round(proposal["relevant_df"] / denominator, 4)
        proposal["extraction_layer"] = proposal_bucket(proposal)
        by_concept[str(proposal["concept"])].append(proposal)

    shortlist: list[dict[str, Any]] = []
    tail: list[dict[str, Any]] = []
    per_concept: dict[str, dict[str, int]] = {}
    for concept in sorted(by_concept):
        rows = by_concept[concept]
        rows.sort(
            key=lambda row: (
                -int(row["relevant_df"]),
                0 if row["field"] == "mesh" else 1,
                str(row["term"]).lower(),
            )
        )
        selected = pubmed_tool.select_diverse_term_candidates(rows, max_terms_per_concept)
        selected_keys = {(str(row["normalized_term"]), str(row["field"])) for row in selected}
        shortlist.extend(selected)
        tail.extend(
            row for row in rows if (str(row["normalized_term"]), str(row["field"])) not in selected_keys
        )
        per_concept[concept] = {
            "generated": len(rows),
            "promoted_for_review": len(selected),
            "below_review_threshold": len(rows) - len(selected),
            "coverage_denominator": max(1, int(coverage_denominators.get(concept, 0))),
        }

    shortlist.sort(
        key=lambda row: (
            str(row["concept"]).lower(),
            -float(row["coverage"]),
            -int(row["relevant_df"]),
            str(row["term"]).lower(),
        )
    )
    # Candidate terms are attributed per record, not per term, so a record assigned to two concepts
    # proposes all of its terms under both. Surface that directly: a term shortlisted under several
    # concepts needs the reviewer to decide which one it actually belongs to.
    concepts_by_term: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for row in shortlist:
        concepts_by_term[(str(row["normalized_term"]), str(row["field"]))].add(str(row["concept"]))
    for index, proposal in enumerate(shortlist, start=1):
        proposal["proposal_id"] = f"V{index:04d}"
        shared = concepts_by_term[(str(proposal["normalized_term"]), str(proposal["field"]))]
        proposal["also_proposed_for_concepts"] = sorted(shared - {str(proposal["concept"])})

    source_counts: Counter[str] = Counter()
    support_counts: Counter[int] = Counter()
    concept_counts: Counter[str] = Counter()
    fingerprints: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for row in tail:
        source_counts[str(row["extraction_layer"])] += 1
        support_counts[int(row["relevant_df"])] += 1
        concept_counts[str(row["concept"])] += 1
        fingerprints[(str(row["concept"]), str(row["field"]))].append(str(row["normalized_term"]))

    below = {
        "note": BELOW_THRESHOLD_NOTE,
        "count": len(tail),
        "counts_by_concept": dict(sorted(concept_counts.items())),
        "counts_by_extraction_layer": dict(sorted(source_counts.items())),
        "counts_by_supporting_record_count": {
            str(support): count for support, count in sorted(support_counts.items())
        },
        "fingerprints": [
            {
                "concept": concept,
                "field": field,
                "normalized_terms": sorted(set(fingerprints[(concept, field)])),
            }
            for concept, field in sorted(fingerprints)
        ],
    }
    selection = {
        "policy": "per-concept diverse selection across mesh/keyword/acronym/phrase layers",
        "max_review_terms_per_concept": max_terms_per_concept,
        "ranking": "local supporting-record coverage, then marginal record coverage within layer",
        "cross_concept_note": (
            "Terms are attributed per record, so a record assigned to several concepts proposes its "
            "terms under each. `also_proposed_for_concepts` marks those; assigning the term to the "
            "right concept is a review decision."
        ),
        "pubmed_lift_computed": False,
        "pubmed_lift_note": "Background lift needs one PubMed query per term; run term-rank on the shortlist.",
        "by_concept": per_concept,
    }
    return shortlist, {"review_selection": selection, "below_review_threshold": below}


def excluded_diagnosis(records: list[dict[str, Any]], ledger: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    sources: defaultdict[str, set[str]] = defaultdict(set)
    reasons: Counter[str] = Counter()
    excluded_pmids = []
    for record in records:
        pmid = str(record.get("pmid") or "")
        ledger_item = ledger.get(pmid, {})
        if ledger_item.get("decision") != "exclude":
            continue
        excluded_pmids.append(pmid)
        reasons[str(ledger_item.get("eligibility_reason") or "unspecified")] += 1
        seen: set[str] = set()
        for term, source in candidate_terms(record):
            normalized = pubmed_tool.normalize_for_match(term)
            if normalized and normalized not in seen:
                seen.add(normalized)
                counts[normalized] += 1
                sources[normalized].add(source)
    return {
        "record_count": len(excluded_pmids),
        "pmids": excluded_pmids,
        "eligibility_reason_counts": dict(reasons),
        "frequent_terminology": [
            {"term": term, "record_count": count, "sources": sorted(sources[term])}
            for term, count in counts.most_common(50)
        ],
        "used_for_proposals": False,
        "note": "Excluded-record terminology is diagnostic only and cannot enter vocabulary proposals.",
    }


def extract_learning(
    scope_file: str,
    ledger_file: str,
    records_file: str,
    config_file: str,
    *,
    scope_version: int,
    previous_learning: dict[str, Any] | None = None,
    max_review_terms_per_concept: int = REVIEW_TERMS_PER_CONCEPT_DEFAULT,
) -> dict[str, Any]:
    scope, scope_labels = load_scope_labels(scope_file, scope_version)
    protocol_sha = (
        hashlib.sha256(
            json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if scope.get("dsl_version") == 1
        else None
    )
    ledger, discovery_pmids, holdout_pmids = load_ledger(
        ledger_file,
        scope_version,
        expected_protocol_id=str(scope.get("protocol_id") or "") if protocol_sha else None,
        expected_protocol_sha256=protocol_sha,
    )
    records = records_from_file(records_file)
    records_by_pmid = {str(item.get("pmid")): item for item in records}
    assignments, existing, challenges = load_config(config_file, scope_labels, scope_version)
    if previous_learning is not None:
        if previous_learning.get("operation") != "vocabulary-learning-extract":
            raise VocabularyLearningError("Previous learning artifact has the wrong operation")
        if previous_learning.get("scope_version") != scope_version:
            raise VocabularyLearningError("Previous learning artifact has the wrong scope_version")
        if protocol_sha and (
            previous_learning.get("protocol_id") != scope.get("protocol_id")
            or previous_learning.get("protocol_sha256") != protocol_sha
        ):
            raise VocabularyLearningError("Previous learning artifact does not match the review protocol")
    previous_processed = {str(value) for value in (previous_learning or {}).get("processed_included_pmids", [])}
    previous_terms = {
        (str(item.get("concept")), pubmed_tool.normalize_for_match(str(item.get("term") or "")))
        for item in (previous_learning or {}).get("proposals", [])
        if isinstance(item, dict)
    }
    # Candidates the previous round retained below its review threshold were never reviewed, so
    # they must not be re-proposed as if newly discovered. Without this the long tail would return
    # in full every round.
    previous_below = (previous_learning or {}).get("below_review_threshold")
    for group in (previous_below or {}).get("fingerprints", []) if isinstance(previous_below, dict) else []:
        if not isinstance(group, dict):
            continue
        concept = str(group.get("concept") or "")
        previous_terms.update(
            (concept, str(term)) for term in group.get("normalized_terms", []) if str(term)
        )
    newly_included = [pmid for pmid in discovery_pmids if pmid not in previous_processed]
    proposals: dict[tuple[str, str, str], dict[str, Any]] = {}
    unassigned = []
    processing_blockers: list[dict[str, Any]] = []
    processed_this_round: set[str] = set()
    coverage_denominators: Counter[str] = Counter()
    for pmid in newly_included:
        record = records_by_pmid.get(pmid)
        if not record:
            processing_blockers.append(
                {"type": "missing-record-content", "pmid": pmid, "required_action": "supply saved record content before vocabulary learning"}
            )
            continue
        labels = assignments.get(pmid, [])
        if not labels:
            unassigned.append({"pmid": pmid, "terms": sorted({term for term, _source in candidate_terms(record)})[:100]})
            continue
        for label in labels:
            coverage_denominators[label] += 1
            for term, source in candidate_terms(record):
                normalized = pubmed_tool.normalize_for_match(term)
                if not normalized or normalized in existing.get(label, set()) or (label, normalized) in previous_terms:
                    continue
                field = "mesh" if source == "mesh" else "tiab"
                key = (label, normalized, field)
                proposal = proposals.setdefault(
                    key,
                    {
                        "proposal_id": f"V{len(proposals) + 1:04d}",
                        "concept": label,
                        "term": term,
                        "normalized_term": normalized,
                        "field": field,
                        "suggested_query": f'"{term}"[Mesh]' if field == "mesh" else (f'"{term}"[tiab]' if " " in term else f"{term}[tiab]"),
                        "sources": [],
                        "supporting_pmids": [],
                        "decision": "pending",
                        "decision_reason": "",
                        "within_locked_concept_attested": False,
                    },
                )
                if source not in proposal["sources"]:
                    proposal["sources"].append(source)
                if pmid not in proposal["supporting_pmids"]:
                    proposal["supporting_pmids"].append(pmid)
        processed_this_round.add(pmid)
    for pmid, item in ledger.items():
        if item.get("scope_challenge") or item.get("eligibility_interpretation_change"):
            challenges.append(
                {
                    "type": "eligibility-interpretation",
                    "pmid": pmid,
                    "detail": item.get("scope_challenge") or item.get("eligibility_interpretation_change"),
                    "required_action": "reopen retrieval scope and issue a new scope version before adopting related vocabulary",
                }
            )
    generated = list(proposals.values())
    shortlist, bounding = rank_and_bound_proposals(
        generated, dict(coverage_denominators), max(1, int(max_review_terms_per_concept))
    )
    result = {
        "operation": "vocabulary-learning-extract",
        "ok": True,
        "scope_version": scope_version,
        "locked_concepts": sorted(set(scope_labels.values())),
        "newly_included_pmids": newly_included,
        "processed_included_pmids": sorted(previous_processed | processed_this_round, key=int),
        "holdout_pmids_frozen": holdout_pmids,
        "candidate_generation": {
            "total_generated": len(generated),
            "promoted_for_review": len(shortlist),
            "below_review_threshold": bounding["below_review_threshold"]["count"],
            "reconciled": len(shortlist) + bounding["below_review_threshold"]["count"] == len(generated),
        },
        "review_selection": bounding["review_selection"],
        "below_review_threshold": bounding["below_review_threshold"],
        "proposals": shortlist,
        "unassigned_included_records": unassigned,
        "assignment_required": bool(unassigned),
        "processing_blockers": processing_blockers,
        "excluded_record_diagnosis": excluded_diagnosis(records, ledger),
        "scope_challenges": challenges,
        "scope_reentry_required": bool(challenges),
        "note": (
            "Only terms assigned to already locked concepts are proposed. Excluded-record terminology "
            "is diagnostic only. `proposals` is the bounded review shortlist and is the only list "
            "requiring a per-term disposition; `below_review_threshold` retains the remainder as "
            "measurements, not decisions."
        ),
    }
    if scope.get("dsl_version") == 1:
        result.update({
            "dsl_version": 1,
            "protocol_id": scope.get("protocol_id"),
            "protocol_sha256": protocol_sha,
        })
    return result


def load_blocks(path: str) -> dict[str, dict[str, Any]]:
    raw = read_json(path)
    if isinstance(raw, dict):
        raw = [{"label": label, **(value if isinstance(value, dict) else {"query": value})} for label, value in raw.items()]
    if not isinstance(raw, list):
        raise VocabularyLearningError("Blocks file must contain a list or object map")
    blocks = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or item.get("name") or "").split())
        query = pubmed_tool.normalize_query(str(item.get("query") or ""))
        if label and query:
            blocks[label.casefold()] = {
                "label": label,
                "query": query,
                "block_id": str(item.get("block_id") or item.get("concept_id") or "").strip(),
            }
    return blocks


def translation_drift_issues(search: dict[str, Any]) -> list[dict[str, Any]]:
    hook = search.get("query_translation_hook") if isinstance(search.get("query_translation_hook"), dict) else {}
    issues = hook.get("issues") if isinstance(hook.get("issues"), list) else []
    return [item for item in issues if isinstance(item, dict) and item.get("severity") in {"warning", "error"}]


def retest_learning(
    client: pubmed_tool.NcbiClient,
    extraction: dict[str, Any],
    blocks_file: str,
    *,
    scope_version: int,
    sample_size: int,
) -> dict[str, Any]:
    if extraction.get("operation") != "vocabulary-learning-extract" or extraction.get("scope_version") != scope_version:
        raise VocabularyLearningError("Extraction artifact is invalid or has the wrong scope_version")
    if extraction.get("scope_reentry_required") is True:
        raise VocabularyLearningError("Scope re-entry is required; issue a new scope version and rerun extraction before accepting terms")
    if extraction.get("assignment_required") is True:
        raise VocabularyLearningError("Newly included records remain unassigned to locked concepts; update the vocabulary config and rerun extraction")
    if extraction.get("processing_blockers"):
        raise VocabularyLearningError("Vocabulary extraction has unresolved record-content blockers")
    blocks = load_blocks(blocks_file)
    locked = {str(value).casefold() for value in extraction.get("locked_concepts", [])}
    holdout = [str(value) for value in extraction.get("holdout_pmids_frozen", [])]
    proposals = extraction.get("proposals")
    if not isinstance(proposals, list):
        raise VocabularyLearningError("Extraction artifact lacks proposals")
    retested = []
    for index, proposal in enumerate(proposals, start=1):
        if not isinstance(proposal, dict):
            raise VocabularyLearningError(f"Proposal {index} must be an object")
        decision = str(proposal.get("decision") or "").strip().casefold()
        if decision not in {"accepted", "rejected", "deferred"}:
            raise VocabularyLearningError(f"Proposal {proposal.get('proposal_id') or index} requires accepted/rejected/deferred decision")
        reason = str(proposal.get("decision_reason") or "").strip()
        if not reason:
            raise VocabularyLearningError(f"Proposal {proposal.get('proposal_id') or index} requires decision_reason")
        row = dict(proposal)
        if decision != "accepted":
            row["retest"] = {"required": False, "reason": f"term was {decision}"}
            retested.append(row)
            continue
        concept = str(proposal.get("concept") or "").strip()
        if concept.casefold() not in locked or concept.casefold() not in blocks:
            raise VocabularyLearningError(f"Accepted proposal {proposal.get('proposal_id')} targets a concept outside the locked blocks")
        if proposal.get("within_locked_concept_attested") is not True:
            raise VocabularyLearningError(f"Accepted proposal {proposal.get('proposal_id')} lacks within_locked_concept_attested=true")
        term_query = pubmed_tool.normalize_query(str(proposal.get("query") or proposal.get("suggested_query") or ""))
        pubmed_tool.assert_plain_query(str(proposal.get("proposal_id") or index), term_query)
        current_query = str(blocks[concept.casefold()]["query"])
        expanded_query = f"({current_query}) OR ({term_query})"
        current_search = pubmed_tool.esearch(client, current_query, retmax=0, retstart=0, sort=None)
        expanded_search = pubmed_tool.esearch(client, expanded_query, retmax=0, retstart=0, sort=None)
        if holdout:
            current_retrieved = pubmed_tool.retrieve_against_pmids(client, current_query, holdout)
            expanded_retrieved = pubmed_tool.retrieve_against_pmids(client, expanded_query, holdout)
            holdout_test = {
                "status": "development-validation-tested",
                "tested_pmids": holdout,
                "current_retrieved": [pmid for pmid in holdout if pmid in current_retrieved],
                "expanded_retrieved": [pmid for pmid in holdout if pmid in expanded_retrieved],
                "rescued_pmids": [pmid for pmid in holdout if pmid in expanded_retrieved and pmid not in current_retrieved],
                "remaining_missed_pmids": [pmid for pmid in holdout if pmid not in expanded_retrieved],
            }
        else:
            holdout_test = {"status": "unavailable-no-development-validation", "tested_pmids": [], "rescued_pmids": []}
        differential_query = f"({expanded_query}) NOT ({current_query})"
        search = pubmed_tool.esearch(client, differential_query, retmax=max(1, sample_size), retstart=0, sort=None)
        pmids = [str(value) for value in search.get("pmids", [])]
        fetched = pubmed_tool.efetch(client, pmids) if pmids else {"records": []}
        current_heldout = set(holdout_test.get("current_retrieved", []))
        expanded_heldout = set(holdout_test.get("expanded_retrieved", []))
        lost_heldout = sorted(current_heldout - expanded_heldout, key=int)
        drift_issues = translation_drift_issues(expanded_search)
        syntax_ok = expanded_query.count("(") == expanded_query.count(")") and expanded_query.count('"') % 2 == 0
        workload = {
            "baseline_count": int(current_search.get("count", 0) or 0),
            "revised_count": int(expanded_search.get("count", 0) or 0),
        }
        workload["absolute_change"] = workload["revised_count"] - workload["baseline_count"]
        workload["percent_change"] = round((workload["absolute_change"] / workload["baseline_count"]) * 100, 2) if workload["baseline_count"] else None
        reviewed_relevant = [
            str(value) for value in proposal.get("reviewed_relevant_differential_pmids", [])
        ]
        if any(not value.isdigit() or value not in pmids for value in reviewed_relevant):
            raise VocabularyLearningError(
                f"Accepted proposal {proposal.get('proposal_id')} has reviewed differential PMIDs outside the saved differential sample"
            )
        reviewed_relevant = pubmed_tool.dedup_preserving_order(reviewed_relevant)
        defect_fixed = bool(holdout_test.get("rescued_pmids") or reviewed_relevant)
        checks = [
            revision_guard.check(
                "named-defect-fixed",
                defect_fixed,
                {
                    "proposal_id": proposal.get("proposal_id"),
                    "rescued_pmids": holdout_test.get("rescued_pmids", []),
                    "reviewed_relevant_differential_pmids": reviewed_relevant,
                    "differential_count": int(search.get("count", 0) or 0),
                },
                "accepted term rescues no held-out record and has no reviewed relevant differential record tied to the named gap",
            ),
            revision_guard.check("heldout-preserved", not lost_heldout, {"current_retrieved": sorted(current_heldout, key=int), "expanded_retrieved": sorted(expanded_heldout, key=int), "lost_pmids": lost_heldout}, "expanded block loses a previously retrieved held-out record"),
            revision_guard.check("required-blocks-justified", proposal.get("within_locked_concept_attested") is True, {"added_required_blocks": [], "concept": concept}, "vocabulary revision is not confined to an existing OR block"),
            revision_guard.check("syntax-translation-stable", syntax_ok and not drift_issues, {"syntax_ok": syntax_ok, "translation_drift_issues": drift_issues, "query_translation": expanded_search.get("query_translation", "")}, "expanded block introduces syntax or PubMed translation drift"),
            revision_guard.check("scope-unchanged-or-explicit", extraction.get("scope_reentry_required") is False and concept.casefold() in locked, {"scope_version": scope_version, "concept": concept, "scope_reentry_required": extraction.get("scope_reentry_required")}, "vocabulary revision silently changes scope"),
            revision_guard.check("workload-recorded", True, workload, "before/after result counts are unavailable"),
            revision_guard.check(
                "no-narrowing-under-low-signal",
                True,
                {
                    "applicable": False,
                    "reason": "vocabulary expansion adds terms within an existing OR block; block breadth is non-decreasing",
                    "added_term_query": term_query,
                },
                "vocabulary expansion unexpectedly reduced block breadth",
            ),
        ]
        experimental = {
            "retain_if_failed": proposal.get("retain_experimental_if_failed") is True,
            "variant_id": proposal.get("experimental_variant_id"),
            "label": proposal.get("experimental_variant_label"),
        }
        no_harm_passed, guard_disposition = revision_guard.disposition_for_checks(checks, experimental)
        row["retest"] = {
            "required": True,
            "term_query": term_query,
            "current_block_query": current_query,
            "expanded_block_query": expanded_query,
            "holdout_test": holdout_test,
            "differential_sample": {
                "query": differential_query,
                "count": int(search.get("count", 0) or 0),
                "pmids": pmids,
                "records": fetched.get("records", []),
                "query_translation": search.get("query_translation", ""),
                "query_translation_hook": search.get("query_translation_hook", {}),
            },
            "before_after_workload": workload,
            "expanded_query_translation": expanded_search.get("query_translation", ""),
            "expanded_query_translation_hook": expanded_search.get("query_translation_hook", {}),
        }
        row["no_harm"] = {
            "guard_version": 1,
            "checks": checks,
            "no_harm_passed": no_harm_passed,
            "failed_checks": [item["name"] for item in checks if not item["passed"]],
            "disposition": guard_disposition,
            "authoritative_block_query": expanded_query if guard_disposition == "adopt" else current_query,
            "experimental_block_query": expanded_query if guard_disposition == "experimental-only" else None,
            "experimental_variant": experimental if guard_disposition == "experimental-only" else None,
            "workload_effect": workload,
        }
        row["effective_decision"] = "adopted" if guard_disposition == "adopt" else guard_disposition
        retested.append(row)
    accepted = [item for item in retested if item.get("decision") == "accepted"]
    adopted = [item for item in accepted if item.get("effective_decision") == "adopted"]
    experimental = [item for item in accepted if item.get("effective_decision") == "experimental-only"]
    reverted = [item for item in accepted if item.get("effective_decision") == "revert-to-baseline"]
    result = {
        "operation": "vocabulary-learning",
        "ok": True,
        "scope_version": scope_version,
        "locked_concepts": sorted(extraction.get("locked_concepts", [])),
        "locked_concept_ids": sorted(
            {
                str(blocks[str(concept).casefold()].get("block_id") or "").strip()
                for concept in extraction.get("locked_concepts", [])
                if str(concept).casefold() in blocks
                and str(blocks[str(concept).casefold()].get("block_id") or "").strip()
            }
        ),
        "newly_included_pmids": extraction.get("newly_included_pmids", []),
        "processed_included_pmids": extraction.get("processed_included_pmids", []),
        "candidate_generation": extraction.get("candidate_generation", {}),
        "review_selection": extraction.get("review_selection", {}),
        "below_review_threshold": extraction.get("below_review_threshold", {}),
        "excluded_record_diagnosis": extraction.get("excluded_record_diagnosis", {}),
        "scope_challenges": extraction.get("scope_challenges", []),
        "scope_reentry_required": False,
        "unassigned_included_records": [],
        "assignment_required": False,
        "processing_blockers": [],
        "proposals": retested,
        "accepted_term_count": len(adopted),
        "authored_accepted_term_count": len(accepted),
        "experimental_term_count": len(experimental),
        "reverted_term_count": len(reverted),
        "all_accepted_terms_retested": all(isinstance(item.get("retest"), dict) and item["retest"].get("required") is True and isinstance(item.get("no_harm"), dict) for item in accepted),
        "no_harm_checks_complete": all(isinstance(item.get("no_harm"), dict) and len(item["no_harm"].get("checks", [])) == len(revision_guard.CHECK_NAMES) for item in accepted),
        "note": (
            "Accepted terms are additions within locked concepts only. New concepts or eligibility "
            "interpretations require scope re-entry. Dispositions cover the bounded review shortlist; "
            "`below_review_threshold` was never reviewed and carries no decision."
        ),
        "request_info": client.metadata(),
    }
    for key in ("dsl_version", "protocol_id", "protocol_sha256"):
        if extraction.get(key) is not None:
            result[key] = extraction[key]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Learn vocabulary from screened records without allowing scope drift.")
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--scope-file", required=True)
    extract.add_argument("--candidate-ledger", required=True)
    extract.add_argument("--records-file", required=True)
    extract.add_argument("--config-file", required=True)
    extract.add_argument("--previous-learning")
    extract.add_argument("--scope-version", type=int, required=True)
    extract.add_argument(
        "--max-review-terms-per-concept",
        type=int,
        default=REVIEW_TERMS_PER_CONCEPT_DEFAULT,
        help="Review shortlist size per locked concept, split across extraction layers (default: %(default)s).",
    )
    extract.add_argument("--output", required=True)
    retest = sub.add_parser("retest")
    retest.add_argument("--extraction-file", required=True)
    retest.add_argument("--blocks-file", required=True)
    retest.add_argument("--scope-version", type=int, required=True)
    retest.add_argument("--sample-size", type=int, default=10)
    retest.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            previous = read_json(args.previous_learning) if args.previous_learning else None
            if previous is not None and not isinstance(previous, dict):
                raise VocabularyLearningError("Previous-learning artifact must be an object")
            result = extract_learning(
                args.scope_file,
                args.candidate_ledger,
                args.records_file,
                args.config_file,
                scope_version=args.scope_version,
                previous_learning=previous,
                max_review_terms_per_concept=args.max_review_terms_per_concept,
            )
        else:
            extraction = read_json(args.extraction_file)
            if not isinstance(extraction, dict):
                raise VocabularyLearningError("Extraction artifact must be an object")
            result = retest_learning(
                pubmed_tool.NcbiClient(),
                extraction,
                args.blocks_file,
                scope_version=args.scope_version,
                sample_size=max(1, args.sample_size),
            )
        write_json(args.output, result)
        receipt = {
            "operation": result["operation"],
            "ok": True,
            "scope_version": args.scope_version,
            "output": args.output,
            "proposal_count": len(result.get("proposals", [])),
            "candidate_generation": result.get("candidate_generation", {}),
            "scope_reentry_required": result.get("scope_reentry_required"),
        }
    except (VocabularyLearningError, pubmed_tool.PubMedError, OSError) as exc:
        receipt = {"operation": args.command, "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
