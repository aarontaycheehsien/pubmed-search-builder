"""Deterministic PubMed retrieval profiles for evidence-synthesis reports.

These profiles are transparent query components, not claims that a locally
composed filter has external validation.  Each component retains its source
and indexing limitation so it can be evaluated against the locked protocol.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from pubmed_search_builder.core.io import canonical_json_bytes
from pubmed_search_builder.domain.review_types import eligible_synthesis_types, targets_evidence_syntheses


PROFILE_VERSION = 1
MESH_YEAR = 2026
SOURCES = (
    {
        "source_id": "nlm-systematic-reviews-subset",
        "url": "https://www.nlm.nih.gov/bsd/pubmed_subsets/sysreviews_strategy.html",
        "strategy_last_modified": "2018-12",
        "purpose": "Official PubMed systematic-review subset component",
    },
    {
        "source_id": "nlm-mesh-publication-types",
        "url": "https://www.nlm.nih.gov/mesh/pubtypes.html",
        "mesh_year": MESH_YEAR,
        "purpose": "Publication-type vocabulary and scope notes",
    },
)


def _branch(branch_id: str, query: str, types: tuple[str, ...], *, kind: str, source_id: str, indexing: str) -> dict[str, Any]:
    return {
        "branch_id": branch_id,
        "query": query,
        "eligible_types": list(types),
        "kind": kind,
        "source_id": source_id,
        "indexing_dependency": indexing,
    }


def _branches_for(types: tuple[str, ...]) -> list[dict[str, Any]]:
    selected = set(types)
    branches: list[dict[str, Any]] = []
    if "systematic-review" in selected:
        branches.extend(
            [
                _branch("systematic-subset", "systematic[sb]", ("systematic-review",), kind="official-subset", source_id="nlm-systematic-reviews-subset", indexing="mixed"),
                _branch("systematic-title-rescue", '("systematic review"[tiab] OR "systematic literature review"[tiab])', ("systematic-review",), kind="text-rescue", source_id="nlm-systematic-reviews-subset", indexing="none"),
            ]
        )
    publication_types = {
        "meta-analysis": '"meta-analysis"[pt]',
        "network-meta-analysis": '"network meta-analysis"[pt]',
        "scoping-review": '"scoping review"[pt]',
    }
    for synthesis_type, query in publication_types.items():
        if synthesis_type in selected:
            branches.append(_branch(f"{synthesis_type}-pt", query, (synthesis_type,), kind="publication-type", source_id="nlm-mesh-publication-types", indexing="medline-or-publisher"))
    rescue_queries = {
        "meta-analysis": '("meta-analysis"[tiab] OR "meta analysis"[tiab] OR "meta-analyses"[tiab])',
        "network-meta-analysis": '("network meta-analysis"[tiab] OR "network meta analyses"[tiab] OR "mixed treatment comparison"[tiab])',
        "scoping-review": '("scoping review"[tiab] OR "mapping review"[tiab] OR "scoping literature review"[tiab])',
        "umbrella-review": '("umbrella review"[tiab] OR "overview of reviews"[tiab] OR "review of reviews"[tiab])',
        "rapid-review": '"rapid review"[tiab]',
        "living-systematic-review": '"living systematic review"[tiab]',
        "qualitative-evidence-synthesis": '("qualitative evidence synthesis"[tiab] OR "meta-synthesis"[tiab] OR "metasynthesis"[tiab])',
        "evidence-map": '("evidence map"[tiab] OR "evidence mapping"[tiab])',
    }
    for synthesis_type in types:
        query = rescue_queries.get(synthesis_type)
        if query:
            branches.append(_branch(f"{synthesis_type}-text-rescue", query, (synthesis_type,), kind="text-rescue", source_id="nlm-mesh-publication-types", indexing="none"))
    return branches


def compile_review_profile(protocol: Mapping[str, Any]) -> dict[str, Any]:
    """Compile a scope-bound, provenance-rich evidence-synthesis profile."""

    if not targets_evidence_syntheses(protocol):
        raise ValueError("The protocol does not explicitly target evidence syntheses")
    types = eligible_synthesis_types(protocol)
    if not types:
        raise ValueError("An evidence-synthesis target requires at least one eligible type")
    branches = _branches_for(types)
    query = "(" + " OR ".join(item["query"] for item in branches) + ")"
    target = protocol["evidence_target"]
    result = {
        "operation": "review-retrieval-profile",
        "artifact_type": "review-retrieval/profile",
        "artifact_version": PROFILE_VERSION,
        "ok": True,
        "profile_id": f"pubmed-evidence-synthesis-{PROFILE_VERSION}",
        "profile_version": PROFILE_VERSION,
        "protocol_id": protocol["protocol_id"],
        "scope_version": protocol["scope_version"],
        "eligible_types": list(types),
        "screening_policy": {
            key: target[key]
            for key in ("protocols", "narrative_reviews", "methods_papers")
        },
        "mesh_year": MESH_YEAR,
        "sources": list(SOURCES),
        "branches": branches,
        "query": query,
        "limitations": [
            "Publication-type branches can miss publisher-supplied or incompletely indexed citations.",
            "Text-rescue branches require screening and are not externally validated as a composite hedge.",
            "Methods-topic headings are deliberately excluded from a profile targeting completed evidence syntheses.",
        ],
    }
    result["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
    result["profile_sha256"] = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    return result
