````markdown
## Review protocol provenance

- **Protocol DSL used:** [yes / no]
- **Protocol ID and DSL version:** [identifier / version or not applicable]
- **Locked scope version:** [N]
- **Source protocol file and hash:** [path / SHA-256]
- **Compile receipt and verification result:** [path / pass-fail]
- **Superseded protocol versions and change reasons:** [list or none]

## Search structure

- **Framework:** [framework, question type, and reason]
- **Concept 1:** [name and scope; MeSH + tiab / tiab-only / MeSH-only]
- **Concept 2:** [name and scope; MeSH + tiab / tiab-only / MeSH-only]
- **Concept 3:** [name and scope, if used]
- **Concept gate status:** [completed for completed strategy builds; not performed/not applicable only for incomplete or non-build contexts]
- **AND-block admission summary:** [which candidates passed, failed, or were deferred, with concise reasons]
- **Concepts kept inside existing `OR` blocks:** [list, or not applicable]
- **Omitted or reserve concepts:** [list with sensitivity rationale]
- **Methodological filters or limits:** [none, or name/source/version/interface/adaptation]

## Retrieval-scope versions

- **Current version:** [positive integer]
- **Status:** [locked]
- **Current artifact:** [review_protocol_vN.json and protocol_compile_vN.json]
- **Scope-change rationale:** [not applicable for v1, or critic finding/user decision that triggered re-entry]

| Version | Artifact | Reason | Locked UTC |
|---:|---|---|---|
| [1] | [review_protocol_v1.json / protocol_compile_v1.json] | [initial protocol-only scope lock] | [timestamp] |

## Stage Trace

| Stage | Reference files | Action taken | Blocked actions | Decision needed | User/protocol decision |
|---|---|---|---|---|---|
| [stage name] | [exact reference files in force] | [work performed in this stage] | [work explicitly deferred or blocked] | [decision needed, or none] | [answer, protocol decision, or not yet resolved] |

## User decisions on optional concept blocks

- **Explicit user choice:** **[Optional or sensitivity-dangerous concept]** was asked because [why it could narrow retrieval] -> user chose **[omit/include/test as variant/filter]**. [How handled in the strategy.]
- **No user decision requested:** **[Optional or sensitivity-dangerous concept]** was not asked -> analyst decision under workflow: **[omit/include/test as variant/filter]**. [Why no explicit user question was requested and how handled.]
- **Not applicable:** no materially plausible optional concept block or filter was identified for user decision.
- **Seed PMIDs:** offered -> user chose **[provided PMIDs / no seeds - proceed without / not asked because already supplied]**. After scope lock: [malformed/not-found PMIDs, screening decisions, retractions, use roles, and validation implication].
- **Study-design, date, language, age, species, or publication-type limits:** [offered/required/not applicable] -> [decision and recall-risk note].

## Decision ledger

