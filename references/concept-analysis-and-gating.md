# Concept Analysis And Gating

Use this step after the plain-language question and seed-status decision are resolved, but before fetching or mining seed/candidate records, MeSH lookup, PubMed exploration, or concept-block drafting. Save a lock-valid review protocol version 1 from question/protocol evidence alone so objective evidence can challenge a visible baseline rather than silently shaping it.

The purpose is to decide what belongs in the main high-sensitivity strategy, what belongs only inside an existing `OR` block, what should be omitted from the main search, and what requires a separate methodological filter decision.

Do not skip this step just because the topic looks straightforward. It is the main safeguard against turning every PICO element into a separate `AND` block.

Start this step with the concise **Scope lock** marker from `SKILL.md`. State only the unresolved scope decision, if any. Keep detailed stage/reference tracking in the manifest rather than exposing internal file names to the user.

## Required sequence

Use `workflow.md` as the canonical source for the full build sequence and high-sensitivity mental model.

The seed PMID decision is resolved when the user supplies PMIDs, says there are none, or explicitly asks to proceed without them. Before scope version 1 is locked, normalize supplied identifiers only; do not fetch, mine, expand, or inspect record content.

Produce the scope-lock summary, validate `review_protocol_v1.json` in lock mode, compile its derived artifacts, and lock it before any record fetch, MeSH lookup, PubMed exploration, block construction, filter check, focused variant, or validation. Objective evidence enters only after this baseline exists.

## Concept-analysis ledger

Record a concept-analysis ledger before drafting blocks. Keep it concise, but make it auditable.

Use these fields:

- `scope_version`: positive integer; start at `1` and increment only after a structural or scope re-entry.
- `candidate_concept`: the concept, limit, or filter idea being considered
- `framework_slot`: the review-framework slot or custom role being considered, such as Population, Condition, Exposure, Phenomenon, Context, Outcome, Comparator, Study design, Limit, or `not applicable`
- `source`: user question, protocol text, seed record, pre-MeSH brainstorm, or inferred framework slot
- `role`: essential `AND` block, within-block synonym/term only, sensitivity-dangerous optional `AND` block, methodological/filter concept, or omitted concept
- `conceptual_evidence`: protocol/question wording, framework reasoning, and scope assumptions used for the initial lock
- `objective_evidence`: screened-in discovery records, MeSH/ATM evidence, counts, samples, or validation evidence added after scope lock, or `not performed`
- `post_gate_validation_evidence`: MeSH sweep, PubMed ATM/query translation, sample-record pattern, concept-block count, final QA, filter check, or `not performed`
- `scope_breadth_check`: for methodological or automation topics, whether the target is a narrow action or a broader workflow, with the reason
- `fragility_status`: `stable`, `fragile`, `very_fragile`, or `not applicable`, based on whether the concept is likely to be named inconsistently, described operationally, or unsafe to require as a searchable concept
- `fragility_score`: total score from the Fragility Scoring Rubric below, or `not applicable`
- `fragility_dimension_scores`: score each dimension `0`, `1`, or `2`: terminology stability; controlled-vocabulary/indexing reliability; explicitness of author reporting; retrieval/noise behavior; validation or pilot evidence
- `fragility_evidence_sources`: question/protocol wording, seed records, MeSH mapping, PubMed ATM/query translation, known-item or pilot retrieval, block counts, sample-record wording, or `not performed`
- `fragility_hard_red_flags`: any hard red flags from the rubric below, or `none`
- `fragility_trigger`: for fragile or very fragile concepts, the trigger such as methodological/study-design label, workflow/process concept, behavior, health-services/setting concept, weak MeSH, historical/regional wording drift, author-described operation, or poor searchability despite safety-layer expansion; for stable concepts, the evidence supporting stable terminology/MeSH coverage
- `fragility_consequence`: normal expansion, exact plus descriptive safety layer, omit from sensitive main strategy and screen, focused/reserve variant, or protocol-required inclusion with recall risk
- `safety_layer_handling`: `exact plus descriptive layer required`, `offer leave-out alternative - very fragile`, `safety layer not applicable - stable concept`, `waived with evidence`, or `deferred`, with the reason carried into `tiab-expansion.md`
- `recall_risk`: why the concept could miss records if required, or `low` for truly essential concepts
- `and_block_admission`: pass, fail, deferred, or not applicable, with the specific reason
- `decision_needed`: whether user/protocol input is required before proceeding
- `question_asked_to_user`: exact user-facing question asked at the concept gate or later testing checkpoint, or `not asked`
- `user_or_protocol_decision`: include, omit, test as focused variant, use validated filter, or not yet resolved
- `final_handling`: main `AND` block, inside an existing `OR` block, reserve/focused variant, validated filter, omitted, or deferred

