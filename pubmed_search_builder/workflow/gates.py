"""Named, composable handoff predicates for workflow-v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pubmed_search_builder.core.diagnostics import Diagnostic


@dataclass(frozen=True)
class GatePredicate:
    id: str
    evaluate: Callable[[dict[str, Any]], list[Diagnostic]]


def _question_resolved(state: dict[str, Any]) -> list[Diagnostic]:
    decisions = state.get("decisions") if isinstance(state.get("decisions"), dict) else {}
    question = decisions.get("question") if isinstance(decisions.get("question"), dict) else {}
    if question.get("status") == "resolved":
        return []
    return [Diagnostic("workflow.intake.question_pending", "The review question decision is unresolved.", stage="intake")]


def _no_pending_decisions(state: dict[str, Any]) -> list[Diagnostic]:
    decisions = state.get("decisions") if isinstance(state.get("decisions"), dict) else {}
    return [
        Diagnostic("workflow.decision.pending", f"Decision {decision_id!r} is still pending.", stage="intake")
        for decision_id, decision in decisions.items()
        if isinstance(decision, dict) and decision.get("status") == "pending"
    ]


def _required_stage_outputs(state: dict[str, Any]) -> list[Diagnostic]:
    # Imported lazily to keep the stage registry independent of this evaluator.
    from pubmed_search_builder.workflow.stages import CANONICAL_STAGES

    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    diagnostics: list[Diagnostic] = []
    for spec in CANONICAL_STAGES:
        if spec.condition != "always":
            continue
        for role in spec.required_output_roles:
            if role not in artifacts:
                diagnostics.append(
                    Diagnostic(
                        "workflow.stage.output_missing",
                        f"Stage {spec.id} lacks required active output role {role!r}.",
                        stage=spec.id,
                    )
                )
    return diagnostics


def _conditional_outputs(state: dict[str, Any]) -> list[Diagnostic]:
    context = state.get("workflow_context") if isinstance(state.get("workflow_context"), dict) else {}
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    requirements: list[tuple[str, str, str]] = []
    if context.get("no_seed_build") is True:
        requirements.append(("candidate-discovery", "pilot-saturation", "no-seed discovery"))
    if context.get("evidence_synthesis_targeted") is True:
        requirements.extend(
            [
                ("review-discovery", "review-profile", "evidence-synthesis retrieval profile"),
                ("review-discovery", "review-candidates", "evidence-synthesis candidate discovery"),
                ("candidate-screening", "review-classification", "review candidate classification"),
                ("validation", "review-filter-evaluation", "evidence-synthesis filter evaluation"),
            ]
        )
    if context.get("fragile_topic") is True:
        requirements.extend(
            [
                ("block-testing", "two-strand", "fragile-topic two-strand analysis"),
                ("block-testing", "screening-burden", "fragile-topic screening burden"),
            ]
        )
    if context.get("external_validation_enabled") is True:
        requirements.append(("validation", "external-validation", "external PubMed leak validation"))
    return [
        Diagnostic(
            "workflow.conditional_output_missing",
            f"Protocol requires {label}, but active output role {role!r} is missing.",
            stage=stage,
        )
        for stage, role, label in requirements
        if role not in artifacts
    ]


def _no_stale_artifacts(state: dict[str, Any]) -> list[Diagnostic]:
    count = state.get("stale_artifact_count", 0)
    if not count:
        return []
    return [Diagnostic("workflow.artifact.stale", f"{count} artifact(s) belong to an older scope version.")]


PREDICATES = (
    GatePredicate("question-resolved", _question_resolved),
    GatePredicate("no-pending-decisions", _no_pending_decisions),
    GatePredicate("required-stage-outputs", _required_stage_outputs),
    GatePredicate("conditional-outputs", _conditional_outputs),
    GatePredicate("no-stale-artifacts", _no_stale_artifacts),
)


def evaluate_handoff(state: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for predicate in PREDICATES:
        diagnostics.extend(predicate.evaluate(state))
    return diagnostics