| Decision point | Options considered | Evidence or test used | Decision made | Rationale / recall-risk note | Reflected in strategy/report |
|---|---|---|---|---|---|
| Seed PMID handling | [provided / no seeds / proceed without; malformed/missing/retracted/out-of-scope triage] | [user answer, seed fetch/mine, found/missing PMIDs, retraction/scope check, or not available] | [decision] | [impact on validation and concept gate] | [seed validation section] |
| Scope lock / re-entry | [candidate concepts, framework slots, optional blocks, and filter ideas] | [question/protocol concept ledger, AND-block admission checks, and later objective challenge evidence] | [essential / inside OR / screening-only / focused variant / omitted / deferred / filter] | [why this protects recall or why a new scope version was required] | [retrieval-scope versions / strategy / variants] |
| Pre-MeSH vocabulary brainstorm | [vocabulary families and domain frames considered] | [user/protocol wording, seeds, brainstorm checklist, domain-framing question if asked] | [accepted / rejected / deferred / not needed] | [recall/noise or scope rationale] | [title/abstract expansion log / rationale] |
| MeSH/SCR choice | [accepted, rejected, deferred candidates] | [sweep, details, tree, ATM, seed indexing, counts] | [decision] | [scope, explosion/noexp, duplicate/noise/wrong-sense reason] | [MeSH descriptors considered] |
| Text-word/proximity/wildcard choice | [terms or expressions considered] | [MeSH entry terms, seeds, samples, counts, warnings] | [decision] | [recall/noise rationale] | [title/abstract expansion log] |
| Broad retrieval safety layer | [stable/fragile/very-fragile classification, fragility score/dimensions/red flags, exact-label terms, descriptive/action terms, tethering logic, leave-out alternatives, waivers] | [pre-MeSH brainstorm, known-item records, samples, term-rank, layer counts, variant counts, or not available] | [added / waived / not applicable - stable / omitted from sensitive strategy / focused-reserve variant / revised] | [why broader author language was needed, safely waived, omitted from the sensitive strategy, or not applicable for a stable concept] | [title/abstract expansion log / final strategy / variants] |
| Bramer reciprocal gap analysis | [performed / waived / not applicable / not performed per concept] | [MeSH/SCR NOT text-word count; text-word NOT MeSH/SCR count; sample JSON if inspected] | [terms accepted/rejected, or waiver] | [term-discovery rationale or waiver reason] | [MeSH descriptors considered / title-abstract expansion log] |
| Filter/limit/variant choice | [main, focused, precision, filter, reserve] | [counts, seeds, labelled samples if available, QA] | [chosen main design] | [sensitivity/workload rationale] | [final strategy / PubMed CLI checks] |
| Low-count plausibility check | [final topic-only count `<500` triggered check / not triggered] | [final topic-only count, block counts, query translation, final-qa, filter/limit comparison, seed/gold retrieval, no-seed recall offer status] | [expanded and retested / documented as plausible / not triggered] | [diagnosis and recall-risk note] | [PubMed CLI checks / reporting notes] |
| Zero-hit and duplicate terms | [zero-hit terms from `phrases_not_found`; exact duplicates from `duplicate_term`] | [per-term PubMed counts, spelling/hyphenation variant checks, `final-qa`] | [duplicates removed; each genuinely zero-hit term removed+documented by default, or kept by user choice] | [default is remove+document zero-hit terms (they match no records); reason if kept] | [final strategy / title-abstract expansion log] |
| QA or caveat | [warning, limitation, or unresolved check] | [query translation, final-qa, filter-check, sample inspection] | [resolved / documented / not performed] | [remaining risk] | [rationale / reporting notes] |

## Candidate evidence screening

- **Status:** [complete / not applicable with reason]
- **Scope version:** [version used for screening]
- **Candidate ledger and validation receipt:** [paths]
- **Counts by decision:** [include / exclude / uncertain]
- **Counts by use:** [discovery / holdout / both / heuristic / neither]
- **Eligible discovery PMIDs:** [list]
- **Independent holdout PMIDs:** [list]
- **Non-independent validation PMIDs:** [list]
- **Heuristic PMIDs:** [list]
- **Screening and holdout rationale:** [eligibility evidence, exclusions/uncertainties, representativeness, and independence limits]

Only screened-in discovery records may support objective term mining. Keep raw pilot/related neighbors separate from confirmed evidence.

For optional-block or filter rows in the decision ledger, record whether a user question was explicitly asked, the exact question when asked, and whether the final handling came from explicit user input, protocol direction, or analyst judgment under the workflow.

## Record-content evidence reviewed

Use this table whenever a decision depends on `fetch`, `mine`, or `sample` record content. Receipt-only stdout cannot support relevance, scope, noise, term-discovery, seed-validity, or concept-role decisions.

| Decision | Evidence file reviewed | Record content reviewed | Abstracts reviewed | Receipt-only stdout used as decision evidence | Decision supported |
|---|---|---|---|---|---|
| [decision] | [saved JSON path] | yes/no/not applicable | yes/no/not available/not applicable | no | yes/no |

## Final PubMed strategy (draft)

```text
(...)
AND
(...)
```

**Result count on [date searched]:** [count] records.

**Low-count plausibility check (`<500` final topic-only records):** [triggered/not triggered]. Diagnosis: [expected rare/new/tightly scoped/protocol-limited topic, or avoidable narrowing from over-specific block, too many AND blocks, narrow workflow/action terms, missing variants, PubMed translation/parse issue, or restrictive filter/limit/hedge]. Expansion/retest decision: [expanded and retested with before/after counts / documented as plausible / not applicable].

