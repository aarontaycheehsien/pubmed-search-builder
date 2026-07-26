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

When the protocol explicitly targets evidence syntheses, separately define eligible completed report types and the handling of protocols, narrative reviews, and methods papers. Read `references/evidence-synthesis-retrieval.md`; its profile branches are retrieval aids, never eligibility evidence, and every report candidate needs human classification against the locked protocol.

The default operating mode is `pubmed-only`: make no external registry calls and do not claim review-level completeness. When intervention trials are eligible and the protocol enables `pubmed-plus-external-validation`, read `references/external-trial-registry-validation.md` and run the registry sentinel only as an external PubMed leak check. Registry records never feed PubMed term mining.

When a structured review protocol is supplied, read `references/protocol-dsl.md`. Validate it in lock mode and compile it before any record or PubMed evidence is inspected. Treat the versioned protocol as the scope authority; generated ledgers and packets are derived artifacts, not alternate places to edit scope.

## Intake Modes

### New build

Require an independently stated plain-language research/review question. If it is missing, ask only for it and stop. Once confirmed, ask once for optional known-relevant seed PMIDs. Seeds are useful but not required.

If the user supplies `review_protocol*.json`, use its plain-language question and resolved decisions after `protocol_tool.py validate --mode lock` passes. Do not ask again about decisions already encoded in a valid locked protocol.

### Existing-strategy review or resumed build

Require the plain-language question before inspecting the supplied strategy. Treat its terms, blocks, filters, and line structure as review objects, never as scope evidence. If a prior audit and manifest exist, read them and resume from the latest resolved scope version and critic round.

Do not search PubMed or the web to answer the substantive evidence question. The deliverable is the strategy, empirical QA, and audit.

## Canonical Loop

1. **Lock conceptual scope.** Read `references/framework-selection.md`, `references/concept-analysis-and-gating.md`, and `references/anti-patterns.md`. When the question asks how well a method, tool, or technology performs a task in some application context, read `references/methods-evaluation-framework.md` and set `review.framework.profile_id` to `methods-evaluation`; its application context never converts the protocol into an evidence-synthesis retrieval target. Author, validate, and compile a versioned review-protocol DSL file before mining records. It is the locked source for essential `AND` blocks, within-block term families, screening-only elements, optional/focused concepts, filters, date boundaries, seed roles, priorities, and resolved decisions. Import a legacy retrieval-scope JSON only through `protocol_tool.py migrate-scope`.
2. **Build a candidate evidence set.** Read `references/candidate-screening.md` and, when seeds exist, `references/seed-pmid-validation.md`. Discover candidates only after scope version 1 is locked. Screen candidates with `scripts/screening_tool.py` against a rubric compiled from the locked protocol before they can drive term mining: every criterion gets an explicit verdict, evidence is quoted verbatim from the hash-bound record, unresolved criteria force `uncertain`, and a rule-only decision cannot supply a discovery or holdout record without adjudication. When evidence syntheses are eligible, also compile the scoped review-retrieval profile, classify every report candidate, and evaluate the final strategy by eligible report type. Keep user-confirmed seeds, screened-in discovery records, held-out validation records, review-report candidates, and unscreened heuristic neighbors distinct.
3. **Build and probe.** Read `references/workflow.md` and load the tool, MeSH, title/abstract, wildcard, gap-analysis, filter, and no-seed references only when their stage is reached. After screening, run active vocabulary learning only within locked concepts; diagnose excluded records separately and route new concepts or eligibility interpretations through scope re-entry. Retest every accepted term against the frozen holdout when available and differential samples. Mine accepted discovery records, sweep MeSH, inspect PubMed translation, construct blocks, and run reversible diagnostic comparisons. When screened relevant records exist, calculate empirical fragility metrics for every block; preserve any human override only with a reason. Run automatic leave-one-block-out concept ablation for every strategy with two or more proposed `AND` blocks. Objective terms are candidates, not automatic additions.
4. **Critique, revise, and retest.** Read `references/press-critic.md` and `references/no-harm-revisions.md`. Freeze the critic inputs with `critic_tool.py --build-bundle`, then use `critic_tool.py --run-independent` to launch a schema-constrained fresh-context child critic against only that bundle. Same-context, manually authored critic rounds do not satisfy handoff. Use critic contract version 2: explicit evidence-referenced verdicts for every PRESS domain and stable finding IDs carried across rounds until resolved. Route lexical findings to the affected `OR` block; structural findings back through `AND`-block admission; scope findings to the user/protocol; filter findings to topic-only versus filtered comparison; and syntax findings to repair. Before adoption, prove the named defect is fixed, held-out retrieval is preserved, required blocks remain justified, syntax/translation is stable, scope is unchanged or explicitly versioned, and before/after workload is recorded. Automatically keep the baseline authoritative when any check fails; retain a failing change only as a labelled experimental variant. Re-probe every affected branch. Repeat until no actionable finding remains open.
5. **Validate and hand off.** Validate against held-out relevant records when available; otherwise label reused-seed or heuristic checks as non-independent. If external validation is enabled, screen registry trials separately, link publications, and test only eligible linked PubMed PMIDs against the final strategy. For fragile topics, deliver a recall-first main strategy and a focused prioritization strategy by default; never let the focused strand replace the main search. Estimate screening burden from reproducible stratified labels and use it only to choose among variants that already meet the independent held-out recall requirement. Run final PubMed translation/hygiene checks, render the Markdown audit, save `run_manifest.json`, and flag the strategy for external human PRESS peer review.

