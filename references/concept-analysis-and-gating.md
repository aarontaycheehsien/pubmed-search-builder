# Concept Analysis And Gating

Use this step after the seed PMID decision is resolved and before MeSH lookup, broad PubMed exploration, or concept-block drafting. If supplied seed PMIDs are available after pre-gate seed triage, limited seed fetch/mining may happen immediately before the concept gate only to inform the concept-analysis ledger.

The purpose is to decide what belongs in the main high-sensitivity strategy, what belongs only inside an existing `OR` block, what should be omitted from the main search, and what requires a separate methodological filter decision.

Do not skip this step just because the topic looks straightforward. It is the main safeguard against turning every PICO element into a separate `AND` block.

Start this step with the **Concept gate** stage banner from `SKILL.md`, citing `references/framework-selection.md`, `references/concept-analysis-and-gating.md`, and `references/anti-patterns.md` as references in force. The stage banner must state that MeSH/PubMed exploration, block testing, optional secondary blocks, filters, focused variants, final QA, and audit output are not being done yet unless the gate and user/protocol decisions permit them.

## Required sequence

Use `workflow.md` as the canonical source for the full build sequence and high-sensitivity mental model.

The seed PMID decision is resolved when the user supplies seed PMIDs, says they have no seeds, or explicitly asks to proceed without seeds.

After seed status is resolved and seed PMIDs were supplied, run pre-gate seed triage from `seed-pmid-validation.md`. You may fetch/mine only usable found seed PMIDs before the concept gate to extract titles, abstracts, assigned MeSH, keywords, publication types, acronyms, and distinctive phrases for concept-role decisions. This limited seed work is not PubMed exploration, block testing, seed validation, variant comparison, final QA, or filter checking.

Before any MeSH lookup, broad PubMed exploration, block construction, filter check, focused variant, or full strategy validation, produce the pre-MeSH gate summary described below. Do not run MeSH lookup, broad PubMed exploration, block construction, final QA, filter checks, variants, optional secondary block tests, or full strategy validation before the required seed and concept-gate decisions are resolved. The only other exception is shallow parsing of the user's prompt so you can identify candidate concepts and required upfront decisions.

## Concept-analysis ledger

Record a concept-analysis ledger before drafting blocks. Keep it concise, but make it auditable.

Use these fields:

- `candidate_concept`: the concept, limit, or filter idea being considered
- `framework_slot`: the review-framework slot or custom role being considered, such as Population, Condition, Exposure, Phenomenon, Context, Outcome, Comparator, Study design, Limit, or `not applicable`
- `source`: user question, protocol text, seed record, pre-MeSH brainstorm, or inferred framework slot
- `role`: essential `AND` block, within-block synonym/term only, sensitivity-dangerous optional `AND` block, methodological/filter concept, or omitted concept
- `seed_evidence`: seed-derived title/abstract term, seed MeSH, seed keyword, seed publication type, in-scope seed retrieval concern, or `not available - no seed PMIDs supplied`
- `pre_gate_no_seed_evidence`: protocol/question wording, shallow framework parsing, pre-MeSH vocabulary/domain brainstorm needed for the gate, or `not applicable - seed evidence used`
- `post_gate_validation_evidence`: MeSH sweep, PubMed ATM/query translation, sample-record pattern, concept-block count, final QA, filter check, or `not performed`
- `scope_breadth_check`: for methodological or automation topics, whether the target is a narrow action or a broader workflow, with the reason
- `recall_risk`: why the concept could miss records if required, or `low` for truly essential concepts
- `and_block_admission`: pass, fail, deferred, or not applicable, with the specific reason
- `decision_needed`: whether user/protocol input is required before proceeding
- `question_asked_to_user`: exact user-facing question asked at the concept gate or later testing checkpoint, or `not asked`
- `user_or_protocol_decision`: include, omit, test as focused variant, use validated filter, or not yet resolved
- `final_handling`: main `AND` block, inside an existing `OR` block, reserve/focused variant, validated filter, omitted, or deferred

