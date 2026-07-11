# Title/Abstract Expansion

For high-sensitivity PubMed searching, `[tiab]` expansion is essential.

Recent records may lack MeSH indexing. Authors may use language that differs from MeSH. Indexing may be inconsistent. Acronyms may appear without full forms.

## Sources for `[tiab]` variants

Use:

- MeSH preferred descriptors
- MeSH entry terms
- MeSH scope notes
- narrower MeSH descriptors
- related MeSH descriptors
- seed paper titles
- seed paper abstracts
- author keywords, where available
- PubMed sample records
- common clinical or disciplinary synonyms
- acronyms and abbreviations
- acronym expansions
- spelling variants
- hyphenated and non-hyphenated forms
- singular and plural forms
- adjective and noun forms
- eponyms
- lay terms
- older terminology
- newer terminology
- drug generic names, brand names, and class names
- device, procedure, or intervention variants
- Greek-letter, spelled-out, and symbol variants
- Roman numeral and Arabic numeral variants

## Broad retrieval safety layer for fragile concepts

First classify each essential concept as `stable`, `fragile`, or `very_fragile` using the Fragility Scoring Rubric in `concept-analysis-and-gating.md`. If the concept-gate score was provisional, update it here using MeSH mapping, ATM/query translation, known-item or pilot retrieval, block counts, and sample-record wording. Add a broad retrieval safety layer only for fragile concepts before finalising the concept block. This protects recall when relevant records describe the idea without using the searcher's preferred label.

Fragile concepts include:

- methodological or study-design labels
- workflow, process, or implementation concepts
- health-services, setting, or service-delivery concepts
- social-science, behavioral, qualitative, or psychosocial constructs
- concepts with weak or recently changed MeSH coverage
- concepts with older/newer, regional, or discipline-specific wording
- author-described behaviors where papers may describe what happened rather than name the construct

Very fragile concepts are fragile concepts whose searchable language remains especially unreliable even after safety-layer thinking. Signals include very inconsistent author wording, mostly implicit reporting, highly generic action verbs, weak or absent controlled vocabulary, old literature with sparse abstracts, or pilot/known-item evidence that exact and descriptive layers both miss records or create unusable noise. Use the concept-gate hard red flags to upgrade to `very_fragile` even when the numeric score is lower. For very fragile concepts, first consider leaving the concept out of the sensitive main strategy and handling it at screening. If searched, usually keep it as a focused/reserve variant unless the protocol explicitly accepts the recall risk.

Stable concepts include established biomedical diseases, drugs, devices, organisms, or procedures with reliable MeSH coverage and predictable author wording. For stable concepts, record `safety layer not applicable - stable terminology/MeSH coverage` and proceed with normal MeSH plus `[tiab]` expansion.

For each fragile concept that remains in the search, include all applicable layers inside the same concept `OR` block:

- exact-label layer: controlled vocabulary, publication types where appropriate, formal names, acronyms, standard labels, and distinctive phrases
- descriptive-action layer: generic verbs/nouns and author-language patterns describing what happened rather than naming the concept
- artifact/role layer: protocols, pathways, algorithms, checklists, sequences, rosters, records, queues, forms, personnel roles, or other operational artifacts that authors may use to describe the concept
- historical/disciplinary layer: older/newer labels, regional wording, field-specific shorthand, spelling variants, and loosened phrase/proximity forms

The safety layer stays inside the same concept `OR` block. Do not turn it into a separate `AND` block. Generic descriptive terms must be context-tethered to trial, intervention, workflow, setting, population, or protocol anchors; do not leave broad verbs such as `assign*`, `screen*`, `refer*`, `triage*`, or `allocat*` floating alone. Keep the broader layer unless testing shows that it duplicates existing coverage or is unacceptably noisy after tethering and combination with the other essential blocks. A waived descriptive layer for a fragile concept needs an explicit audit reason and supporting evidence.

Examples of safety-layer thinking:

- A study-design concept may need trial/publication-type terms plus generic `assign*`, `allocat*`, `group*`, `controlled`, or `trial*` language tied to the intervention context.
- A workflow concept may need both exact workflow labels and broader words for the tasks authors perform.
- A setting concept may need formal service names plus local/regional labels, acronyms, and common author shorthand.