Read `references/workflow.md` for the detailed sequence, re-entry rules, stop criteria, and tool-to-artifact requirements.

## User Interaction

Show only four concise user-facing markers: `Intake`, `Scope lock`, `Empirical build and critic loop`, and `Handoff`.

Stop only when a decision would change review scope, eligibility interpretation, or final adoption of a recall-reducing block, filter, or limit. Read-only PubMed probes and labelled variant comparisons may run without prior authorization; present their evidence before asking the user to adopt a narrowing design.

Also stop early when no-seed discovery yields an empty or thin screened-in set (the adjudicator emits `saturation_gate.user_decision`). Surface it verbatim — what happened, the measured topic volume, and the choices (supply seeds, name adjacent reviews to benchmark against, repair the pilots, or accept an empirically-unvalidated search) — and let the user choose before continuing. Proceeding with an unvalidated search is the user's adoption-confidence decision, not a silent fallback deferred to the final peer-review label.

When no-seed discovery screens in relevant records but no external benchmark exists, the adjudicator computes an internal pilot-convergence diagnostic (`internal_convergence_diagnostic`; deprecated command name `no_seed_discovery.py recapture`). The pilot families are dependent and are not capture occasions: never report Chao1/Chao2, an unseen-population estimate, or completeness. Frequent re-finding is weak internal evidence; a high unique eligible yield raises a recall-risk flag. The diagnostic never resolves saturation or a completion gate. See `references/no-seed-recall-estimation.md`.

