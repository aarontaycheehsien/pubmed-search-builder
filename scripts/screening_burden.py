#!/usr/bin/env python3
"""Estimate strategy screening burden from reproducible stratified relevance samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pubmed_tool


LABELS = {"likely-relevant", "irrelevant", "uncertain"}


class ScreeningBurdenError(ValueError):
    pass


def read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScreeningBurdenError(f"Could not read JSON {path}: {exc}") from exc


def write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def protocol_policy(path: str | None, scope_version: int) -> dict[str, Any] | None:
    if not path:
        return None
    protocol_path = Path(path)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("dsl_version") != 1:
        raise ScreeningBurdenError("Protocol file must use dsl_version 1")
    if data.get("scope_version") != scope_version:
        raise ScreeningBurdenError("Protocol scope_version does not match --scope-version")
    protocol_id = str(data.get("protocol_id") or "").strip()
    if not protocol_id:
        raise ScreeningBurdenError("Protocol file requires protocol_id")
    variants = data.get("focused_variants", [])
    permitted = {
        str(item.get("id") or "").strip()
        for item in variants
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    } if isinstance(variants, list) else set()
    priorities = data.get("priorities") if isinstance(data.get("priorities"), dict) else {}
    recall = priorities.get("recall") if isinstance(priorities.get("recall"), dict) else {}
    minimum = recall.get("minimum_heldout_recall", priorities.get("minimum_heldout_recall"))
    return {
        "protocol_id": protocol_id,
        "protocol_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "dsl_version": 1,
        "permitted_focused_variant_ids": sorted(permitted),
        "minimum_heldout_recall": float(minimum) if isinstance(minimum, (int, float)) else 1.0,
    }


def load_variants(path: str) -> tuple[list[dict[str, Any]], str]:
    queries, baseline = pubmed_tool.parse_variant_queries(pubmed_tool.read_text_source(path))
    if len(queries) < 2:
        raise ScreeningBurdenError("Screening-burden comparison requires at least two strategy variants")
    labels = [str(item["label"]) for item in queries]
    return queries, baseline or labels[0]


def complete_retrieval_sets(
    client: pubmed_tool.NcbiClient,
    variants: list[dict[str, Any]],
    *,
    retrieval_sets_file: str | None,
    auto_retrieval_limit: int,
) -> dict[str, dict[str, Any]]:
    supplied: Any = read_json(retrieval_sets_file) if retrieval_sets_file else None
    if isinstance(supplied, dict) and "variants" in supplied:
        supplied = supplied["variants"]
    results: dict[str, dict[str, Any]] = {}
    for item in variants:
        label = str(item["label"])
        query = str(item["query"])
        if isinstance(supplied, dict) and label in supplied:
            source = supplied[label]
            if not isinstance(source, dict):
                raise ScreeningBurdenError(f"Retrieval set {label!r} must be an object")
            pmids = pubmed_tool.dedup_preserving_order([str(value) for value in source.get("ranked_pmids", source.get("pmids", []))])
            pubmed_tool.assert_numeric_pmids(pmids, source=f"retrieval set {label}")
            total = source.get("total_count")
            if source.get("complete") is not True or not isinstance(total, int) or total != len(pmids):
                raise ScreeningBurdenError(
                    f"Retrieval set {label!r} must declare complete=true and total_count equal to the complete PMID list length"
                )
            results[label] = {"label": label, "variant_id": item.get("variant_id"), "query": query, "total_count": total, "ranked_pmids": pmids, "source": "provided-complete-export"}
            continue
        count_result = pubmed_tool.esearch(client, query, retmax=0, retstart=0, sort="relevance")
        total = int(count_result.get("count", 0) or 0)
        if total > auto_retrieval_limit:
            raise ScreeningBurdenError(
                f"Variant {label!r} has {total} records, above the complete automatic retrieval limit {auto_retrieval_limit}. "
                "Provide --retrieval-sets-file with a complete ranked PMID export; a top-results frame would bias precision."
            )
        full = pubmed_tool.esearch(client, query, retmax=max(1, total), retstart=0, sort="relevance") if total else {"pmids": []}
        pmids = pubmed_tool.dedup_preserving_order([str(value) for value in full.get("pmids", [])])
        if len(pmids) != total:
            raise ScreeningBurdenError(f"PubMed returned an incomplete PMID frame for variant {label!r}: {len(pmids)}/{total}")
        results[label] = {"label": label, "variant_id": item.get("variant_id"), "query": query, "total_count": total, "ranked_pmids": pmids, "source": "pubmed-complete-frame"}
    return results


def make_strata(retrieval_sets: dict[str, dict[str, Any]], rank_bands: int) -> dict[str, list[dict[str, Any]]]:
    occurrence = Counter(pmid for item in retrieval_sets.values() for pmid in item["ranked_pmids"])
    output: dict[str, list[dict[str, Any]]] = {}
    for label, item in retrieval_sets.items():
        pmids = list(item["ranked_pmids"])
        total = len(pmids)
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for rank, pmid in enumerate(pmids):
            relationship = "shared" if occurrence[pmid] > 1 else "unique"
            band = min(rank_bands - 1, (rank * rank_bands) // max(total, 1))
            grouped[f"{relationship}:rank-{band + 1}-of-{rank_bands}"].append(pmid)
        output[label] = [
            {"stratum": name, "population_size": len(values), "population_pmids": values}
            for name, values in sorted(grouped.items())
        ]
    return output


def balanced_allocation(strata: list[dict[str, Any]], target: int) -> dict[str, int]:
    allocation = {str(item["stratum"]): 0 for item in strata}
    remaining = min(target, sum(int(item["population_size"]) for item in strata))
    while remaining:
        progressed = False
        for item in strata:
            name = str(item["stratum"])
            if allocation[name] < int(item["population_size"]):
                allocation[name] += 1
                remaining -= 1
                progressed = True
                if not remaining:
                    break
        if not progressed:
            break
    return allocation


def deterministic_sample(pmids: list[str], size: int, seed: str, label: str, stratum: str) -> list[str]:
    return sorted(
        pmids,
        key=lambda pmid: hashlib.sha256(f"{seed}|{label}|{stratum}|{pmid}".encode("utf-8")).hexdigest(),
    )[:size]


def sample_variants(
    client: pubmed_tool.NcbiClient,
    variants: list[dict[str, Any]],
    baseline_label: str,
    *,
    scope_version: int,
    sample_size: int,
    rank_bands: int,
    seed: str,
    retrieval_sets_file: str | None,
    auto_retrieval_limit: int,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sets = complete_retrieval_sets(
        client, variants, retrieval_sets_file=retrieval_sets_file, auto_retrieval_limit=auto_retrieval_limit
    )
    if baseline_label not in sets:
        raise ScreeningBurdenError(f"Baseline variant not found: {baseline_label}")
    strata_by_variant = make_strata(sets, max(1, rank_bands))
    appearances: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    variant_rows = []
    sampled_pmids: set[str] = set()
    for label, item in sets.items():
        strata = strata_by_variant[label]
        effective_target = max(1, sample_size, len(strata))
        allocation = balanced_allocation(strata, effective_target)
        sampled_strata = []
        for stratum in strata:
            name = str(stratum["stratum"])
            selected = deterministic_sample(stratum.pop("population_pmids"), allocation[name], seed, label, name)
            sampled_pmids.update(selected)
            for pmid in selected:
                appearances[pmid].append({"variant": label, "stratum": name})
            sampled_strata.append({**stratum, "sample_size": len(selected), "sample_pmids": selected})
        variant_rows.append(
            {
                "label": label,
                "variant_id": item.get("variant_id"),
                "query": item["query"],
                "total_count": item["total_count"],
                "retrieval_frame_complete": True,
                "retrieval_frame_source": item["source"],
                "actual_sample_size": sum(allocation.values()),
                "strata": sampled_strata,
                "protocol_status": (
                    "main-authoritative"
                    if label == baseline_label
                    else "permitted"
                    if policy and str(item.get("variant_id") or "") in set(policy.get("permitted_focused_variant_ids", []))
                    else "diagnostic-only"
                ),
            }
        )
    fetched = pubmed_tool.efetch(client, sorted(sampled_pmids, key=int)) if sampled_pmids else {"records": []}
    by_pmid = {str(item.get("pmid")): item for item in fetched.get("records", []) if isinstance(item, dict)}
    queue = []
    for pmid in sorted(sampled_pmids, key=int):
        record = by_pmid.get(pmid, {"pmid": pmid})
        queue.append(
            {
                "sample_id": "S" + hashlib.sha256(pmid.encode("utf-8")).hexdigest()[:12].upper(),
                "pmid": pmid,
                "title": record.get("title", ""),
                "abstract": record.get("abstract", ""),
                "year": record.get("year", ""),
                "appearances": appearances[pmid],
                "label": "unlabelled",
                "label_reason": "",
            }
        )
    result = {
        "operation": "screening-burden-sample",
        "ok": True,
        "scope_version": scope_version,
        "baseline_label": baseline_label,
        "sampling_seed": seed,
        "sampling_date_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sampling_design": "complete-frame shared/unique by rank-band stratified simple random sample via SHA-256 ordering",
        "rank_band_count": max(1, rank_bands),
        "target_sample_size_per_variant": max(1, sample_size),
        "variants": variant_rows,
        "label_values": sorted(LABELS),
        "label_queue": queue,
        "note": "Label each unique PMID once. Complete retrieval frames are required; capped top-result samples are rejected as biased.",
        "request_info": client.metadata(),
    }
    if policy:
        result.update({key: value for key, value in policy.items() if key != "minimum_heldout_recall"})
    return result


def wilson_interval(proportion: float, effective_n: float, z: float = 1.959963984540054) -> tuple[float, float]:
    if effective_n <= 0:
        return 0.0, 1.0
    denominator = 1 + z * z / effective_n
    centre = (proportion + z * z / (2 * effective_n)) / denominator
    spread = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * effective_n)) / effective_n) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def inverse_burden(value: float) -> float | None:
    return round(1 / value, 2) if value > 0 else None


def estimate_variant(row: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    observations: list[tuple[str, float]] = []
    stratum_rows = []
    for stratum in row.get("strata", []):
        if not isinstance(stratum, dict):
            continue
        pmids = [str(value) for value in stratum.get("sample_pmids", [])]
        n = len(pmids)
        population = int(stratum.get("population_size", 0) or 0)
        if not n and population:
            raise ScreeningBurdenError(f"Variant {row.get('label')!r} has an unsampled non-empty stratum")
        unit_weight = population / n if n else 0.0
        counts = Counter(labels[pmid] for pmid in pmids)
        for pmid in pmids:
            observations.append((labels[pmid], unit_weight))
        stratum_rows.append(
            {
                "stratum": stratum.get("stratum"),
                "population_size": population,
                "sample_size": n,
                "label_counts": dict(counts),
                "sampling_weight_per_record": round(unit_weight, 6),
            }
        )
    decided = [(label, weight) for label, weight in observations if label != "uncertain"]
    decided_weight = sum(weight for _label, weight in decided)
    relevant_weight = sum(weight for label, weight in decided if label == "likely-relevant")
    point = relevant_weight / decided_weight if decided_weight else None
    if point is None:
        lower = upper = None
        effective_n = 0.0
    else:
        normalized = [weight / decided_weight for _label, weight in decided]
        effective_n = 1 / sum(weight * weight for weight in normalized) if normalized else 0.0
        lower, upper = wilson_interval(point, effective_n)
    total_weight = sum(weight for _label, weight in observations)
    likely_all = sum(weight for label, weight in observations if label == "likely-relevant")
    uncertain_all = sum(weight for label, weight in observations if label == "uncertain")
    uncertainty_lower = likely_all / total_weight if total_weight else None
    uncertainty_upper = (likely_all + uncertain_all) / total_weight if total_weight else None
    total_count = int(row.get("total_count", 0) or 0)
    return {
        "label": row.get("label"),
        "query": row.get("query"),
        "total_count": total_count,
        "strata": stratum_rows,
        "label_counts_unweighted": dict(Counter(label for label, _weight in observations)),
        "precision_estimate": round(point, 6) if point is not None else None,
        "precision_confidence_interval_95": {
            "lower": round(lower, 6) if lower is not None else None,
            "upper": round(upper, 6) if upper is not None else None,
            "method": "Wilson interval using Kish effective sample size for stratified weights",
            "effective_sample_size": round(effective_n, 2),
        },
        "uncertain_label_precision_bounds": {
            "lower_uncertain_as_irrelevant": round(uncertainty_lower, 6) if uncertainty_lower is not None else None,
            "upper_uncertain_as_relevant": round(uncertainty_upper, 6) if uncertainty_upper is not None else None,
        },
        "estimated_records_screened_per_relevant_report": inverse_burden(point) if point is not None else None,
        "screening_burden_confidence_interval_95": {
            "lower": inverse_burden(upper) if upper is not None else None,
            "upper": inverse_burden(lower) if lower is not None else None,
        },
        "estimated_relevant_reports_in_retrieval": round(total_count * point, 2) if point is not None else None,
    }


def resolve_holdout(candidate_ledger: str | None, explicit_pmids: list[str]) -> tuple[list[str], str]:
    if candidate_ledger:
        pmids, meta = pubmed_tool.candidate_ledger_pmids(candidate_ledger, "validation")
        if meta.get("independent") is not True:
            raise ScreeningBurdenError("Candidate ledger lacks an independent holdout; burden comparison requires held-out recall")
        return pmids, f"candidate-ledger:{candidate_ledger}"
    pmids = pubmed_tool.dedup_preserving_order([str(value) for value in explicit_pmids])
    pubmed_tool.assert_numeric_pmids(pmids, source="heldout PMIDs")
    if not pmids:
        raise ScreeningBurdenError("Provide an independent candidate ledger or explicit heldout PMIDs")
    return pmids, "explicit-independent-heldout"


def estimate_burden(
    client: pubmed_tool.NcbiClient,
    sample: dict[str, Any],
    *,
    scope_version: int,
    heldout_pmids: list[str],
    heldout_source: str,
    minimum_recall: float,
) -> dict[str, Any]:
    if sample.get("operation") != "screening-burden-sample" or sample.get("scope_version") != scope_version:
        raise ScreeningBurdenError("Sample artifact is invalid or has the wrong scope_version")
    label_map: dict[str, str] = {}
    for index, item in enumerate(sample.get("label_queue", []), start=1):
        if not isinstance(item, dict):
            raise ScreeningBurdenError(f"Label item {index} must be an object")
        pmid = str(item.get("pmid") or "")
        label = str(item.get("label") or "").strip().casefold()
        if label not in LABELS:
            raise ScreeningBurdenError(f"PMID {pmid or index} requires one of: {', '.join(sorted(LABELS))}")
        if not str(item.get("label_reason") or "").strip():
            raise ScreeningBurdenError(f"PMID {pmid} requires label_reason")
        if pmid in label_map and label_map[pmid] != label:
            raise ScreeningBurdenError(f"PMID {pmid} has inconsistent labels")
        label_map[pmid] = label
    variants = []
    baseline_label = str(sample.get("baseline_label") or "")
    baseline_count = next(
        (int(row.get("total_count", 0) or 0) for row in sample.get("variants", []) if isinstance(row, dict) and row.get("label") == baseline_label),
        0,
    )
    baseline_retrieved = 0
    for row in sample.get("variants", []):
        if not isinstance(row, dict):
            continue
        estimate = estimate_variant(row, label_map)
        estimate["variant_id"] = row.get("variant_id")
        estimate["protocol_status"] = row.get("protocol_status", "legacy-unspecified")
        query = str(row.get("query") or "")
        retrieved = pubmed_tool.retrieve_against_pmids(client, query, heldout_pmids)
        retrieved_pmids = [pmid for pmid in heldout_pmids if pmid in retrieved]
        recall = len(retrieved_pmids) / len(heldout_pmids)
        if row.get("label") == baseline_label:
            baseline_retrieved = len(retrieved_pmids)
        estimate.update(
            {
                "heldout_retrieved_pmids": retrieved_pmids,
                "heldout_missed_pmids": [pmid for pmid in heldout_pmids if pmid not in retrieved],
                "heldout_recall": round(recall, 6),
                "recall_requirement_met": recall >= minimum_recall,
            }
        )
        variants.append(estimate)
    for row in variants:
        row["incremental_vs_baseline"] = {
            "additional_records_to_screen": int(row["total_count"]) - baseline_count,
            "additional_heldout_records_retrieved": len(row["heldout_retrieved_pmids"]) - baseline_retrieved,
            "heldout_recall_change": round(row["heldout_recall"] - (baseline_retrieved / len(heldout_pmids)), 6),
        }
    eligible = [
        row for row in variants
        if row["recall_requirement_met"]
        and row["precision_estimate"] is not None
        and row.get("protocol_status") != "diagnostic-only"
    ]
    recommended = None
    if len(eligible) >= 2:
        recommended = min(
            eligible,
            key=lambda row: (
                float(row["estimated_records_screened_per_relevant_report"] or float("inf")),
                int(row["total_count"]),
                str(row["label"]),
            ),
        )["label"]
    result = {
        "operation": "screening-burden",
        "ok": True,
        "scope_version": scope_version,
        "labels_complete": True,
        "heldout_source": heldout_source,
        "heldout_pmids": heldout_pmids,
        "minimum_heldout_recall": minimum_recall,
        "baseline_label": baseline_label,
        "variants": variants,
        "selection": {
            "burden_used_for_selection": len(eligible) >= 2,
            "eligible_variant_labels": [row["label"] for row in eligible],
            "recommended_variant_label": recommended,
            "rule": "Compare burden only among variants meeting the held-out recall requirement; choose the lowest estimated records screened per relevant report.",
            "diagnostic_only_variant_labels": [row["label"] for row in variants if row.get("protocol_status") == "diagnostic-only"],
        },
        "caveat": "Precision and burden are sample estimates. Counts remain exact workload totals; uncertain labels are reported as sensitivity bounds.",
        "request_info": client.metadata(),
    }
    for key in ("protocol_id", "protocol_sha256", "dsl_version"):
        if sample.get(key) is not None:
            result[key] = sample[key]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estimate PubMed screening burden from labelled stratified samples.")
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("--variants-file", required=True)
    sample.add_argument("--baseline-label")
    sample.add_argument("--retrieval-sets-file")
    sample.add_argument("--scope-version", type=int, required=True)
    sample.add_argument("--protocol-file")
    sample.add_argument("--sample-size", type=int, default=60)
    sample.add_argument("--rank-bands", type=int, default=3)
    sample.add_argument("--seed", default="pubmed-screening-burden-v1")
    sample.add_argument("--auto-retrieval-limit", type=int, default=10000)
    sample.add_argument("--output", required=True)
    estimate = sub.add_parser("estimate")
    estimate.add_argument("--sample-file", required=True)
    holdout = estimate.add_mutually_exclusive_group(required=True)
    holdout.add_argument("--candidate-ledger")
    holdout.add_argument("--heldout-pmids", nargs="+")
    estimate.add_argument("--scope-version", type=int, required=True)
    estimate.add_argument("--protocol-file")
    estimate.add_argument("--minimum-heldout-recall", type=float)
    estimate.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = pubmed_tool.NcbiClient()
    try:
        policy = protocol_policy(args.protocol_file, args.scope_version)
        if args.command == "sample":
            variants, file_baseline = load_variants(args.variants_file)
            result = sample_variants(
                client,
                variants,
                args.baseline_label or file_baseline,
                scope_version=args.scope_version,
                sample_size=max(1, args.sample_size),
                rank_bands=max(1, args.rank_bands),
                seed=args.seed,
                retrieval_sets_file=args.retrieval_sets_file,
                auto_retrieval_limit=max(1, args.auto_retrieval_limit),
                policy=policy,
            )
        else:
            minimum_recall = args.minimum_heldout_recall
            if minimum_recall is None:
                minimum_recall = float(policy.get("minimum_heldout_recall", 1.0)) if policy else 1.0
            if not 0 <= minimum_recall <= 1:
                raise ScreeningBurdenError("--minimum-heldout-recall must be between 0 and 1")
            sample = read_json(args.sample_file)
            if not isinstance(sample, dict):
                raise ScreeningBurdenError("Sample file must contain an object")
            if policy and (
                sample.get("protocol_id") != policy.get("protocol_id")
                or sample.get("protocol_sha256") != policy.get("protocol_sha256")
            ):
                raise ScreeningBurdenError("Sample artifact does not match the supplied protocol")
            heldout_pmids, heldout_source = resolve_holdout(args.candidate_ledger, args.heldout_pmids or [])
            result = estimate_burden(
                client,
                sample,
                scope_version=args.scope_version,
                heldout_pmids=heldout_pmids,
                heldout_source=heldout_source,
                minimum_recall=minimum_recall,
            )
        write_json(args.output, result)
        receipt = {
            "operation": result["operation"],
            "ok": True,
            "scope_version": args.scope_version,
            "output": args.output,
            "variant_count": len(result.get("variants", [])),
        }
    except (ScreeningBurdenError, pubmed_tool.PubMedError, OSError) as exc:
        receipt = {"operation": args.command, "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
