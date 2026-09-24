#!/usr/bin/env python3
"""Turn complete-loop gate issues into an ordered list of next actions.

The completion gate reports what is wrong as free text: close to two hundred distinct messages.
That tells a builder a check failed but not what to run next or which reference covers it, so a
long or resumed build had to reconstruct the workflow from the references. This module groups the
open issues by workflow stage, orders the stages the way a build proceeds, and attaches the
action, the commands, and the reference for each. It classifies issues; it never decides whether
the gate passes.
"""

from __future__ import annotations

import re
from typing import Any

# Each stage: stable id, what to do, the commands that do it, the reference that explains it,
# and the patterns that route a gate issue to it. Stages are listed in build order, which is the
# order actions are returned in. `route_order` below controls matching, where the more specific
# stages must win (a "critic round required revision" issue is a revision task, not a critic one).
STAGES: tuple[dict[str, Any], ...] = (
    {
        "stage": "manifest-integrity",
        "action": "Repair the run manifest: re-register missing or changed artifacts instead of editing hashes.",
        "commands": ["workflow_tool.py --manifest run_manifest.json --kind <kind> --output <artifact> -- <command>"],
        "reference": "references/mesh-and-pubmed-tools.md",
        "patterns": (r"^entry ", r"^superseded ", r"^missing top-level key", r"^duplicate entry"),
    },
    {
        "stage": "intake",
        "action": "Resolve the open intake gates, pending user question, or open manifest decisions.",
        "commands": ["manifest_tool.py state resolve-gate", "manifest_tool.py state set-question / clear-question"],
        "reference": "references/workflow.md (1. Intake)",
        "patterns": (r"gate is not resolved", r"unresolved user question", r"unresolved manifest decisions",
                     r"build_state not initialized: track stages", r"build_state not initialized;",
                     r"^build_state not initialized$"),
    },
    {
        "stage": "scope-lock",
        "action": "Validate, compile, and lock the review protocol, and register its essential blocks.",
        "commands": ["protocol_tool.py validate <protocol> --mode lock", "protocol_tool.py compile",
                     "manifest_tool.py state lock-protocol"],
        "reference": "references/protocol-dsl.md",
        "patterns": (r"retrieval scope is not locked", r"retrieval-scope artifact", r"dsl-locked scope",
                     r"registered essential blocks do not match", r"^protocol block ",
                     r"is not registered against the current scope version", r"no essential blocks registered",
                     r"protocol verification failed", r"build_state not initialized: register essential blocks with"),
    },
    {
        "stage": "protocol-binding",
        "action": "Re-run artifacts produced under an older protocol version so they bind to the current one.",
        "commands": ["re-run the named tool against the current protocol, then re-register its output"],
        "reference": "references/protocol-dsl.md (Scope changes)",
        "patterns": (r"does not match the current protocol$", r"lacks a protocol-bound json object"),
    },
    {
        "stage": "candidate-discovery",
        "action": "Complete no-seed orthogonal-pilot discovery to saturation and freeze roles, or record the user's decision.",
        "commands": ["no_seed_discovery.py discover", "no_seed_discovery.py adjudicate",
                     "manifest_tool.py state resolve-recall-offer", "manifest_tool.py state resolve-unvalidated-handoff"],
        "reference": "references/no-seed-recall-estimation.md",
        "patterns": (r"orthogonal-pilot", r"no-seed build", r"lacks the surfaced no-seed user decision",
                     r"no-seed recall", r"recall offer", r"recall check"),
    },
    {
        "stage": "candidate-screening",
        "action": "Finish evidence-backed screening, the independent re-screen and adjudication, then record the ledger.",
        "commands": ["screening_tool.py sample / replicate / agreement / to-ledger", "candidate_ledger.py",
                     "manifest_tool.py state record-candidate-screen"],
        "reference": "references/candidate-screening.md",
        "patterns": (r"candidate screening", r"candidate-screening", r"candidate ledger", r"candidate-ledger",
                     r"screening provenance", r"screening agreement", r"agreement check"),
    },
    {
        "stage": "block-evidence",
        "action": "Complete per-block MeSH, count, and reciprocal gap-analysis evidence, or record a reasoned waiver.",
        "commands": ["mesh_tool.py sweep --details", "pubmed_tool.py term-diff", "pubmed_tool.py term-rank",
                     "manifest_tool.py state waive-requirement"],
        "reference": "references/workflow.md (4. Build objective evidence and concept blocks)",
        "patterns": (r"^block .* missing ", r"bramer", r"build_state not initialized: register essential blocks and run"),
    },
    {
        "stage": "fragility",
        "action": "Score empirical fragility for every registered block.",
        "commands": ["strategy_analysis.py fragility-score"],
        "reference": "references/empirical-fragility.md",
        "patterns": (r"fragility-score",),
    },
    {
        "stage": "vocabulary-learning",
        "action": "Run vocabulary learning on newly included records, give every shortlisted term a reasoned disposition, and retest accepted terms.",
        "commands": ["vocabulary_learning.py extract", "vocabulary_learning.py retest"],
        "reference": "references/active-vocabulary-learning.md",
        "patterns": (r"vocabulary", r"excluded-record terminology"),
    },
    {
        "stage": "block-testing",
        "action": "Run concept ablation across the AND blocks and, for fragile topics, the two-strand and screening-burden comparisons.",
        "commands": ["strategy_analysis.py concept-ablation", "strategy_analysis.py two-strand",
                     "screening_burden.py sample / estimate"],
        "reference": "references/concept-ablation-and-strands.md; references/screening-burden.md",
        "patterns": (r"concept-ablation", r"two-strand", r"screening-burden", r"screening burden"),
    },
    {
        "stage": "external-validation",
        "action": "Complete the enabled trial-registry sentinel and resolve every eligible linked PubMed miss.",
        "commands": ["registry_sentinel.py"],
        "reference": "references/external-trial-registry-validation.md",
        "patterns": (r"external registry", r"external validation", r"external pubmed benchmark"),
    },
    {
        "stage": "validation",
        "action": "Run development validation against the current strategy and resolve every missed PMID.",
        "commands": ["pubmed_tool.py validate --candidate-ledger", "pubmed_tool.py recall"],
        "reference": "references/seed-pmid-validation.md; references/final-test-validation.md",
        "patterns": (r"required validation", r"seed/holdout validation", r"final-test result"),
    },
    {
        "stage": "revision",
        "action": "Revise the strategy for the critic's findings and record each revision with its no-harm check.",
        "commands": ["revision_guard.py", "manifest_tool.py state record-revision"],
        "reference": "references/no-harm-revisions.md",
        "patterns": (r"revision cycle", r"revision-cycle", r"required revision"),
    },
    {
        "stage": "critic",
        "action": "Build the critic evidence bundle, run the independent critic, validate it, and record the round.",
        "commands": ["critic_tool.py --build-bundle", "critic_tool.py --run-independent",
                     "critic_tool.py <critic_round.json> --output <validation.json>", "manifest_tool.py state record-critic"],
        "reference": "references/press-critic.md",
        "patterns": (r"critic",),
    },
    {
        "stage": "final-qa",
        "action": "Run final QA on the final strategy and a fresh uncached topic-only search bound to the same file.",
        "commands": ["hooks_tool.py final-qa", "pubmed_tool.py --no-cache search --query-file <strategy> --retmax 0",
                     "hooks_tool.py low-count-review"],
        "reference": "references/workflow.md (8. Final QA)",
        "patterns": (r"final qa", r"final-qa", r"final topic", r"hooks_tool", r"low-count"),
    },
    {
        "stage": "audit",
        "action": "Regenerate the audit scaffold from the manifest, complete it, render the Markdown audit, and register it.",
        "commands": ["pubmed_tool.py audit-scaffold --manifest run_manifest.json", "audit_markdown.py"],
        "reference": "references/audit-template.md; references/prisma-s-reporting.md",
        "patterns": (r"final audit", r"audit markdown", r"empirically-unvalidated handoff is not labelled"),
    },
)
OTHER_STAGE = {
    "stage": "other",
    "action": "Resolve these gate issues; see the workflow reference for the stage they belong to.",
    "commands": [],
    "reference": "references/workflow.md",
}
# Matching order: specific stages before the broad keyword stages that would otherwise claim them.
ROUTE_ORDER = (
    "manifest-integrity", "audit", "final-qa", "validation", "revision", "candidate-discovery",
    "intake", "scope-lock", "protocol-binding", "candidate-screening", "block-evidence", "fragility",
    "vocabulary-learning", "block-testing", "external-validation", "critic",
)
_BY_ID = {stage["stage"]: stage for stage in STAGES}
_COMPILED = [
    (stage_id, [re.compile(pattern, re.IGNORECASE) for pattern in _BY_ID[stage_id]["patterns"]])
    for stage_id in ROUTE_ORDER
]
# Prefixes `manifest_tool.py show` adds when it combines several gates into one issue list.
_PREFIX = re.compile(r"^(complete-loop gap|gap-analysis gap|coverage gap|not ready for handoff):\s*")


def classify_issue(issue: str) -> str:
    """Return the stage id an issue belongs to, or ``other``."""

    text = _PREFIX.sub("", str(issue))
    for stage_id, patterns in _COMPILED:
        if any(pattern.search(text) for pattern in patterns):
            return stage_id
    return "other"


def plan_next_actions(issues: list[str]) -> list[dict[str, Any]]:
    """Group gate issues into ordered actions; the first entry is the next thing to do."""

    grouped: dict[str, list[str]] = {}
    for issue in issues:
        grouped.setdefault(classify_issue(issue), []).append(_PREFIX.sub("", str(issue)))
    ordered = [stage for stage in STAGES if stage["stage"] in grouped]
    if "other" in grouped:
        ordered.append(OTHER_STAGE)
    return [
        {
            "order": index,
            "stage": stage["stage"],
            "action": stage["action"],
            "commands": list(stage["commands"]),
            "reference": stage["reference"],
            "issues": grouped[stage["stage"]],
        }
        for index, stage in enumerate(ordered, start=1)
    ]
