---
name: pubmed-search-builder
description: "Build, resume, or run a PRESS-informed internal review of high-sensitivity PubMed/MEDLINE Boolean search strategies for systematic reviews, scoping reviews, rapid reviews, evidence maps, and other evidence syntheses. Use when Codex must define searchable scope separately from screening criteria, expand MeSH and free-text vocabulary, discover and prescreen candidate relevant studies, test blocks and variants in PubMed, validate against seeds or a held-out set, run an internal critic/revision loop, and produce PRISMA-S-ready audit documentation. For reviews of an existing strategy, require an independent plain-language review question before inspecting its syntax so the draft cannot define its own scope. Do not use this skill to answer the evidence question."
---

# PubMed High-Sensitivity Search Builder

## Contract

Build a recall-first PubMed strategy and a reproducible audit trail. Keep three layers distinct:

1. **Conceptual scope** defines what the review is about, which eligibility elements are safe to search, and which belong at screening.
2. **Objective evidence** challenges that scope and vocabulary using prescreened records, MeSH/indexing, PubMed probes, and retrieval diagnostics.
3. **PRESS-informed internal QA** critiques the assembled draft and routes findings back to revision. It is not a substitute for human PRESS peer review.

Never let a seed set, candidate set, existing Boolean strategy, or retrieval count silently redefine eligibility.

## Intake Modes

### New build

Require an independently stated plain-language research/review question. If it is missing, ask only for it and stop. Once confirmed, ask once for optional known-relevant seed PMIDs. Seeds are useful but not required.

### Existing-strategy review or resumed build

Require the plain-language question before inspecting the supplied strategy. Treat its terms, blocks, filters, and line structure as review objects, never as scope evidence. If a prior audit and manifest exist, read them and resume from the latest resolved scope version and critic round.

Do not search PubMed or the web to answer the substantive evidence question. The deliverable is the strategy, empirical QA, and audit.

## Canonical Loop

1. **Lock conceptual scope.** Read `references/framework-selection.md`, `references/concept-analysis-and-gating.md`, and `references/anti-patterns.md`. Save a versioned retrieval-scope artifact before mining records. It must identify essential `AND` blocks, within-block term families, screening-only elements, optional/focused concepts, filters, ambiguities, and the user/protocol decisions that fixed them.
2. **Build a candidate evidence set.** Read `references/candidate-screening.md` and, when seeds exist, `references/seed-pmid-validation.md`. Discover candidates only after scope version 1 is locked. Prescreen candidates as include/exclude/uncertain before they can drive term mining. Keep user-confirmed seeds, screened-in discovery records, held-out validation records, and unscreened heuristic neighbors distinct.
3. **Build and probe.** Read `references/workflow.md` and load the tool, MeSH, title/abstract, wildcard, gap-analysis, filter, and no-seed references only when their stage is reached. After screening, run active vocabulary learning only within locked concepts; diagnose excluded records separately and route new concepts or eligibility interpretations through scope re-entry. Retest every accepted term against the frozen holdout when available and differential samples. Mine accepted discovery records, sweep MeSH, inspect PubMed translation, construct blocks, and run reversible diagnostic comparisons. When screened relevant records exist, calculate empirical fragility metrics for every block; preserve any human override only with a reason. Run automatic leave-one-block-out concept ablation for every strategy with two or more proposed `AND` blocks. Objective terms are candidates, not automatic additions.
4. **Critique, revise, and retest.** Read `references/press-critic.md`. Freeze the critic inputs with `critic_tool.py --build-bundle`, then run a fresh-context PRESS-informed critic against that evidence bundle. Use critic contract version 2: explicit evidence-referenced verdicts for every PRESS domain and stable finding IDs carried across rounds until resolved. Route lexical findings to the affected `OR` block; structural findings back through `AND`-block admission; scope findings to the user/protocol; filter findings to topic-only versus filtered comparison; and syntax findings to repair. Re-probe every affected branch. Repeat until no actionable finding remains open.
5. **Validate and hand off.** Validate against held-out relevant records when available; otherwise label reused-seed or heuristic checks as non-independent. For fragile topics, deliver a recall-first main strategy and a focused prioritization strategy by default; never let the focused strand replace the main search. Estimate screening burden from reproducible stratified labels and use it only to choose among variants that already meet the independent held-out recall requirement. Run final PubMed translation/hygiene checks, render the Markdown audit, save `run_manifest.json`, and flag the strategy for external human PRESS peer review.

