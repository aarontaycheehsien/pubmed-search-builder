#!/usr/bin/env python3
"""Operational tests for AND-block admission and recall-first/focused strategy strands."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pubmed_tool


FOCUSED_VARIANT_MIN_REDUCTION_PERCENT_DEFAULT = 10.0


class StrategyAnalysisError(ValueError):
    pass


def validate_percentage_threshold(value: float, *, name: str) -> float:
    threshold = float(value)
    if not 0 <= threshold <= 100:
        raise StrategyAnalysisError(f"{name} must be between 0 and 100")
    return threshold


def read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyAnalysisError(f"Could not read JSON {path}: {exc}") from exc


def protocol_policy(path: str | None, scope_version: int) -> dict[str, Any] | None:
    if not path:
        return None
    protocol_path = Path(path)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("dsl_version") != 1:
        raise StrategyAnalysisError("Protocol file must be a review protocol using dsl_version 1")
    if data.get("scope_version") != scope_version:
        raise StrategyAnalysisError("Protocol scope_version does not match --scope-version")
    protocol_id = str(data.get("protocol_id") or "").strip()
    if not protocol_id:
        raise StrategyAnalysisError("Protocol file requires protocol_id")
    variants = data.get("focused_variants", [])
    if not isinstance(variants, list):
        raise StrategyAnalysisError("Protocol focused_variants must be a list")
    variant_ids = {
        str(item.get("id") or "").strip()
        for item in variants
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    variant_specs = {
        str(item.get("id")): item
        for item in variants
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    filters = data.get("filters_and_limits") if isinstance(data.get("filters_and_limits"), dict) else {}
    filter_limit_ids = {
        str(item.get("id") or "").strip()
        for item in filters.get("decisions", [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    return {
        "protocol_id": protocol_id,
        "protocol_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "dsl_version": 1,
        "permitted_focused_variant_ids": sorted(variant_ids),
        "focused_variant_specs": variant_specs,
        "filter_limit_ids": sorted(filter_limit_ids),
    }


def load_block_registry(path: str | None, policy: dict[str, Any] | None, scope_version: int) -> dict[str, dict[str, Any]] | None:
    if not path:
        if policy:
            raise StrategyAnalysisError("--block-registry is required with --protocol-file")
        return None
    raw = read_json(path)
    if not isinstance(raw, dict) or raw.get("artifact_type") != "block-registry":
        raise StrategyAnalysisError("Block registry must be a generated block-registry artifact")
    if raw.get("scope_version") != scope_version:
        raise StrategyAnalysisError("Block registry scope_version does not match --scope-version")
    generated = raw.get("generated_from")
    if policy and (
        raw.get("protocol_id") != policy.get("protocol_id")
        or not isinstance(generated, dict)
        or generated.get("sha256") != policy.get("protocol_sha256")
    ):
        raise StrategyAnalysisError("Block registry does not match the supplied protocol")
    registry: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw.get("blocks", []), start=1):
        if not isinstance(item, dict):
            raise StrategyAnalysisError(f"Block registry row {index} must be an object")
        block_id = str(item.get("block_id") or "").strip()
        if not block_id or block_id in registry:
            raise StrategyAnalysisError(f"Block registry row {index} has an empty or duplicate block_id")
        registry[block_id] = item
    if not registry:
        raise StrategyAnalysisError("Block registry contains no blocks")
    return registry


def bind_blocks_to_registry(
    blocks: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]] | None,
    filter_limit_ids: set[str] | None = None,
) -> None:
    if registry is None:
        return
    seen: set[str] = set()
    allowed_filters = filter_limit_ids or set()
    for index, block in enumerate(blocks, start=1):
        filter_id = str(block.get("filter_limit_id") or "").strip()
        if filter_id:
            if filter_id not in allowed_filters:
                raise StrategyAnalysisError(f"Executable filter/limit {filter_id!r} is not declared in the protocol")
            if filter_id in seen:
                raise StrategyAnalysisError(f"Executable blocks duplicate filter_limit_id {filter_id!r}")
            seen.add(filter_id)
            continue
        block_id = str(block.get("block_id") or block.get("concept_id") or "").strip()
        if not block_id:
            raise StrategyAnalysisError(f"Executable block {index} requires block_id with a protocol registry")
        if block_id in seen:
            raise StrategyAnalysisError(f"Executable blocks duplicate block_id {block_id!r}")
        seen.add(block_id)
        registered = registry.get(block_id)
        if not registered:
            raise StrategyAnalysisError(f"Executable block {block_id!r} is not declared in the protocol registry")
        if str(block.get("label") or "").strip() != str(registered.get("label") or "").strip():
            raise StrategyAnalysisError(f"Executable block {block_id!r} label does not match the protocol registry")


def load_blocks(path: str, *, require_rationale: bool = False) -> list[dict[str, Any]]:
    raw = read_json(path)
    if isinstance(raw, dict):
        raw = [({"label": label, **value} if isinstance(value, dict) else {"label": label, "query": value}) for label, value in raw.items()]
    if not isinstance(raw, list) or not raw:
        raise StrategyAnalysisError("Blocks file must be a non-empty list or object map")
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise StrategyAnalysisError(f"Block {index} must be an object")
        label = str(item.get("label") or item.get("name") or "").strip()
        query = pubmed_tool.normalize_query(str(item.get("query") or ""))
        if not label or label.casefold() in seen:
            raise StrategyAnalysisError(f"Block {index} has an empty or duplicate label")
        pubmed_tool.assert_plain_query(label, query)
        if require_rationale and not str(item.get("rationale") or item.get("workload_rationale") or "").strip():
            raise StrategyAnalysisError(f"Focused narrowing block {label!r} requires rationale")
        seen.add(label.casefold())
        blocks.append({**item, "label": label, "query": query})
    return blocks


def load_concepts(path: str) -> list[dict[str, Any]]:
    raw = read_json(path)
    if not isinstance(raw, list) or not raw:
        raise StrategyAnalysisError("Concepts file must be a non-empty list")
    concepts: list[dict[str, Any]] = []
    labels: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise StrategyAnalysisError(f"Concept {index} must be an object")
        label = str(item.get("label") or "").strip()
        exact = pubmed_tool.normalize_query(str(item.get("exact_query") or ""))
        descriptive = pubmed_tool.normalize_query(str(item.get("descriptive_query") or ""))
        if not label or label.casefold() in labels:
            raise StrategyAnalysisError(f"Concept {index} has an empty or duplicate label")
        pubmed_tool.assert_plain_query(f"{label} exact layer", exact)
        pubmed_tool.assert_plain_query(f"{label} descriptive layer", descriptive)
        override = str(item.get("human_override") or "").strip().casefold().replace("_", "-")
        if override and override not in {"stable", "fragile", "very-fragile"}:
            raise StrategyAnalysisError(f"Concept {label!r} has invalid human_override")
        labels.add(label.casefold())
        concepts.append({**item, "label": label, "exact_query": exact, "descriptive_query": descriptive})
    return concepts


def and_query(parts: list[str]) -> str:
    cleaned = [pubmed_tool.normalize_query(part) for part in parts if pubmed_tool.normalize_query(part)]
    if not cleaned:
        raise StrategyAnalysisError("Cannot construct an empty strategy")
    return " AND ".join(f"({part})" for part in cleaned)


def search_summary(client: pubmed_tool.NcbiClient, query: str, retmax: int) -> dict[str, Any]:
    result = pubmed_tool.esearch(client, query, retmax=max(0, retmax), retstart=0, sort=None)
    return {
        "query": query,
        "count": int(result.get("count", 0) or 0),
        "pmids": [str(v) for v in result.get("pmids", [])],
        "query_translation": result.get("query_translation", ""),
        "warnings": result.get("warnings", {}),
        "query_translation_hook": result.get("query_translation_hook", {}),
    }


def known_item_comparison(
    client: pubmed_tool.NcbiClient,
    full_query: str,
    alternate_query: str,
    pmids: list[str],
) -> dict[str, Any]:
    tested = pubmed_tool.dedup_preserving_order([str(pmid) for pmid in pmids])
    if not tested:
        return {"tested_count": 0, "full_retrieved": [], "alternate_retrieved": [], "lost_due_to_full": []}
    full = pubmed_tool.retrieve_against_pmids(client, full_query, tested)
    alternate = pubmed_tool.retrieve_against_pmids(client, alternate_query, tested)
    return {
        "tested_count": len(tested),
        "full_retrieved": [pmid for pmid in tested if pmid in full],
        "alternate_retrieved": [pmid for pmid in tested if pmid in alternate],
        "lost_due_to_full": [pmid for pmid in tested if pmid in alternate and pmid not in full],
        "full_missed": [pmid for pmid in tested if pmid not in full],
    }


def differential(
    client: pubmed_tool.NcbiClient,
    left_query: str,
    right_query: str,
    retmax: int,
) -> dict[str, Any]:
    query = f"({left_query}) NOT ({right_query})"
    search = search_summary(client, query, retmax)
    fetched = pubmed_tool.efetch(client, search["pmids"]) if search["pmids"] else {"records": []}
    return {**search, "records": fetched.get("records", [])}


def recommend_block(
    block: dict[str, Any],
    development: dict[str, Any],
    holdout: dict[str, Any],
    workload_change: dict[str, Any],
    *,
    focused_variant_min_reduction_percent: float = FOCUSED_VARIANT_MIN_REDUCTION_PERCENT_DEFAULT,
) -> dict[str, Any]:
    focused_variant_min_reduction_percent = validate_percentage_threshold(
        focused_variant_min_reduction_percent,
        name="focused_variant_min_reduction_percent",
    )
    role = str(block.get("role") or block.get("proposed_role") or "required").strip().casefold()
    fragility = str(block.get("fragility") or "stable").strip().casefold().replace("_", "-")
    parent = str(block.get("parent_block") or block.get("move_inside_or_block") or "").strip()
    losses = list(development.get("lost_due_to_full", [])) + list(holdout.get("lost_due_to_full", []))
    reduction = float(workload_change.get("reduction_percent") or 0)
    if parent or role in {"within-block", "within_or", "synonym"}:
        disposition = "move-inside-another-or-block"
        reason = f"The proposal is vocabulary within {parent or 'an existing concept'}, not an independently required concept."
    elif losses:
        disposition = "handle-at-screening"
        reason = f"Requiring this block loses {len(set(losses))} known relevant record(s); it is unsafe in the recall-first strand."
    elif role in {"optional", "focused", "reserve", "screening"} or fragility in {"fragile", "very-fragile", "very fragile"}:
        if reduction >= focused_variant_min_reduction_percent:
            disposition = "focused-variant-only"
            reason = (
                f"The block is {fragility or role} and reduces estimated workload by {reduction:.2f}% "
                f"(at or above the {focused_variant_min_reduction_percent:.2f}% focused-variant threshold) "
                "without observed known-item loss."
            )
        else:
            disposition = "handle-at-screening"
            reason = (
                f"The block is not essential and changes estimated workload by only {reduction:.2f}%, "
                f"below the {focused_variant_min_reduction_percent:.2f}% focused-variant threshold."
            )
    else:
        disposition = "keep-as-required"
        reason = "The block is marked essential/stable and caused no observed development or holdout loss."
    return {
        "disposition": disposition,
        "reason": reason,
        "advisory": "Empirical ablation cannot establish conceptual essentiality; reconcile this recommendation with the locked retrieval scope.",
    }


def concept_ablation(
    client: pubmed_tool.NcbiClient,
    blocks: list[dict[str, Any]],
    *,
    development_pmids: list[str],
    holdout_pmids: list[str],
    scope_version: int,
    sample_size: int,
    focused_variant_min_reduction_percent: float = FOCUSED_VARIANT_MIN_REDUCTION_PERCENT_DEFAULT,
) -> dict[str, Any]:
    focused_variant_min_reduction_percent = validate_percentage_threshold(
        focused_variant_min_reduction_percent,
        name="focused_variant_min_reduction_percent",
    )
    if len(blocks) < 2:
        raise StrategyAnalysisError("Concept ablation requires at least two proposed AND blocks")
    full_query = and_query([str(block["query"]) for block in blocks])
    full = search_summary(client, full_query, 0)
    analyses: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        without_query = and_query([str(item["query"]) for pos, item in enumerate(blocks) if pos != index])
        without = search_summary(client, without_query, 0)
        development = known_item_comparison(client, full_query, without_query, development_pmids)
        holdout = known_item_comparison(client, full_query, without_query, holdout_pmids)
        delta = without["count"] - full["count"]
        workload = {
            "full_count": full["count"],
            "without_block_count": without["count"],
            "additional_records_without_block": delta,
            "reduction_percent": round((delta / without["count"]) * 100, 2) if without["count"] else 0.0,
        }
        block_development = known_item_comparison(client, str(block["query"]), str(block["query"]), development_pmids)
        block_holdout = known_item_comparison(client, str(block["query"]), str(block["query"]), holdout_pmids)
        identity = {
            key: block[key]
            for key in ("block_id", "concept_id")
            if str(block.get(key) or "").strip()
        }
        analysis = {
            "label": block["label"],
            **identity,
            "block_query": block["query"],
            "without_block_query": without_query,
            "metadata": {key: value for key, value in block.items() if key not in {"label", "query"}},
            "workload_change": workload,
            "development": {**development, "block_retrieved": block_development["full_retrieved"]},
            "holdout": {**holdout, "block_retrieved": block_holdout["full_retrieved"]},
            "differential_sample": differential(client, without_query, full_query, sample_size),
        }
        analysis["recommendation"] = recommend_block(
            block,
            development,
            holdout,
            workload,
            focused_variant_min_reduction_percent=focused_variant_min_reduction_percent,
        )
        analyses.append(analysis)
    return {
        "operation": "concept-ablation",
        "ok": True,
        "scope_version": scope_version,
        "full_strategy": full,
        "development_pmids": development_pmids,
        "holdout_pmids": holdout_pmids,
        "decision_thresholds": {
            "focused_variant_min_reduction_percent": focused_variant_min_reduction_percent,
        },
        "analyses": analyses,
        "recommendation_values": [
            "keep-as-required",
            "move-inside-another-or-block",
            "handle-at-screening",
            "focused-variant-only",
        ],
        "note": "Run for every proposed AND block before critic review. Counts are workload proxies; recommendations do not redefine eligibility.",
        "request_info": client.metadata(),
    }


def two_strand(
    client: pubmed_tool.NcbiClient,
    main_query: str,
    narrowing_blocks: list[dict[str, Any]],
    *,
    development_pmids: list[str],
    holdout_pmids: list[str],
    scope_version: int,
    sample_size: int,
) -> dict[str, Any]:
    focused_query = and_query([main_query] + [str(block["query"]) for block in narrowing_blocks])
    main = search_summary(client, main_query, 0)
    focused = search_summary(client, focused_query, 0)
    development = known_item_comparison(client, main_query, focused_query, development_pmids)
    holdout = known_item_comparison(client, main_query, focused_query, holdout_pmids)
    main_unique = differential(client, main_query, focused_query, sample_size)
    focused_unique = differential(client, focused_query, main_query, sample_size)
    reduction = main["count"] - focused["count"]
    return {
        "operation": "two-strand",
        "ok": True,
        "scope_version": scope_version,
        "main": {**main, "role": "recall-first-authoritative"},
        "focused": {**focused, "role": "prioritization-only"},
        "narrowing_blocks": [
            {
                "label": block["label"],
                "query": block["query"],
                "rationale": block.get("rationale") or block.get("workload_rationale"),
            }
            for block in narrowing_blocks
        ],
        "development": {
            "tested_count": development["tested_count"],
            "main_retrieved": development["full_retrieved"],
            "focused_retrieved": development["alternate_retrieved"],
            "focused_losses": [pmid for pmid in development["full_retrieved"] if pmid not in development["alternate_retrieved"]],
        },
        "holdout": {
            "tested_count": holdout["tested_count"],
            "main_retrieved": holdout["full_retrieved"],
            "focused_retrieved": holdout["alternate_retrieved"],
            "focused_losses": [pmid for pmid in holdout["full_retrieved"] if pmid not in holdout["alternate_retrieved"]],
        },
        "records_unique_to_main": main_unique,
        "records_unique_to_focused": focused_unique,
        "estimated_screening_workload": {
            "main_records": main["count"],
            "focused_records": focused["count"],
            "records_deferred_by_using_focused_for_prioritization": reduction,
            "focused_reduction_percent": round((reduction / main["count"]) * 100, 2) if main["count"] else 0.0,
            "note": "PubMed result counts are screening-workload proxies, not precision estimates.",
        },
        "safeguards": {
            "main_is_authoritative": True,
            "focused_cannot_replace_main": True,
            "focused_use": "Prioritize screening or supply a secondary strand; search and retain the recall-first main results.",
        },
        "request_info": client.metadata(),
    }


def percentage(count: int, denominator: int) -> float | None:
    return round((count / denominator) * 100, 2) if denominator else None


def record_year(record: dict[str, Any]) -> int | None:
    match = re.search(r"\b(18|19|20)\d{2}\b", str(record.get("year") or ""))
    return int(match.group(0)) if match else None


def era_name(year: int | None) -> str:
    if year is None:
        return "unknown"
    if year < 2000:
        return "pre-2000"
    if year < 2010:
        return "2000-2009"
    if year < 2020:
        return "2010-2019"
    return "2020-present"


def record_vocabulary(record: dict[str, Any]) -> set[str]:
    terms = set(pubmed_tool.record_keyword_set(record)) | set(pubmed_tool.record_acronym_set(record))
    terms |= set(pubmed_tool.record_phrase_set(record)) | set(pubmed_tool.record_mesh_set(record))
    return {
        pubmed_tool.normalize_for_match(term)
        for term in terms
        if pubmed_tool.normalize_for_match(term) and not pubmed_tool.term_rank_noise_reason(term, "tiab")
    }


def query_vocabulary(query: str) -> set[str]:
    values = re.findall(r'"([^"]+)"', query)
    values.extend(re.findall(r"\b([A-Za-z][A-Za-z0-9*-]+)\s*\[[^\]]+\]", query))
    return {pubmed_tool.normalize_for_match(value.replace("*", "")) for value in values if pubmed_tool.normalize_for_match(value.replace("*", ""))}


def era_variation(
    records: list[dict[str, Any]],
    exact: set[str],
    descriptive: set[str],
    mesh: set[str],
    concept_terms: set[str],
) -> dict[str, Any]:
    eras: dict[str, dict[str, Any]] = {}
    for record in records:
        pmid = str(record.get("pmid") or "")
        era = era_name(record_year(record))
        bucket = eras.setdefault(era, {"pmids": [], "vocabulary": set()})
        bucket["pmids"].append(pmid)
        observed = record_vocabulary(record)
        searchable_text = pubmed_tool.normalize_for_match(
            " ".join([str(record.get("title") or ""), str(record.get("abstract") or "")] + list(pubmed_tool.record_mesh_set(record)))
        )
        matched_terms = {term for term in concept_terms if term and term in searchable_text}
        bucket["vocabulary"].update((observed & concept_terms) | matched_terms)
    rows = []
    vocabularies: list[set[str]] = []
    for era, data in sorted(eras.items()):
        pmids = data["pmids"]
        vocab = data["vocabulary"]
        if era != "unknown" and vocab:
            vocabularies.append(vocab)
        rows.append(
            {
                "era": era,
                "record_count": len(pmids),
                "exact_coverage_percent": percentage(len(set(pmids) & exact), len(pmids)),
                "descriptive_coverage_percent": percentage(len(set(pmids) & descriptive), len(pmids)),
                "mesh_coverage_percent": percentage(len(set(pmids) & mesh), len(pmids)),
                "vocabulary_term_count": len(vocab),
            }
        )
    similarities: list[float] = []
    for index, left in enumerate(vocabularies):
        for right in vocabularies[index + 1 :]:
            union = left | right
            similarities.append(len(left & right) / len(union) if union else 1.0)
    minimum = round(min(similarities), 4) if similarities else None
    return {
        "eras": rows,
        "minimum_pairwise_vocabulary_jaccard": minimum,
        "variation_index": round(1 - minimum, 4) if minimum is not None else None,
        "note": "Vocabulary variation is measured across publication-era record sets; one observed era is insufficient and scores as uncertain.",
    }


def dimension_score(value: float | None, stable_cut: float, fragile_cut: float, *, higher_is_better: bool = True) -> int:
    if value is None:
        return 1
    if higher_is_better:
        return 0 if value >= stable_cut else 1 if value >= fragile_cut else 2
    return 0 if value <= stable_cut else 1 if value <= fragile_cut else 2


def empirical_fragility(
    client: pubmed_tool.NcbiClient,
    concepts: list[dict[str, Any]],
    *,
    development_pmids: list[str],
    holdout_pmids: list[str],
    scope_version: int,
    ablation_data: dict[str, Any] | None = None,
    sample_size: int = 10,
) -> dict[str, Any]:
    relevant = pubmed_tool.dedup_preserving_order(development_pmids + holdout_pmids)
    if not relevant:
        raise StrategyAnalysisError("Empirical fragility scoring requires screened relevant development or holdout records")
    fetched = pubmed_tool.efetch(client, relevant)
    records = [record for record in fetched.get("records", []) if isinstance(record, dict)]
    ablation_by_label = {
        str(item.get("label") or "").casefold(): item
        for item in (ablation_data or {}).get("analyses", [])
        if isinstance(item, dict)
    }
    results = []
    for concept in concepts:
        label = str(concept["label"])
        exact_query = str(concept["exact_query"])
        descriptive_query = str(concept["descriptive_query"])
        mesh_query = pubmed_tool.normalize_query(str(concept.get("mesh_query") or ""))
        safety_query = pubmed_tool.normalize_query(str(concept.get("safety_query") or "")) or f"({exact_query}) OR ({descriptive_query})"
        exact = pubmed_tool.retrieve_against_pmids(client, exact_query, relevant)
        descriptive = pubmed_tool.retrieve_against_pmids(client, descriptive_query, relevant)
        mesh = pubmed_tool.retrieve_against_pmids(client, mesh_query, relevant) if mesh_query else set()
        safety = pubmed_tool.retrieve_against_pmids(client, safety_query, relevant)
        exact_count = search_summary(client, exact_query, 0)["count"]
        safety_count = search_summary(client, safety_query, 0)["count"]
        noise_added = max(0, safety_count - exact_count)
        noise_multiplier = round(safety_count / exact_count, 2) if exact_count else (None if not safety_count else float("inf"))
        ablation = ablation_by_label.get(label.casefold(), {})
        ablation_holdout = ablation.get("holdout") if isinstance(ablation.get("holdout"), dict) else {}
        attributable = list(ablation_holdout.get("lost_due_to_full") or [])
        attribution_method = "concept-ablation"
        if not ablation and holdout_pmids:
            attributable = [pmid for pmid in holdout_pmids if pmid not in safety]
            attribution_method = "block-nonretrieval-fallback"
        exact_pct = (len(exact) / len(relevant)) if relevant else None
        mesh_pct = (len(mesh) / len(relevant)) if relevant and mesh_query else None
        safety_pct = (len(safety) / len(relevant)) if relevant else None
        configured_terms = {
            pubmed_tool.normalize_for_match(str(value))
            for value in concept.get("terminology_terms", [])
            if pubmed_tool.normalize_for_match(str(value))
        }
        concept_terms = configured_terms or query_vocabulary(f"{exact_query} {descriptive_query} {mesh_query}")
        era = era_variation(records, exact, descriptive, mesh, concept_terms)
        era["concept_terms_assessed"] = sorted(concept_terms)
        terminology = dimension_score(era["minimum_pairwise_vocabulary_jaccard"], 0.50, 0.25)
        controlled = dimension_score(mesh_pct, 0.80, 0.40)
        explicitness = dimension_score(exact_pct, 0.80, 0.40)
        noise_value = None if noise_multiplier is None else (1000.0 if noise_multiplier == float("inf") else noise_multiplier)
        noise_score = dimension_score(noise_value, 2.0, 10.0, higher_is_better=False)
        validation_score = 1 if not holdout_pmids else (0 if not attributable else 1 if len(attributable) <= max(1, round(len(holdout_pmids) * 0.20)) else 2)
        dimensions = {
            "terminology_stability": terminology,
            "controlled_vocabulary_indexing": controlled,
            "author_reporting_explicitness": explicitness,
            "retrieval_noise_behavior": noise_score,
            "validation_evidence": validation_score,
        }
        total = sum(dimensions.values())
        hard_flags = []
        if len(relevant) >= 4 and exact_pct is not None and exact_pct < 0.25:
            hard_flags.append("concept rarely named explicitly in relevant titles/abstracts")
        if len(relevant) >= 4 and safety_pct is not None and safety_pct < 0.80:
            hard_flags.append("exact plus descriptive safety layer misses relevant records")
        if noise_value is not None and noise_value > 20:
            hard_flags.append("descriptive safety layer adds extreme retrieval noise")
        if mesh_query and mesh_pct is not None and mesh_pct < 0.10 and exact_pct is not None and exact_pct < 0.40:
            hard_flags.append("no reliable MeSH or explicit-label coverage")
        empirical = "very-fragile" if hard_flags or total >= 7 else "fragile" if total >= 3 else "stable"
        override = str(concept.get("human_override") or "").strip().casefold().replace("_", "-")
        override_reason = str(concept.get("override_reason") or "").strip()
        if override and not override_reason:
            raise StrategyAnalysisError(
                f"Concept {label!r} supplies human_override={override} but lacks override_reason"
            )
        final = override or empirical
        identity = {
            key: concept[key]
            for key in ("block_id", "concept_id")
            if str(concept.get(key) or "").strip()
        }
        results.append(
            {
                "label": label,
                **identity,
                "queries": {"mesh": mesh_query, "exact": exact_query, "descriptive": descriptive_query, "safety": safety_query},
                "metrics": {
                    "relevant_record_count": len(relevant),
                    "explicit_title_abstract_naming_percent": percentage(len(exact), len(relevant)),
                    "mesh_coverage_percent": percentage(len(mesh), len(relevant)) if mesh_query else None,
                    "exact_label_coverage_percent": percentage(len(exact), len(relevant)),
                    "additional_descriptive_coverage_percent": percentage(len(descriptive - exact), len(relevant)),
                    "safety_layer_relevant_coverage_percent": percentage(len(safety), len(relevant)),
                    "exact_label_pubmed_count": exact_count,
                    "safety_layer_pubmed_count": safety_count,
                    "noise_added_by_safety_layer": noise_added,
                    "safety_layer_noise_multiplier": None if noise_multiplier == float("inf") else noise_multiplier,
                    "heldout_misses_attributable_to_block": attributable,
                    "heldout_attribution_method": attribution_method,
                    "terminology_variation_across_eras": era,
                },
                "safety_layer_differential_sample": differential(client, safety_query, exact_query, sample_size),
                "dimension_scores": dimensions,
                "total_score": total,
                "hard_red_flags": hard_flags,
                "empirical_recommendation": empirical,
                "human_override": override or None,
                "override_reason": override_reason or None,
                "final_recommendation": final,
                "handling": "normal expansion" if final == "stable" else "exact plus descriptive safety layer" if final == "fragile" else "omit from recall-first main; screening/focused strand",
            }
        )
    return {
        "operation": "fragility-score",
        "ok": True,
        "scope_version": scope_version,
        "development_pmids": development_pmids,
        "holdout_pmids": holdout_pmids,
        "concepts": results,
        "method_note": "Empirical decision aid using the documented five-dimension rubric. Human overrides are preserved but conflicting overrides require a reason.",
        "request_info": client.metadata(),
    }


def ledger_sets(
    path: str | None,
    scope_version: int,
    policy: dict[str, Any] | None,
) -> tuple[list[str], list[str], dict[str, Any] | None]:
    if not path:
        return [], [], None
    binding = {
        "expected_scope_version": scope_version,
        "expected_protocol_id": policy.get("protocol_id") if policy else None,
        "expected_protocol_sha256": policy.get("protocol_sha256") if policy else None,
    }
    development, development_meta = pubmed_tool.candidate_ledger_pmids(path, "discovery", **binding)
    holdout, holdout_meta = pubmed_tool.candidate_ledger_pmids(path, "validation", **binding)
    disjoint = bool(holdout_meta.get("disjoint_from_discovery"))
    if not disjoint:
        holdout = []
    return development, holdout, {"development": development_meta, "validation": holdout_meta}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run concept-ablation and two-strand PubMed strategy analyses.")
    sub = parser.add_subparsers(dest="command", required=True)
    ablation = sub.add_parser("concept-ablation")
    ablation.add_argument("--blocks-file", required=True)
    ablation.add_argument("--candidate-ledger")
    ablation.add_argument("--development-pmids", nargs="*", default=[])
    ablation.add_argument("--holdout-pmids", nargs="*", default=[])
    ablation.add_argument("--scope-version", type=int, required=True)
    ablation.add_argument("--protocol-file")
    ablation.add_argument("--block-registry")
    ablation.add_argument("--sample-size", type=int, default=10)
    ablation.add_argument(
        "--focused-min-reduction-percent",
        type=float,
        default=FOCUSED_VARIANT_MIN_REDUCTION_PERCENT_DEFAULT,
        help=(
            "Minimum workload reduction required to route an optional/fragile, loss-free block to "
            f"focused-variant-only (default {FOCUSED_VARIANT_MIN_REDUCTION_PERCENT_DEFAULT:g})."
        ),
    )
    ablation.add_argument("--output", required=True)
    strands = sub.add_parser("two-strand")
    strands.add_argument("--main-strategy-file", required=True)
    strands.add_argument("--narrowing-blocks-file", required=True)
    strands.add_argument("--candidate-ledger")
    strands.add_argument("--development-pmids", nargs="*", default=[])
    strands.add_argument("--holdout-pmids", nargs="*", default=[])
    strands.add_argument("--scope-version", type=int, required=True)
    strands.add_argument("--protocol-file")
    strands.add_argument("--block-registry")
    strands.add_argument("--focused-variant-id", help="Declared protocol variant ID; undeclared or omitted variants remain diagnostic-only.")
    strands.add_argument("--sample-size", type=int, default=10)
    strands.add_argument("--output", required=True)
    fragility = sub.add_parser("fragility-score")
    fragility.add_argument("--concepts-file", required=True)
    fragility.add_argument("--candidate-ledger")
    fragility.add_argument("--development-pmids", nargs="*", default=[])
    fragility.add_argument("--holdout-pmids", nargs="*", default=[])
    fragility.add_argument("--concept-ablation-json")
    fragility.add_argument("--scope-version", type=int, required=True)
    fragility.add_argument("--protocol-file")
    fragility.add_argument("--block-registry")
    fragility.add_argument("--sample-size", type=int, default=10)
    fragility.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = pubmed_tool.NcbiClient()
    try:
        policy = protocol_policy(args.protocol_file, args.scope_version)
        registry = load_block_registry(args.block_registry, policy, args.scope_version)
        ledger_development, ledger_holdout, ledger_meta = ledger_sets(
            args.candidate_ledger, args.scope_version, policy
        )
        development = pubmed_tool.dedup_preserving_order(ledger_development + [str(v) for v in args.development_pmids])
        holdout = pubmed_tool.dedup_preserving_order(ledger_holdout + [str(v) for v in args.holdout_pmids])
        pubmed_tool.assert_numeric_pmids(development, source="development PMID input")
        pubmed_tool.assert_numeric_pmids(holdout, source="holdout PMID input")
        if args.command == "concept-ablation":
            focused_min_reduction = validate_percentage_threshold(
                args.focused_min_reduction_percent,
                name="--focused-min-reduction-percent",
            )
            blocks = load_blocks(args.blocks_file)
            bind_blocks_to_registry(blocks, registry, set(policy.get("filter_limit_ids", [])) if policy else set())
            result = concept_ablation(
                client,
                blocks,
                development_pmids=development,
                holdout_pmids=holdout,
                scope_version=args.scope_version,
                sample_size=max(1, args.sample_size),
                focused_variant_min_reduction_percent=focused_min_reduction,
            )
        elif args.command == "two-strand":
            main_query = pubmed_tool.normalize_query(pubmed_tool.read_text_source(args.main_strategy_file))
            pubmed_tool.assert_plain_query("main strategy", main_query)
            blocks = load_blocks(args.narrowing_blocks_file, require_rationale=True)
            bind_blocks_to_registry(blocks, registry, set(policy.get("filter_limit_ids", [])) if policy else set())
            requested_variant = str(args.focused_variant_id or "").strip()
            specs = policy.get("focused_variant_specs", {}) if policy else {}
            if requested_variant and requested_variant in specs:
                spec = specs[requested_variant]
                expected = set(spec.get("optional_concept_ids", [])) | set(spec.get("filter_limit_ids", []))
                actual = {
                    str(block.get("filter_limit_id") or block.get("block_id") or block.get("concept_id") or "").strip()
                    for block in blocks
                }
                if actual != expected:
                    raise StrategyAnalysisError(
                        f"Focused variant {requested_variant!r} realization IDs do not match the protocol declaration"
                    )
            result = two_strand(
                client,
                main_query,
                blocks,
                development_pmids=development,
                holdout_pmids=holdout,
                scope_version=args.scope_version,
                sample_size=max(1, args.sample_size),
            )
        else:
            concepts = load_concepts(args.concepts_file)
            if registry is not None:
                concept_ids = {str(item.get("concept_id") or item.get("block_id") or "") for item in concepts}
                unknown = sorted(value for value in concept_ids if value and value not in registry)
                if unknown:
                    raise StrategyAnalysisError("Fragility concepts are not in the protocol registry: " + ", ".join(unknown))
            ablation_data = read_json(args.concept_ablation_json) if args.concept_ablation_json else None
            if ablation_data is not None and not isinstance(ablation_data, dict):
                raise StrategyAnalysisError("Concept-ablation JSON must contain an object")
            result = empirical_fragility(
                client,
                concepts,
                development_pmids=development,
                holdout_pmids=holdout,
                scope_version=args.scope_version,
                ablation_data=ablation_data,
                sample_size=max(1, args.sample_size),
            )
        if ledger_meta:
            result["candidate_ledger_source"] = ledger_meta
        if policy:
            result.update({
                key: value for key, value in policy.items()
                if key not in {"permitted_focused_variant_ids", "focused_variant_specs", "filter_limit_ids"}
            })
        if args.command == "two-strand":
            requested = str(args.focused_variant_id or "").strip()
            permitted = set(policy.get("permitted_focused_variant_ids", [])) if policy else set()
            declared = bool(requested and requested in permitted)
            result["focused_variant_policy"] = {
                "variant_id": requested or None,
                "declared_in_protocol": declared,
                "diagnostic_only": not declared,
                "adoption_eligible": declared,
                "rule": "Undeclared variants may be tested, but require a new protocol version before adoption, registration, or handoff.",
            }
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        receipt = {
            "operation": result["operation"],
            "ok": True,
            "output": args.output,
            "scope_version": args.scope_version,
            "analysis_count": len(result.get("analyses", [])),
        }
    except (StrategyAnalysisError, pubmed_tool.PubMedError, OSError) as exc:
        receipt = {"operation": args.command, "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
