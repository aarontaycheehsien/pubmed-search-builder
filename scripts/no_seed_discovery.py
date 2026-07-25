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

# Internal convergence thresholds. These are heuristic triggers, not validated
# cutoffs. Pilot families share concepts, indexing, and a database, so they are
# not independent capture occasions and must not be used for capture-recapture.
RECAPTURE_MIN_SCREENED_IN_FOR_ESTIMATE = 5  # below this: no estimate at all
RECAPTURE_MIN_SCREENED_IN_FOR_FIRM_VERDICT = 15  # below this: verdict is indicative-only
RECAPTURE_CONVERGED_COMPLETENESS = 0.85  # completeness at/above this reads as converged
RECAPTURE_UNDERSATURATED_COMPLETENESS = 0.60  # completeness below this reads as a leak signal


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


def classify_discrimination_verdict(
    discriminating_volume: int,
    discriminating_basis: str | None,
    *,
    sparse_ceiling: int,
    bottleneck_floor: int,
) -> str:
    validate_volume_thresholds(sparse_ceiling, bottleneck_floor)
    """Map a measured broad-topic volume to a verdict, respecting the basis confidence.

    A ``single-concept-proxy`` volume is the max over single essential-concept counts,
    which is an upper bound on the true essential-AND core (the intersection can only
    be smaller). So a proxy at/under the ceiling still *confirms* sparsity, but a proxy
    at/over the floor cannot *confirm* a ``discovery-bottleneck`` - one large concept
    says nothing about the size of the intersection. Proxy volumes above the ceiling are
    therefore capped at ``indeterminate`` (which also blocks saturation) rather than
    reported as a false, over-confident bottleneck. A ``topic-core`` basis directly
    measures the core, so all three verdicts remain reachable.
    """
    verdict = classify_topic_volume(
        discriminating_volume, sparse_ceiling=sparse_ceiling, bottleneck_floor=bottleneck_floor
    )
    if discriminating_basis == "single-concept-proxy" and verdict == "discovery-bottleneck":
        return "indeterminate"
    return verdict


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


def internal_convergence_diagnostic(
    included_pmids: list[str],
    provenance: dict[str, Any],
    *,
    min_screened_in_for_estimate: int = RECAPTURE_MIN_SCREENED_IN_FOR_ESTIMATE,
    min_screened_in_for_firm_verdict: int = RECAPTURE_MIN_SCREENED_IN_FOR_FIRM_VERDICT,
    converged_completeness: float = RECAPTURE_CONVERGED_COMPLETENESS,
    undersaturated_completeness: float = RECAPTURE_UNDERSATURATED_COMPLETENESS,
) -> dict[str, Any]:
    """Internal overlap/convergence diagnostic over eligible pilot records.

    This intentionally does *not* perform capture-recapture. The pilot families
    are dependent and heterogeneous. Re-finding records across families is weak
    evidence of internal convergence; a high unique-family yield is a recall-risk
    flag. Neither result estimates the unseen population or completes a gate.
    The historical function name is retained for API compatibility.
    """
    min_screened_in_for_estimate = max(1, int(min_screened_in_for_estimate))
    min_screened_in_for_firm_verdict = max(1, int(min_screened_in_for_firm_verdict))
    if not 0 <= undersaturated_completeness <= converged_completeness <= 1:
        raise NoSeedDiscoveryError(
            "Internal convergence thresholds must satisfy 0 <= undersaturated <="
            " converged <= 1"
        )

    prov_by_pmid = {
        str(item.get("pmid")): item
        for item in provenance.get("records", [])
        if isinstance(item, dict) and item.get("pmid")
    }
    families: list[str] = []
    per_family: dict[str, list[str]] = {}
    capture_counts: dict[str, int] = {}
    matched: list[str] = []
    for pmid in included_pmids:
        entry = prov_by_pmid.get(str(pmid))
        if entry is None:
            continue
        pilot_types = [str(t) for t in entry.get("pilot_types", []) if str(t)]
        if not pilot_types:
            continue
        matched.append(str(pmid))
        capture_counts[str(pmid)] = len(pilot_types)
        for family in pilot_types:
            if family not in per_family:
                per_family[family] = []
                families.append(family)
            per_family[family].append(str(pmid))

    s_obs = len(matched)
    freq: dict[int, int] = {}
    for count in capture_counts.values():
        freq[count] = freq.get(count, 0) + 1
    f1 = freq.get(1, 0)
    f2 = freq.get(2, 0)

    per_family_capture_counts = {family: len(pmids) for family, pmids in sorted(per_family.items())}
    pairwise_jaccard = []
    sorted_families = sorted(per_family)
    for i, a in enumerate(sorted_families):
        for b in sorted_families[i + 1 :]:
            set_a, set_b = set(per_family[a]), set(per_family[b])
            union = set_a | set_b
            jaccard = round(len(set_a & set_b) / len(union), 3) if union else 0.0
            pairwise_jaccard.append({"families": [a, b], "jaccard": jaccard})
    mean_jaccard = (
        round(sum(item["jaccard"] for item in pairwise_jaccard) / len(pairwise_jaccard), 3)
        if pairwise_jaccard
        else None
    )

    result: dict[str, Any] = {
        "screened_in_observed": s_obs,
        "pilot_families_represented": sorted_families,
        "per_family_capture_counts": per_family_capture_counts,
        "capture_frequency": {str(k): freq[k] for k in sorted(freq)},
        "f1_singletons": f1,
        "f2_doubletons": f2,
        "pairwise_jaccard": pairwise_jaccard,
        "mean_pairwise_jaccard": mean_jaccard,
        "diagnostic_type": "internal-convergence-not-capture-recapture",
        "independence_assumption_met": False,
        "formal_population_estimate": None,
        "unique_family_yield": None if not s_obs else round(f1 / s_obs, 4),
        "convergence_score": None if not s_obs else round(1.0 - (f1 / s_obs), 4),
        "decision_thresholds": {
            "min_screened_in_for_estimate": min_screened_in_for_estimate,
            "min_screened_in_for_firm_verdict": min_screened_in_for_firm_verdict,
            "converged_convergence_score_at_or_above": converged_completeness,
            "recall_risk_convergence_score_below": undersaturated_completeness,
        },
    }

    if s_obs < min_screened_in_for_estimate:
        result.update(
            {
                "verdict": "indeterminate",
                "confidence": "insufficient-data",
                "reason": "too-few-screened-in",
                "interpretation": (
                    f"Only {s_obs} screened-in relevant record(s) with pilot provenance; below the "
                    f"{min_screened_in_for_estimate}-record floor, overlap cannot be interpreted reliably."
                ),
            }
        )
        return result
    if not any(count >= 2 for count in capture_counts.values()):
        result.update(
            {
                "verdict": "recall-risk",
                "confidence": "indicative",
                "reason": "no-recaptures",
                "interpretation": (
                    "Every eligible record is unique to one pilot family. This is an internal instability "
                    "signal, not a population estimate; investigate with seeds, an adjacent-review benchmark, "
                    "citation searching, or optional external trial-registry validation."
                ),
            }
        )
        return result

    convergence = result["convergence_score"]
    firm = s_obs >= min_screened_in_for_firm_verdict
    if convergence is not None and convergence >= converged_completeness:
        verdict = "converged"
        interpretation = (
            "Pilot families frequently re-found eligible records. This is weak internal convergence evidence "
            "only; it does not estimate or prove completeness."
        )
    elif convergence is not None and convergence < undersaturated_completeness:
        verdict = "recall-risk"
        interpretation = (
            "Pilot families have a high unique eligible yield. This is an internal recall-risk signal: add an "
            "external benchmark, broaden a pilot family, or supply seeds before trusting recall."
        )
    else:
        verdict = "indeterminate"
        interpretation = (
            "Pilot overlap is intermediate. Treat it as inconclusive pending a stronger external benchmark."
        )
    result.update(
        {
            "verdict": verdict,
            "confidence": "descriptive" if firm else "indicative",
            "reason": "descriptive-overlap" if firm else "below-firm-verdict-floor",
            "interpretation": interpretation,
            "converged_completeness": converged_completeness,
            "undersaturated_completeness": undersaturated_completeness,
        }
    )
    return result