The ledger may begin as a compact table in the response or working notes, but its decisions must be carried forward into the final audit Markdown file's decision ledger. An optional audit workbook or other handoff artifact can supplement the Markdown audit file, but does not replace it.

If a candidate's role is optional secondary `AND` block, outcome block, safety block, filter/limit, or focused variant and it is materially plausible, default `decision_needed` to yes unless the protocol already fixes the decision. `decision_needed` means the candidate cannot be adopted without a user or protocol decision; it does not by itself mean the question blocks the concept gate. See the gate-blocking rule in Phase 1.

Do not use pasted Boolean syntax, line numbers, field tags, filters, or prior strategy structure as a source of concept evidence. If the user supplied Boolean syntax, use only an independently confirmed plain-language topic or protocol question as the source for concept analysis.

## Fragility Scoring Rubric

Use this rubric for every candidate that could become an essential concept block. The score is a decision aid, not a statistical model; hard red flags override the numeric total when recall is at risk.

A fragile concept is one where failure to retrieve the preferred label is weak evidence that the paper lacks the concept. These concepts may be precise for screeners but unreliable for searching because authors or indexers use variable labels, describe the operation without naming the construct, mention it only in methods/full text, or map it inconsistently to controlled vocabulary. Do not treat high retrieval count alone as fragility; score retrieval/noise fragility when the language needed to express the concept is so generic that it threatens recall or makes the concept unsafe as a required `AND` block.

Determine fragility in two passes:

1. At the concept gate, assign a provisional score from the question/protocol wording, concept type, seed wording if available, likely MeSH/publication-type support, and the pre-MeSH vocabulary/domain brainstorm.
2. During MeSH lookup and title/abstract expansion, revise the score using PubMed ATM/translation behavior, MeSH mapping, known-item or pilot misses, block counts, sample-record wording, and whether exact-label plus context-tethered descriptive layers retrieve plausible records.
3. Record the final score, dimension scores, evidence sources, hard red flags, and search consequence in the concept ledger and audit. If evidence for a dimension is genuinely unknown, score it as `1` rather than `0`; use `0` only when there is positive evidence of stability.

When screened relevant records exist, replace manual final scoring with `strategy_analysis.py fragility-score` as specified in `empirical-fragility.md`. The provisional pre-search score remains a human judgment. The final score must report measured exact-label, MeSH, descriptive-rescue, safety-noise, held-out-miss, and publication-era variation evidence. A human override is allowed only with a recorded reason.

Score each dimension:

- `0` = stable/searchable
- `1` = some instability or uncertainty
- `2` = high instability or likely retrieval loss

Dimensions:

