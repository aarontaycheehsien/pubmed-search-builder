"""Extract workflow-relevant facts from a locked review protocol."""

from __future__ import annotations

from typing import Any, Mapping

from pubmed_search_builder.domain.review_types import eligible_synthesis_types, targets_evidence_syntheses


def workflow_context(protocol: Mapping[str, Any]) -> dict[str, Any]:
    """Return only protocol facts that alter workflow applicability.

    Missing legacy fields deliberately remain unknown instead of being treated as
    a no-seed, fragile, or external-validation build.
    """

    result: dict[str, Any] = {}
    mode = protocol.get("information_source_mode")
    external = protocol.get("external_validation")
    if isinstance(mode, str):
        result["information_source_mode"] = mode
    if isinstance(external, dict):
        result["external_validation_enabled"] = (
            mode == "pubmed-plus-external-validation" and external.get("status") == "enabled"
        )
    seeds = protocol.get("seeds")
    if isinstance(seeds, dict) and isinstance(seeds.get("records"), list):
        result["no_seed_build"] = len(seeds["records"]) == 0
    concepts = ((protocol.get("searchable_scope") or {}).get("concepts") if isinstance(protocol.get("searchable_scope"), dict) else None)
    if isinstance(concepts, list):
        result["fragile_topic"] = any(
            isinstance(item, dict)
            and item.get("role") == "essential"
            and str(item.get("provisional_fragility") or "").casefold() in {"fragile", "very_fragile", "very-fragile"}
            for item in concepts
        )
    if targets_evidence_syntheses(protocol):
        result["evidence_synthesis_targeted"] = True
        result["eligible_evidence_synthesis_types"] = list(eligible_synthesis_types(protocol))
    return result
