"""How much of the full evidence loop a review's timeline requires.

A rapid review and a full systematic review should not pay the same process cost for the same
PubMed strategy. Depth waives only steps whose cost is mostly human effort spent optimising a
strategy that is already recall-safe: labelled screening-burden sampling, the focused second
strand, and iterative vocabulary-learning rounds with per-term dispositions. The automated
recall safeguards stay at every depth: scope lock, evidence-backed screening with an
independent re-screen, per-block MeSH and count evidence, fragility scoring, concept ablation,
validation, the independent critic, no-harm revision checks, final QA, and the audit.

Every waiver is a disclosed limitation, never a silent omission: the audit must list each one.
"""

from __future__ import annotations

from typing import Any, Mapping

DEFAULT_DEPTH = "full"
DEPTHS = ("full", "standard", "rapid")

# Gate checks each depth may skip, keyed by the check's stable identifier.
WAIVABLE_CHECKS = {
    "screening-burden": "Labelled stratified screening-burden sample comparing strategy variants",
    "two-strand": "Focused prioritisation strand delivered alongside the recall-first main strategy",
    "vocabulary-learning": "Iterative vocabulary-learning rounds with per-term dispositions and retests",
}
DEPTH_WAIVERS: dict[str, tuple[str, ...]] = {
    "full": (),
    "standard": ("screening-burden", "two-strand"),
    "rapid": ("screening-burden", "two-strand", "vocabulary-learning"),
}


def protocol_depth(protocol: Mapping[str, Any] | None) -> str:
    """The protocol's declared depth; legacy or unset protocols run at full depth."""

    review = protocol.get("review") if isinstance(protocol, Mapping) else None
    value = review.get("depth") if isinstance(review, Mapping) else None
    return value if value in DEPTHS else DEFAULT_DEPTH


def waived_checks(depth: str) -> tuple[str, ...]:
    return DEPTH_WAIVERS.get(depth, ())


def depth_disclosure(protocol: Mapping[str, Any] | None) -> dict[str, Any]:
    """The depth record the audit must reproduce."""

    depth = protocol_depth(protocol)
    review = protocol.get("review") if isinstance(protocol, Mapping) else None
    rationale = review.get("depth_rationale") if isinstance(review, Mapping) else None
    return {
        "depth": depth,
        "rationale": str(rationale or "").strip(),
        "waived_checks": [
            {"id": check, "description": WAIVABLE_CHECKS[check]} for check in waived_checks(depth)
        ],
    }