1. **Terminology stability**: `0` = one dominant label with predictable synonyms; `1` = several labels, regional/disciplinary variation, or historical drift; `2` = no dominant label, mostly operational wording, or terminology changes across eras.
2. **Controlled-vocabulary/indexing reliability**: `0` = reliable MeSH/publication type or established indexing; `1` = partial, new, lagging, or inconsistent indexing; `2` = no reliable descriptor/publication type, weak mapping, or likely sparse indexing.
3. **Explicitness of author reporting**: `0` = usually named in title/abstract/indexing; `1` = often in methods/full text or implicit; `2` = frequently implicit, described only by procedure, or not abstracted.
4. **Retrieval/noise behavior**: `0` = exact and ordinary text-word layer is selective; `1` = broad terms need tethering or produce moderate noise; `2` = even tethered descriptive terms are very noisy or exact terms are too brittle.
5. **Validation or pilot evidence**: `0` = known items/pilots retrieve reliably; `1` = some misses or uncertain no-seed evidence; `2` = known-item/pilot misses caused by this concept, or no-seed benchmark shows a coherent missed cluster/noisy unusable expansion.

Classify by total score unless a hard red flag applies:

- `stable`: total `0-2` and no hard red flag.
- `fragile`: total `3-6`, or one serious weakness that can plausibly be handled by exact-label plus descriptive safety-layer searching.
- `very_fragile`: total `7+`, or any hard red flag below.

Hard red flags forcing `very_fragile` unless protocol evidence overrides:

- the concept is often implicit rather than named
- exact-label and descriptive-action layers both miss known-item or pilot records
- descriptive terms are unusably noisy even after context tethering
- the concept is an eligibility property, interpretation, mechanism, bias/risk judgment, or outcome-like qualifier rather than a searchable topic anchor
- old or sparse abstracts make author-language coverage unreliable
- no reliable MeSH, publication type, or text-word family exists for the concept

Examples:

- `stable`: named diseases, drugs, organisms, established devices, and well-indexed procedures.
- `fragile`: trial methods, allocation mechanisms, triage/referral workflows, adherence, help-seeking, telehealth or service settings.
- `very_fragile`: recruitment speed, selection-bias risk, allocation concealment when rarely reported, pragmaticness, workflow fidelity, implicit clinician behavior, and other concepts usually judged during screening or risk-of-bias assessment.

Consequences:

- `stable`: normal MeSH plus `[tiab]` expansion; broad safety layer is not applicable.
- `fragile`: require exact-label plus context-tethered descriptive/action safety layer unless waived with evidence.
- `very_fragile`: default the sensitive main strategy to omit the concept and handle it at screening; any searched version is a focused/reserve variant unless the protocol explicitly accepts the recall risk.

## AND-block admission test

A candidate becomes an essential `AND` block only if all acceptance checks pass:

1. It is required for every in-scope record under the plain-language review question.
2. It names a searchable topic anchor, not only an eligibility-screening property.
3. It is broad and stable enough to search safely using MeSH and/or title/abstract coverage.
4. It is not merely an outcome, comparator, narrow setting, subgroup, mechanism, severity marker, service-use qualifier, or study-design preference.
5. It cannot be handled more safely inside an existing `OR` block, at screening, as a focused/reserve variant, or as a validated methodological filter.
6. No high-impact framework-slot ambiguity remains unresolved.
7. For methodological or automation topics, the scope breadth check does not show that a broader workflow concept is plausibly in scope.
8. No conceptual reason already suggests that inconsistent wording, indexing, publication type, or missing abstracts would make the block unsafe. Later objective evidence must retest this; failure triggers structural re-entry rather than silent mutation.

Default if uncertain: do not admit the candidate as a main `AND` block. Classify it as screening-only, omitted, deferred, reserve/focused-variant-only, or a filter decision, then record the recall risk.

Outcomes, comparators, narrow settings, demographic subgroups, and study-design concepts fail the admission test unless the user question or protocol makes them true topic anchors and the recall risk is explicitly accepted.

Very fragile concepts are candidates whose terminology is so inconsistent, operational, implicit, or noise-prone that even an exact-label plus descriptive safety layer may miss in-scope records or overwhelm the search. When a very fragile concept is not absolutely required as a searchable topic anchor, default the sensitive main strategy to leave it out and handle it at screening. If the concept is plausibly useful for workload or interpretation, offer a focused/reserve variant that includes the safety-layer block. When the protocol appears to require searching a very fragile concept as an essential block, pause at the concept gate and offer the trade-off explicitly: sensitive main strategy without the concept versus focused/reserve strategy with the concept.