The ledger may begin as a compact table in the response or working notes, but its decisions must be carried forward into the final audit Markdown file's decision ledger. An optional audit workbook or other handoff artifact can supplement the Markdown audit file, but does not replace it.

If a candidate's role is optional secondary `AND` block, outcome block, safety block, filter/limit, or focused variant and it is materially plausible, default `decision_needed` to yes unless the protocol already fixes the decision.

Do not use pasted Boolean syntax, line numbers, field tags, filters, or prior strategy structure as a source of concept evidence. If the user supplied Boolean syntax, use only an independently confirmed plain-language topic or protocol question as the source for concept analysis.

## AND-block admission test

A candidate becomes an essential `AND` block only if all acceptance checks pass:

1. It is required for every in-scope record under the plain-language review question.
2. It names a searchable topic anchor, not only an eligibility-screening property.
3. It is broad and stable enough to search safely using MeSH and/or title/abstract coverage.
4. It is not merely an outcome, comparator, narrow setting, subgroup, mechanism, severity marker, service-use qualifier, or study-design preference.
5. It cannot be handled more safely inside an existing `OR` block, at screening, as a focused/reserve variant, or as a validated methodological filter.
6. No high-impact framework-slot ambiguity remains unresolved.
7. For methodological or automation topics, the scope breadth check does not show that a broader workflow concept is plausibly in scope.
8. If seed PMIDs were supplied, seed evidence does not suggest likely retrieval loss from inconsistent wording, indexing, publication type, or missing abstracts.

Default if uncertain: do not admit the candidate as a main `AND` block. Classify it as screening-only, omitted, deferred, reserve/focused-variant-only, or a filter decision, then record the recall risk.

Outcomes, comparators, narrow settings, demographic subgroups, and study-design concepts fail the admission test unless the user question or protocol makes them true topic anchors and the recall risk is explicitly accepted.

## Concept-gate pilot-test protocol

The concept gate has two phases. The first phase is mandatory before MeSH lookup; the second phase is scheduled for iterative testing after blocks exist.

### Phase 1 - pre-MeSH admission check

Before MeSH lookup or PubMed exploration:

1. Choose the review framework and extract candidate concepts from the plain-language question.
2. Run the PICO-slot ambiguity check below.
3. Run the scope breadth check below for methodological or automation topics.
4. Apply the AND-block admission test to each candidate concept.
5. Mark each candidate as a core required concept, within-block term family, screening-only concept, omitted concept, reserve/focused-variant candidate, or filter/limit decision.
6. Ask the user at the concept gate by default whenever a materially plausible optional secondary `AND` block, outcome block, safety block, filter/limit, or focused variant is identified unless the protocol already decides it. Also ask when needed to resolve a high-impact framework ambiguity.

This phase may use the user question, protocol wording, and limited seed fetch/mining when seed PMIDs were supplied. It must not run MeSH lookup, broad PubMed exploration, block construction, block testing, variants, final QA, or filter checks.

When no seed PMIDs are supplied, Phase 1 may use only protocol/question wording, shallow framework parsing, and any pre-MeSH vocabulary/domain brainstorm needed to decide whether a candidate is a core concept, term family, screening-only concept, omitted concept, reserve/focused concept, or filter/limit decision. Do not use MeSH sweeps, PubMed ATM/query translations, sample-record patterns, concept-block counts, final QA, or filter checks as pre-gate evidence.

### Phase 2 - post-block pilot checks

Phase 2 is allowed only after the Phase 1 gate is resolved and the user or protocol has authorized testing the optional secondary `AND` block, filter, limit, or focused variant, or after later testing reveals a materially sharper optional-block trade-off that now requires a user decision. After the admitted essential concept blocks have been built and tested, pilot any authorized material optional-block or filter trade-off before promoting it beyond reserve/focused status:

