---
name: pubmed-search-builder
description: "Build high-sensitivity PubMed/MEDLINE Boolean search strategies for systematic reviews, scoping reviews, rapid reviews, evidence maps, narrative/evidence syntheses, and other evidence-synthesis searches. When invoked, interpret topic questions as strategy-building requests, ask for optional seed PMIDs first, and do not answer the evidence question by searching PubMed. Use for MeSH and free-text expansion, seed PMID validation, PRESS-style review, PRISMA-S reporting, and audit-ledger documentation."
license: MIT
metadata:
  version: "1.0.0"
---

# PubMed High-Sensitivity Search Builder

## Core Goal

Build high-sensitivity PubMed Boolean strategies for evidence syntheses from a topic or review question. Minimize missed relevant records. Precision is secondary, but noise should be tested, explained, and controlled when it can be controlled without damaging recall.

## Invocation Contract

When this skill is invoked, treat the user's topic or question as a request to build a PubMed search strategy. Do not answer clinical, epidemiological, prevalence, treatment, prognosis, or background questions by searching PubMed or the web for substantive answers. The deliverable is a documented Boolean strategy and audit trail.

If the prompt looks like an answerable evidence question, convert it into the plain-language review question for strategy building and begin the seed PMID intake. Evidence-answer synthesis belongs only in a separate non-skill follow-up outside this strategy-building workflow.

## First Response

At the start of a new strategy-building task, including when the skill is invoked with an answerable-looking question, ask once whether the user has known relevant seed PMIDs. Make clear that seeds are optional. If the user already provided seeds, do not ask again.

Pause and wait for the user's answer before MeSH/PubMed exploration, strategy drafting, topical answer searches, or the high-sensitivity concept-gate question. Continue only after the user supplies seed PMIDs, says they have no seeds, or explicitly asks to proceed without seeds. If seed PMIDs are supplied, limited seed fetch/mining is allowed before the concept gate solely to support concept analysis; do not run broader PubMed exploration, answer-finding searches, block testing, validation, variants, final QA, or filter checks before seed and concept-gate decisions are resolved.

## Required Input

Build only from an independently stated topic, review question, or protocol-style question that is understandable without pasted Boolean syntax.

- If the user provides a topic or review question, build the strategy from that question.
- After seed status is resolved, use supplied seed PMIDs or seed papers as optional validation and supporting evidence; do not overfit to them.
- If there are no seeds or the user asks to proceed without them, follow the no-seed workflow and state validation limits.
- If the user provides only Boolean syntax, a PubMed line set, a field-tagged query, or a strategy fragment without a topic/review question, ask for the topic or review question in plain language.
- If the user provides Boolean syntax along with a topic, ask them to provide or confirm the topic/review question without using the pasted strategy. Do not use pasted Boolean terms, operators, filters, or line structure as term evidence, logic evidence, hazard evidence, or review input.

## Canonical Workflow

Read `references/workflow.md` for the canonical build sequence, high-sensitivity mental model, tool-heavy build/test/validate flow, revision loop, final hygiene, stop criteria, audit Markdown handoff, and PRESS framing. Before MeSH lookup, read `references/concept-analysis-and-gating.md` for concept roles, seed/no-seed branches, the canonical concept-gate question, optional block/filter decisions, and pre-MeSH vocabulary/domain brainstorm rules.

Use `references/mesh-and-pubmed-tools.md` for bundled script usage and audit tooling. Load title/abstract expansion, wildcard, filter, seed-validation, PRISMA-S, and examples only when needed. If the user starts with `/goal` or asks for goal tracking, read `references/goal-tracking.md` for pre-goal intake rules.

## Stop Condition

Use the stop criteria in `references/workflow.md`; explicitly mark incomplete checks as `not performed`, `not available`, or `not applicable`.

## Output Format

For every completed strategy build, save a Markdown audit report in the user's working/output folder, preferably `audit_YYYY-MM-DD.md` or `audit_<topic-slug>_YYYY-MM-DD.md` if multiple searches may share a folder. If a matching file exists, do not overwrite it silently; choose a clear suffix or ask when overwriting would be ambiguous. Report the saved path in the final response and in `Reporting notes`.

Use `references/audit-template.md` as the final report structure. Include the final strategy, a decision ledger, user/protocol decisions, search-design decisions, accepted/rejected/deferred MeSH or SCR choices, term-expansion choices, optional block/filter/limit handling, variant choices, seed-validation decisions, and QA caveats. Do not invent audit details. Mark unsupported or incomplete checks as `not performed`, `not available`, or `not applicable`.

## References

- `references/workflow.md`: full workflow.
- `references/concept-analysis-and-gating.md`: concept ledger, seed/no-seed branches, roles, and gates.
- `references/goal-tracking.md`: `/goal` intake and state rules.
- `references/mesh-and-pubmed-tools.md`: bundled scripts.
- `references/validated-methodological-filters-and-hedges.md`: filters and hedges.
- `references/tiab-expansion.md`: title/abstract expansion.
- `references/wildcard-and-truncation.md`: wildcard risk.
- `references/seed-pmid-validation.md`: seed validation.
- `references/audit-template.md`: audit Markdown template.
- `references/prisma-s-reporting.md`: reporting notes.
- `references/examples.md`: examples.
