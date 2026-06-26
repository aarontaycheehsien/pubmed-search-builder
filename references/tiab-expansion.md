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

## Objective / data-driven term selection

Manual brainstorming and MeSH entry terms are necessary but not sufficient: the resulting term list reflects what the searcher could recall, not what the relevant literature actually uses. When seed PMIDs or a pilot relevant set are available, also derive terms objectively by measuring which words and MeSH headings are enriched in known-relevant records relative to PubMed as a whole. Raw frequency alone is misleading: generic words such as "patients" or the MeSH heading `"Animals"[Mesh]` occur in nearly every record, so rank candidates by discrimination, not by count.

Run `pubmed_tool.py term-rank` (see `mesh-and-pubmed-tools.md`) to score candidate terms from a relevant/seed set. `--fields` selects the scoring layers and accepts only `tiab` and/or `mesh` (default both): the `tiab` layer scores free-text candidates harvested together from titles, abstracts, acronyms, and author keywords, while `mesh` scores assigned MeSH headings. There is no separate `keywords`, `acronym`, or `phrase` field. The per-term scores are:

- `coverage`: the share of relevant records that contain the term (recall potential within known-relevant records).
- `background_count`: the term's count across PubMed (a noise proxy).
- `lift`: coverage divided by the term's PubMed prevalence (distinctiveness). High-coverage, high-lift terms are strong candidates; high-coverage but low-lift terms (e.g. `"Animals"[Mesh]`) are usually noise.

`term-rank` drops obvious non-topical noise before scoring so it does not crowd the ranked list: structured-abstract section labels (OBJECTIVE, METHODS, RESULTS, CONCLUSIONS, …), statistical fragments (e.g. `p 0`, `95 ci`), and non-topical MeSH — check tags (Humans, Animals, Male, Female, age groups) and common geographic descriptors (e.g. Queensland). The geographic list is curated rather than exhaustive, so a rare place name can still appear; treat any that does as noise.

Treat the ranked output as candidates, not automatic additions: confirm scope, check PubMed behaviour, and keep within-block `OR` synonyms that improve recall even when they are absent from a small seed set. This complements, and does not replace, the pre-MeSH vocabulary/domain brainstorm below; the brainstorm protects author-language and disciplinary framing that objective scoring on a small seed set cannot surface.

The relevant set fed to `term-rank` need not be only the raw seed PMIDs. When seeds exist, first expand them with `pubmed_tool.py related` (PubMed similar-articles and citation chaining) and pass the high-overlap candidate PMIDs to `term-rank`; a larger relevant set sharpens coverage and lift and surfaces vocabulary a 2-5 PMID seed set would miss. Keep related-set evidence labelled separately from user-confirmed seeds (see `seed-pmid-validation.md` and `mesh-and-pubmed-tools.md`).

When **no seeds** are supplied, objective ranking is still reachable, and this is the common case. After the concept gate resolves (during MeSH/PubMed exploration and block building, never before the gate), draft a small, deliberately **high-precision** pilot relevant-set query - the inverse of the final sensitive strategy, e.g. tight exact phrases for the one or two most distinctive concepts, `AND`ed together - and pass it via `pubmed_tool.py term-rank --relevant-query-file pilot.txt`. Bound the set with `--relevant-retmax` (default 200). Precision matters more than completeness here, because a noisy pilot set pollutes coverage and lift. Treat the ranked output as pilot-relevant-set candidates, labelled distinctly from seed-derived evidence; never report it as validated recall or search sensitivity, and do not bound the final strategy to pilot-query language (the overfitting rule for seeds applies equally - see `seed-pmid-validation.md`). Do not use this as a backdoor to run PubMed before the gate: building the pilot query is post-gate block-building work.

This follows the tradition of objectively derived search strategies (Hausner et al. 2012, *Syst Rev*, [doi:10.1186/2046-4053-1-19](https://doi.org/10.1186/2046-4053-1-19)) and word-frequency-analysis tools such as PubMed PubReMiner and the Yale MeSH Analyzer.

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

Use one of three approaches.

### 1. Safe wildcard stem

```text
ulcer*[tiab]
injur*[tiab]
wound*[tiab]
amputat*[tiab]
intervention*[tiab]
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