1. Compare the sensitive topic-only strategy with and without the optional concept or filter.
2. If seed PMIDs were supplied, test whether every in-scope seed is still retrieved.
3. Inspect count changes and, when useful, samples or labelled samples as workload evidence.
4. Treat counts as workload proxies, not precision, unless PMID-level relevance labels exist.
5. Keep the sensitive design as the default unless the focused/filter design preserves known-item retrieval, keeps MeSH plus text-word coverage for each essential concept, avoids PubMed parse hazards, and has an explicit user/protocol rationale.

If counts, seed behavior, or noise patterns reveal a meaningful optional-block or filter trade-off that was not obvious at the concept gate, pause and ask before testing or promoting that focused/filter variant. Do not re-ask when the user already answered at the concept gate unless the new evidence materially changes the decision context.

Record Phase 2 results in the search design ledger and final audit. Do not use Phase 2 as permission to run PubMed exploration before the Phase 1 gate is resolved, and do not use it to test unauthorized optional secondary blocks, filters, limits, or focused variants.

## Gate output contract

Before MeSH lookup, record a compact pre-MeSH gate summary containing:

- chosen framework, question type, and rationale
- whether a framework question was needed, and why or why not
- candidate concepts with framework slots and ambiguity grades
- scope breadth check for methodological or automation topics, including whether the main workflow concept is narrow or broad
- concepts admitted as core required search concepts
- concepts kept inside existing `OR` blocks as term families
- screening-only, omitted, deferred, reserve, or focused-variant concepts with recall-risk reasons
- optional concept offers: each materially plausible optional secondary `AND` block, outcome block, safety block, filter, limit, or focused variant, or `none identified`
- methodological filter or limit decisions needed before narrowing the strategy
- optional secondary `AND` blocks, outcome blocks, safety blocks, filters, limits, or focused variants that require user/protocol authorization before testing
- the one next user-facing question, if a human decision is required before proceeding

If no human decision is needed, state that the gate is resolved and continue to the pre-MeSH vocabulary/domain brainstorm.

## PICO-slot ambiguity check

Before role assignment, list any ambiguities about which framework slot each candidate concept belongs to, and grade impact as `low`, `medium`, or `high`.

Common high-impact ambiguities to check:

- Could the candidate be either Population or Outcome? Example: in a review of post-stroke depression, is depression the outcome of stroke or the population condition being studied?
- Could the candidate be either Intervention or Exposure? Example: is hormone replacement therapy an intervention (RCT framing) or an exposure (observational framing)?
- Could the question be Diagnostic accuracy or Screening effectiveness? These call for different frameworks (PIRD vs PICO) and different validated filters.
- Could what was classified as Population actually be a Condition that should anchor the search? Example: "adults with depression" - the search anchor is usually depression, with adults handled at screening unless the demographic is itself central to scope.

If any ambiguity is graded `high` and would change which concept enters the gate as an essential `AND` block, pause and ask the user before proceeding to MeSH lookup or block drafting. Do not silently commit to one interpretation. See `anti-patterns.md` Mistake 7 for the underlying failure mode.

## Scope breadth check for methodological and automation topics

Before role assignment for methodological or automation topics, ask: **Could this topic be represented as a broader workflow than the exact wording in the user question?**

Record whether the topic is:

- a narrow action, such as Boolean search-strategy formulation, query generation, or query translation
- a broader workflow, such as literature/database searching, screening, study selection, data extraction, synthesis, or evidence-synthesis conduct
- ambiguous, with a focused narrow variant and a broader recall-first main strategy both plausible

If the user says "recall first" and no seed PMIDs are available, default to the broader workflow concept unless the protocol explicitly narrows the review to the narrow action. Treat the narrow action language as a focused variant or within-block term family, not as the only main strategy, when broader workflow language is plausibly in scope.

For LLM/AI evidence-synthesis topics, explicitly consider whether each of these workflow areas is in scope before fixing the essential block: search strategy/query generation, literature/database searching, title/abstract screening, full-text screening, study selection, data extraction, risk of bias, synthesis, and review drafting.