# Backward-compatible import alias. The returned artifact is a convergence
# diagnostic and contains no population-size or completeness estimate.
estimate_completeness = internal_convergence_diagnostic


def accumulated_provenance(
    adjudicated_records: list[dict[str, Any]] | None,
    *extra: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble a cumulative provenance map for the convergence diagnostic.

    Per-round discovery only writes provenance for records first seen that round,
    so a single round's provenance file cannot describe how the pilot families
    overlap across the whole screened-in set - and it collapses to empty at the
    saturation round, exactly when the diagnostic is read. Each adjudicated record
    keeps the pilot families that found it in ``provenance_detail`` (captured in the
    round it was discovered), so the accumulated ledger is the complete, correct
    source. Any ``extra`` single-round provenance maps are unioned in as a fallback
    for records that lack ``provenance_detail``.
    """
    families: dict[str, list[str]] = {}
    order: list[str] = []

    def absorb(pmid: Any, pilot_types: Any) -> None:
        text = str(pmid or "").strip()
        if not text:
            return
        if text not in families:
            families[text] = []
            order.append(text)
        for family in pilot_types or []:
            name = str(family)
            if name and name not in families[text]:
                families[text].append(name)

    for item in adjudicated_records or []:
        if not isinstance(item, dict):
            continue
        detail = item.get("provenance_detail") if isinstance(item.get("provenance_detail"), dict) else {}
        absorb(item.get("pmid"), detail.get("pilot_types"))
    for source in extra:
        if not isinstance(source, dict):
            continue
        for item in source.get("records", []):
            if isinstance(item, dict):
                absorb(item.get("pmid"), item.get("pilot_types"))
    return {"records": [{"pmid": pmid, "pilot_types": families[pmid]} for pmid in order]}


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


def candidate_template_binding(path: str | None, scope_version: int) -> dict[str, Any] | None:
    """Read the compiled candidate-ledger template as protocol-binding authority."""
    if not path:
        return None
    data = read_json(path)
    if not isinstance(data, dict):
        raise NoSeedDiscoveryError("Candidate-ledger template must be a JSON object")
    issues, _ = candidate_ledger.validate_template(data)
    if issues:
        raise NoSeedDiscoveryError("Candidate-ledger template is invalid: " + "; ".join(issues))
    if data.get("scope_version") != scope_version:
        raise NoSeedDiscoveryError("Candidate-ledger template scope_version does not match --scope-version")
    generated = data.get("generated_from") if isinstance(data.get("generated_from"), dict) else {}
    return {
        "protocol_id": str(data["protocol_id"]),
        "protocol_sha256": str(generated["sha256"]),
        "dsl_version": 1,
        "protocol_path": str(generated.get("path") or path),
    }


def resolve_protocol_binding(
    protocol_file: str | None,
    candidate_template: str | None,
    scope_version: int,
) -> dict[str, Any] | None:
    """Accept either DSL source or its compiled ledger template, never mismatched both."""
    from_protocol = protocol_binding(protocol_file, scope_version)
    from_template = candidate_template_binding(candidate_template, scope_version)
    if from_protocol and from_template:
        for key in ("protocol_id", "protocol_sha256", "dsl_version"):
            if from_protocol[key] != from_template[key]:
                raise NoSeedDiscoveryError(
                    f"Candidate-ledger template {key} does not match the supplied protocol file"
                )
    return from_protocol or from_template


def requires_protocol_binding(*artifacts: dict[str, Any]) -> bool:
    """A bound input may not silently produce an unbound continuation artifact."""
    return any(
        any(key in artifact for key in ("protocol_id", "protocol_sha256", "dsl_version"))
        for artifact in artifacts
    )


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
    stripped) is the high-confidence basis. When several topic-core probes are
    supplied they are competing vocabulary renderings of the *same* essential-AND;
    the aggregate is the ``max`` across them, because ``genuinely-sparse`` is the
    only verdict that accepts an empty screened-in set, so it must be hard to reach.
    Trusting the smallest rendering (``min``) would let one narrow/broken rendering -
    the very failure mode that produces an empty screened-in set - trigger a false
    sparse verdict; ``max`` declares sparse only when even the most generous
    rendering is small, and over-blocks (forces repair) otherwise.

    When only ``essential-concept`` probes are supplied, the maximum single-concept
    volume is a lower-confidence proxy: it can only rule sparsity *out*, never
    confirm a bottleneck on its own. Both branches therefore take the aggregate that
    makes ``genuinely-sparse`` hardest to reach.
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
        discriminating_volume = max(topic_core_volumes)
        basis = "topic-core"
        confidence = "high"
    else:
        discriminating_volume = max(essential_volumes) if essential_volumes else 0
        basis = "single-concept-proxy"
        confidence = "low"
    verdict = classify_discrimination_verdict(
        discriminating_volume, basis, sparse_ceiling=sparse_ceiling, bottleneck_floor=bottleneck_floor
    )
    artifact = {
        "operation": "orthogonal-pilot-discrimination",
        "ok": True,
        "scope_version": scope_version,
        "probes": probe_receipts,
        "topic_core_volume": max(topic_core_volumes) if topic_core_volumes else None,
        "topic_core_volume_range": (
            {"min": min(topic_core_volumes), "max": max(topic_core_volumes)} if topic_core_volumes else None
        ),
        "max_essential_concept_volume": max(essential_volumes) if essential_volumes else None,
        "discriminating_volume": discriminating_volume,
        "discriminating_basis": basis,
        "verdict_confidence": confidence,
        "sparse_volume_ceiling": sparse_ceiling,
        "bottleneck_volume_floor": bottleneck_floor,
        "provisional_verdict": verdict,
        "note": (
            "Provisional verdict is advisory; the adjudicate gate re-derives the binding "
            "verdict against the actual screened-in count. Multiple topic-core renderings are "
            "combined with max (the most generous volume), so one narrow rendering cannot force a "
            "false genuinely-sparse verdict. A single-concept-proxy basis can only rule sparsity "
            "out, not confirm a bottleneck."
        ),
    }
    if binding:
        artifact.update({key: value for key, value in binding.items() if key != "protocol_path"})
    return artifact


def blind_id(scope_version: int, pmid: str) -> str:
    return "C" + hashlib.sha256(f"scope:{scope_version}:pmid:{pmid}".encode("utf-8")).hexdigest()[:12].upper()


def validate_volume_thresholds(sparse_ceiling: int, bottleneck_floor: int) -> None:
    if sparse_ceiling < 0 or bottleneck_floor < 0 or sparse_ceiling >= bottleneck_floor:
        raise NoSeedDiscoveryError(
            "Volume thresholds require 0 <= sparse_volume_ceiling < bottleneck_volume_floor"
        )


def validate_bound_artifact(
    payload: dict[str, Any],
    *,
    label: str,
    operation: str,
    scope_version: int,
    binding: dict[str, Any] | None,
) -> None:
    if payload.get("operation") != operation or payload.get("ok", True) is not True:
        raise NoSeedDiscoveryError(f"{label} has the wrong operation or is not successful")
    if payload.get("scope_version") != scope_version:
        raise NoSeedDiscoveryError(f"{label} scope_version does not match --scope-version")
    if binding:
        for key in ("protocol_id", "protocol_sha256"):
            if payload.get(key) != binding.get(key):
                raise NoSeedDiscoveryError(f"{label} {key} does not match the supplied protocol")


def validate_previous_state(
    previous_state: dict[str, Any] | None,
    *,
    scope_version: int,
    binding: dict[str, Any] | None,
    next_round: int,
) -> None:
    if previous_state is None:
        return
    validate_bound_artifact(
        previous_state,
        label="Previous adjudication state",
        operation="orthogonal-pilot-adjudication",
        scope_version=scope_version,
        binding=binding,
    )
    previous_round = previous_state.get("round")
    if not isinstance(previous_round, int) or previous_round >= next_round:
        raise NoSeedDiscoveryError("Previous adjudication round must precede the current round")
    seen_pmids: set[str] = set()
    for index, record in enumerate(previous_state.get("adjudicated_records", []), start=1):
        if not isinstance(record, dict):
            raise NoSeedDiscoveryError(f"Previous adjudication record {index} must be an object")
        pmid = str(record.get("pmid") or "")
        candidate_id = str(record.get("candidate_id") or "")
        if not pmid.isdigit() or candidate_id != blind_id(scope_version, pmid):
            raise NoSeedDiscoveryError(f"Previous adjudication record {index} has invalid candidate identity")
        if pmid in seen_pmids:
            raise NoSeedDiscoveryError(f"Previous adjudication repeats PMID {pmid}")
        seen_pmids.add(pmid)


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
    validate_previous_state(
        previous_state,
        scope_version=scope_version,
        binding=binding,
        next_round=round_number,
    )
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
    provenance_records = [provenance[pmid] for pmid in sorted(provenance, key=int)]
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


# Fields the next round actually consumes from a carried-forward record: identity, its screening
# outcome, and the pilot families that found it. Record text (title/abstract/keywords/MeSH) is not
# re-read -- cumulative vocabulary is carried in `vocabulary_terms` instead -- so the checkpoint no
# longer grows a full copy of every screened record every round. The text stays recoverable through
# the hashed screening artifacts listed in `source_references`.
CHECKPOINT_RECORD_FIELDS = (
    "pmid",
    "candidate_id",
    "decision",
    "eligibility_reason",
    "title_abstract_reviewed",
    "provenance_detail",
)


def checkpoint_record(record: dict[str, Any]) -> dict[str, Any]:
    """Reduce an adjudicated record to the fields required to resume the next round."""
    return {key: record[key] for key in CHECKPOINT_RECORD_FIELDS if key in record}


def artifact_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


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
    recapture_min_screened_in_for_estimate: int = RECAPTURE_MIN_SCREENED_IN_FOR_ESTIMATE,
    recapture_min_screened_in_for_firm_verdict: int = RECAPTURE_MIN_SCREENED_IN_FOR_FIRM_VERDICT,
    recapture_converged_completeness: float = RECAPTURE_CONVERGED_COMPLETENESS,
    recapture_undersaturated_completeness: float = RECAPTURE_UNDERSATURATED_COMPLETENESS,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    validate_volume_thresholds(sparse_volume_ceiling, bottleneck_volume_floor)
    if binding is None and requires_protocol_binding(
        screening,
        provenance,
        previous_state or {},
    ):
        raise NoSeedDiscoveryError(
            "Protocol-bound no-seed artifacts require --protocol-file or --candidate-ledger-template"
        )
    if screening.get("operation") != "orthogonal-pilot-screening" or screening.get("provenance_blinded") is not True:
        raise NoSeedDiscoveryError("Screening artifact is not a provenance-blinded orthogonal-pilot file")
    validate_bound_artifact(
        screening,
        label="Screening artifact",
        operation="orthogonal-pilot-screening",
        scope_version=scope_version,
        binding=binding,
    )
    validate_bound_artifact(
        provenance,
        label="Provenance artifact",
        operation="orthogonal-pilot-provenance",
        scope_version=scope_version,
        binding=binding,
    )
    round_number = screening.get("round")
    if not isinstance(round_number, int) or provenance.get("round") != round_number:
        raise NoSeedDiscoveryError("Screening/provenance round mismatch")
    validate_previous_state(
        previous_state,
        scope_version=scope_version,
        binding=binding,
        next_round=round_number,
    )
    provenance_by_id = {
        str(item.get("candidate_id")): item
        for item in provenance.get("records", [])
        if isinstance(item, dict)
    }
    if len(provenance_by_id) != len([item for item in provenance.get("records", []) if isinstance(item, dict)]):
        raise NoSeedDiscoveryError("Provenance artifact repeats candidate IDs")
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
        pmid = str(record.get("pmid") or "")
        if not pmid.isdigit() or candidate_id != blind_id(scope_version, pmid):
            raise NoSeedDiscoveryError(f"Screening record {index} has invalid candidate identity")
        if str(prov.get("pmid") or "") != pmid:
            raise NoSeedDiscoveryError(f"Screening record {index} does not match its provenance PMID")
        current_records.append(
            {
                **record,
                "provenance_detail": {"pilot_types": prov.get("pilot_types", []), "pilot_labels": prov.get("pilot_labels", [])},
            }
        )
    previous_records = [dict(item) for item in (previous_state or {}).get("adjudicated_records", []) if isinstance(item, dict)]
    provenance_by_pmid = {
        str(item.get("pmid")): item
        for item in provenance.get("records", [])
        if isinstance(item, dict) and str(item.get("pmid") or "").isdigit()
    }
    for item in previous_records:
        pmid = str(item.get("pmid") or "")
        observed = provenance_by_pmid.get(pmid)
        if not observed:
            continue
        detail = dict(item.get("provenance_detail") or {})
        detail["pilot_types"] = sorted(
            set(detail.get("pilot_types", [])) | set(observed.get("pilot_types", []))
        )
        detail["pilot_labels"] = sorted(
            set(detail.get("pilot_labels", [])) | set(observed.get("pilot_labels", []))
        )
        item["provenance_detail"] = detail
    combined_by_pmid = {str(item.get("pmid")): item for item in previous_records + current_records if item.get("pmid")}
    combined = list(combined_by_pmid.values())
    previous_included = {str(value) for value in (previous_state or {}).get("included_pmids", [])}
    included = {str(item.get("pmid")) for item in combined if item.get("decision") == "include"}
    previous_vocabulary = {str(value) for value in (previous_state or {}).get("vocabulary_terms", [])}
    # Vocabulary is a per-record union, so extending the carried cumulative set with this round's
    # records equals recomputing over every record -- without needing the earlier record text. The
    # accumulation is monotonic: a record re-decided out of scope no longer retracts terminology it
    # already contributed, which is the correct reading for a "have we stopped seeing new terms" test.
    vocabulary = previous_vocabulary | vocabulary_from_records(current_records)
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
    # Internal convergence diagnostic over the *accumulated* screened-in relevant
    # set. The current round's provenance file only covers records first seen this
    # round, so overlap is derived from the accumulated ledger (each adjudicated
    # record carries its pilot families in provenance_detail), with the current
    # provenance file unioned in as a fallback. This is descriptive only and never
    # changes saturation or estimates completeness.
    completeness = internal_convergence_diagnostic(
        sorted(included, key=int),
        accumulated_provenance(combined, provenance),
        min_screened_in_for_estimate=recapture_min_screened_in_for_estimate,
        min_screened_in_for_firm_verdict=recapture_min_screened_in_for_firm_verdict,
        converged_completeness=recapture_converged_completeness,
        undersaturated_completeness=recapture_undersaturated_completeness,
    ) if included else None
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
            validate_bound_artifact(
                discrimination,
                label="Discrimination artifact",
                operation="orthogonal-pilot-discrimination",
                scope_version=scope_version,
                binding=binding,
            )
            volume = int(discrimination.get("discriminating_volume", 0) or 0)
            verdict = classify_discrimination_verdict(
                volume,
                discrimination.get("discriminating_basis"),
                sparse_ceiling=sparse_volume_ceiling,
                bottleneck_floor=bottleneck_volume_floor,
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
        if completeness is not None and completeness.get("verdict") == "recall-risk":
            decision["convergence_flag"] = (
                "The internal pilot-overlap diagnostic shows a high unique eligible yield "
                f"({completeness.get('unique_family_yield')}); this reinforces the recall-risk reading above "
                "but is not a capture-recapture estimate."
            )
        gate["user_decision"] = decision
        gate["user_decision_text"] = render_user_decision_text(decision)
    source_references = [
        dict(item)
        for item in (previous_state or {}).get("source_references", [])
        if isinstance(item, dict)
    ]
    source_references.append(
        {
            "round": round_number,
            "screening_sha256": artifact_digest(screening),
            "provenance_sha256": artifact_digest(provenance),
            "screened_record_count": len(current_records),
        }
    )
    state = {
        "operation": "orthogonal-pilot-adjudication",
        "ok": True,
        "scope_version": scope_version,
        "round": screening.get("round"),
        "provenance_blinded": True,
        "pilot_types": sorted(PILOT_TYPES),
        "seen_pmids": sorted(combined_by_pmid, key=int),
        "included_pmids": sorted(included, key=int),
        "adjudicated_records": [checkpoint_record(item) for item in combined],
        "source_references": source_references,
        "review_summary": {
            "note": (
                "Compact round-by-round view for human and critic review. Full record content is not "
                "duplicated here; it lives in the hashed screening artifacts in `source_references`."
            ),
            "round": round_number,
            "screened_total": len(combined_by_pmid),
            "included_total": len(included),
            "new_included_this_round": len(new_included),
            "new_vocabulary_this_round": len(new_vocabulary),
            "vocabulary_total": len(vocabulary),
            "round_saturated": round_saturated,
            "consecutive_saturated_rounds": consecutive,
            "safety_cap_reached_any": cap_reached_any,
            "saturation_gate_verdict": gate.get("verdict"),
            "saturation_gate_applies": gate.get("applies"),
        },
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
    if completeness is not None:
        state["internal_convergence_diagnostic"] = completeness
        if completeness.get("verdict") == "recall-risk":
            state["recall_risk"] = {
                "source": "internal-pilot-convergence",
                "verdict": "recall-risk",
                "unique_family_yield": completeness.get("unique_family_yield"),
                "convergence_score": completeness.get("convergence_score"),
                "critic_must_clear": True,
                "user_message": (
                    "The internal pilot-overlap diagnostic found a high unique eligible yield "
                    f"({completeness.get('unique_family_yield')}). Add an adjacent-review benchmark, broaden a "
                    "pilot family, supply seeds, or use optional external trial-registry validation. This is "
                    "not capture-recapture and does not estimate completeness or block saturation."
                ),
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


BENCHMARK_SOURCE_LABEL = "prior-review-semi-independent"
BENCHMARK_INTEGRITY_NOTE = (
    "Semi-independent: non-independent and external. It imports the prior review's scope bias (and, "
    "unscreened, citation noise), so it is never an independent gold standard. Use it only as a benchmark "
    "for relative recall; benchmark records must not feed term mining. Interpret asymmetrically - low recall "
    "is a real leak signal, high recall is weak positive evidence."
)
BENCHMARK_SOURCE_TIERS = {
    "declared-included-study-list",
    "machine-extracted-pending-confirmation",
    "screened-cited-reference",
    "legacy-unclassified",
}


def _pmid_sort_key(pmid: str) -> tuple[int, str]:
    text = str(pmid)
    return (0, f"{int(text):020d}") if text.isdigit() else (1, text)


def harvest_benchmark(
    client: pubmed_tool.NcbiClient,
    *,
    review_pmids: list[str],
    included_pmids: list[str],
    scope_version: int,
    safety_cap: int,
    max_per_review: int,
    binding: dict[str, Any] | None = None,
    included_source_evidence: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Harvest a screenable benchmark-candidate set from named adjacent reviews.

    Two sources are merged: a user-supplied included-study PMID list (from the
    review's appendix) and the cited references of review PMIDs (via the ``refs``
    elink). The review PMIDs themselves are excluded. The result is a
    screening/provenance pair on a track separate from discovery, so the benchmark
    can never leak into term mining.
    """
    review_set = {str(value) for value in review_pmids}
    sources: dict[str, list[str]] = {}
    source_evidence: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []

    def add(pmid: Any, source: str, source_tier: str) -> None:
        text = str(pmid).strip()
        if not text or text in review_set:
            return
        if text not in sources:
            sources[text] = []
            order.append(text)
        if source not in sources[text]:
            sources[text].append(source)
        evidence = {"source": source, "source_tier": source_tier}
        if evidence not in source_evidence.setdefault(text, []):
            source_evidence[text].append(evidence)

    for pmid in included_pmids:
        add(pmid, "included-study-list", "declared-included-study-list")
    for item in included_source_evidence or []:
        if not isinstance(item, dict):
            raise NoSeedDiscoveryError("Included-study evidence rows must be objects")
        tier = str(item.get("source_tier") or "").strip()
        if tier not in BENCHMARK_SOURCE_TIERS - {"screened-cited-reference", "legacy-unclassified"}:
            raise NoSeedDiscoveryError(f"Unsupported included-study source_tier {tier!r}")
        add(item.get("pmid"), "included-study-evidence", tier)
    cap_reached = False
    if review_set:
        related = pubmed_tool.related_pmids(
            client,
            sorted(review_set, key=_pmid_sort_key),
            links=["refs"],
            max_per_seed=max(1, max_per_review),
            max_total=safety_cap,
        )
        cap_reached = int(related.get("candidate_count_before_cap", 0) or 0) > safety_cap
        for item in related.get("candidate_pmids", []):
            if isinstance(item, dict) and item.get("pmid"):
                add(item["pmid"], "prior-review-refs", "screened-cited-reference")

    candidates = pubmed_tool.dedup_preserving_order(order)
    fetched = pubmed_tool.efetch(client, candidates) if candidates else {"records": []}
    by_pmid = {
        str(record.get("pmid")): record
        for record in fetched.get("records", [])
        if isinstance(record, dict) and record.get("pmid")
    }
    screening_records = []
    provenance_records = []
    for pmid in candidates:
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
        provenance_records.append(
            {
                "candidate_id": candidate_id,
                "pmid": pmid,
                "benchmark_sources": sources[pmid],
                "source_evidence": source_evidence[pmid],
            }
        )
    source_reviews = sorted(review_set, key=_pmid_sort_key)
    screening = {
        "operation": "prior-review-benchmark-screening",
        "artifact_type": "prior-review-benchmark/evidence",
        "artifact_version": 1,
        "scope_version": scope_version,
        "benchmark_candidate": True,
        "source_reviews": source_reviews,
        "candidate_count": len(candidates),
        "retrieval_safety_cap": safety_cap,
        "safety_cap_reached": cap_reached,
        "records": screening_records,
        "note": (
            "Screen these prior-review-sourced candidates against the locked scope before freezing a "
            "benchmark. Screened-in records become a semi-independent recall benchmark; they must never "
            "feed term mining."
        ),
    }
    provenance = {
        "operation": "prior-review-benchmark-provenance",
        "artifact_type": "prior-review-benchmark/evidence",
        "artifact_version": 1,
        "scope_version": scope_version,
        "source_reviews": source_reviews,
        "records": provenance_records,
    }
    if binding:
        public_binding = {key: value for key, value in binding.items() if key != "protocol_path"}
        screening.update(public_binding)
        provenance.update(public_binding)
    return screening, provenance


def freeze_benchmark(
    screening: dict[str, Any],
    *,
    scope_version: int,
    screened: bool,
    binding: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze a screened (or, tiered, unscreened) prior-review benchmark artifact.

    A screened freeze keeps only screened-in ``include`` records and is labelled
    ``semi-independent``. An unscreened freeze keeps every harvested candidate and
    is labelled ``indicative`` (it imports citation noise on top of scope bias).
    """
    if screening.get("operation") != "prior-review-benchmark-screening":
        raise NoSeedDiscoveryError("Not a prior-review benchmark screening artifact")
    if screening.get("scope_version") != scope_version:
        raise NoSeedDiscoveryError("Benchmark screening scope_version does not match --scope-version")
    if binding:
        for key in ("protocol_id", "protocol_sha256"):
            if screening.get(key) != binding.get(key):
                raise NoSeedDiscoveryError(f"Benchmark screening {key} does not match the supplied protocol")
    if screening.get("safety_cap_reached") is True:
        raise NoSeedDiscoveryError(
            "Benchmark harvest reached its retrieval safety cap; resolve the cap before freezing"
        )
    records = [item for item in screening.get("records", []) if isinstance(item, dict)]
    if screened:
        pmids = []
        for index, record in enumerate(records, start=1):
            decision = str(record.get("decision") or "").strip().casefold()
            if decision not in candidate_ledger.DECISIONS:
                raise NoSeedDiscoveryError(f"Benchmark record {index} decision must be include, exclude, or uncertain")
            if record.get("title_abstract_reviewed") is not True:
                raise NoSeedDiscoveryError(f"Benchmark record {index} must record title_abstract_reviewed=true")
            if not str(record.get("eligibility_reason") or "").strip():
                raise NoSeedDiscoveryError(f"Benchmark record {index} requires eligibility_reason")
            if decision == "include":
                pmids.append(str(record.get("pmid")))
        status, confidence = "screened", "semi-independent"
    else:
        pmids = [str(record.get("pmid")) for record in records if record.get("pmid")]
        status, confidence = "unscreened", "indicative"
    pmids = pubmed_tool.dedup_preserving_order(pmids)
    provenance_by_pmid: dict[str, list[dict[str, str]]] = {}
    if provenance is not None:
        rows = provenance.get("records") if isinstance(provenance, dict) else None
        if not isinstance(rows, list):
            raise NoSeedDiscoveryError("Benchmark provenance must contain a records list")
        for row in rows:
            if not isinstance(row, dict) or not row.get("pmid"):
                continue
            evidence = row.get("source_evidence")
            if not isinstance(evidence, list):
                evidence = [{"source": value, "source_tier": "legacy-unclassified"} for value in row.get("benchmark_sources", [])]
            provenance_by_pmid[str(row["pmid"])] = [item for item in evidence if isinstance(item, dict)]
    frozen_evidence = {pmid: provenance_by_pmid.get(pmid, []) for pmid in pmids}
    tiers = [str(item.get("source_tier") or "legacy-unclassified") for values in frozen_evidence.values() for item in values]
    tier_counts = {tier: tiers.count(tier) for tier in sorted(set(tiers))}
    if not tiers:
        benchmark_kind = "legacy-unclassified-benchmark"
    elif all(tier == "declared-included-study-list" for tier in tiers):
        benchmark_kind = "declared-included-study-benchmark"
    elif any(tier == "machine-extracted-pending-confirmation" for tier in tiers):
        benchmark_kind = "machine-extracted-candidate-benchmark"
    else:
        benchmark_kind = "screened-citation-benchmark"
    artifact = {
        "operation": "prior-review-benchmark",
        "artifact_type": "prior-review-benchmark/evidence",
        "artifact_version": 1,
        "ok": True,
        "scope_version": scope_version,
        "benchmark_source_label": BENCHMARK_SOURCE_LABEL,
        "benchmark_status": status,
        "screened": bool(screened),
        "confidence": confidence,
        "source_reviews": screening.get("source_reviews", []),
        "benchmark_size": len(pmids),
        "pmids": pmids,
        "benchmark_kind": benchmark_kind,
        "source_tier_counts": tier_counts,
        "source_evidence": frozen_evidence,
        "integrity_note": BENCHMARK_INTEGRITY_NOTE,
    }
    if binding:
        artifact.update({key: value for key, value in binding.items() if key != "protocol_path"})
    return artifact


def load_pmid_list(path: str) -> list[str]:
    data = read_json(path)
    if isinstance(data, dict):
        data = data.get("pmids") or data.get("included_pmids") or []
    if not isinstance(data, list):
        raise NoSeedDiscoveryError("Included-PMIDs file must be a JSON list or an object with a 'pmids' list")
    return [str(value).strip() for value in data if str(value).strip()]


def load_included_source_evidence(path: str) -> list[dict[str, Any]]:
    """Load human-declared or machine-extracted included-study candidate provenance."""

    data = read_json(path)
    if isinstance(data, dict):
        data = data.get("records") or data.get("included_studies") or []
    if not isinstance(data, list):
        raise NoSeedDiscoveryError("Included-study evidence file must contain a records list")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise NoSeedDiscoveryError(f"Included-study evidence row {index} must be an object")
        pmid = str(item.get("pmid") or "").strip()
        tier = str(item.get("source_tier") or "").strip()
        if not pmid.isdigit():
            raise NoSeedDiscoveryError(f"Included-study evidence row {index} requires a numeric PMID")
        if tier not in {"declared-included-study-list", "machine-extracted-pending-confirmation"}:
            raise NoSeedDiscoveryError(f"Included-study evidence row {index} has unsupported source_tier {tier!r}")
        rows.append({"pmid": pmid, "source_tier": tier})
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orthogonal pilot discovery for no-seed PubMed builds.")
    sub = parser.add_subparsers(dest="command", required=True)
    discover_parser = sub.add_parser("discover")
    discover_parser.add_argument("--pilots-file", required=True)
    discover_parser.add_argument("--scope-version", type=int, required=True)
    discover_parser.add_argument("--protocol-file")
    discover_parser.add_argument("--candidate-ledger-template", help="Compiled candidate_ledger_template_vN.json; preserves DSL protocol binding.")
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
    adjudicate_parser.add_argument("--candidate-ledger-template", help="Compiled candidate_ledger_template_vN.json; preserves DSL protocol binding.")
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
    adjudicate_parser.add_argument("--min-screened-in-for-estimate", type=int, default=RECAPTURE_MIN_SCREENED_IN_FOR_ESTIMATE)
    adjudicate_parser.add_argument("--min-screened-in-for-firm-verdict", type=int, default=RECAPTURE_MIN_SCREENED_IN_FOR_FIRM_VERDICT)
    adjudicate_parser.add_argument("--converged-completeness", type=float, default=RECAPTURE_CONVERGED_COMPLETENESS)
    adjudicate_parser.add_argument("--undersaturated-completeness", type=float, default=RECAPTURE_UNDERSATURATED_COMPLETENESS)
    adjudicate_parser.add_argument("--state-output", required=True)
    adjudicate_parser.add_argument("--ledger-output", required=True)
    discriminate_parser = sub.add_parser("discriminate")
    discriminate_parser.add_argument("--probes-file", required=True)
    discriminate_parser.add_argument("--scope-version", type=int, required=True)
    discriminate_parser.add_argument("--protocol-file")
    discriminate_parser.add_argument("--candidate-ledger-template", help="Compiled candidate_ledger_template_vN.json; preserves DSL protocol binding.")
    discriminate_parser.add_argument("--sparse-volume-ceiling", type=int, default=SPARSE_VOLUME_CEILING_DEFAULT)
    discriminate_parser.add_argument("--bottleneck-volume-floor", type=int, default=BOTTLENECK_VOLUME_FLOOR_DEFAULT)
    discriminate_parser.add_argument("--output", required=True)
    recapture_parser = sub.add_parser(
        "recapture",
        help="Deprecated command name: emit an internal pilot-overlap convergence diagnostic (not capture-recapture).",
    )
    recapture_parser.add_argument("--provenance-file", required=True)
    recapture_parser.add_argument(
        "--state-file",
        required=True,
        help="Adjudication state file supplying included_pmids (the screened-in relevant records).",
    )
    recapture_parser.add_argument("--scope-version", type=int, required=True)
    recapture_parser.add_argument("--protocol-file")
    recapture_parser.add_argument("--candidate-ledger-template", help="Compiled candidate_ledger_template_vN.json; preserves DSL protocol binding.")
    recapture_parser.add_argument("--min-screened-in-for-estimate", type=int, default=RECAPTURE_MIN_SCREENED_IN_FOR_ESTIMATE)
    recapture_parser.add_argument("--min-screened-in-for-firm-verdict", type=int, default=RECAPTURE_MIN_SCREENED_IN_FOR_FIRM_VERDICT)
    recapture_parser.add_argument("--converged-completeness", type=float, default=RECAPTURE_CONVERGED_COMPLETENESS)
    recapture_parser.add_argument("--undersaturated-completeness", type=float, default=RECAPTURE_UNDERSATURATED_COMPLETENESS)
    recapture_parser.add_argument("--output", required=True)
    harvest_parser = sub.add_parser(
        "benchmark-harvest",
        help="Harvest a screenable benchmark-candidate set from named adjacent reviews (cited references and/or an included-study PMID list).",
    )
    harvest_parser.add_argument("--review-pmids", nargs="+", default=[], help="Adjacent/prior systematic review PMIDs; their cited references are harvested via the refs elink.")
    harvest_parser.add_argument("--included-pmids-file", help="JSON list (or {'pmids': [...]}) of the review's included-study PMIDs.")
    harvest_parser.add_argument(
        "--included-study-evidence-file",
        help="JSON records with PMID and source_tier (declared-included-study-list or machine-extracted-pending-confirmation).",
    )
    harvest_parser.add_argument("--scope-version", type=int, required=True)
    harvest_parser.add_argument("--protocol-file")
    harvest_parser.add_argument("--candidate-ledger-template", help="Compiled candidate_ledger_template_vN.json; preserves DSL protocol binding.")
    harvest_parser.add_argument("--safety-cap", type=int, default=500)
    harvest_parser.add_argument("--max-per-review", type=int, default=200)
    harvest_parser.add_argument("--screening-output", required=True)
    harvest_parser.add_argument("--provenance-output", required=True)
    freeze_parser = sub.add_parser(
        "benchmark-freeze",
        help="Freeze a screened prior-review benchmark (screened-in only) into a labelled semi-independent benchmark JSON.",
    )
    freeze_parser.add_argument("--screening-file", required=True)
    freeze_parser.add_argument("--provenance-file", help="Optional benchmark provenance file used to preserve source-quality tiers.")
    freeze_parser.add_argument("--scope-version", type=int, required=True)
    freeze_parser.add_argument("--protocol-file")
    freeze_parser.add_argument("--candidate-ledger-template", help="Compiled candidate_ledger_template_vN.json; preserves DSL protocol binding.")
    freeze_parser.add_argument(
        "--unscreened",
        action="store_true",
        help="Freeze every harvested candidate without screening as an INDICATIVE-only benchmark (imports citation noise). Default requires screening.",
    )
    freeze_parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        binding = resolve_protocol_binding(
            args.protocol_file,
            args.candidate_ledger_template,
            args.scope_version,
        )
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
        elif args.command == "benchmark-harvest":
            included = load_pmid_list(args.included_pmids_file) if args.included_pmids_file else []
            included_evidence = load_included_source_evidence(args.included_study_evidence_file) if args.included_study_evidence_file else []
            review_pmids = [str(value) for value in (args.review_pmids or [])]
            if not review_pmids and not included and not included_evidence:
                raise NoSeedDiscoveryError("benchmark-harvest requires --review-pmids, --included-pmids-file, and/or --included-study-evidence-file")
            screening, provenance = harvest_benchmark(
                pubmed_tool.NcbiClient(),
                review_pmids=review_pmids,
                included_pmids=included,
                scope_version=args.scope_version,
                safety_cap=max(1, args.safety_cap),
                max_per_review=max(1, args.max_per_review),
                binding=binding,
                included_source_evidence=included_evidence,
            )
            write_json(args.screening_output, screening)
            write_json(args.provenance_output, provenance)
            receipt = {
                "operation": "prior-review-benchmark-harvest",
                "ok": True,
                "screening_output": args.screening_output,
                "provenance_output": args.provenance_output,
                "candidate_count": screening["candidate_count"],
                "source_reviews": screening["source_reviews"],
                "safety_cap_reached": screening["safety_cap_reached"],
                "next_step": (
                    "Screen the candidates against the locked scope, then run benchmark-freeze. The screened-in "
                    "set is a semi-independent (non-independent, external) recall benchmark, never a gold standard."
                ),
            }
        elif args.command == "benchmark-freeze":
            screening = read_json(args.screening_file)
            if not isinstance(screening, dict):
                raise NoSeedDiscoveryError("Benchmark screening file must contain a JSON object")
            artifact = freeze_benchmark(
                screening,
                scope_version=args.scope_version,
                screened=not args.unscreened,
                binding=binding,
                provenance=(read_json(args.provenance_file) if args.provenance_file else None),
            )
            write_json(args.output, artifact)
            receipt = {
                "operation": "prior-review-benchmark",
                "ok": True,
                "output": args.output,
                "benchmark_status": artifact["benchmark_status"],
                "confidence": artifact["confidence"],
                "benchmark_size": artifact["benchmark_size"],
                "benchmark_source_label": artifact["benchmark_source_label"],
                "next_step": (
                    f"Run: pubmed_tool.py recall --benchmark-json {args.output} "
                    "--blocks-file blocks.json --query-file strategy.txt. Interpret asymmetrically."
                ),
            }
        elif args.command == "recapture":
            provenance = read_json(args.provenance_file)
            state = read_json(args.state_file)
            if not isinstance(provenance, dict) or not isinstance(state, dict):
                raise NoSeedDiscoveryError("Provenance and state files must contain JSON objects")
            if provenance.get("scope_version") != args.scope_version or state.get("scope_version") != args.scope_version:
                raise NoSeedDiscoveryError("Provenance/state scope_version does not match --scope-version")
            if binding:
                for key in ("protocol_id", "protocol_sha256"):
                    if provenance.get(key) != binding.get(key):
                        raise NoSeedDiscoveryError(f"Provenance {key} does not match the supplied protocol")
            included_pmids = [str(value) for value in state.get("included_pmids", [])]
            # Prefer the accumulated per-record provenance carried in the state's
            # adjudicated_records; fall back to (and union in) the single-round
            # provenance file for states that predate provenance_detail.
            estimate = internal_convergence_diagnostic(
                included_pmids,
                accumulated_provenance(state.get("adjudicated_records") or [], provenance),
                min_screened_in_for_estimate=max(1, args.min_screened_in_for_estimate),
                min_screened_in_for_firm_verdict=max(1, args.min_screened_in_for_firm_verdict),
                converged_completeness=args.converged_completeness,
                undersaturated_completeness=args.undersaturated_completeness,
            )
            artifact = {
                "operation": "internal-convergence-diagnostic",
                "ok": True,
                "scope_version": args.scope_version,
                **estimate,
                "note": (
                    "This is a descriptive overlap diagnostic, not capture-recapture. High convergence is weak "
                    "positive evidence; high unique eligible yield is a recall-risk flag. It never estimates "
                    "the unseen population or resolves a completion gate."
                ),
            }
            if binding:
                artifact.update({key: value for key, value in binding.items() if key != "protocol_path"})
            write_json(args.output, artifact)
            receipt = {
                "operation": "internal-convergence-diagnostic",
                "ok": True,
                "output": args.output,
                "screened_in_observed": estimate["screened_in_observed"],
                "verdict": estimate["verdict"],
                "convergence_score": estimate.get("convergence_score"),
                "recall_risk": estimate["verdict"] == "recall-risk",
            }
            if estimate["verdict"] == "recall-risk":
                receipt["interpretation"] = estimate["interpretation"]
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
                recapture_min_screened_in_for_estimate=max(1, args.min_screened_in_for_estimate),
                recapture_min_screened_in_for_firm_verdict=max(1, args.min_screened_in_for_firm_verdict),
                recapture_converged_completeness=args.converged_completeness,
                recapture_undersaturated_completeness=args.undersaturated_completeness,
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