## Concept-gate pilot-test protocol

The concept gate has two phases. The first phase is mandatory before MeSH lookup; the second phase is scheduled for iterative testing after blocks exist.

### Phase 1 - conceptual scope lock

Before MeSH lookup or PubMed exploration:

1. Choose the review framework and extract candidate concepts from the plain-language question.
2. Run the PICO-slot ambiguity check below.
2a. If the framework choice selected the `methods-evaluation` profile, run its mandatory ambiguity check and canonical slot profile from `methods-evaluation-framework.md` before assigning roles.
3. Run the scope breadth check below for methodological or automation topics.
4. Apply the AND-block admission test to each candidate concept.
5. Mark each candidate as a core required concept, within-block term family, screening-only concept, omitted concept, reserve/focused-variant candidate, or filter/limit decision.
6. Record every materially plausible optional secondary `AND` block, outcome block, safety block, filter/limit, focused variant, and very-fragile leave-out trade-off as an offer, unless the protocol already decides it. None may be adopted without a user or protocol decision. Then apply the gate-blocking rule below to decide which one, if any, is asked now.

### Which offers block the gate

Recording an offer and blocking on it are different acts. Every recorded offer is already protected by the adoption rule — nothing narrowing enters the strategy without a decision — so the gate only needs to stop for decisions that later evidence cannot settle.

Block the gate and ask now when the decision:

- changes which concepts are in scope, or what the review question means;
- changes the eligibility interpretation;
- resolves a `high`-impact framework-slot or scope-breadth ambiguity that would move the searchable anchor; or
- accepts the recall risk of requiring a very fragile concept that the protocol appears to demand.

Defer to Phase 2, offer recorded, when a reversible read-only comparison can measure the trade-off — most filters, limits, focused variants, and optional blocks. Asking before that evidence exists makes the user guess at a question the build is about to answer empirically. This is the `SKILL.md` stop rule: present the evidence before asking the user to adopt a narrowing design.

Whether an already-in-scope concept should be *required* as an `AND` block is a retrieval-structure question, not a scope question. Leave-one-block-out ablation measures it directly, and the admission test's "default if uncertain, do not admit" already protects recall in the meantime, so defer it. Only the question of whether the concept is in scope at all belongs at the gate.

Ask one question at a time, in the precedence order above, and stop. Several qualifying offers do not become several questions; the rest stay recorded and are raised when each becomes the next decision.

This phase may use only the plain-language question, protocol wording, framework reasoning, and a conceptual vocabulary brainstorm needed to distinguish concepts from eligibility properties. It must not inspect seed/candidate records, run MeSH lookup, PubMed exploration, block construction, variants, final QA, or filters.

Save the resolved roles and decisions as `review_protocol_v1.json`, compile its derivative artifacts, and record it with `manifest_tool.py state lock-protocol`.

### Phase 2 - empirical challenge and re-entry

After scope lock, build and prescreen candidate evidence, then run reversible diagnostic comparisons for material optional-block and filter trade-offs before asking the user to adopt them:

1. Compare the sensitive topic-only strategy with and without the optional concept or filter.
2. If seed PMIDs were supplied, test whether every in-scope seed is still retrieved.
3. Inspect count changes and, when useful, samples or labelled samples as workload evidence.
4. Treat counts as workload proxies, not precision, unless PMID-level relevance labels exist.
5. Keep the sensitive design as the default unless the focused/filter design preserves known-item retrieval, keeps MeSH plus text-word coverage for each essential concept, avoids PubMed parse hazards, and has an explicit user/protocol rationale.