If a validated filter or focused variant was also tested:
- **Topic-plus-filter count:** [count, or not applicable]
- **Focused/precision-supporting variant count:** [count and label, or not performed]
- **Main variant chosen:** [sensitive/main by default, or user/protocol-selected alternative with reason]

### AND-block ablation and two-strand delivery

- **Concept-ablation artifact:** [path; every proposed AND block covered]
- **Per-block disposition:** [keep required / move inside OR / screening-only / focused-only, with workload change, development/holdout effect, and differential sample path]
- **Recall-first main strand:** [query file, count, known-item retrieval, estimated screening workload]
- **Focused prioritization strand:** [query file, count, known-item losses, records unique to each strand, estimated screening workload]
- **Narrowing rationales:** [one reason per additional focused block]
- **Non-substitution safeguard:** The focused strand does not replace the recall-first main search.

### Empirical fragility and no-seed discovery

- **Fragility metrics by block:** [explicit title/abstract naming %, MeSH coverage %, exact-label coverage %, descriptive rescue %, safety-layer noise, held-out attributable misses, era variation]
- **Empirical and final handling:** [stable / fragile / very-fragile; human override and required reason, or none]
- **Orthogonal no-seed pilots:** [MeSH / exact phrase / operational description / prior review / citation-registry / historical terminology, or not applicable]
- **Provenance-blinded screening:** [yes/no/not applicable]
- **Saturation history:** [new included studies and new vocabulary per round; consecutive zero-novelty rounds]
- **Holdout freeze:** [allocation method and ledger path before term mining, or not applicable]

### Active vocabulary learning

- **Newly included records processed:** [PMIDs by round]
- **Within-concept vocabulary proposals:** [concept, term, source records, accepted/rejected/deferred, reason]
- **Excluded-record diagnosis:** [separate terminology and exclusion-reason summary; not used for proposals]
- **Scope challenges:** [new concept or eligibility interpretation; scope re-entry/version, or none]
- **Accepted-term retests:** [held-out records rescued/still missed, differential count, sample path, PubMed translation]

### Labelled-sample screening burden

- **Sampling design:** [complete-frame strata, shared/unique and rank bands, seed, sample size, date]
- **Labels:** [likely relevant / irrelevant / uncertain counts by variant and stratum]
- **Precision:** [weighted estimate, 95% confidence interval, uncertain-label lower/upper bounds]
- **Screening burden:** [estimated records screened per relevant report and confidence interval]
- **Incremental comparison:** [exact workload change and held-out recall change versus main]
- **Recall gate:** [minimum required recall, qualifying variants, whether burden was permitted to select, recommendation or none]

## Search strategy (numbered line set)

PubMed, searched [date]. Rendered by `audit_markdown.py` from `concept_blocks`; line numbers (`#n`) reference earlier lines as in the PubMed Advanced Search history.

| Line | Concept | Search query | Results |
|---|---|---|---:|
| #1 | [concept 1] | [block 1 query] | [count] |
| #2 | [concept 2] | [block 2 query] | [count] |
| #3 | Topic (combined) | #1 AND #2 | [final topic-only count] |
| #4 | Methodological filter | [filter query, or omit row] | [count or not applicable] |
| #5 | Topic + filter | #3 AND #4 | [count or not applicable] |

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
- Bramer reciprocal gap analysis: [performed / waived / not applicable / not performed]
- `MeSH/SCR NOT text-word` count: [count or not performed/not applicable]
- `text-word NOT MeSH/SCR` count: [count or not performed/not applicable]
- Gap samples inspected: [sample size and saved JSON path(s), or not performed/not applicable]
- Gap-derived terms/descriptors accepted: [list with rationale, or none]
- Gap-derived terms/descriptors rejected: [list with rationale, or none]
- Waiver rationale: [reason, or not applicable]

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
- Bramer reciprocal gap analysis: [performed / waived / not applicable / not performed]
- `MeSH/SCR NOT text-word` count: [count or not performed/not applicable]
- `text-word NOT MeSH/SCR` count: [count or not performed/not applicable]
- Gap samples inspected: [sample size and saved JSON path(s), or not performed/not applicable]
- Gap-derived terms/descriptors accepted: [list with rationale, or none]
- Gap-derived terms/descriptors rejected: [list with rationale, or none]
- Waiver rationale: [reason, or not applicable]

