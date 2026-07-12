#!/usr/bin/env python3
"""Orthogonal no-seed pilot discovery with provenance-blinded screening and saturation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import candidate_ledger
import pubmed_tool


PILOT_TYPES = {
    "mesh-led",
    "exact-phrase-led",
    "operational-description-led",
    "prior-review-led",
    "citation-registry-led",
    "historical-terminology-led",
}

PROBE_ROLES = {"topic-core", "essential-concept"}

# Heuristic triggers, not validated cutoffs. A broad essential-concept/topic-core
# volume at or below the ceiling is consistent with a genuinely sparse topic; a
# volume at or above the floor means substantial literature exists, so an empty
# screened-in set points at broken discovery rather than an empty topic.
SPARSE_VOLUME_CEILING_DEFAULT = 500
BOTTLENECK_VOLUME_FLOOR_DEFAULT = 1000


class NoSeedDiscoveryError(ValueError):
    pass


def classify_topic_volume(
    discriminating_volume: int,
    *,
    sparse_ceiling: int,
    bottleneck_floor: int,
) -> str:
    """Classify a zero-screened-in saturation by the broad topic volume.

    Returns ``genuinely-sparse`` (the empty set is credible), ``discovery-bottleneck``
    (literature exists but discovery surfaced nothing, so saturation is not real), or
    ``indeterminate`` (the volume falls in the inconclusive band).
    """
    if discriminating_volume <= sparse_ceiling:
        return "genuinely-sparse"
    if discriminating_volume >= bottleneck_floor:
        return "discovery-bottleneck"
    return "indeterminate"


def build_user_decision(
    *,
    verdict: str,
    screened_in_count: int,
    discriminating_volume: int | None,
    discriminating_basis: str | None,
    consecutive_rounds: int,
) -> dict[str, Any]:
    """Build the explicit, user-facing decision for an empty/thin discovery result.

    Accepting an empirically-unvalidated search is an adoption-confidence choice,
    so it is surfaced early with what happened and the concrete options, rather
    than deferred to the final peer-review label.
    """
    volume_text = "unmeasured" if discriminating_volume is None else f"~{discriminating_volume:,}"
    seed_opt = {
        "id": "supply-seeds",
        "label": "Supply known-relevant seed PMIDs",
        "consequence": "Anchors discovery and enables known-item recall validation (strongest fix).",
    }
    benchmark_opt = {
        "id": "name-adjacent-reviews",
        "label": "Name adjacent or prior systematic reviews to benchmark against",
        "consequence": "Their included studies become a semi-independent recall benchmark.",
    }
    repair_opt = {
        "id": "repair-pilots",
        "label": "Repair or broaden the discovery pilots and run another round",
        "consequence": "Re-attempts discovery; may surface screenable relevant records the current pilots miss.",
    }
    accept_opt = {
        "id": "accept-unvalidated",
        "label": "Proceed with a protocol-only search, accepting it is empirically unvalidated",
        "consequence": "The search rests on the protocol plus structural checks; recall cannot be tested against any relevant-record set. Flagged for human PRESS peer review.",
    }

    if verdict == "discovery-bottleneck":
        what = (
            f"Discovery screened in {screened_in_count} relevant records, but the topic core returns "
            f"{volume_text} records - substantial literature exists."
        )
        why = (
            "An empty screened-in set on a topic this size almost always means the pilots or an essential "
            "AND block are too narrow, not that the topic is empty. Accepting the search now risks shipping "
            "a silent recall hole."
        )
        options = [
            {**repair_opt, "recommended": True},
            seed_opt,
            benchmark_opt,
            {**accept_opt, "recommended": False, "not_recommended_reason": "Evidence indicates the topic is not sparse, so an unvalidated search is high-risk."},
        ]
        recommended = "repair-pilots"
    elif verdict == "genuinely-sparse":
        what = (
            f"Discovery screened in {screened_in_count} relevant records, and a broad probe confirms the topic "
            f"is small ({volume_text} records)."
        )
        why = (
            "There is no relevant-record set to validate recall against. The search will rest on the protocol "
            "plus structural checks only - a reasonable outcome for a genuinely sparse topic, but you should "
            "accept the unvalidated status explicitly."
        )
        options = [
            {**accept_opt, "recommended": True},
            seed_opt,
            benchmark_opt,
        ]
        recommended = "accept-unvalidated"
    elif verdict == "indeterminate":
        what = (
            f"Discovery screened in {screened_in_count} relevant records; the topic-volume probe is inconclusive "
            f"({volume_text} records, between the sparse and bottleneck thresholds)."
        )
        why = "We cannot yet tell whether the topic is genuinely small or the search is too narrow."
        options = [
            {**repair_opt, "recommended": True},
            seed_opt,
            benchmark_opt,
            {**accept_opt, "recommended": False, "not_recommended_reason": "Topic size is unresolved; establish the cause before accepting an unvalidated search."},
        ]
        recommended = "repair-pilots"
    else:  # pending-discrimination
        what = (
            f"Discovery screened in {screened_in_count} relevant records and topic volume has not been measured yet."
        )
        why = "Run the volume-discrimination probe first so the empty result can be interpreted; the choices below then apply."
        options = [
            {
                "id": "measure-volume",
                "label": "Run the volume-discrimination probe (discriminate), then re-adjudicate",
                "consequence": "Measures broad topic volume to tell a sparse topic from a broken search.",
                "recommended": True,
            },
            seed_opt,
            benchmark_opt,
            accept_opt,
        ]
        recommended = "measure-volume"

    return {
        "trigger": "empty-or-thin-screened-in-discovery",
        "verdict": verdict,
        "screened_in_count": screened_in_count,
        "topic_volume": discriminating_volume,
        "topic_volume_basis": discriminating_basis,
        "consecutive_saturated_rounds": consecutive_rounds,
        "what_happened": what,
        "why_it_matters": why,
        "options": options,
        "recommended_option": recommended,
        "note": (
            "Present this to the user before continuing. Accepting an empirically-unvalidated search is an "
            "adoption-confidence decision, not an automatic fallback."
        ),
    }


def render_user_decision_text(decision: dict[str, Any]) -> str:
    """Render the user decision as a plain-text block the agent can surface verbatim."""
    volume = decision.get("topic_volume")
    volume_text = "unmeasured" if volume is None else f"{volume:,}"
    lines = [
        "Discovery confidence decision - your input needed",
        "",
        f"What happened: {decision['what_happened']}",
        f"Why it matters: {decision['why_it_matters']}",
        "",
        (
            f"Evidence: screened-in relevant records = {decision['screened_in_count']}; "
            f"topic volume = {volume_text} ({decision.get('topic_volume_basis') or 'n/a'}); "
            f"verdict = {decision['verdict']}."
        ),
        "",
        "Your choices:",
    ]
    for index, option in enumerate(decision.get("options", []), start=1):
        tag = "   [recommended]" if option.get("recommended") else ""
        lines.append(f"  {index}. {option['label']}{tag}")
        lines.append(f"       -> {option['consequence']}")
        if option.get("not_recommended_reason"):
            lines.append(f"       (not recommended: {option['not_recommended_reason']})")
    return "\n".join(lines)


def read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NoSeedDiscoveryError(f"Could not read JSON {path}: {exc}") from exc


def write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def protocol_binding(path: str | None, scope_version: int) -> dict[str, Any] | None:
    if not path:
        return None
    protocol_path = Path(path)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("dsl_version") != 1:
        raise NoSeedDiscoveryError("Protocol file must use dsl_version 1")
    if data.get("scope_version") != scope_version:
        raise NoSeedDiscoveryError("Protocol scope_version does not match --scope-version")
    protocol_id = str(data.get("protocol_id") or "").strip()
    if not protocol_id:
        raise NoSeedDiscoveryError("Protocol file requires protocol_id")
    return {
        "protocol_id": protocol_id,
        "protocol_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "dsl_version": 1,
        "protocol_path": str(protocol_path),
    }


def load_pilots(path: str) -> list[dict[str, Any]]:
    raw = read_json(path)
    if not isinstance(raw, list) or not raw:
        raise NoSeedDiscoveryError("Pilots file must be a non-empty JSON list")
    pilots: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise NoSeedDiscoveryError(f"Pilot {index} must be an object")
        pilot_type = str(item.get("type") or "").strip().casefold()
        if pilot_type not in PILOT_TYPES or pilot_type in seen_types:
            raise NoSeedDiscoveryError(f"Pilot {index} has an invalid or duplicate type: {pilot_type!r}")
        query = pubmed_tool.normalize_query(str(item.get("query") or ""))
        anchors = pubmed_tool.dedup_preserving_order([str(value) for value in item.get("anchor_pmids", [])])
        if not query and not anchors:
            raise NoSeedDiscoveryError(f"Pilot {pilot_type!r} requires query or anchor_pmids")
        if query:
            pubmed_tool.assert_plain_query(pilot_type, query)
        pubmed_tool.assert_numeric_pmids(anchors, source=f"{pilot_type} anchor_pmids")
        seen_types.add(pilot_type)
        pilots.append({**item, "type": pilot_type, "query": query, "anchor_pmids": anchors})
    missing = sorted(PILOT_TYPES - seen_types)
    if missing:
        raise NoSeedDiscoveryError("Pilots file is missing orthogonal types: " + ", ".join(missing))
    return pilots


def load_probes(path: str) -> list[dict[str, Any]]:
    """Load broad volume-discrimination probes.

    Each probe measures how much literature exists for the topic core or an
    essential concept *alone* (no fragile/optional AND blocks), so a
    zero-screened-in saturation can be told apart from a genuinely empty topic.
    """
    raw = read_json(path)
    if not isinstance(raw, list) or not raw:
        raise NoSeedDiscoveryError("Probes file must be a non-empty JSON list")
    probes: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise NoSeedDiscoveryError(f"Probe {index} must be an object")
        role = str(item.get("role") or "essential-concept").strip().casefold()
        if role not in PROBE_ROLES:
            raise NoSeedDiscoveryError(f"Probe {index} has an invalid role: {role!r} (use topic-core or essential-concept)")
        query = pubmed_tool.normalize_query(str(item.get("query") or ""))
        if not query:
            raise NoSeedDiscoveryError(f"Probe {index} ({role}) requires a query")
        pubmed_tool.assert_plain_query(f"{role} probe", query)
        probes.append({"label": str(item.get("label") or role), "role": role, "query": query})
    return probes


def discriminate(
    client: pubmed_tool.NcbiClient,
    probes: list[dict[str, Any]],
    *,
    scope_version: int,
    sparse_ceiling: int,
    bottleneck_floor: int,
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure broad topic volume and emit a discrimination artifact.

    A ``topic-core`` probe (essential concepts AND-ed, fragile/optional blocks
    stripped) is the high-confidence basis. When only ``essential-concept``
    probes are supplied, the maximum single-concept volume is a lower-confidence
    proxy: it can only rule sparsity *out*, never confirm a bottleneck on its own.
    """
    probe_receipts = []
    topic_core_volumes: list[int] = []
    essential_volumes: list[int] = []
    for probe in probes:
        search = pubmed_tool.esearch(client, probe["query"], retmax=0, retstart=0, sort=None)
        count = int(search.get("count", 0) or 0)
        probe_receipts.append({"label": probe["label"], "role": probe["role"], "query": probe["query"], "count": count})
        if probe["role"] == "topic-core":
            topic_core_volumes.append(count)
        else:
            essential_volumes.append(count)
    if topic_core_volumes:
        discriminating_volume = min(topic_core_volumes)
        basis = "topic-core"
        confidence = "high"
    else:
        discriminating_volume = max(essential_volumes) if essential_volumes else 0
        basis = "single-concept-proxy"
        confidence = "low"
    verdict = classify_topic_volume(
        discriminating_volume, sparse_ceiling=sparse_ceiling, bottleneck_floor=bottleneck_floor
    )
    artifact = {
        "operation": "orthogonal-pilot-discrimination",
        "ok": True,
        "scope_version": scope_version,
        "probes": probe_receipts,
        "topic_core_volume": min(topic_core_volumes) if topic_core_volumes else None,
        "max_essential_concept_volume": max(essential_volumes) if essential_volumes else None,
        "discriminating_volume": discriminating_volume,
        "discriminating_basis": basis,
        "verdict_confidence": confidence,
        "sparse_volume_ceiling": sparse_ceiling,
        "bottleneck_volume_floor": bottleneck_floor,
        "provisional_verdict": verdict,
        "note": (
            "Provisional verdict is advisory; the adjudicate gate re-derives the binding "
            "verdict against the actual screened-in count. A single-concept-proxy basis can "
            "only rule sparsity out, not confirm a bottleneck."
        ),
    }
    if binding:
        artifact.update({key: value for key, value in binding.items() if key != "protocol_path"})
    return artifact


