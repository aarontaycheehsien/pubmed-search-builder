## Search structure

- **Concept 1:** [name and scope; MeSH + tiab / tiab-only / MeSH-only]
- **Concept 2:** [name and scope; MeSH + tiab / tiab-only / MeSH-only]
- **Concept 3:** [name and scope, if used]
- **Concept gate status:** [completed / skipped with reason / not applicable]
- **Concepts kept inside existing `OR` blocks:** [list, or not applicable]
- **Omitted or reserve concepts:** [list with sensitivity rationale]
- **Methodological filters or limits:** [none, or name/source/version/interface/adaptation]

## User decisions on optional concept blocks

- **[Optional or sensitivity-dangerous concept]:** offered because [why it could narrow retrieval] -> user chose **[omit/include/test as variant/filter]**. [How handled in the strategy.]
- **Seed PMIDs:** offered -> user chose **[provided PMIDs / no seeds - proceed without / not asked because already supplied]**. [Validation implication.]
- **Study-design, date, language, age, species, or publication-type limits:** [offered/required/not applicable] -> [decision and recall-risk note].

## Decision ledger

| Decision point | Options considered | Evidence or test used | Decision made | Rationale / recall-risk note | Reflected in strategy/report |
|---|---|---|---|---|---|
| Seed PMID handling | [provided / no seeds / proceed without] | [user answer, seed fetch/mine, or not available] | [decision] | [impact on validation] | [seed validation section] |
| Concept gate | [candidate concepts and optional blocks] | [concept-analysis ledger, seed/no-seed evidence, counts if tested] | [essential / inside OR / focused variant / omitted / deferred] | [why this protects recall or workload] | [search structure / final strategy / variants] |
| Pre-MeSH vocabulary brainstorm | [vocabulary families and domain frames considered] | [user/protocol wording, seeds, brainstorm checklist, domain-framing question if asked] | [accepted / rejected / deferred / not needed] | [recall/noise or scope rationale] | [title/abstract expansion log / rationale] |
| MeSH/SCR choice | [accepted, rejected, deferred candidates] | [sweep, details, tree, ATM, seed indexing, counts] | [decision] | [scope, explosion/noexp, duplicate/noise/wrong-sense reason] | [MeSH descriptors considered] |
| Text-word/proximity/wildcard choice | [terms or expressions considered] | [MeSH entry terms, seeds, samples, counts, warnings] | [decision] | [recall/noise rationale] | [title/abstract expansion log] |
| Filter/limit/variant choice | [main, focused, precision, filter, reserve] | [counts, seeds, labelled samples if available, QA] | [chosen main design] | [sensitivity/workload rationale] | [final strategy / PubMed CLI checks] |
| QA or caveat | [warning, limitation, or unresolved check] | [query translation, final-qa, filter-check, sample inspection] | [resolved / documented / not performed] | [remaining risk] | [rationale / reporting notes] |

## Final PubMed strategy (draft)

```text
(...)
AND
(...)
```

**Result count on [date searched]:** [count] records.

If a validated filter or focused variant was also tested:
- **Topic-plus-filter count:** [count, or not applicable]
- **Focused/precision-supporting variant count:** [count and label, or not performed]
- **Main variant chosen:** [sensitive/main by default, or user/protocol-selected alternative with reason]

## NCBI CLI work performed

### MeSH descriptors considered (per concept)

**Concept 1 - [name]**
- Sweep inputs: [concept phrase, variants, separate subtype/acronym/device/procedure/drug/older/newer-term sweeps, or not performed]
- Sweep outputs and candidate sources: [MeSH sweep candidates, seed-assigned MeSH, PubMed ATM/query translations, sample-record indexing, or not performed]
- Details/tree inspected: [descriptor/SCR IDs and labels; tree/SPARQL evidence, or not performed; do not infer comprehensive tree positions from `details` alone]
- Candidates accepted:
  - `"[Descriptor]"[Mesh]` or `"[SCR]"[Supplementary Concept]`: [source(s), scope/tree evidence, explosion/noexp decision, and reason]
- Candidates rejected with rationale:
  - `"[Descriptor]"[Mesh]` or `"[SCR]"[Supplementary Concept]`: [too broad / too narrow / wrong sense / obsolete / duplicate / noisy / outside scope]
- Candidates deferred or reserved: [list with reason and what would trigger use, or none]
- SCR or ATM mappings resolved: [mapping, decision, and rationale; none relevant / not performed]
- Entry terms harvested as `[tiab]`: [list, or none]
- Entry terms omitted: [ambiguous/noisy/outside-scope terms with reason, or none]
- Counts tested: MeSH-only [count or not performed]; text-word-only [count or not performed]; combined concept block [count or not performed]

**Concept 2 - [name]**
- Sweep inputs: [concept phrase, variants, separate subtype/acronym/device/procedure/drug/older/newer-term sweeps, or not performed]
- Sweep outputs and candidate sources: [MeSH sweep candidates, seed-assigned MeSH, PubMed ATM/query translations, sample-record indexing, or not performed]
- Details/tree inspected: [descriptor/SCR IDs and labels; tree/SPARQL evidence, or not performed]
- Candidates accepted: [list with source(s), scope/tree evidence, explosion/noexp decision, and reason, or none]
- Candidates rejected with rationale: [list with reason, or none]
- Candidates deferred or reserved: [list with reason and what would trigger use, or none]
- SCR or ATM mappings resolved: [mapping, decision, and rationale; none relevant / not performed]
- Entry terms harvested as `[tiab]`: [list, or none]
- Entry terms omitted: [ambiguous/noisy/outside-scope terms with reason, or none]
- Counts tested: MeSH-only [count or not performed]; text-word-only [count or not performed]; combined concept block [count or not performed]

