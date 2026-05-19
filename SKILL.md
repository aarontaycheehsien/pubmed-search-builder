---
name: pubmed-search-builder
description: "Build high-sensitivity PubMed/MEDLINE Boolean search strategies for systematic reviews, scoping reviews, rapid reviews, evidence maps, narrative/evidence syntheses, and other evidence-synthesis searches. When invoked, interpret topic questions as strategy-building requests, ask for optional seed PMIDs first, and do not answer the evidence question by searching PubMed. Use for MeSH and free-text expansion, seed PMID validation, PRESS-style review, PRISMA-S reporting, and audit-ledger documentation."
license: MIT
metadata:
  version: "1.0.0"
---

# PubMed High-Sensitivity Search Builder

## Core Goal

Build high-sensitivity PubMed Boolean strategies for evidence syntheses from a topic or review question. Minimize missed relevant records. Precision is secondary, but noise should be tested, explained, and controlled where it can be controlled without damaging recall.

## Invocation Contract

When this skill is invoked, always treat the user's topic or question as a request to build a PubMed search strategy. Do not answer the clinical, epidemiological, prevalence, treatment, prognosis, or background question by searching PubMed or the web for a substantive answer. The deliverable is a documented Boolean strategy and audit trail.

If the prompt looks like an answerable evidence question, convert it into the plain-language review question for strategy building and begin the seed PMID intake below. Only provide evidence-answer synthesis in a separate non-skill follow-up request outside this strategy-building workflow.

## First Response

At the start of a new strategy-building task, including when the skill is invoked with an answerable-looking question, ask once whether the user has known relevant seed PMIDs. Make clear that seeds are optional. If the user already provided seeds, do not ask again.

Pause and wait for the user's answer before running MeSH/PubMed exploration, drafting the strategy, searching PubMed for topical answers, or asking the high-sensitivity concept-gate question. Continue only after the user supplies seed PMIDs, says they have no seeds, or explicitly asks to proceed without seeds. If seed PMIDs are supplied, limited seed fetch/mining is allowed before the concept gate solely to populate seed evidence for concept analysis; do not run broader PubMed exploration, answer-finding searches, block testing, validation, variants, final QA, or filter checks before the seed and concept-gate decisions are resolved.

## Required Input

Build only from an independently stated topic, review question, or protocol-style question. The topic or review question must be understandable without relying on pasted Boolean syntax.

- If the user provides a topic or review question, build the strategy from that question.
- After seed status is resolved, use supplied seed PMIDs or seed papers as optional validation and supporting evidence; do not overfit to them.
- If the user confirms there are no seed PMIDs or explicitly asks to proceed without seeds, follow the no-seed workflow and state the validation limits.
- If the user provides only Boolean syntax, a PubMed line set, a field-tagged query, or a strategy fragment without a topic/review question, ask for the topic or review question in plain language.
- If the user provides Boolean syntax along with a topic, ask them to provide or confirm the topic/review question without using the pasted strategy. Do not use pasted Boolean terms, operators, filters, or line structure as term evidence, logic evidence, hazard evidence, or review input.

## Goal Tracking

If the user starts with `/goal` or asks for goal tracking, read `references/goal-tracking.md` for pre-goal intake rules.

## Canonical Workflow

Read `references/workflow.md` for the canonical build sequence, high-sensitivity mental model, tool-heavy build/test/validate flow, revision loop, final hygiene, stop criteria, audit Markdown handoff, and PRESS draft framing. Read `references/mesh-and-pubmed-tools.md` for bundled script usage.

## Concept Selection

Read `references/concept-analysis-and-gating.md` before MeSH lookup for concept roles, gates, ledgers, optional block/filter decisions, and pre-MeSH vocabulary/domain brainstorm rules.

## Build, Test, And Validate

Read `references/workflow.md` for build/test/validate flow; load the specific tool, tiab, wildcard, filter, and seed-validation references when those steps are reached.

## Stop Condition

Use the stop criteria in `references/workflow.md`; explicitly mark incomplete checks as `not performed`, `not available`, or `not applicable`.

## Output Format

Use the audit report template in `references/audit-template.md` for final outputs. For every completed strategy build, save the audit report as a Markdown file in the user's working/output folder, preferably named `audit_YYYY-MM-DD.md` or `audit_<topic-slug>_YYYY-MM-DD.md` if multiple searches may share a folder. If a file with that name already exists, do not overwrite it silently; choose a clear suffix or ask when overwriting would be ambiguous. Report the saved audit Markdown path in the final response and in the report's `Reporting notes`.

The audit Markdown file must include a decision ledger of decisions made during the build. Capture user/protocol decisions, agent search-design decisions, accepted/rejected/deferred MeSH or SCR choices, term-expansion choices, optional block/filter/limit handling, variant choice, seed-validation decisions, and QA caveats. Do not invent audit details. If a report item was not actually tested, cannot be supported by available data, or is outside PubMed scope, state `not performed`, `not available`, or `not applicable`.

When structured audit notes are available, prefer `scripts/audit_markdown.py` to write the Markdown audit file. For completed strategy builds, first save the structured notes as a UTF-8 audit JSON file, then pass that file path to `audit_markdown.py`; do not pipe large structured audit objects through stdin. Its default output is a compact JSON receipt with the saved path, byte count, placeholder count, and section count; do not print or paste the full audit report unless the user asks for it.

Read `references/audit-template.md` before drafting final outputs and use it as the audit Markdown structure.

## References

- `references/workflow.md`: full workflow.
- `references/concept-analysis-and-gating.md`: formal concept-analysis ledger, seed/no-seed branches, role definitions, and concept-gate pilot-test protocol.
- `references/goal-tracking.md`: `/goal` state rules, pre-goal intake sequence, blockers, completion audit, and objective wording.
- `references/mesh-and-pubmed-tools.md`: how to use the bundled scripts.
- `references/validated-methodological-filters-and-hedges.md`: validated filters and hedges.
- `references/tiab-expansion.md`: title/abstract expansion guidance.
- `references/wildcard-and-truncation.md`: wildcard risk and testing.
- `references/seed-pmid-validation.md`: seed validation workflow.
- `references/audit-template.md`: complete audit report Markdown template.
- `references/prisma-s-reporting.md`: reporting notes.
- `references/examples.md`: example patterns.