If counts, validation behavior, or samples reveal a new trade-off, gather the read-only comparison evidence. Ask only before adopting a recall-reducing block/filter or changing scope. Do not re-ask unless evidence materially changes the decision context.

If objective evidence changes an essential concept's role or meaning, run `manifest_tool.py state reopen-scope`, record the reason, rerun the admission test, save the next scope version, re-screen affected candidate records, re-register blocks, and rerun affected evidence. Record all Phase 2 results in the revision and decision ledgers.

## Gate output contract

Before MeSH lookup, record a compact pre-MeSH gate summary containing:

- retrieval-scope version and saved artifact path
- chosen framework, question type, and rationale
- whether a framework question was needed, and why or why not
- candidate concepts with framework slots and ambiguity grades
- candidate concepts classified as `stable`, `fragile`, or `very_fragile`, with fragility score, dimension scores, evidence sources, hard red flags, and fragility trigger or stable-concept rationale
- very-fragile concepts for which the sensitive main strategy should omit the concept and handle it at screening, plus any focused/reserve variant offer
- scope breadth check for methodological or automation topics, including whether the main workflow concept is narrow or broad
- concepts admitted as core required search concepts
- concepts kept inside existing `OR` blocks as term families
- screening-only, omitted, deferred, reserve, or focused-variant concepts with recall-risk reasons
- optional concept offers: each materially plausible optional secondary `AND` block, outcome block, safety block, filter, limit, focused variant, or very-fragile leave-out alternative, or `none identified`
- methodological filter or limit decisions needed before narrowing the strategy
- optional secondary `AND` blocks, outcome blocks, safety blocks, filters, limits, or focused variants that require user/protocol authorization before testing
- the one next user-facing question, if an offer blocks the gate under the precedence rule; otherwise `gate resolved`, listing the offers deferred to Phase 2

If no human decision is needed, state that the gate is resolved and continue to the pre-MeSH vocabulary/domain brainstorm.

## PICO-slot ambiguity check

Before role assignment, list any ambiguities about which framework slot each candidate concept belongs to, and grade impact as `low`, `medium`, or `high`.

Common high-impact ambiguities to check:

- Could the candidate be either Population or Outcome? Example: in a review of post-stroke depression, is depression the outcome of stroke or the population condition being studied?
- Could the candidate be either Intervention or Exposure? Example: is hormone replacement therapy an intervention (RCT framing) or an exposure (observational framing)?
- Could the question be Diagnostic accuracy or Screening effectiveness? These call for different frameworks (PIRD vs PICO) and different validated filters.
- Could what was classified as Population actually be a Condition that should anchor the search? Example: "adults with depression" - the search anchor is usually depression, with adults handled at screening unless the demographic is itself central to scope.

For method, tool, or technology performance-evaluation questions, `methods-evaluation-framework.md` adds three mandatory high-impact checks: whether the method is performing the task or being evaluated at it; which workflow stage is in scope; and whether evidence synthesis is the application context or the eligible report type. Run them instead of forcing the question through the PICO slots above.

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

Under the `methods-evaluation` profile this check governs the `task_function` slot, and the workflow areas above are the candidate stages. The application context, comparator, and performance outcome are handled by the slot defaults in `methods-evaluation-framework.md`, not by this check.

## Concept roles

Use these roles consistently:

- Essential `AND` block: a concept that must be present for a record to be in scope, and that is broad enough to search safely.
- Within-block synonym/term only: a synonym, acronym, spelling variant, MeSH entry term, subtype, device/procedure/drug name, proximity expression, or wildcard candidate that belongs inside an existing essential `OR` block.
- Sensitivity-dangerous optional `AND` block: a concept that may help precision or interpretation but could exclude relevant records if required.
- Methodological/filter concept: study design, evidence type, date, language, publication type, age group, species, humans-only, full-text, or another limit/filter.
- Omitted concept: a concept deliberately excluded from the main sensitive strategy to preserve recall.