Read `references/workflow.md` for the detailed sequence, re-entry rules, stop criteria, and tool-to-artifact requirements.

## User Interaction

Show only four concise user-facing markers: `Intake`, `Scope lock`, `Empirical build and critic loop`, and `Handoff`.

Stop only when a decision would change review scope, eligibility interpretation, or final adoption of a recall-reducing block, filter, or limit. Read-only PubMed probes and labelled variant comparisons may run without prior authorization; present their evidence before asking the user to adopt a narrowing design.

## Evidence Integrity

- No reviewed JSON, no decision: inspect saved `fetch`, `mine`, `sample`, candidate-ledger, and critic artifacts before using them as evidence.
- Use only screened-in discovery records for objective term mining.
- Allocate discovery and holdout roles deterministically in the candidate ledger before mining. Use ledger-native inputs so holdout records cannot flow into discovery commands. If reuse is unavoidable, state that validation is non-independent.
- Register executable stages through `scripts/workflow_tool.py`; it records return codes, scope versions, input/output hashes, and counts only after successful commands.
- Treat related-record and pilot-expansion recall as heuristic, never as absolute sensitivity.
- Do not overfit to seeds, pilots, filters, low counts, or PRESS-critic suggestions.
- Record scope changes explicitly; never mutate the meaning of a block under the same scope version.

## Completion Gate

For a completed build, save:

- versioned retrieval-scope, candidate-screening, strategy/block, probe, critic, and revision artifacts;
- the final Markdown audit, preferably `audit_<topic-slug>_YYYY-MM-DD.md`;
- the canonical append-only `run_manifest.json`.

Run `scripts/manifest_tool.py show --validate --check-files --require-complete-loop` before handoff. This combined gate must confirm resolved intake/scope decisions, candidate-screening status, per-block evidence, required validation, a passing final critic round, final QA, audit output, and no pending user question or must-fix finding.

Use `references/audit-template.md` and `scripts/audit_markdown.py` for the report. Do not imply that automated PRESS-informed QA is human PRESS peer review.

## Reference Routing

- `references/workflow.md` - canonical loop, re-entry paths, stop criteria, and artifact sequence.
- `references/framework-selection.md` - question type and framework selection.
- `references/concept-analysis-and-gating.md` - scope artifact, concept roles, fragility, and `AND`-block admission.
- `references/empirical-fragility.md` - measured fragility dimensions, classification, and reasoned human overrides.
- `references/concept-ablation-and-strands.md` - executable leave-one-block-out testing and two-strand fragile-topic delivery.
- `references/screening-burden.md` - reproducible stratified samples, precision intervals, workload estimates, and recall-gated variant selection.
- `references/candidate-screening.md` - candidate discovery, prescreening, discovery/holdout roles, and ledger schema.
- `references/active-vocabulary-learning.md` - iterative term extraction, excluded-record diagnosis, scope protection, and accepted-term retesting.
- `references/press-critic.md` - critic inputs, findings schema, routing, and pass criteria.
- `references/mesh-and-pubmed-tools.md` - bundled command usage and manifest operations.
- `references/tiab-expansion.md` - title/abstract expansion and objective term ranking.
- `references/bramer-reciprocal-gap-analysis.md` - reciprocal controlled-vocabulary/text-word gap checks.
- `references/validated-methodological-filters-and-hedges.md` - validated PubMed filters and translation safeguards.
- `references/seed-pmid-validation.md` - seeded discovery and validation.
- `references/no-seed-recall-estimation.md` - optional pilot-expansion heuristic.
- `references/audit-template.md` - audit and iteration-ledger structure.
- `references/goal-tracking.md` - `/goal` intake and completion rules.