Repeat for additional essential concepts.

### MeSH derived from seed records

Seed PMIDs provided: **[Yes/No]**.

- If yes: [seed PMID list, assigned MeSH/keywords/title-abstract terminology that informed the strategy, and retrieval validation impact].
- If no: True seed-derived MeSH was **not available**. If sample records were fetched, label them as sample-record MeSH patterns, not seed-derived evidence: [summary, or not performed].
- Evidence file reviewed: [saved `mine`/`fetch` JSON path, or not applicable]
- Record content reviewed: [yes/no/not applicable]
- Abstracts reviewed: [yes/no/not available/not applicable]
- Receipt-only stdout used as decision evidence: no
- Decision supported: [yes/no/not applicable]

### Post-scope seed fetch and screening

- Requested seed entries: [list, or none]
- Normalized unique numeric PMIDs: [list, or none]
- Malformed entries excluded: [list and reason, or none]
- Fetched seed records: [PMID, title, year/publication type summary, or not performed]
- Evidence file reviewed: [saved `fetch` or `mine` JSON path, or not performed]
- Record content reviewed: [yes/no/not applicable]
- Abstracts reviewed: [yes/no/not available/not applicable]
- Receipt-only stdout used as decision evidence: no
- Decision supported: [yes/no/not applicable]
- Missing/not-found PMIDs excluded: [list, or none]
- Retracted seeds: [list and metadata signal, or none]
- Likely out-of-scope seeds: [list and reason, or none]
- User/protocol decision when paused: [exclude / replace / retain as special validation seed / not applicable]

### Seed-set expansion (related)

- Expansion run: **[Yes/No/not applicable - no usable seeds]**
- Link types used: [similar / citedin / refs, or none]
- Per-link candidate counts and caps: [link_counts, max-per-seed, max-total, or not performed]
- High-overlap candidate PMIDs used for term discovery: [list, or none]
- How related-set evidence was used: [fed to term-rank / recall heuristic / not used]
- Labelling: related-set evidence is recorded **separately from user-confirmed seed evidence** and is **not** treated as validated recall.

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
| Concept 1 - MeSH/SCR NOT text-word diagnostic gap | [count or not performed/not applicable] |
| Concept 1 - text-word NOT MeSH/SCR diagnostic gap | [count or not performed/not applicable] |
| Concept 1 - combined | [count] |
| Concept 2 - combined | [count] |
| Final combined topic-only strategy | [count] |
| Low-count plausibility check (`<500` final topic-only records) | [triggered/not triggered; diagnosis, revision decision, and final retest count if revised] |
| Topic-plus-filter or focused variant | [count or not applicable] |
| Differential/noise sample | [count and sample result, or not performed] |

For every row based on `fetch`, `mine`, or `sample` record content, record the saved JSON path in the Record-content evidence reviewed table.

### Relative-recall estimation

- Relative-recall check run: **[Yes/No/not performed]**
- Benchmark source: [independent gold standard (e.g. prior review included studies) / seed-expansion heuristic (related) / not applicable]
- Benchmark size: [n, or not performed]
- Relative recall: [percent, or not performed] (relative to the benchmark, **not** absolute sensitivity)
- Per-block recall and bottleneck block: [block recall percents and the lowest-recall block, or not performed]
- Misses and culprit blocks: [summary of missed PMIDs and the blocks responsible, including any and_interaction, or none]
- Caveat: relative recall is recorded **separately from known-item seed validation**; a seed-expansion benchmark is a heuristic that can flatter recall.

## Title/abstract, proximity, and wildcard expansion log