Sensitivity-dangerous concepts include outcomes, comparators, mechanisms, mediators, moderators, barriers, facilitators, narrow settings, service-use qualifiers, disease severity, subgroup-only population limits, and ad hoc study-design terms. Outcomes and comparators in particular have empirically lower retrieval potential in PubMed and Embase ([Frandsen et al. 2020](https://doi.org/10.1016/j.jclinepi.2020.07.005)); two-block PICO searches retrieved more relevant systematic reviews than four-block searches ([Ho et al. 2016](https://doi.org/10.1371/journal.pone.0167170)).

Do not ask about ordinary term expansion that stays inside an existing `OR` block. Record every materially plausible optional secondary `AND` block, outcome block, safety block, filter, limit, or focused variant as an offer unless the protocol already decides it, then apply the gate-blocking rule: ask at the gate when the decision changes an essential block or the eligibility interpretation, and otherwise in Phase 2 with the comparison evidence attached. During later testing, ask again only if new evidence materially changes the trade-off context.

After drafting two or more proposed `AND` blocks, operationalize this admission test with `references/concept-ablation-and-strands.md`. Leave-one-block-out counts, known-item effects, and differential samples challenge over-structured designs but never redefine the locked question. For fragile topics, default to separate recall-first and focused strands.

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
3. Normalize and deduplicate numeric PMIDs, document malformed entries, and lock conceptual scope before fetching them.
4. After scope lock, fetch and screen every seed against the scope using `references/candidate-screening.md`.
5. Allocate screened-in records to discovery, holdout, or `both`; do not use excluded, uncertain, or unresolved records for term mining.
6. Expand with `related` only after scope lock. Screen candidates before they influence `term-rank`; unscreened neighbors remain heuristic only.
7. Classify seed-derived terms by existing concept role before adding them to an `OR` layer.
8. Validate against held-out records when possible. Label reuse of discovery records as non-independent.
9. If a methodological filter is used, validate topic-only and topic-plus-filter retrieval separately.

Seed PMIDs are validation aids, not the whole target set. Do not overfit the strategy to retrieve only the language used in a small seed set. If a seed is out of scope, report it rather than distorting the strategy.

## With no seed PMIDs

If the user says there are no seed PMIDs or asks to proceed without seeds:

1. Treat seed status as resolved.
2. Run the formal concept analysis and concept gate before MeSH/PubMed exploration.
3. Lock scope from question/protocol evidence and mark seed evidence unavailable.
4. After scope lock, run the orthogonal-pilot workflow in `no-seed-recall-estimation.md`; do not rely on one high-precision vocabulary cluster.
5. For methodological or automation topics where recall-first is requested and the protocol does not explicitly narrow the scope, apply the scope breadth check and default the main workflow block to the broader workflow rather than only the exact narrow action wording.
6. Record post-lock evidence from candidate screening, MeSH sweeps, PubMed ATM/query translations, sample-record patterns, block counts, objective term ranking, final QA, and filter checks.
6a. Feed only screened-in pilot anchors to `term-rank --pmids` or an accepted whitelist. Do not treat raw pilot-query hits as a relevant set merely because the pilot was precise.
7. Do not report true seed-derived MeSH, seed-derived title/abstract terminology, known-item recall, or seed validation results.
8. State that validation is limited to MeSH checks, PubMed block testing, sample inspection, final query hygiene, `final-qa`, and `filter-check` where relevant. Objective term ranking against a pilot relevant set is available as term-discovery support, not recall validation; do not present it as known-item recall.

Sample-record MeSH patterns are not seed-derived evidence. Label them as sample-record patterns.

## Goal-tracked concept gates

When the prompt starts with `/goal` or the user asks for goal tracking, concept analysis is a pre-goal intake step whenever it requires human decisions. It is not a reason to start a goal early.

Use `goal-tracking.md` as the canonical reference for `/goal` state rules, the pre-goal decision sequence, blockers, completion audit, and objective wording.
