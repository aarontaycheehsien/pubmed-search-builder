# Workflow

Use this detailed workflow when constructing a new high-sensitivity PubMed strategy. When the skill is invoked, the task is strategy construction, even if the user's wording looks like a clinical, prevalence, treatment, prognosis, or background question. Do not search PubMed or the web to answer the evidence question; first ask for optional seed PMIDs, then build and validate the Boolean strategy.

Core sequence:

```text
question
-> seed PMID decision
-> limited seed fetch/mining, if supplied, only to inform concept analysis
-> formal concept analysis and concept gate
-> pre-MeSH vocabulary/domain brainstorm for weak-MeSH or social-science concepts
-> MeSH/PubMed exploration
-> text-word, proximity, and wildcard candidate generation
-> concept-block construction and testing
-> seed PMID validation, if seeds were provided
-> revision
-> final query hygiene and QA
-> save audit Markdown file with decision ledger
-> documented draft strategy for human PRESS peer review
```

High-sensitivity PubMed strategies use this mental model:

```text
(MeSH layer OR title/abstract layer OR proximity/wildcard layer)
AND
(MeSH layer OR title/abstract layer OR proximity/wildcard layer)
```

MeSH does not replace free text. Free text does not replace MeSH. Proximity and wildcards do not replace either.

## 1. Understand the review question

Identify:

- population or problem
- intervention, exposure, phenomenon, or condition
- comparator, if essential
- outcome, if essential
- study type, if explicitly required
- setting, date, language, publication type, or other limits, if explicitly required

Do not assume every PICO element belongs in the search.

For high sensitivity, outcomes and comparators are often omitted unless central to the topic.

## 2. Ask once for seed PMIDs

Ask the user once whether they have known relevant seed PMIDs. Make clear that seeds are optional. If the user has already provided seeds, do not ask again. This is the first action after understanding the review question; do not run PubMed answer searches first.

Pause and wait for the user's answer before running MeSH/PubMed exploration, drafting the strategy, searching PubMed for substantive answers, or asking the concept-gate question. Continue only after the user supplies seed PMIDs, says they have no seeds, or explicitly asks to proceed without seeds.

If seed PMIDs are supplied, limited fetch/mining of those PMIDs is allowed after the seed decision and before the concept gate solely to inform the concept-analysis ledger. Do not use this as permission for broader PubMed exploration, block testing, validation, variants, final QA, or filter checks.

## 3. Run formal concept analysis and the concept gate

Use `concept-analysis-and-gating.md` as the canonical procedure for the detailed ledger, seed/no-seed branches, role definitions, sensitivity-dangerous concept handling, and concept-gate pilot-test protocol. Use `goal-tracking.md` for `/goal` pre-creation rules and active-goal behavior.

Run this step after the seed PMID decision is resolved and, when seed PMIDs were supplied, after limited seed fetch/mining for concept evidence. Run it before MeSH lookup, broad PubMed exploration, or concept-block drafting. The goal is to decide which concepts become essential `AND` blocks, which remain inside existing `OR` blocks, which are omitted for sensitivity, and which require a methodological/filter decision.

Pause before MeSH lookup or concept-block construction whenever a candidate concept could become a sensitivity-dangerous `AND` block or filter. For `/goal`, do not call `create_goal` while seed status, concept-gate decisions, or required filter/limit decisions are unresolved; ask only the next unresolved decision.

Prefer fewer `AND` blocks.

Use:

```text
(concept 1)
AND
(concept 2)
```

or:

```text
(concept 1)
AND
(concept 2)
AND
(concept 3)
```

Avoid:

```text
(population)
AND
(intervention)
AND
(comparator)
AND
(outcome)
AND
(study design)
```

unless each block is truly essential.

## 4. Run the pre-MeSH vocabulary/domain brainstorm

Before MeSH lookup, run a lightweight vocabulary brainstorm for any social-science, psychosocial, behavioral, qualitative, health-services, or weak-controlled-vocabulary concept. For straightforward biomedical concepts with stable MeSH and terminology, this may be brief and documented as not needed.

Use `tiab-expansion.md` for the social-science/psychosocial checklist. Include author-language, disciplinary synonyms, adjacent theories, lived-experience terms, access/help-seeking terms, identity/minority-stress terms, disclosure/concealment terms, and unmet/perceived-need terms when relevant.