Repeat for additional essential concepts.

### MeSH derived from seed records

Seed PMIDs provided: **[Yes/No]**.

- If yes: [seed PMID list, assigned MeSH/keywords/title-abstract terminology that informed the strategy, and retrieval validation impact].
- If no: True seed-derived MeSH was **not available**. If sample records were fetched, label them as sample-record MeSH patterns, not seed-derived evidence: [summary, or not performed].

### MeSH derived from PubMed query translations

| Free-text query | ATM/query translation observed | Added explicitly? |
|---|---|---|
| `[query]` | `[mapping or warning]` | `[yes/no/n/a and reason]` |

Use `not performed` if exploratory untagged ATM checks were not run.

### PubMed CLI checks

| Block / query tested (PubMed, [date]) | Result count |
|---|---:|
| Concept 1 - MeSH only | [count or not performed] |
| Concept 1 - tiab/proximity/wildcard only | [count or not performed] |
| Concept 1 - combined | [count] |
| Concept 2 - combined | [count] |
| Final combined topic-only strategy | [count] |
| Topic-plus-filter or focused variant | [count or not applicable] |
| Differential/noise sample | [count and sample result, or not performed] |

## Title/abstract, proximity, and wildcard expansion log

- **Pre-MeSH brainstorm required:** [yes/no and reason]
- **Domain-framing question asked:** [question and user answer, or not needed]
- **Brainstormed vocabulary families accepted:** [list, or none]
- **Brainstormed vocabulary families rejected:** [list with reason, or none]
- **Brainstormed vocabulary families deferred/reserved:** [list with reason, or none]
- **MeSH-entry-derived `[tiab]` variants added:** [list, or none]
- **Seed-derived `[tiab]` variants added:** [list, or n/a if no seeds]
- **Sample-record-derived `[tiab]` variants added:** [list, or not performed]
- **Acronyms and abbreviations added:** [list, or none retained]
- **Acronyms and abbreviations tested but rejected:** [list with reason, or not performed]
- **Singular/plural variants added:** [list]
- **Spelling variants added:** [list]
- **Hyphenation variants added:** [list]
- **Proximity expressions added:** [list, or none]
- **Proximity expressions tested but rejected:** [list and reason, or not performed]
- **Wildcard stems added:** [list]
- **Wildcard stems tested but rejected:** [list and reason, or not performed]

## Rationale

- **MeSH choices.** [Why included descriptors were selected and rejected descriptors were excluded.]
- **Text-word choices.** [Why title/abstract terms, spelling variants, acronyms, proximity, and wildcard stems were selected or rejected.]
- **Pre-MeSH vocabulary/domain choices.** [Why brainstormed vocabulary families were accepted, rejected, deferred, or treated as optional/focused concepts.]
- **Concept-gate and omitted-block choices.** [Dangerous optional blocks, user decisions, and screening-vs-search rationale.]
- **Methodological filters or limits.** [None used, or validated source/version/interface/adaptation and recall risk.]
- **Sensitivity vs precision.** [Chosen design, reserve/focused variants, count/workload evidence, seed impact if available.]
- **QA.** `query_translation_drift`: [none/issues]; final query hygiene: [done/warnings]; `final-qa`: [none/issues]; `filter-check`: [none/not applicable/issues].

## Seed PMID validation

Seed PMIDs provided: **[Yes/No]**.

If yes:
- Seed PMIDs tested: [list]
- Retrieved: [list]
- Missed: [list]
- Reason for misses: [summary, or none]
- Revisions made after seed testing: [summary]
- Seeds judged out of scope, if any: [list and reason]

If no:
- Validation was limited to MeSH checks, PubMed block testing, sample inspection, final QA, and filter checks where relevant.
- True seed-derived MeSH and known-item recall were not available.

Do not report formal precision or NNR unless PMID-level relevance labels were provided. If labelled samples were used, report labelled sample size, estimated precision, NNR, and the caveat that pilot NNR is only as valid as the labelled sample.

## Peer review status

**This is a draft strategy. Per PRESS (McGowan et al., 2016), it should be peer reviewed by a second information specialist before being run as the final search.**

Peer-review attention points:
1. [High-impact descriptor/block/filter decision]
2. [Noisy term retained or rejected]
3. [Limits/filter/seed-validation caveat]

Do not imply that PRESS peer review has occurred unless it actually has.

## Reporting notes

- **Database:** PubMed
- **Date searched:** [date]
- **Limits, filters, validated filters used:** [none, or source/version/interface/adaptation]
- **Restrictions and justifications:** [none applied, or state clearly]
- **Audit Markdown file:** [path saved]
- **Audit workbook:** [path if exported, otherwise not exported]
- **Remaining caveats:** [seed validation, noisy terms, untested tree context, sample inspection limits, etc.]
- **Other databases:** Database-specific strategies for Ovid MEDLINE, Embase, CENTRAL, CINAHL, EconLit, grey literature, or other sources were [not requested / not built / built separately]. Do not present them unless separately constructed.

For PRISMA-S 2021 reporting items applicable to this skill, see `references/prisma-s-reporting.md`.
