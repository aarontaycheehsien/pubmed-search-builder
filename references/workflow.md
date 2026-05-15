# Workflow

Use this detailed workflow when constructing a new high-sensitivity PubMed strategy.

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

Ask the user once whether they have known relevant seed PMIDs. Make clear that seeds are optional and that you will proceed without them. If the user has already provided seeds, do not ask again.

If the user does not provide seed PMIDs, proceed.

## 3. Select essential concepts

Classify each candidate concept as:

- essential concept
- possible concept
- omitted concept
- filter concept

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

## 4. Build each concept block

Before selecting MeSH headings, run an aggressive MeSH sweep. Do not rely on a single descriptor lookup.

For each essential concept:

1. Create a variant list from the user phrase, synonyms, acronyms, spelling variants, hyphenation variants, older/newer terminology, seed-paper title/abstract terms, seed-paper MeSH headings, and PubMed ATM/query translation clues.
2. Run `mesh_tool.py sweep --concept "..." --variant "..." --details`.
3. Inspect all plausible descriptors/supplementary concepts, entry terms, related descriptors, qualifiers where available, and tree/explosion implications.
4. Run separate sweeps for clinically meaningful subtypes, syndromes, devices, procedures, drug classes, generic drug names, common acronyms, newer terminology, and older terminology.
5. Test accepted and rejected descriptors in PubMed with `pubmed_tool.py search '"Descriptor"[Mesh]' --retmax 0`.
6. Document rejected plausible descriptors/supplementary concepts with reasons.

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

## 5. Decide whether a methodological filter or hedge is needed

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

## 6. Test iteratively

Test:

1. each accepted MeSH term
2. each plausible but rejected MeSH term
3. each major text-word cluster
4. each proximity expression that may affect recall
5. each wildcard stem that may affect recall
6. each concept block
7. each pair of blocks
8. the full topic-only strategy
9. the full topic-plus-filter strategy, if a filter is used
10. the strategy against seed PMIDs, if provided
11. whether adding the filter causes seed PMIDs to be lost

## 7. Revise

Revise when:

- a seed PMID is missed
- a term retrieves mostly unrelated concepts
- a MeSH heading is too broad or too narrow
- a concept block is over-constrained
- a phrase is too exact
- a wildcard stem is too short or too noisy
- a recent record lacks MeSH indexing and needs text-word coverage
- an in-scope seed PMID is lost after adding a methodological filter

## 8. Stop

Stop when:

- in-scope seed PMIDs are retrieved, or misses are explained
- essential concepts have MeSH and text-word coverage after an aggressive MeSH sweep
- accepted and rejected plausible MeSH descriptors/supplementary concepts are documented
- important variants have been considered
- any methodological filter has been chosen from a validated source where available
- the topic-only and topic-plus-filter versions have been compared when a filter is used
- further expansion mainly adds unrelated noise
- caveats are documented
- the strategy is flagged as a draft pending human peer review (PRESS, McGowan et al., 2016)