Ask one concise user-facing domain-framing question before MeSH lookup when vocabulary framing can materially change the strategy. Use wording like:

```text
Before MeSH lookup, I see several possible vocabulary frames for this concept: [A], [B], [C]. Should the sensitive strategy include all as within-block synonyms, or should any be treated as separate optional/focused concepts?
```

Do not ask about ordinary synonyms that clearly stay inside an existing `OR` block. Do not turn brainstormed adjacent constructs into extra `AND` blocks unless the user or protocol confirms they are essential.

Record accepted, rejected, and deferred brainstormed vocabulary families for the final audit.

## 5. Build each concept block

Before selecting MeSH headings, run the pre-MeSH brainstorm where required, then run an aggressive MeSH sweep. Do not rely on a single descriptor lookup. Use `mesh-and-pubmed-tools.md` for the bundled `mesh_tool.py` and `pubmed_tool.py` commands referenced in this workflow.

For each essential concept:

1. Create a variant list from the user phrase, pre-MeSH brainstormed vocabulary, synonyms, acronyms, spelling variants, hyphenation variants, older/newer terminology, seed-paper title/abstract terms, seed-paper MeSH headings, and PubMed ATM/query translation clues.
2. Run `mesh_tool.py sweep --concept "..." --variant "..." --details`.
3. After each MeSH sweep, do not draft the concept block yet. Complete a MeSH candidate ledger first:
  - List sweep inputs separately from sweep outputs.
  - Add candidates from MeSH sweep output, seed-assigned MeSH, PubMed ATM/query translations, and sample-record indexing.
  - For each plausible descriptor or supplementary concept record (SCR), inspect descriptor details, scope, entry terms, related descriptors, and tree/explosion context where relevant.
  - Run `mesh_tool.py tree --descriptor ...` for every included descriptor and for every plausible rejected descriptor where scope, sibling context, descendants, SCR mapping, or explosion/noexp could affect the decision.
  - Accept, reject, or defer each candidate with a reason.
  - Harvest all non-ambiguous entry terms from accepted descriptors/SCRs as `[tiab]` candidates; document omitted entry terms.
  - Run separate sweeps for important subtypes, procedures, devices, drugs, acronyms, older terms, and newer terms, or state why they were not needed.
  - Test accepted descriptors in PubMed; test plausible rejected descriptors when the decision affects recall or noise.
  - Test MeSH-only, text-word-only, and combined concept-block counts.
  - Resolve or document all MeSH/SCR mappings surfaced by PubMed ATM before finalising the block.
4. Draft the concept block only after the candidate ledger is complete.

Each block should usually include:

- MeSH heading
- narrower MeSH headings, where useful
- MeSH entry terms as `[tiab]`
- seed-paper title and abstract terms
- synonyms
- acronyms
- singular and plural forms
- spelling variants
- hyphenation variants
- older and newer terminology
- proximity expressions (`"word1 word2"[tiab:~N]`) where word order varies
- wildcard stems where useful

Use `wildcard-and-truncation.md` before accepting proximity expressions or wildcard stems, especially when a stem may be short, ambiguous, or likely to retrieve unrelated concepts.

Pattern:

```text
(
  "Preferred MeSH Term"[Mesh]
  OR "Narrower MeSH Term"[Mesh]
  OR "entry term phrase"[tiab]
  OR synonym[tiab]
  OR acronym[tiab]
  OR "phrase variant"[tiab]
  OR "word1 word2"[tiab:~3]
  OR truncat*[tiab]
)
```

If a methodological filter is needed (study design, evidence type, age group, etc.), do not build an ad hoc block first. Use `validated-methodological-filters-and-hedges.md` to choose a validated, PubMed-appropriate filter where available. Common source families include Cochrane HSSS, McMaster HIRU Hedges, PubMed Clinical Queries, and the ISSG Search Filters Resource. Cite the source, version, interface, and any adaptation.

## 6. Decide whether a methodological filter or hedge is needed

Only add a methodological filter when the protocol or user genuinely requires a study design, evidence type, age group, species group, or other filter.

If a filter is needed:

1. Identify the filter purpose.
2. Choose a validated PubMed filter where available.
3. Prefer sensitivity-maximising versions for evidence synthesis.
4. Avoid copying Ovid, Embase, or CINAHL syntax into PubMed.
5. Record the source, version, interface, and any adaptation.
6. Plan to test both the topic-only strategy and the topic-plus-filter strategy.

If no filter is needed, state that no methodological filter was applied and why.

See `validated-methodological-filters-and-hedges.md`.

## 7. Test iteratively

Use `mesh-and-pubmed-tools.md` for PubMed count, sample, batch, validation, and variant commands used during iterative testing.

Test:

1. each accepted MeSH term
2. each plausible but rejected MeSH term
3. each major text-word cluster
4. each proximity expression that may affect recall, including exact phrase comparisons, multiple `N` values where useful, concept-block with/without comparisons, and seed PMID impact when seeds exist
5. each wildcard stem that may affect recall
6. each concept block
7. each pair of blocks
8. the full topic-only strategy
9. the full topic-plus-filter strategy, if a filter is used
10. the strategy against seed PMIDs, if provided
11. whether adding the filter causes seed PMIDs to be lost
12. labelled search design alternatives with `pubmed_tool.py variants` when sensitivity/precision or workload trade-offs matter

When seed PMIDs were provided, use `seed-pmid-validation.md` for known-item validation, missed-seed diagnosis, and topic-only versus topic-plus-filter seed retrieval checks.

## 7a. Record search design alternatives

When broad terms, optional blocks, proximity distance, wildcards, or filters create a meaningful sensitivity/workload trade-off, create a search design ledger with labelled alternatives:

- `sensitive` or `main`: recall-first baseline
- `focused`: removes or narrows noisy terms while preserving essential concepts
- `precision`: intentionally workload-reducing design
- `filter`: topic-plus-methodological-filter design
- `reserve`: plausible fallback not selected

For each design, record the hypothesis, changes from baseline, recall risk, workload rationale, decision status, and decision reason. Use `pubmed_tool.py variants --seed-pmids ...` to attach known-item retrieval when seeds exist. Use `--labelled-samples labelled_samples.json` only when a PMID-level relevance-labelled pilot sample exists. NNR equals labelled sample size divided by relevant labelled records; without labels, report counts as workload proxies, not precision.

Select the sensitive design by default. Prefer a focused design only when it preserves all in-scope seed PMIDs, keeps MeSH plus text-word coverage for each essential concept, materially reduces count or estimated NNR, avoids parse/translation hazards, and documents every removed or narrowed term, filter, or block.

## 7b. Maintain and write the final audit Markdown ledger

Final output uses the template in `audit-template.md`. Use `prisma-s-reporting.md` for PRISMA-S reporting notes and evidence-synthesis reporting caveats. While searching, keep enough notes to populate that report without reconstructing unsupported details later.

For every completed strategy build, create a Markdown audit file in the user's working/output folder, preferably `audit_YYYY-MM-DD.md` or `audit_<topic-slug>_YYYY-MM-DD.md`. The file must contain the final strategy audit report and a decision ledger. If a matching audit file already exists, do not overwrite it silently; use a clear suffix or ask when overwriting is ambiguous. Report the saved audit Markdown path in the final response. If a structured audit JSON artifact was created, also report that JSON path in the final response and Reporting notes. The optional `.xlsx` audit workbook is a supplement, not a replacement for the Markdown audit file.

When possible, collect the audit facts into a structured JSON object, save that object to a UTF-8 audit JSON file such as `audit_<topic-slug>_YYYY-MM-DD.json`, and render the report from that file with `scripts/audit_markdown.py`. The tool writes the full Markdown report to disk and prints only a compact JSON receipt by default, which keeps token use low during long strategy builds. Use `--if-exists suffix` when an automatic clear suffix is preferred over failing on an existing file. Avoid large shell pipelines such as PowerShell `ConvertTo-Json | python scripts/audit_markdown.py -`; for completed strategy builds, file-based JSON input is the reliable path.

Record:

- decision ledger: each user/protocol or search-design decision point, options considered, evidence or test used, decision made, rationale or recall-risk note, and where the decision is reflected in the strategy/report
- search structure: essential blocks, within-block terms, concept-gate status, dangerous optional blocks, user decisions, filters, and omitted concepts
- MeSH work per concept: candidate ledger inputs and outputs, candidate sources, `tree` outputs or unusual SPARQL follow-ups where actually checked, accepted/rejected/deferred descriptors or SCRs with rationale, entry terms harvested and omitted, ATM/SCR mapping decisions, and MeSH-only/text-word-only/combined block counts
- seed or sample record evidence: seed-derived MeSH only when seed PMIDs were supplied; otherwise label any fetched-record MeSH as sample-record patterns
- pre-MeSH brainstorm evidence: vocabulary families considered, domain-framing question and answer when asked, and accepted/rejected/deferred brainstorm terms
- PubMed query translation observations: free-text exploratory queries, ATM mappings, parse warnings, and whether any mapping was added explicitly
- PubMed count checks: MeSH-only, text-word-only, combined concept blocks, pairwise blocks when useful, final topic-only strategy, topic-plus-filter strategy, focused/reserve variants, and differential/noise samples when run
- title/abstract expansion decisions: MeSH-entry-derived terms, seed-derived terms, sample-record-derived terms, acronyms added or rejected, singular/plural forms, spelling and hyphenation variants, proximity expressions added or rejected, and wildcard stems added or rejected
- sample inspection notes: number inspected, sampling method or sort, observed relevance/noise patterns, and whether records were formally labelled
- QA and reporting notes: final query hygiene, `query_translation_drift`, `final-qa`, `filter-check`, limits/restrictions, audit workbook path, and remaining caveats

Guardrails:

- If an item was not tested, say `not performed`.
- If a data source cannot support an item, say `not available`.
- If an item does not apply to the topic, say `not applicable`.
- Do not report true seed-derived MeSH, known-item recall, formal precision, or NNR unless the necessary seed PMIDs or labelled samples were provided and tested.
- Do not report exact top-page relevance counts unless those records were actually inspected and labelled during the run.
- Do not present comprehensive MeSH tree positions unless `tree`, unusual SPARQL follow-up checks, or equivalent tree evidence were actually run; `details` alone is not comprehensive tree review.
- Do not reconstruct command history that was not recorded. Summarize tool work performed from available outputs.
- Do not imply PRESS peer review, non-PubMed database translations, or grey-literature coverage unless they were actually performed.

## 8. Revise

Revise when:

- a seed PMID is missed
- a term retrieves mostly unrelated concepts
- a MeSH heading is too broad or too narrow
- a concept block is over-constrained
- a phrase is too exact
- a wildcard stem is too short or too noisy
- a recent record lacks MeSH indexing and needs text-word coverage
- an in-scope seed PMID is lost after adding a methodological filter

## 9. Final query hygiene

Before presenting the final draft:

1. Save the final topic-only strategy, and topic-plus-filter strategy if applicable, as UTF-8 query files.
2. Deduplicate exact repeated terms inside `OR` blocks while retaining intentional spelling, plural, hyphenation, field-tag, and proximity variants.
3. Run `pubmed_tool.py search --query-file ... --retmax 0`.
4. Review PubMed parse/translation warnings, especially `quotedphrasesnotfound`, `phrasesignored`, output messages, and `query_translation_drift` issues.
5. Remove, replace, or justify dead quoted phrases and other warnings, then rerun until warnings are resolved or documented.
6. If variants were tested, rerun the selected final variant after hygiene so the reported count matches the delivered strategy.
7. Run `hooks_tool.py final-qa --strategy-file ...` after the final query text stabilizes.

Do not use hygiene to silently narrow a recall-first strategy.

## 10. Stop

Stop when:

- the concept gate is completed, skipped with a stated reason, or not applicable
- in-scope seed PMIDs are retrieved, or misses are explained
- essential concepts have MeSH and text-word coverage after an aggressive MeSH sweep
- accepted and rejected plausible MeSH descriptors/supplementary concepts are documented
- important variants have been considered
- any methodological filter has been chosen from a validated source where available
- the topic-only and topic-plus-filter versions have been compared when a filter is used
- final query hygiene has removed exact duplicates and dead PubMed phrases, or remaining warnings are documented
- further expansion mainly adds unrelated noise
- audit Markdown file with decision ledger has been saved and its path is reported
- caveats are documented
- the strategy is flagged as a draft pending human peer review (PRESS, McGowan et al., 2016)
