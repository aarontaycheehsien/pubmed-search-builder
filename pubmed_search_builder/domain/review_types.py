"""Typed scope rules for searches that target evidence syntheses."""

from __future__ import annotations

from typing import Any, Mapping


TARGET_MODES = frozenset({"primary-studies", "evidence-syntheses", "mixed"})
SYNTHESIS_TYPES = frozenset(
    {
        "systematic-review",
        "meta-analysis",
        "network-meta-analysis",
        "scoping-review",
        "umbrella-review",
        "rapid-review",
        "living-systematic-review",
        "qualitative-evidence-synthesis",
        "evidence-map",
    }
)
SCREENING_HANDLING = frozenset({"include", "exclude", "screen"})


def evidence_target(protocol: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the explicit evidence target, never inferring it for legacy protocols."""

    value = protocol.get("evidence_target")
    return value if isinstance(value, Mapping) else None


def targets_evidence_syntheses(protocol: Mapping[str, Any]) -> bool:
    target = evidence_target(protocol)
    return bool(target and target.get("mode") in {"evidence-syntheses", "mixed"})


def eligible_synthesis_types(protocol: Mapping[str, Any]) -> tuple[str, ...]:
    target = evidence_target(protocol)
    if not target:
        return ()
    values = target.get("eligible_types")
    if not isinstance(values, list):
        return ()
    return tuple(sorted({str(value) for value in values if str(value) in SYNTHESIS_TYPES}))