- **Pre-MeSH brainstorm required:** [yes/no and reason]
- **Domain-framing question asked:** [question and user answer, or not needed]
- **Brainstormed vocabulary families accepted:** [list, or none]
- **Brainstormed vocabulary families rejected:** [list with reason, or none]
- **Brainstormed vocabulary families deferred/reserved:** [list with reason, or none]
- **Stable/fragile/very-fragile concept classification:** [each essential concept with provisional/final status, total score, dimension scores, hard red flags, evidence sources used, and reason]
- **Fragility scoring dimensions:** [terminology stability; controlled-vocabulary/indexing reliability; explicitness of author reporting; retrieval/noise behavior; validation or pilot evidence; unknown dimensions scored as 1]
- **Fragility evidence sources:** [question/protocol wording, seed records, MeSH mapping, PubMed ATM/query translation, known-item or pilot retrieval, block counts, sample-record wording, or not performed]
- **Broad retrieval safety-layer check:** [fragile concepts checked, exact-label terms, descriptive/action terms, artifact/role terms, tethering logic, waivers with rationale, or not applicable for stable concepts]
- **Very-fragile leave-out alternative:** [concept omitted from sensitive main strategy and handled at screening / focused-reserve variant tested / protocol required inclusion / not applicable]
- **Safety-layer counts:** [exact-label layer count, descriptive/action layer count, combined block count, or not performed]
- **MeSH-entry-derived `[tiab]` variants added:** [list, or none]
- **Seed-derived `[tiab]` variants added:** [list, or n/a if no seeds]
- **Record-content evidence file reviewed:** [saved `mine`/`sample` JSON path, or not applicable]
- **Record content reviewed:** [yes/no/not applicable]
- **Abstracts reviewed:** [yes/no/not available/not applicable]
- **Receipt-only stdout used as decision evidence:** no
- **Decision supported:** [yes/no/not applicable]
- **Sample-record-derived `[tiab]` variants added:** [list, or not performed]
- **Acronyms and abbreviations added:** [list, or none retained]
- **Acronyms and abbreviations tested but rejected:** [list with reason, or not performed]
- **Singular/plural variants added:** [list]
- **Morphology review for singular/plural `[tiab]` phrase families:**

| Phrase family | Explicit forms | Phrase-anchored/concept-specific wildcard candidate | Tested? | Decision | Rationale |
|---|---|---|---|---|---|
| [phrase family] | [explicit singular/plural forms] | [phrase-final, phrase-anchored/concept-specific wildcard candidate, or not applicable] | [yes/no/not applicable] | [wildcard retained / explicit forms retained / wildcard not applicable] | [count/noise/recall rationale] |

- **Spelling variants added:** [list]
- **Hyphenation variants added:** [list]
- **Proximity candidates tested:** [exact phrase(s), Boolean AND, and proximity widths tested, or not applicable]
- **Proximity expressions added:** [list, or none]
- **Proximity expressions tested but rejected:** [list and reason, or not performed]
- **Proximity not applicable rationale:** [reason, or not applicable]
- **Wildcard stems added:** [list]
- **Wildcard stems tested but rejected:** [list and reason, or not performed]
- **Zero-hit terms removed (documented):** [list, or none]
- **Zero-hit terms kept after user choice (documented as intentional):** [list with reason, or none]

## Rationale

- **MeSH choices.** [Why included descriptors were selected and rejected descriptors were excluded.]
- **Text-word choices.** [Why title/abstract terms, spelling variants, acronyms, proximity, and wildcard stems were selected or rejected.]
- **Pre-MeSH vocabulary/domain choices.** [Why brainstormed vocabulary families were accepted, rejected, deferred, or treated as optional/focused concepts.]
- **Concept-gate and omitted-block choices.** [Dangerous optional blocks, user decisions, and screening-vs-search rationale.]
- **Methodological filters or limits.** [None used, or validated source/version/interface/adaptation and recall risk.]
- **Sensitivity vs precision.** [Chosen design, reserve/focused variants, count/workload evidence, seed impact if available.]
- **Low-count plausibility.** [If final topic-only count was `<500`, diagnosis, expansion/retest decision, before/after counts if revised, and why the final count is acceptable.]
- **QA.** `query_translation_drift`: [none/issues]; final query hygiene: [done/warnings]; `final-qa`: [none/issues]; `filter-check`: [none/not applicable/issues].

## PRESS-informed internal critic rounds

These rounds are automated internal QA, not PRESS peer review.