For fragile concepts, test the exact-label layer, descriptive/action layer, and combined concept block where feasible. If the descriptive layer is noisy, tighten the tether or preserve a focused/reserve variant; do not drop the layer by default. For stable concepts, normal MeSH-only, text-word-only, and combined block testing is sufficient.

For very fragile concepts, compare the sensitive strategy with the concept omitted against a focused/reserve variant containing the safety-layer block. Read-only diagnostic testing does not require advance authorization; adopting the narrower design does. Prefer omission from the sensitive strategy unless validation evidence or protocol direction shows that searching the concept is necessary and tolerably safe.

## Objective / data-driven term selection

Manual brainstorming and MeSH entry terms are necessary but not sufficient: the resulting term list reflects what the searcher could recall, not what the relevant literature actually uses. When seed PMIDs or a pilot relevant set are available, also derive terms objectively by measuring which words and MeSH headings are enriched in known-relevant records relative to PubMed as a whole. Raw frequency alone is misleading: generic words such as "patients" or the MeSH heading `"Animals"[Mesh]` occur in nearly every record, so rank candidates by discrimination, not by count.

Run `pubmed_tool.py term-rank` (see `mesh-and-pubmed-tools.md`) to score candidate terms from a relevant/seed set. `--fields` selects the scoring layers and accepts only `tiab` and/or `mesh` (default both): the `tiab` layer scores free-text candidates harvested together from titles, abstracts, acronyms, and author keywords, while `mesh` scores assigned MeSH headings. There is no separate `keywords`, `acronym`, or `phrase` field. The per-term scores are:

- `coverage`: the share of relevant records that contain the term (recall potential within known-relevant records).
- `background_count`: the term's count across PubMed (a noise proxy).
- `lift`: coverage divided by the term's PubMed prevalence (distinctiveness). High-coverage, high-lift terms are strong candidates; high-coverage but low-lift terms (e.g. `"Animals"[Mesh]`) are usually noise.
- `supporting_pmids` and `marginal_record_count_at_selection`: which discovery records support a term and how many records it newly represents when the bounded scoring budget selects it.

The background-count budget is selected round-robin across MeSH, author-keyword, acronym, and phrase layers, with deterministic marginal-record coverage inside each layer. This prevents frequent MeSH or generic phrases from consuming every API call while rare terms that rescue one discovery record go untested.

`term-rank` drops obvious non-topical noise before scoring so it does not crowd the ranked list: structured-abstract section labels (OBJECTIVE, METHODS, RESULTS, CONCLUSIONS, …), statistical fragments (e.g. `p 0`, `95 ci`), and non-topical MeSH — check tags (Humans, Animals, Male, Female, age groups) and common geographic descriptors (e.g. Queensland). The geographic list is curated rather than exhaustive, so a rare place name can still appear; treat any that does as noise.

Treat the ranked output as candidates, not automatic additions: confirm scope, check PubMed behaviour, and keep within-block `OR` synonyms that improve recall even when they are absent from a small seed set. This complements, and does not replace, the pre-MeSH vocabulary/domain brainstorm below; the brainstorm protects author-language and disciplinary framing that objective scoring on a small seed set cannot surface.

The relevant set fed to `term-rank` must come from the validated candidate ledger. When seeds exist, expand screened-in records with `pubmed_tool.py related`, screen the candidates, and pass only PMIDs assigned `discovery` or `both`. High overlap and similarity prioritize screening but do not establish relevance. Keep user seeds, screened discovery records, holdouts, and heuristic neighbors distinct (see `candidate-screening.md` and `seed-pmid-validation.md`).

When **no seeds** are supplied, objective ranking remains available after scope version 1 is locked. Draft a deliberately high-precision pilot query, fetch its candidate anchors, and screen them against the scope. Then pass only screened-in discovery PMIDs to `term-rank --pmids`; do not treat raw pilot hits as relevant merely because the pilot is precise. Bound candidate discovery, label all provenance, and never report pilot-derived evidence as validated recall or sensitivity.

