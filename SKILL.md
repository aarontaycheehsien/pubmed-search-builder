---
name: pubmed-search-builder
description: "Build high-sensitivity PubMed/MEDLINE Boolean search strategies for systematic reviews, scoping reviews, rapid reviews, evidence maps, narrative/evidence syntheses, and other evidence-synthesis searches. When invoked, interpret topic questions as strategy-building requests, require a plain-language research/review question before asking for optional seed PMIDs, and do not answer the evidence question by searching PubMed. Never accept user-entered Boolean syntax, PubMed line sets, field-tagged queries, or strategy fragments as build input. Use for MeSH and free-text expansion, seed PMID validation, PRESS-style QA, PRISMA-S reporting, and audit-ledger documentation."
license: MIT
metadata:
  version: "1.0.0"
---

# PubMed High-Sensitivity Search Builder

## Core Goal

Build high-sensitivity PubMed Boolean strategies for evidence syntheses from a topic or review question. Minimize missed relevant records; precision is secondary, but noise should be tested and controlled where that does not damage recall.

When this skill is invoked, treat the user's topic or question as a request to build a PubMed search strategy, even when it looks like an answerable clinical, epidemiological, prevalence, treatment, prognosis, or background question. Do not answer it by searching PubMed or the web; the deliverable is a documented Boolean strategy and audit trail. Provide substantive evidence answers only in a separate non-skill follow-up.

## First Response

At the start of a new strategy-building task, including when the skill is invoked with an answerable-looking question, first require an independently stated plain-language research/review question or protocol-style question. If the user has not supplied one, ask only for the research/review question and stop.

After the plain-language research/review question is confirmed, ask once whether the user has known relevant seed PMIDs. Make clear that seeds are optional. If the user already provided seeds, do not ask again. Pause and wait for the user's answer before running MeSH/PubMed exploration, drafting the strategy, searching PubMed for topical answers, or asking the concept-gate question.

Seed gate policy: if the user has no seeds or asks to proceed without seeds, follow the no-seed workflow and state the validation limits. If seed PMIDs are supplied, normalize and deduplicate numeric PMIDs, document malformed entries and not-found PMIDs, and run only limited pre-gate seed fetch/mining of found records to populate seed evidence for concept analysis. Proceed past malformed or not-found PMIDs after documenting their exclusion. Pause before the concept gate only when a fetched seed is retracted or appears materially out of scope; then ask only whether to exclude it, replace it, or retain it as a special validation seed. Do not run broader PubMed exploration, block testing, validation, variants, final QA, or filter checks before the seed and concept-gate decisions are resolved. See `references/seed-pmid-validation.md`.

## Stage Reporting Contract

State a concise user-facing stage report before each major workflow transition, at one of two levels. **Decision-gate stages** - initial question intake, seed PMID intake, the concept gate, and any stage where a user/protocol decision is needed - require a full stage banner with all six fields below. **Other transitions** require only a one-line stage marker naming the stage and the governing reference files, unless a user decision arises (then promote to a full banner).

A full stage banner includes these fields:

- `Stage`: name the current stage from `references/workflow.md`.
- `Reference(s) in force`: cite the exact governing reference files, such as `references/workflow.md`, `references/framework-selection.md`, `references/concept-analysis-and-gating.md`, `references/mesh-and-pubmed-tools.md`, `references/seed-pmid-validation.md`, or `references/audit-template.md`.
- `Doing now`: the work about to happen in this stage.
- `Allowed now`: actions allowed by the governing references at this point.
- `Not doing yet`: actions blocked until a later stage or user/protocol decision.
- `User decision needed`: the exact unresolved user/protocol question, or `none`.

Keep banners short. At the concept gate, always include an explicit optional-concept-offers summary, even if it says none were identified. When materially plausible optional secondary blocks, outcome blocks, safety blocks, filters, limits, or focused variants are present, the `User decision needed` line must name them explicitly. When a stage banner says a user decision is needed, ask only that decision and stop.

## Required Input

Build only from an independently stated topic, review question, or protocol-style question, understandable without pasted Boolean syntax.

- If the user provides a topic or review question, build the strategy from that question.
- After seed status is resolved, use supplied seed PMIDs or seed papers as optional validation and supporting evidence; do not overfit to them.
- If the user confirms there are no seed PMIDs or explicitly asks to proceed without seeds, follow the no-seed workflow and state the validation limits.
- If the user provides only Boolean syntax, a PubMed line set, a field-tagged query, or a strategy fragment without a topic/review question, ask only for the topic or review question in plain language. Do not ask for seed PMIDs in the same response.
- If the user provides Boolean syntax along with possible prose or topic context, ignore the pasted syntax and ask them to restate or confirm the topic/review question in plain language before asking for seed PMIDs.
- Never use pasted Boolean terms, operators, filters, line numbers, field tags, or line structure as term evidence, logic evidence, scope evidence, hazard evidence, or review input.

## Goal Tracking

If the user starts with `/goal` or asks for goal tracking, read `references/goal-tracking.md` for pre-goal intake rules.

## Canonical Workflow