When the user names adjacent or prior systematic reviews (the `name-adjacent-reviews` option in the decision, or in response to a `recall_risk`), build a semi-independent benchmark from them: `no_seed_discovery.py benchmark-harvest` (cited references and/or an included-study PMID list) → screen the candidates against the locked scope → `benchmark-freeze` → `pubmed_tool.py recall --benchmark-json`. It is non-independent and external (imports the prior review's scope bias), never a gold standard; benchmark records must not feed term mining, and low recall is a real leak signal while high recall is weak positive evidence.

## Evidence Integrity

- No reviewed JSON, no decision: inspect saved `fetch`, `mine`, `sample`, candidate-ledger, and critic artifacts before using them as evidence.
- Use only screened-in discovery records for objective term mining.
- A screening decision must be supported by the record, not merely accompanied by a reason string. Every discovery/holdout record carries a rubric hash, a record-content hash, quoted evidence, and how the decision was made. Verified quotation shows the text exists, not that it supports the verdict, so an independent re-screening of a decision-stratified sample is required and its disagreements and evidence divergences must be adjudicated.
- Allocate discovery and holdout roles deterministically in the candidate ledger before mining. Use ledger-native inputs so holdout records cannot flow into discovery commands. If reuse is unavoidable, state that validation is non-independent.
- Register executable stages through `scripts/workflow_tool.py`; it records return codes, scope versions, input/output hashes, and counts only after successful commands.
- Treat related-record and pilot-expansion recall as heuristic, never as absolute sensitivity.
- Do not overfit to seeds, pilots, filters, low counts, or PRESS-critic suggestions.
- Record scope changes explicitly; never mutate the meaning of a block under the same scope version.
- A report-level profile is not a validated universal filter: preserve its NLM source snapshot, branch indexing limitations, human classifications, and per-type retrieval misses.

## Completion Gate

For a completed build, save:

- the locked review protocol and compile receipt when the DSL was used;
- versioned retrieval-scope, candidate-screening, strategy/block, probe, critic, and revision artifacts;
- the final Markdown audit, preferably `audit_<topic-slug>_YYYY-MM-DD.md`;
- the canonical append-only `run_manifest.json`.

Run `scripts/manifest_tool.py show --validate --check-files --require-complete-loop` before handoff. This combined gate must confirm resolved intake/scope decisions, candidate-screening status, per-block evidence, required validation, a passing final critic round, final QA, audit output, and no pending user question or must-fix finding.

In `pubmed-plus-external-validation` mode, also require completed/declined/unavailable status for every enabled registry source, complete trial screening and publication linking, evaluation of all eligible linked PubMed PMIDs, and resolution of every PubMed miss. In `pubmed-only` mode, no registry artifact is required; the audit must state that review-level completeness was not assessed.

When `evidence_target.mode` is `evidence-syntheses` or `mixed`, the conditional review-discovery gate additionally requires the profile, report candidates, complete classifications, and review retrieval evaluation before handoff.

Use `references/audit-template.md` and `scripts/audit_markdown.py` for the report. Do not imply that automated PRESS-informed QA is human PRESS peer review.

## Reference Routing

- `references/protocol-dsl.md` - versioned review-protocol authoring, validation, compilation, verification, and legacy migration.
- `references/workflow.md` - canonical loop, re-entry paths, stop criteria, and artifact sequence.
- `references/workflow-contracts.md` - generated stage aliases, typed input/output roles, and executable conditions.
- `references/framework-selection.md` - question type and framework selection.
- `references/methods-evaluation-framework.md` - method/tool performance-evaluation profile, canonical slots, ambiguity check, and evidence-target rule.
- `references/concept-analysis-and-gating.md` - scope artifact, concept roles, fragility, and `AND`-block admission.
- `references/empirical-fragility.md` - measured fragility dimensions, classification, and reasoned human overrides.
- `references/concept-ablation-and-strands.md` - executable leave-one-block-out testing and two-strand fragile-topic delivery.
- `references/screening-burden.md` - reproducible stratified samples, precision intervals, workload estimates, and recall-gated variant selection.
- `references/candidate-screening.md` - candidate discovery, criterion-level evidence-backed screening, discovery/holdout roles, and ledger schema.
- `references/active-vocabulary-learning.md` - iterative term extraction, excluded-record diagnosis, scope protection, and accepted-term retesting.
- `references/no-harm-revisions.md` - mandatory revision checks, automatic baseline fallback, and experimental-only retention.
- `references/press-critic.md` - critic inputs, findings schema, routing, and pass criteria.
- `references/mesh-and-pubmed-tools.md` - bundled command usage and manifest operations.
- `references/tiab-expansion.md` - title/abstract expansion and objective term ranking.
- `references/bramer-reciprocal-gap-analysis.md` - reciprocal controlled-vocabulary/text-word gap checks.
- `references/validated-methodological-filters-and-hedges.md` - validated PubMed filters and translation safeguards.
- `references/evidence-synthesis-retrieval.md` - scope-bound systematic-review/meta-analysis retrieval, classification, source snapshots, and benchmark tiers.
- `references/seed-pmid-validation.md` - seeded discovery and validation.
- `references/no-seed-recall-estimation.md` - optional pilot-expansion heuristic.
- `references/external-trial-registry-validation.md` - optional registry sentinel for external PubMed leak detection.
- `references/audit-template.md` - audit and iteration-ledger structure.
- `references/goal-tracking.md` - `/goal` intake and completion rules.