If the scope is ambiguous and would change an essential `AND` block, pause and ask the user unless the user has already chosen recall-first with no seeds. In that no-seed recall-first case, continue with the broader workflow as the main strategy and document any narrower formulation/search-strategy-only query as a focused or reserve variant.

## Concept roles

Use these roles consistently:

- Essential `AND` block: a concept that must be present for a record to be in scope, and that is broad enough to search safely.
- Within-block synonym/term only: a synonym, acronym, spelling variant, MeSH entry term, subtype, device/procedure/drug name, proximity expression, or wildcard candidate that belongs inside an existing essential `OR` block.
- Sensitivity-dangerous optional `AND` block: a concept that may help precision or interpretation but could exclude relevant records if required.
- Methodological/filter concept: study design, evidence type, date, language, publication type, age group, species, humans-only, full-text, or another limit/filter.
- Omitted concept: a concept deliberately excluded from the main sensitive strategy to preserve recall.

Sensitivity-dangerous concepts include outcomes, comparators, mechanisms, mediators, moderators, barriers, facilitators, narrow settings, service-use qualifiers, disease severity, subgroup-only population limits, and ad hoc study-design terms. Outcomes and comparators in particular have empirically lower retrieval potential in PubMed and Embase ([Frandsen et al. 2020](https://doi.org/10.1016/j.jclinepi.2020.07.005)); two-block PICO searches retrieved more relevant systematic reviews than four-block searches ([Ho et al. 2016](https://doi.org/10.1371/journal.pone.0167170)).

Do not ask about ordinary term expansion that stays inside an existing `OR` block. Ask by default at the concept gate whenever a materially plausible optional secondary `AND` block, outcome block, safety block, filter, limit, or focused variant is identified, unless the protocol already decides it. During later testing, ask again only if new evidence materially changes the trade-off context.

## User-facing output labels

When summarising the concept-gate result to the user, the role taxonomy above may be too granular. Use these user-facing labels as a compact summary in the audit Markdown or final response:

| Internal role | User-facing label |
|---|---|
| Essential `AND` block | Core required search concept |
| Within-block synonym/term only | (do not surface; implicit in the `OR` block) |
| Sensitivity-dangerous optional `AND` block, tested as variant | Optional search concept |
| Sensitivity-dangerous optional, deferred to screening | Screening-only concept |
| Reserved/focused-variant-only | Separate search strand |
| Omitted concept | Not searched (with reason) |
| Methodological/filter concept | Filter (named source and version) |

The internal role taxonomy remains primary in the decision ledger; the user-facing labels are a presentation convention for the final summary.

## Pre-MeSH vocabulary/domain brainstorm

Run this step after the concept gate and before MeSH lookup when a concept is social-science, psychosocial, behavioral, qualitative, health-services, or otherwise weakly covered by controlled vocabulary. For straightforward biomedical concepts with stable MeSH and terminology, keep the step brief and document why no extended brainstorm was needed.

For concepts such as stigma, do not rely on MeSH language alone. Brainstorm disciplinary and author-language frames, including felt/enacted/anticipated/internalised stigma, public/self/structural stigma, minority stress, disclosure/concealment, help-seeking, unmet need, perceived need, access barriers, identity terms, and lived-experience wording where relevant.

Ask one concise user-facing domain-framing question before MeSH lookup when the brainstorm surfaces multiple plausible frames that could materially change the strategy:

```text
Before MeSH lookup, I see several possible vocabulary frames for this concept: [A], [B], [C]. Should the sensitive strategy include all as within-block synonyms, or should any be treated as separate optional/focused concepts?
```

Do not ask about ordinary synonyms that clearly stay inside an existing `OR` block. Do not turn adjacent constructs from the brainstorm into extra `AND` blocks unless the user or protocol confirms they are essential. Record accepted, rejected, and deferred vocabulary families in the concept-analysis ledger and final audit.

## With seed PMIDs

If seed PMIDs are supplied at the start of a strategy build:

1. Do not ask for seeds again.
2. Treat seed status as resolved.
3. Run pre-gate seed triage: normalize and deduplicate numeric PMIDs, document malformed and missing/not-found PMIDs, and exclude them from seed evidence unless corrected.
4. Use limited seed fetch/mining before the concept gate when usable found seed evidence would help classify concepts or filters.
4a. Optionally run `pubmed_tool.py related` to expand the confirmed seeds into a candidate relevant set and feed high-overlap candidates to `term-rank`. Use this only to enrich candidate evidence; label related-set evidence separately from user-confirmed seed evidence, classify any harvested term by concept role, and do not treat neighbor retrieval as validated recall. See `seed-pmid-validation.md`.
5. Pause before the concept gate only for fetched seeds that are retracted or clearly out of scope; ask whether to exclude, replace, or retain the PMID as a special validation seed.
6. Use seed records and the pre-MeSH brainstorm to inform the concept-analysis ledger before MeSH block construction.
7. Use seed titles, abstracts, MeSH headings, keywords, publication types, acronyms, and distinctive phrases as candidate evidence.
8. Classify seed-derived terms by concept role before adding them to the strategy.
9. Validate the final topic-only strategy against in-scope seeds.
10. If a methodological filter is used, validate topic-only and topic-plus-filter seed retrieval separately.

Seed PMIDs are validation aids, not the whole target set. Do not overfit the strategy to retrieve only the language used in a small seed set. If a seed is out of scope, report it rather than distorting the strategy.

## With no seed PMIDs

If the user says there are no seed PMIDs or asks to proceed without seeds:

1. Treat seed status as resolved.
2. Run the formal concept analysis and concept gate before MeSH/PubMed exploration.
3. In the ledger, mark seed evidence as `not available - no seed PMIDs supplied`.
4. Use pre-gate no-seed evidence only from protocol/question wording, shallow framework parsing, and pre-MeSH vocabulary/domain brainstorm needed for the gate.
5. For methodological or automation topics where recall-first is requested and the protocol does not explicitly narrow the scope, apply the scope breadth check and default the main workflow block to the broader workflow rather than only the exact narrow action wording.
6. After the gate resolves, record post-gate validation/audit evidence from MeSH sweeps, PubMed ATM/query translations, sample-record patterns, concept-block counts, objective term ranking from a high-precision pilot relevant-set query (`term-rank --relevant-query-file`), final QA, and filter checks where those steps were actually performed.
6a. Objective term discovery is available even without seeds. After the gate, build a small, deliberately high-precision pilot relevant-set query and feed it to `pubmed_tool.py term-rank --relevant-query-file` to rank candidate `[tiab]`/MeSH terms by coverage and lift instead of eyeballing them. Label results as pilot-relevant-set evidence, distinct from seed-derived evidence; treat them as term-discovery candidates, not validated recall, and do not overfit the strategy to pilot-query language. See `tiab-expansion.md` and `mesh-and-pubmed-tools.md`.
7. Do not report true seed-derived MeSH, seed-derived title/abstract terminology, known-item recall, or seed validation results.
8. State that validation is limited to MeSH checks, PubMed block testing, sample inspection, final query hygiene, `final-qa`, and `filter-check` where relevant. Objective term ranking against a pilot relevant set is available as term-discovery support, not recall validation; do not present it as known-item recall.

Sample-record MeSH patterns are not seed-derived evidence. Label them as sample-record patterns.

## Goal-tracked concept gates

When the prompt starts with `/goal` or the user asks for goal tracking, concept analysis is a pre-goal intake step whenever it requires human decisions. It is not a reason to start a goal early.

Use `goal-tracking.md` as the canonical reference for `/goal` state rules, the pre-goal decision sequence, blockers, completion audit, and objective wording.