Read `references/workflow.md` for the canonical build sequence, high-sensitivity mental model, tool-heavy build/test/validate flow, revision loop, final hygiene, stop criteria, and audit handoff. Read `references/framework-selection.md` before extracting candidate slots: the default LLM behaviour is to force every question into PICO, which often reduces recall for exposure-based (PECO), qualitative (PICo/SPIDER), diagnostic (PIRD), or scoping (PCC) questions. Read `references/mesh-and-pubmed-tools.md` for bundled script usage.

## Concept Selection

Read `references/concept-analysis-and-gating.md` before MeSH lookup for concept roles, gates, ledgers, seed/no-seed branches, optional block/filter decisions, and the pre-MeSH vocabulary/domain brainstorm. Read `references/anti-patterns.md` for catalogued failure modes (PICO-as-template, default outcomes/comparators, overfitting to seeds, ignoring failed retrieval, silent committal on ambiguous questions, one-shot Boolean) that the concept gate must guard against.

## Build, Test, And Validate

Read `references/workflow.md` for the build/test/validate flow; load the specific tool, tiab, wildcard, Bramer gap-analysis, filter, and seed-validation references when those steps are reached. `fetch`, `mine`, and `sample` are record-content commands: they require `--output` and print only a receipt; a stray `--summary` is tolerated as a no-op (noted in the receipt), not a hard error. Inspect the saved JSON, including abstracts where available, before recording any relevance, scope, noise, term-discovery, or concept-role decision. Compact output is appropriate for count, translation, validation, recall, variant, related-record, and term-rank dashboards.

## Stop Condition

Use the stop criteria in `references/workflow.md`; explicitly mark incomplete checks as `not performed`, `not available`, or `not applicable`.

## Output Format

For every completed strategy build, save the audit report as a Markdown file in the user's working/output folder, preferably named `audit_YYYY-MM-DD.md` or `audit_<topic-slug>_YYYY-MM-DD.md`. If a file with that name already exists, do not overwrite it silently; choose a clear suffix or ask. The audit must include a decision ledger of the user/protocol and search-design decisions made during the build; do not invent audit details, and mark untested or unsupported items as `not performed`, `not available`, or `not applicable`. Prefer `scripts/audit_markdown.py` (optionally seeded by `pubmed_tool.py audit-scaffold`) to render the report from a saved audit JSON file, and read `references/audit-template.md` for the audit structure. With a `concept_blocks` list the renderer also emits a numbered PubMed line set and a PRISMA-S appendix; `--emit-appendix <path>` writes those as a standalone paste-ready file.

Final-strategy handoff rule: whenever a final PubMed search strategy has been generated or presented, explicitly offer the complete Markdown audit file if it has not already been generated. For completed builds, generate and save the audit Markdown by default rather than leaving it as an offer. If the user asked only for the strategy or the workflow is paused before audit output, ask one concise question offering to generate the complete audit Markdown documenting every workflow stage, user/protocol decision, search-design decision, evidence file reviewed, and rationale. Do not claim the audit file exists until it has been saved.

Also save a canonical `run_manifest.json` with `scripts/manifest_tool.py`: an append-only provenance ledger that records every command run, its output path, the date, the result count, and any superseded file. Run `manifest_tool.py show --validate --check-files --require-ready` before finishing - the binding handoff gate that exits non-zero unless the build-state concept gate is resolved and no user question is pending - then report both the saved audit Markdown path and the `run_manifest.json` path in the final response. Also run the opt-in per-block coverage check (`state coverage` / `show --require-coverage`) so every essential block has a recorded MeSH sweep and block count, or a reasoned waiver; see `references/mesh-and-pubmed-tools.md`. On a no-seed build, offer the optional heuristic recall check at the Validation stage and record its outcome (`state resolve-recall-offer`; opt-in gate `show --require-recall-offer`); see `references/no-seed-recall-estimation.md`.

## References

- `references/workflow.md` - full build sequence, mental model, and stop criteria.
- `references/framework-selection.md` - question-type-to-framework selection table.
- `references/concept-analysis-and-gating.md` - concept-analysis ledger, concept gate, and seed/no-seed branches.
- `references/anti-patterns.md` - catalogued LLM failure modes with literature anchors.
- `references/goal-tracking.md` - `/goal` pre-goal intake and state rules.
- `references/mesh-and-pubmed-tools.md` - bundled script usage and the tool-to-stage map.
- `references/tiab-expansion.md` - title/abstract expansion and objective term ranking.
- `references/wildcard-and-truncation.md` - wildcard safety and the 600-variant cap.
- `references/bramer-reciprocal-gap-analysis.md` - conditional controlled-vocabulary/text-word gap analysis.
- `references/seed-pmid-validation.md` - seed PMID validation workflow.
- `references/no-seed-recall-estimation.md` - optional no-seed heuristic recall check (pilot → related → recall).
- `references/validated-methodological-filters-and-hedges.md` - validated filters and hedges.
- `references/prisma-s-reporting.md` - PRISMA-S reporting notes.
- `references/audit-template.md` - complete audit report Markdown template.
- `references/examples.md` - example search-strategy patterns.