def blind_id(scope_version: int, pmid: str) -> str:
    return "C" + hashlib.sha256(f"scope:{scope_version}:pmid:{pmid}".encode("utf-8")).hexdigest()[:12].upper()


def discover(
    client: pubmed_tool.NcbiClient,
    pilots: list[dict[str, Any]],
    *,
    scope_version: int,
    round_number: int,
    previous_state: dict[str, Any] | None,
    safety_cap_per_pilot: int,
    binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    seen_pmids = {str(value) for value in (previous_state or {}).get("seen_pmids", [])}
    provenance: dict[str, dict[str, Any]] = {}
    pilot_receipts = []
    cap_reached = False
    for pilot in pilots:
        pilot_type = str(pilot["type"])
        found: list[str] = list(pilot.get("anchor_pmids") or [])
        query = str(pilot.get("query") or "")
        query_count = None
        pilot_cap_reached = False
        if query:
            search = pubmed_tool.esearch(client, query, retmax=safety_cap_per_pilot, retstart=0, sort=None)
            query_count = int(search.get("count", 0) or 0)
            pilot_cap_reached = query_count > safety_cap_per_pilot
            found.extend(str(value) for value in search.get("pmids", []))
        anchors = pubmed_tool.dedup_preserving_order(found)
        if pilot_type == "citation-registry-led" and anchors and pilot.get("expand_links", True):
            related = pubmed_tool.related_pmids(
                client,
                anchors,
                links=list(pilot.get("links") or ["similar", "citedin", "refs"]),
                max_per_seed=max(1, int(pilot.get("max_per_seed") or 20)),
                max_total=safety_cap_per_pilot,
            )
            found.extend(
                str(item.get("pmid"))
                for item in related.get("candidate_pmids", [])
                if isinstance(item, dict) and item.get("pmid")
            )
            pilot_cap_reached = pilot_cap_reached or int(related.get("candidate_count_before_cap", 0) or 0) > safety_cap_per_pilot
        cap_reached = cap_reached or pilot_cap_reached
        found = pubmed_tool.dedup_preserving_order(found)
        pilot_receipts.append(
            {
                "type": pilot_type,
                "label": pilot.get("label") or pilot_type,
                "query_count": query_count,
                "candidate_count": len(found),
                "safety_cap_reached": pilot_cap_reached,
            }
        )
        for pmid in found:
            entry = provenance.setdefault(
                pmid,
                {"pmid": pmid, "candidate_id": blind_id(scope_version, pmid), "pilot_types": [], "pilot_labels": []},
            )
            if pilot_type not in entry["pilot_types"]:
                entry["pilot_types"].append(pilot_type)
            label = str(pilot.get("label") or pilot_type)
            if label not in entry["pilot_labels"]:
                entry["pilot_labels"].append(label)

    new_pmids = sorted(set(provenance) - seen_pmids, key=int)
    fetched = pubmed_tool.efetch(client, new_pmids) if new_pmids else {"records": []}
    by_pmid = {
        str(record.get("pmid")): record
        for record in fetched.get("records", [])
        if isinstance(record, dict) and record.get("pmid")
    }
    screening_records = []
    provenance_records = []
    for pmid in new_pmids:
        record = by_pmid.get(pmid, {"pmid": pmid})
        candidate_id = blind_id(scope_version, pmid)
        screening_records.append(
            {
                "candidate_id": candidate_id,
                "pmid": pmid,
                "title": record.get("title", ""),
                "abstract": record.get("abstract", ""),
                "year": record.get("year", ""),
                "mesh_headings": record.get("mesh_headings", []),
                "keywords": record.get("keywords", []),
                "decision": "",
                "title_abstract_reviewed": False,
                "eligibility_reason": "",
            }
        )
        provenance_records.append(provenance[pmid])
    screening = {
        "operation": "orthogonal-pilot-screening",
        "scope_version": scope_version,
        "round": round_number,
        "provenance_blinded": True,
        "pilot_types_excluded_from_screening_view": sorted(PILOT_TYPES),
        "records": screening_records,
        "note": "Screen titles/abstracts without consulting the separate provenance map.",
    }
    provenance_output = {
        "operation": "orthogonal-pilot-provenance",
        "scope_version": scope_version,
        "round": round_number,
        "pilot_types": sorted(PILOT_TYPES),
        "pilot_receipts": pilot_receipts,
        "records": provenance_records,
        "retrieval_safety_cap_per_pilot": safety_cap_per_pilot,
        "safety_cap_reached": cap_reached,
        "note": "The cap is an operational safety ceiling, never the discovery stopping rule.",
    }
    if binding:
        public_binding = {key: value for key, value in binding.items() if key != "protocol_path"}
        screening.update(public_binding)
        provenance_output.update(public_binding)
    return screening, provenance_output


def vocabulary_from_records(records: list[dict[str, Any]]) -> set[str]:
    vocabulary: set[str] = set()
    for record in records:
        if record.get("decision") != "include":
            continue
        terms = set(pubmed_tool.record_keyword_set(record)) | set(pubmed_tool.record_mesh_set(record))
        terms |= set(pubmed_tool.record_phrase_set(record)) | set(pubmed_tool.record_acronym_set(record))
        vocabulary.update(pubmed_tool.normalize_for_match(term) for term in terms if pubmed_tool.normalize_for_match(term))
    return vocabulary


def adjudicate(
    screening: dict[str, Any],
    provenance: dict[str, Any],
    *,
    previous_state: dict[str, Any] | None,
    scope_version: int,
    required_saturated_rounds: int,
    allocation_seed: str,
    binding: dict[str, Any] | None = None,
    discrimination: dict[str, Any] | None = None,
    min_screened_in_for_saturation: int = 1,
    sparse_volume_ceiling: int = SPARSE_VOLUME_CEILING_DEFAULT,
    bottleneck_volume_floor: int = BOTTLENECK_VOLUME_FLOOR_DEFAULT,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if screening.get("operation") != "orthogonal-pilot-screening" or screening.get("provenance_blinded") is not True:
        raise NoSeedDiscoveryError("Screening artifact is not a provenance-blinded orthogonal-pilot file")
    if screening.get("scope_version") != scope_version or provenance.get("scope_version") != scope_version:
        raise NoSeedDiscoveryError("Screening/provenance scope_version mismatch")
    if binding:
        for key in ("protocol_id", "protocol_sha256"):
            if screening.get(key) != binding.get(key) or provenance.get(key) != binding.get(key):
                raise NoSeedDiscoveryError(f"Screening/provenance {key} does not match the supplied protocol")
    provenance_by_id = {
        str(item.get("candidate_id")): item
        for item in provenance.get("records", [])
        if isinstance(item, dict)
    }
    current_records = []
    for index, record in enumerate(screening.get("records", []), start=1):
        if not isinstance(record, dict):
            raise NoSeedDiscoveryError(f"Screening record {index} must be an object")
        candidate_id = str(record.get("candidate_id") or "")
        if candidate_id not in provenance_by_id:
            raise NoSeedDiscoveryError(f"Screening record {index} has no matching provenance entry")
        decision = str(record.get("decision") or "").strip().casefold()
        if decision not in candidate_ledger.DECISIONS:
            raise NoSeedDiscoveryError(f"Screening record {index} decision must be include, exclude, or uncertain")
        if record.get("title_abstract_reviewed") is not True:
            raise NoSeedDiscoveryError(f"Screening record {index} must record title_abstract_reviewed=true")
        reason = str(record.get("eligibility_reason") or "").strip()
        if not reason:
            raise NoSeedDiscoveryError(f"Screening record {index} requires eligibility_reason")
        prov = provenance_by_id[candidate_id]
        current_records.append(
            {
                **record,
                "provenance_detail": {"pilot_types": prov.get("pilot_types", []), "pilot_labels": prov.get("pilot_labels", [])},
            }
        )
    previous_records = [item for item in (previous_state or {}).get("adjudicated_records", []) if isinstance(item, dict)]
    combined_by_pmid = {str(item.get("pmid")): item for item in previous_records + current_records if item.get("pmid")}
    combined = list(combined_by_pmid.values())
    previous_included = {str(value) for value in (previous_state or {}).get("included_pmids", [])}
    included = {str(item.get("pmid")) for item in combined if item.get("decision") == "include"}
    previous_vocabulary = {str(value) for value in (previous_state or {}).get("vocabulary_terms", [])}
    vocabulary = vocabulary_from_records(combined)
    new_included = sorted(included - previous_included, key=int)
    new_vocabulary = sorted(vocabulary - previous_vocabulary)
    round_saturated = not new_included and not new_vocabulary
    consecutive = int((previous_state or {}).get("consecutive_saturated_rounds") or 0) + 1 if round_saturated else 0
    # Every round reruns all required pilot families. A clean rerun resolves an earlier cap after
    # the pilot was narrowed/completed, while a cap in the current round still blocks saturation.
    cap_reached_any = provenance.get("safety_cap_reached") is True
    novelty_saturation_reached = consecutive >= max(1, required_saturated_rounds) and not cap_reached_any

    # Volume-discrimination gate: an empty (or below-floor) screened-in set at novelty
    # saturation cannot be trusted as "the topic is exhausted" until a broad-concept
    # probe shows the topic really is sparse. Otherwise a broken search or weak pilots
    # would masquerade as saturation. Applies only at/under the configured floor, so a
    # single screened-in record still freezes a small (non-independent) ledger as before.
    included_count = len(included)
    min_screened_in = max(0, int(min_screened_in_for_saturation))
    gate: dict[str, Any] = {
        "applies": bool(novelty_saturation_reached and included_count < min_screened_in),
        "screened_in_count": included_count,
        "min_screened_in_for_saturation": min_screened_in,
        "verdict": "not-applicable",
    }
    saturation_reached = novelty_saturation_reached
    if gate["applies"]:
        if discrimination is None:
            gate["verdict"] = "pending-discrimination"
            gate["required_action"] = (
                "An empty screened-in set cannot be declared saturated. Run "
                "`no_seed_discovery.py discriminate` with a topic-core or essential-concept "
                "probe and pass it via --discrimination-file."
            )
            saturation_reached = False
        else:
            if discrimination.get("scope_version") != scope_version:
                raise NoSeedDiscoveryError("Discrimination artifact scope_version does not match --scope-version")
            volume = int(discrimination.get("discriminating_volume", 0) or 0)
            verdict = classify_topic_volume(
                volume, sparse_ceiling=sparse_volume_ceiling, bottleneck_floor=bottleneck_volume_floor
            )
            gate.update(
                {
                    "verdict": verdict,
                    "discriminating_volume": volume,
                    "discriminating_basis": discrimination.get("discriminating_basis"),
                    "sparse_volume_ceiling": sparse_volume_ceiling,
                    "bottleneck_volume_floor": bottleneck_volume_floor,
                }
            )
            if verdict == "genuinely-sparse":
                gate["interpretation"] = (
                    "Broad topic volume is small, so an empty screened-in set is consistent with a "
                    "genuinely sparse topic. Saturation accepted with no included candidates."
                )
            elif verdict == "discovery-bottleneck":
                gate["required_action"] = (
                    "Substantial literature exists for the topic but discovery surfaced no screened-in "
                    "relevant records. Repair or broaden the orthogonal pilots (or reconsider an over-narrow "
                    "essential block) and run another discovery round. Do not declare saturation."
                )
                saturation_reached = False
            else:  # indeterminate
                gate["required_action"] = (
                    "Broad topic volume is inconclusive. Add a topic-core probe, widen the pilots, or obtain "
                    "a human decision before declaring saturation."
                )
                saturation_reached = False
        decision = build_user_decision(
            verdict=gate["verdict"],
            screened_in_count=included_count,
            discriminating_volume=gate.get("discriminating_volume"),
            discriminating_basis=gate.get("discriminating_basis"),
            consecutive_rounds=consecutive,
        )
        gate["user_decision"] = decision
        gate["user_decision_text"] = render_user_decision_text(decision)
    state = {
        "operation": "orthogonal-pilot-adjudication",
        "ok": True,
        "scope_version": scope_version,
        "round": screening.get("round"),
        "provenance_blinded": True,
        "pilot_types": sorted(PILOT_TYPES),
        "seen_pmids": sorted(combined_by_pmid, key=int),
        "included_pmids": sorted(included, key=int),
        "adjudicated_records": combined,
        "vocabulary_terms": sorted(vocabulary),
        "new_included_pmids": new_included,
        "new_vocabulary_terms": new_vocabulary,
        "new_vocabulary_term_count": len(new_vocabulary),
        "round_saturated": round_saturated,
        "consecutive_saturated_rounds": consecutive,
        "required_saturated_rounds": max(1, required_saturated_rounds),
        "safety_cap_reached_any": cap_reached_any,
        "novelty_saturation_reached": novelty_saturation_reached,
        "saturation_gate": gate,
        "saturation_reached": saturation_reached,
        "stopping_rule": "Stop only after consecutive rounds add neither screened-in studies nor vocabulary; a reached safety cap or an unresolved volume-discrimination gate blocks saturation.",
        "ledger_frozen": False,
    }
    if binding:
        state.update({key: value for key, value in binding.items() if key != "protocol_path"})
    ledger = None
    if saturation_reached and included:
        ledger_records = []
        for item in combined:
            decision = str(item.get("decision"))
            ledger_records.append(
                {
                    "pmid": str(item.get("pmid")),
                    "provenance": "pilot-anchor",
                    "decision": decision,
                    "title_abstract_reviewed": True,
                    "eligibility_reason": str(item.get("eligibility_reason")),
                    "use": "both" if decision == "include" else "heuristic" if decision == "uncertain" else "neither",
                    "provenance_detail": item.get("provenance_detail", {}),
                }
            )
        ledger = {"scope_version": scope_version, "records": ledger_records}
        if binding:
            ledger.update({
                "artifact_type": "candidate-ledger",
                "artifact_version": 1,
                "protocol_id": binding["protocol_id"],
                "dsl_version": 1,
                "generated_from": {"path": binding["protocol_path"], "sha256": binding["protocol_sha256"]},
                "ledger_status": "screened",
            })
        ledger, allocation = candidate_ledger.allocate_holdout(ledger, seed=allocation_seed)
        issues, summary = candidate_ledger.validate_ledger(ledger)
        if issues:
            raise NoSeedDiscoveryError("Allocated candidate ledger failed validation: " + "; ".join(issues))
        state["ledger_frozen"] = True
        state["holdout_allocation"] = allocation
        state["candidate_ledger_summary"] = summary
    elif saturation_reached:
        verdict = gate.get("verdict")
        detail = f" (volume-discrimination verdict: {verdict})" if verdict and verdict != "not-applicable" else ""
        state["stop_reason"] = "vocabulary-and-relevant-study saturation reached with no included candidates" + detail
    return state, ledger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orthogonal pilot discovery for no-seed PubMed builds.")
    sub = parser.add_subparsers(dest="command", required=True)
    discover_parser = sub.add_parser("discover")
    discover_parser.add_argument("--pilots-file", required=True)
    discover_parser.add_argument("--scope-version", type=int, required=True)
    discover_parser.add_argument("--protocol-file")
    discover_parser.add_argument("--round", type=int, required=True)
    discover_parser.add_argument("--previous-state")
    discover_parser.add_argument("--safety-cap-per-pilot", type=int, default=500)
    discover_parser.add_argument("--screening-output", required=True)
    discover_parser.add_argument("--provenance-output", required=True)
    adjudicate_parser = sub.add_parser("adjudicate")
    adjudicate_parser.add_argument("--screening-file", required=True)
    adjudicate_parser.add_argument("--provenance-file", required=True)
    adjudicate_parser.add_argument("--previous-state")
    adjudicate_parser.add_argument("--scope-version", type=int, required=True)
    adjudicate_parser.add_argument("--protocol-file")
    adjudicate_parser.add_argument("--required-saturated-rounds", type=int, default=2)
    adjudicate_parser.add_argument("--allocation-seed", default="no-seed-orthogonal-pilots")
    adjudicate_parser.add_argument(
        "--discrimination-file",
        help="Volume-discrimination artifact from the discriminate command; required to accept a zero-screened-in saturation.",
    )
    adjudicate_parser.add_argument(
        "--min-screened-in-for-saturation",
        type=int,
        default=1,
        help="Below this screened-in count the volume-discrimination gate must pass before saturation (default 1: gate only the empty set).",
    )
    adjudicate_parser.add_argument("--sparse-volume-ceiling", type=int, default=SPARSE_VOLUME_CEILING_DEFAULT)
    adjudicate_parser.add_argument("--bottleneck-volume-floor", type=int, default=BOTTLENECK_VOLUME_FLOOR_DEFAULT)
    adjudicate_parser.add_argument("--state-output", required=True)
    adjudicate_parser.add_argument("--ledger-output", required=True)
    discriminate_parser = sub.add_parser("discriminate")
    discriminate_parser.add_argument("--probes-file", required=True)
    discriminate_parser.add_argument("--scope-version", type=int, required=True)
    discriminate_parser.add_argument("--protocol-file")
    discriminate_parser.add_argument("--sparse-volume-ceiling", type=int, default=SPARSE_VOLUME_CEILING_DEFAULT)
    discriminate_parser.add_argument("--bottleneck-volume-floor", type=int, default=BOTTLENECK_VOLUME_FLOOR_DEFAULT)
    discriminate_parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        binding = protocol_binding(args.protocol_file, args.scope_version)
        previous_state_path = getattr(args, "previous_state", None)
        previous = read_json(previous_state_path) if previous_state_path else None
        if previous is not None and not isinstance(previous, dict):
            raise NoSeedDiscoveryError("Previous state must be a JSON object")
        if args.command == "discover":
            pilots = load_pilots(args.pilots_file)
            screening, provenance = discover(
                pubmed_tool.NcbiClient(),
                pilots,
                scope_version=args.scope_version,
                round_number=max(1, args.round),
                previous_state=previous,
                safety_cap_per_pilot=max(1, args.safety_cap_per_pilot),
                binding=binding,
            )
            write_json(args.screening_output, screening)
            write_json(args.provenance_output, provenance)
            receipt = {
                "operation": "orthogonal-pilot-discover",
                "ok": True,
                "screening_output": args.screening_output,
                "provenance_output": args.provenance_output,
                "candidate_count": len(screening["records"]),
                "provenance_blinded": True,
            }
        elif args.command == "discriminate":
            probes = load_probes(args.probes_file)
            artifact = discriminate(
                pubmed_tool.NcbiClient(),
                probes,
                scope_version=args.scope_version,
                sparse_ceiling=max(0, args.sparse_volume_ceiling),
                bottleneck_floor=max(0, args.bottleneck_volume_floor),
                binding=binding,
            )
            write_json(args.output, artifact)
            receipt = {
                "operation": "orthogonal-pilot-discriminate",
                "ok": True,
                "output": args.output,
                "discriminating_volume": artifact["discriminating_volume"],
                "discriminating_basis": artifact["discriminating_basis"],
                "provisional_verdict": artifact["provisional_verdict"],
            }
        else:
            screening = read_json(args.screening_file)
            provenance = read_json(args.provenance_file)
            if not isinstance(screening, dict) or not isinstance(provenance, dict):
                raise NoSeedDiscoveryError("Screening and provenance files must contain JSON objects")
            discrimination = read_json(args.discrimination_file) if args.discrimination_file else None
            if discrimination is not None and not isinstance(discrimination, dict):
                raise NoSeedDiscoveryError("Discrimination file must contain a JSON object")
            state, ledger = adjudicate(
                screening,
                provenance,
                previous_state=previous,
                scope_version=args.scope_version,
                required_saturated_rounds=max(1, args.required_saturated_rounds),
                allocation_seed=args.allocation_seed,
                binding=binding,
                discrimination=discrimination,
                min_screened_in_for_saturation=args.min_screened_in_for_saturation,
                sparse_volume_ceiling=max(0, args.sparse_volume_ceiling),
                bottleneck_volume_floor=max(0, args.bottleneck_volume_floor),
            )
            if ledger is not None:
                write_json(args.ledger_output, ledger)
                state["ledger_output"] = args.ledger_output
            write_json(args.state_output, state)
            gate_state = state["saturation_gate"]
            receipt = {
                "operation": "orthogonal-pilot-adjudicate",
                "ok": True,
                "state_output": args.state_output,
                "saturation_reached": state["saturation_reached"],
                "saturation_gate_verdict": gate_state["verdict"],
                "ledger_frozen": state["ledger_frozen"],
                "ledger_output": args.ledger_output if ledger is not None else None,
            }
            if gate_state.get("user_decision"):
                receipt["user_decision_required"] = True
                receipt["recommended_option"] = gate_state["user_decision"]["recommended_option"]
                receipt["user_decision_text"] = gate_state["user_decision_text"]
    except (NoSeedDiscoveryError, pubmed_tool.PubMedError, candidate_ledger.CandidateLedgerError, OSError) as exc:
        receipt = {"operation": args.command, "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