| Round | Scope version | Overall status | Findings | Open must-fix | Open actionable | Findings and dispositions | Artifact |
|---:|---:|---|---:|---:|---:|---|---|
| [1] | [1] | [revise/pass] | [count] | [count] | [count] | [summary] | [critic_round_1.json] |

## Revision-cycle ledger

| Revision | Critic round | Scope | Classification | Trigger finding | Change | Before/after evidence | Validation effect | Disposition | Artifact |
|---:|---:|---:|---|---|---|---|---|---|---|
| [1] | [1] | [1] | [lexical/structural/scope/filter/syntax/reporting] | [finding] | [exact change] | [counts, samples, evidence files, and required re-probes] | [holdout/seed effect] | [accepted/reverted/superseded] | [revision_cycle_1.json] |

For every critic or vocabulary revision, report the seven no-harm verdicts, failed checks, authoritative baseline/revised file, any labelled experimental variant, and exact before/after workload effect.

## PRESS 2015 element coverage

Map the audit's QA checks to the six PRESS 2015 elements ([McGowan et al. 2016](https://doi.org/10.1016/j.jclinepi.2016.01.021)). For each element, state `addressed`, `not applicable`, or `not performed` and link to the supporting section in this audit.

| PRESS 2015 element | Coverage | Notes / supporting section |
|---|---|---|
| 1. Translation of the research question | [addressed / not performed] | [framework choice and slot mapping; see Search structure] |
| 2. Boolean and proximity operators | [addressed / not performed] | [operator precedence, parenthesisation, proximity expressions; see Title/abstract expansion log] |
| 3. Subject headings | [addressed / not performed] | [MeSH/SCR descriptors considered, accepted, rejected; see MeSH descriptors considered] |
| 4. Text-word search | [addressed / not performed] | [tiab variants, synonyms, acronyms, spelling/hyphenation variants; see Title/abstract expansion log] |
| 5. Spelling, syntax, line numbers | [addressed / not applicable] | [query parse warnings; final-qa run; see PubMed CLI checks and QA] |
| 6. Limits and filters | [addressed / not applicable] | [methodological filter source/version/interface/adaptation; limits applied; see Methodological filters or limits] |

Peer review by an information specialist is still required before the strategy is run as a final search; this self-mapping is a coverage record, not a substitute for external PRESS peer review.

## Seed PMID validation

Seed PMIDs provided: **[Yes/No]**.

If yes:
- Post-scope seed fetch/screening summary: [malformed, missing/not-found, fetched, retracted, include/exclude/uncertain decisions, and discovery/holdout roles]
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
- **Run manifest:** [path saved, e.g. `run_manifest.json`, validated with `manifest_tool.py show --validate --check-files --require-complete-loop`]
- **Remaining caveats:** [seed validation, noisy terms, untested tree context, sample inspection limits, etc.]
- **Other databases:** Database-specific strategies for Ovid MEDLINE, Embase, CENTRAL, CINAHL, EconLit, grey literature, or other sources were [not requested / not built / built separately]. Do not present them unless separately constructed.

For PRISMA-S 2021 reporting items applicable to this skill, see `references/prisma-s-reporting.md`.

## PRISMA-S appendix (PubMed)

Paste-ready reporting block, rendered by `audit_markdown.py` and also emittable as a standalone file with `--emit-appendix`. Items follow PRISMA-S 2021.

- **Database (Item 1):** PubMed (NLM interface, https://pubmed.ncbi.nlm.nih.gov/).
- **Multi-database searching (Item 2):** [out of scope for this strategy; protocol should specify additional databases, each needing translation].
- **Full search strategy (Item 8):** the numbered line set above; final combined strategy reproduced verbatim.
- **Limits and restrictions (Item 9):** [none, or each limit with justification and recall risk].
- **Search filters (Item 10):** [none, or name/source/version/interface/adaptation].
- **Prior work (Item 11):** [cite adapted strategy, or not applicable].
- **Updates (Item 12):** [planned interval, or none].
- **Date of final search (Item 13):** [YYYY-MM-DD].
- **Peer review (Item 14):** [reviewer and date, or not yet peer reviewed].
- **Total records and deduplication (Items 15-16):** to be reported by the review team after the search is run.
````
