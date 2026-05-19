# Concept Analysis And Gating

Use this step after the seed PMID decision is resolved and before MeSH lookup, broad PubMed exploration, or concept-block drafting. If supplied seed PMIDs are available, limited seed fetch/mining may happen immediately before the concept gate only to inform the concept-analysis ledger.

The purpose is to decide what belongs in the main high-sensitivity strategy, what belongs only inside an existing `OR` block, what should be omitted from the main search, and what requires a separate methodological filter decision.

Do not skip this step just because the topic looks straightforward. It is the main safeguard against turning every PICO element into a separate `AND` block.

## Required sequence

Use `workflow.md` as the canonical source for the full build sequence and high-sensitivity mental model.

The seed PMID decision is resolved when the user supplies seed PMIDs, says they have no seeds, or explicitly asks to proceed without seeds.

After seed status is resolved and seed PMIDs were supplied, you may fetch/mine only those seed PMIDs before the concept gate to extract titles, abstracts, assigned MeSH, keywords, publication types, acronyms, and distinctive phrases for concept-role decisions. This limited seed work is not PubMed exploration, block testing, seed validation, variant comparison, final QA, or filter checking.

Do not run MeSH lookup, broad PubMed exploration, block construction, final QA, filter checks, variants, or full strategy validation before the required seed and concept-gate decisions are resolved. The only other exception is shallow parsing of the user's prompt so you can identify candidate concepts and required upfront decisions.

## Concept-analysis ledger

Record a concept-analysis ledger before drafting blocks. Keep it concise, but make it auditable.

Use these fields:

- `candidate_concept`: the concept, limit, or filter idea being considered
- `source`: user question, protocol text, seed record, supplied Boolean context, pre-MeSH brainstorm, or inferred PICO element
- `role`: essential `AND` block, within-block synonym/term only, sensitivity-dangerous optional `AND` block, methodological/filter concept, or omitted concept
- `seed_evidence`: seed-derived title/abstract term, seed MeSH, seed keyword, seed publication type, in-scope seed retrieval concern, or `not available - no seed PMIDs supplied`
- `no_seed_evidence`: pre-MeSH brainstorm, MeSH sweep, PubMed ATM/query translation, sample-record pattern, protocol wording, or `not applicable - seed evidence used`
- `recall_risk`: why the concept could miss records if required, or `low` for truly essential concepts
- `decision_needed`: whether user/protocol input is required before proceeding
- `user_or_protocol_decision`: include, omit, test as focused variant, use validated filter, or not yet resolved
- `final_handling`: main `AND` block, inside an existing `OR` block, reserve/focused variant, validated filter, omitted, or deferred

The ledger may begin as a compact table in the response or working notes, but its decisions must be carried forward into the final audit Markdown file's decision ledger. An optional audit workbook or other handoff artifact can supplement the Markdown audit file, but does not replace it.

## Concept roles

Use these roles consistently:

- Essential `AND` block: a concept that must be present for a record to be in scope, and that is broad enough to search safely.
- Within-block synonym/term only: a synonym, acronym, spelling variant, MeSH entry term, subtype, device/procedure/drug name, proximity expression, or wildcard candidate that belongs inside an existing essential `OR` block.
- Sensitivity-dangerous optional `AND` block: a concept that may help precision or interpretation but could exclude relevant records if required.
- Methodological/filter concept: study design, evidence type, date, language, publication type, age group, species, humans-only, full-text, or another limit/filter.
- Omitted concept: a concept deliberately excluded from the main sensitive strategy to preserve recall.

Sensitivity-dangerous concepts include outcomes, comparators, mechanisms, mediators, moderators, barriers, facilitators, narrow settings, service-use qualifiers, disease severity, subgroup-only population limits, and ad hoc study-design terms.

Do not ask about ordinary term expansion that stays inside an existing `OR` block. Ask only when the decision would add a separate `AND` block, add a filter, or otherwise narrow the main strategy.

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
3. Use limited seed fetch/mining before the concept gate when seed evidence would help classify concepts or filters.
4. Use seed records and the pre-MeSH brainstorm to inform the concept-analysis ledger before MeSH block construction.
5. Use seed titles, abstracts, MeSH headings, keywords, publication types, acronyms, and distinctive phrases as candidate evidence.
6. Classify seed-derived terms by concept role before adding them to the strategy.
7. Validate the final topic-only strategy against in-scope seeds.
8. If a methodological filter is used, validate topic-only and topic-plus-filter seed retrieval separately.

Seed PMIDs are validation aids, not the whole target set. Do not overfit the strategy to retrieve only the language used in a small seed set. If a seed is out of scope, report it rather than distorting the strategy.

## With no seed PMIDs

If the user says there are no seed PMIDs or asks to proceed without seeds:

1. Treat seed status as resolved.
2. Run the formal concept analysis and concept gate before MeSH/PubMed exploration.
3. In the ledger, mark seed evidence as `not available - no seed PMIDs supplied`.
4. Use non-seed evidence: protocol wording, pre-MeSH brainstormed vocabulary, MeSH sweeps, PubMed ATM/query translations, sample-record patterns, concept-block counts, and final QA.
5. Do not report true seed-derived MeSH, seed-derived title/abstract terminology, known-item recall, or seed validation results.
6. State that validation is limited to MeSH checks, PubMed block testing, sample inspection, final query hygiene, `final-qa`, and `filter-check` where relevant.

Sample-record MeSH patterns are not seed-derived evidence. Label them as sample-record patterns.

## Goal-tracked concept gates

When the prompt starts with `/goal` or the user asks for goal tracking, concept analysis is a pre-goal intake step whenever it requires human decisions. It is not a reason to start a goal early.

Use `goal-tracking.md` as the canonical reference for `/goal` state rules, the pre-goal decision sequence, blockers, completion audit, and objective wording.

##
