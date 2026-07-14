"""Canonical workflow stages and legacy aliases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from pubmed_search_builder.core.diagnostics import Diagnostic


@dataclass(frozen=True)
class StageSpec:
    id: str
    aliases: tuple[str, ...]
    required_input_roles: tuple[str, ...] = ()
    required_output_roles: tuple[str, ...] = ()
    accepted_input_types: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    accepted_output_types: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    condition: str = "always"


CANONICAL_STAGES = (
    StageSpec("intake", ("question-intake", "seed-intake"), condition="always"),
    StageSpec(
        "scope-lock", ("concept-gate",), ("protocol",), ("scope",),
        {"protocol": ("legacy/unknown", "protocol/receipt")},
        {"scope": ("protocol/receipt", "legacy/unknown")},
    ),
    StageSpec(
        "review-discovery", ("prior-review-discovery",), ("scope",), ("review-profile", "review-candidates"),
        accepted_output_types={
            "review-profile": ("review-retrieval/profile",),
            "review-candidates": ("review-discovery/evidence",),
        },
        condition="when-evidence-synthesis-targeted",
    ),
    StageSpec("candidate-discovery", ("limited-seed-evidence",), ("scope",), ("candidates",)),
    StageSpec(
        "candidate-screening", (), ("candidates",), ("candidate-ledger",),
        accepted_output_types={"review-classification": ("review-classification/evidence",)},
    ),
    StageSpec("objective-evidence", ("mesh-exploration", "text-word-expansion"), ("candidate-ledger",), ("evidence",)),
    StageSpec("block-testing", ("pre-mesh-brainstorm",), ("evidence",), ("block-analysis",)),
    StageSpec(
        "validation", (), ("block-analysis",), ("validation",),
        accepted_output_types={"review-filter-evaluation": ("review-filter/evaluation",)},
    ),
    StageSpec("critic-review", (), ("validation",), ("critic",)),
    StageSpec("revision", (), ("critic",), ("revision",), condition="when-critic-revises"),
    StageSpec("final-qa", (), ("critic",), ("qa",)),
    StageSpec("audit-output", (), ("qa",), ("audit",), accepted_output_types={"audit": ("audit/evidence", "artifact/markdown")}),
    StageSpec("peer-review-handoff", (), ("audit",), ("handoff",), accepted_output_types={"handoff": ("artifact/markdown", "artifact/file", "workflow/receipt")}),
)

_BY_NAME = {name: spec for spec in CANONICAL_STAGES for name in (spec.id, *spec.aliases)}


def canonical_stage(name: str) -> StageSpec:
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        choices = ", ".join(spec.id for spec in CANONICAL_STAGES)
        raise ValueError(f"Unknown workflow stage {name!r}; choose one of: {choices}") from exc


def stage_statuses(state: dict[str, Any]) -> list[dict[str, Any]]:
    completed = set(state.get("completed_stages", []))
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    decisions = state.get("decisions") if isinstance(state.get("decisions"), dict) else {}
    context = state.get("workflow_context") if isinstance(state.get("workflow_context"), dict) else {}
    result = []
    for spec in CANONICAL_STAGES:
        if spec.id == "intake":
            question = decisions.get("question") if isinstance(decisions.get("question"), dict) else {}
            status = "complete" if question.get("status") == "resolved" else "pending"
        elif spec.condition == "when-evidence-synthesis-targeted":
            status = "complete" if spec.id in completed and all(role in artifacts for role in spec.required_output_roles) else (
                "pending" if context.get("evidence_synthesis_targeted") is True else "conditional"
            )
        elif spec.condition != "always" and spec.id not in completed:
            status = "conditional"
        elif spec.id in completed and all(role in artifacts for role in spec.required_output_roles):
            status = "complete"
        else:
            status = "pending"
        result.append({"id": spec.id, "status": status, "condition": spec.condition})
    return result


def completion_diagnostics(state: dict[str, Any]) -> list[Diagnostic]:
    """Backward-compatible wrapper around the named v2 gate registry."""

    from pubmed_search_builder.workflow.gates import evaluate_handoff

    return evaluate_handoff(state)


def render_contract_reference() -> str:
    """Render the committed workflow reference from the executable registry."""

    lines = [
        "# Executable Workflow Contract",
        "",
        "This file is generated from `pubmed_search_builder.workflow.stages`. Do not edit it manually.",
        "",
        "| Stage | Legacy aliases | Required inputs | Accepted input types | Required outputs | Accepted output types | Condition |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for spec in CANONICAL_STAGES:
        aliases = ", ".join(spec.aliases) or "—"
        inputs = ", ".join(spec.required_input_roles) or "—"
        outputs = ", ".join(spec.required_output_roles) or "—"
        input_types = "; ".join(f"{role}: {', '.join(types)}" for role, types in spec.accepted_input_types.items()) or "—"
        output_types = "; ".join(f"{role}: {', '.join(types)}" for role, types in spec.accepted_output_types.items()) or "—"
        lines.append(
            f"| `{spec.id}` | {aliases} | {inputs} | {input_types} | {outputs} | {output_types} | {spec.condition} |"
        )
    lines += [
        "",
        "## Protocol-driven conditional outputs",
        "",
        "| Protocol fact | Stage | Required output role |",
        "| --- | --- | --- |",
        "| no seed records | `candidate-discovery` | `pilot-saturation` |",
        "| evidence-synthesis target | `review-discovery` | `review-profile`, `review-candidates` |",
        "| evidence-synthesis target | `candidate-screening` | `review-classification` |",
        "| evidence-synthesis target | `validation` | `review-filter-evaluation` |",
        "| fragile essential concept | `block-testing` | `two-strand`, `screening-burden` |",
        "| enabled external validation | `validation` | `external-validation` |",
    ]
    return "\n".join(lines) + "\n"