This follows the tradition of objectively derived search strategies (Hausner et al. 2012, *Syst Rev*, [doi:10.1186/2046-4053-1-19](https://doi.org/10.1186/2046-4053-1-19)) and word-frequency-analysis tools such as PubMed PubReMiner and the Yale MeSH Analyzer.

`term-rank` scores terms you already thought of. To also discover terms you *didn't*, inspect where a concept block's MeSH layer and `[tiab]` layer disagree — **`(MeSH) NOT (tiab)`** reveals free-text phrasings to add to the `[tiab]` layer, and **`(tiab) NOT (MeSH)`** reveals candidate descriptors and indexing gaps. This is the conditional **Bramer reciprocal gap analysis**; run it in one call with `pubmed_tool.py term-diff` (or manually with `search`/`sample`). See `references/bramer-reciprocal-gap-analysis.md` for when to run it, interpretation, and audit requirements, and `mesh-and-pubmed-tools.md` for the command. It is a term-discovery aid, not validated recall, and recall-only: use it to add coverage, never to remove terms.

## Pre-MeSH vocabulary/domain brainstorm

Run a brief brainstorm before MeSH lookup for social-science, psychosocial, behavioral, qualitative, health-services, and weak-controlled-vocabulary concepts. This protects author-language and disciplinary vocabulary from being narrowed too early by MeSH.

Consider:

- construct names and near constructs
- lived-experience language
- disciplinary or theory language
- adjacent theories and frameworks
- help-seeking, access, barriers, facilitators, and service-use language
- identity, marginalisation, minority-stress, discrimination, and inequity language
- disclosure, concealment, privacy, and openness language
- unmet need, perceived need, self-perceived need, and treatment need language
- public, self, structural, enacted, anticipated, internalised, and felt forms for stigma-like concepts
- author keywords and seed-paper wording, when available

For stigma-like concepts, examples of vocabulary families to consider include:

```text
stigma OR stigmatization OR stigmatized
public stigma OR self stigma OR structural stigma
felt stigma OR enacted stigma OR anticipated stigma OR internalised stigma
minority stress OR discrimination OR prejudice
concealment OR disclosure OR openness
help seeking OR care seeking OR service use
unmet need OR perceived need OR treatment need
```

Use brainstormed vocabulary as candidates, not as automatic additions. Accept, reject, or defer each vocabulary family after checking scope, user/protocol intent, PubMed behavior, and recall/noise impact.

## Variant checklist

For each important phrase, consider:

```text
full phrase
short phrase
acronym
acronym with punctuation
singular
plural
hyphenated form
non-hyphenated form
closed compound
open compound
UK spelling
US spelling
noun form
adjective form
older term
newer term
eponym
lay term
technical term
truncated stem
word-order variant
```

Do not assume one exact phrase is enough.

## Plural handling

Do not assume PubMed will automatically handle plurals when terms are field-tagged with `[tiab]`.

Use one of three approaches, and document the morphology decision in the audit. For each important quoted `[tiab]` phrase family with singular/plural variants, default to phrase-anchored or concept-specific wildcard candidates where feasible; otherwise retain explicit singular/plural forms with a rationale, or combine phrase variants with wildcard stems. When a phrase-final wildcard may affect recall, test it before deciding.

### 1. Tested or context-safe wildcard stem

```text
"pressure ulcer*"[tiab]
"diabetic foot ulcer*"[tiab]
"checkpoint inhibitor*"[tiab]
postamputat*[tiab]
```

### 2. Explicit singular and plural phrase variants

```text
"pressure injury"[tiab]
OR "pressure injuries"[tiab]
OR "pressure ulcer"[tiab]
OR "pressure ulcers"[tiab]
```

### 3. Phrase variants plus wildcard stems

```text
"phantom limb"[tiab]
OR "phantom limbs"[tiab]
OR "phantom limb pain"[tiab]
OR amputat*[tiab]
OR postamputat*[tiab]
```

## Phrase loosening

For distinctive multi-word concepts, include exact phrases and looser variants.

Example:

```text
"shared decision making"[tiab]
OR "shared decision-making"[tiab]
OR "shared decision"[tiab]
OR "decision sharing"[tiab]
OR ((shared[tiab] OR sharing[tiab]) AND decision*[tiab])
```

Use looser constructions when exact phrases may miss records.

Do not use loose constructions that overwhelm the concept unless PubMed testing suggests they rescue relevant records or remain acceptable when combined with another concept block.

## Proximity searching (preferred for many phrase-loosening cases)

PubMed has supported proximity searching since November 2022 (NLM Tech Bull. 2022 Nov-Dec). Syntax:

```text
"word1 word2"[field:~N]
```

- `field` must be `[ti]`, `[tiab]`, or `[ad]`. Other fields are not supported.
- `N` is the maximum number of words that may appear between the search terms, in any order.
- Two or more terms inside the double quotes.

Examples:

```text
"shared decision making"[tiab:~2]
"rationing healthcare"[tiab:~2]
"hip pain"[ti:~4]
```

Important behaviour:

- Automatic Term Mapping is **not** applied to proximity searches.
- Truncation/wildcards (`*`) inside the quoted terms cause the proximity operator to be ignored. Choose either proximity or wildcards in a given expression, not both.
- Stopwords inside quoted proximity terms are searched as regular words.
- A higher `N` increases recall but also noise. Test multiple values of `N`.

## Proximity review pass

Run a proximity review for phrase-like concepts before finalising the text-word layer. This is a review-and-test step, not an instruction to insert proximity automatically.

Source-grounded triggers:

- [PubMed Help](https://pubmed.ncbi.nlm.nih.gov/help/#proximity-searching): review proximity when terms need to appear in any order within `[ti]`, `[tiab]`, or `[ad]`, and compare `N` values because higher `N` broadens retrieval while lower `N` may miss records.
- [NLM Tech Bull. 2022](https://www.nlm.nih.gov/pubs/techbull/nd22/nd22_pubmed_proximity_search_available.html): review proximity when a concept may be represented in multiple ways or by phrase variants; compare proximity with exact phrases and Boolean `AND`.
- [Cochrane Technical Supplement / MECIR C33](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/chapter04-tech-supplonlinepdfv65270924): use proximity operators appropriately because they can be more sensitive than direct adjacency or phrase searching and can replace many typed-out phrase variants.
- [PRESS](https://work.cochrane.org/sites/work.cochrane.org/files/uploads/checklist_searches_for_editors_cochrane_work.pdf): review whether proximity could improve precision over `AND` and whether the chosen width is too narrow or too broad.

Trigger a review when:

- a concept uses multiple exact phrase variants with shared content words
- phrase wording or word order varies in the literature
- PubMed reports a quoted phrase as not found in the phrase index
- loose same-field `[tiab] AND [tiab]` wording is used inside one concept block

Do not retain proximity automatically. Test exact phrase(s), Boolean `AND`, and proximity variants, usually `~0`, `~1`, `~2`, and `~3`. Retain the narrowest proximity width that captures expected variants without unacceptable noise. Use `~0` specifically as PubMed's recommended fallback for quoted phrases that are not in the phrase index.

Reject or mark proximity `not applicable` when terms need wildcard/truncation, exact order is essential, a stable named phrase is sufficient, the phrase variation is only singular/plural or hyphenation, or testing shows noise/no added recall. Record retained, rejected, and not-applicable proximity decisions in the audit.

When to prefer proximity over loose Boolean:

- distinctive multi-word concepts where word order varies in the literature (e.g. "shared decision making" / "decision making shared with patient")
- where `(X OR Y) AND Z*[tiab]` constructions retrieve too much unrelated noise
- where the exact phrase variants are numerous and brittle

When **not** to use proximity:

- when one of the words in the phrase needs truncation that proximity cannot accommodate
- when the concept is well captured by a tight exact phrase plus a few hyphenation variants
- when a MeSH heading already covers the concept reliably

Pattern combining proximity with the rest of a concept block:

```text
(
  "Decision Making, Shared"[Mesh]
  OR "shared decision making"[tiab]
  OR "shared decision-making"[tiab]
  OR "shared decisionmaking"[tiab]
  OR "shared decision"[tiab:~2]
  OR "decision shared"[tiab:~2]
)
```

## Proximity testing protocol

For proximity expressions that may affect recall, use the PubMed script to compare:

1. exact phrase and common phrase/hyphenation variants
2. proximity at multiple distances, usually `~1`, `~2`, and `~3`
3. the concept block with and without the proximity expression
4. the full strategy with and without the proximity expression when the effect may be material
5. whether the proximity expression retrieves seed PMIDs
6. whether sample records are plausible
7. whether the proximity expression causes unacceptable noise when combined with another concept block

Use larger distances only with a reason. If a proximity expression broadens too far, narrow `N`, replace it with explicit phrase variants, or reject it. Document kept and rejected proximity expressions in the final output.

## Acronyms

Include common acronyms as candidates.

For ambiguous acronyms:

1. test the acronym alone
2. test it inside the concept block
3. test it with another essential concept
4. inspect sample records
5. keep it if it plausibly retrieves relevant records
6. restrict to `[ti]` only if `[tiab]` is catastrophically noisy

Do not discard acronyms solely because they are ambiguous.

## Watch list for historically drifting or weakly indexed terms

Expand these term families aggressively in `[tiab]` and test against seeds. Controlled vocabulary alone is often insufficient because indexing lags behind authors' usage or because the concept lacks a stable MeSH heading.

### Qualitative methodology labels

MeSH coverage of qualitative methodology is sparse and inconsistent. Include text-word variants:

```text
qualitative[tiab]
OR "qualitative research"[tiab]
OR "qualitative study"[tiab] OR "qualitative studies"[tiab]
OR phenomenolog*[tiab]
OR "grounded theory"[tiab]
OR ethnograph*[tiab]
OR "thematic analysis"[tiab]
OR "content analysis"[tiab]
OR "narrative analysis"[tiab]
OR "discourse analysis"[tiab]
OR "interpretive description"[tiab]
OR "interpretative phenomenological analysis"[tiab]
OR "lived experience"[tiab] OR "lived experiences"[tiab]
OR "focus group"[tiab] OR "focus groups"[tiab]
OR "semi structured interview"[tiab]
OR "semi-structured interview"[tiab]
```

### Newer disease constructs without stable MeSH

When MeSH has not yet stabilised for a concept, rely heavily on `[tiab]`:

```text
"long COVID"[tiab]
OR "long-COVID"[tiab]
OR "post acute sequelae"[tiab]
OR "post-acute sequelae"[tiab]
OR PASC[tiab]
OR "post covid"[tiab] OR "post-covid"[tiab]
OR "chronic covid"[tiab]
OR "post covid syndrome"[tiab]
OR "post covid condition"[tiab]
```

Apply the same approach to other emerging constructs (e.g., newly named syndromes, novel therapeutic classes, recent technologies). If such a variant currently returns zero PubMed records, the final validation gate (`workflow.md` §9) removes and documents it by default; but because an emerging term may gain records as the literature grows, keep it when future-proofing a search that will be re-run (PRISMA-S Item 12), after first ruling out a spelling or hyphenation typo.

### Historical and regional synonym pairs

MeSH may use the current preferred term, but older literature uses the historical form. Include both:

- `"manic depression"[tiab]` / `"manic depressive"[tiab]` for bipolar
- `"senile dementia"[tiab]` for Alzheimer/dementia
- `"juvenile diabetes"[tiab]` for type 1 diabetes
- `"adult onset diabetes"[tiab]` / `"adult-onset diabetes"[tiab]` for type 2 diabetes

### Setting synonyms

Settings are described with regional and disciplinary variation:

```text
"primary care"[tiab]
OR "general practice"[tiab]
OR "family medicine"[tiab]
OR "family practice"[tiab]
OR "primary health care"[tiab]
OR "community health"[tiab]
OR "ambulatory care"[tiab]
OR "outpatient care"[tiab]
```

### Patient-reported outcome measure (PROM) names

PROMs are often referred to by acronym, by full name, by version number, or by author/year. Include variants:

```text
PROMIS[tiab]
OR "Patient Reported Outcomes Measurement Information System"[tiab]
OR EQ-5D[tiab] OR EQ5D[tiab] OR "EuroQol"[tiab]
OR SF-36[tiab] OR SF36[tiab] OR "Short Form 36"[tiab]
OR "Hospital Anxiety and Depression Scale"[tiab] OR HADS[tiab]
```

Verify each PROM term against seed records when seeds are supplied. PROM names may be too narrow or too broad depending on the review scope.
