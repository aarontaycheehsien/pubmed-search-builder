# Validated Methodological Filters and Search Hedges

Use this reference when the user asks for a study-design, evidence-type, age-group, species, or other methodological block in a PubMed search strategy.

## Core rule

Only add a methodological filter when the review question or protocol genuinely requires it.

When a filter is needed, prefer a published, validated, interface-appropriate filter over ad hoc construction.

For high-sensitivity evidence synthesis, default to the sensitivity-maximising version of a filter unless the user explicitly prioritises precision, workload reduction, or a balanced search.

Do not present a hand-built block as a validated hedge.

## Decision order

1. Decide whether a filter is needed at all.
2. Identify the exact methodological purpose: RCTs, controlled clinical trials, diagnosis, prognosis, etiology/causation, clinical prediction, economics, qualitative studies, systematic reviews, observational studies, humans/animals, age group, or another filter type.
3. Choose a validated source appropriate to that purpose.
4. Confirm the filter is for PubMed/MEDLINE via PubMed syntax, not Ovid MEDLINE, Embase, CINAHL, CENTRAL, or another interface.
5. Use the sensitivity-maximising version unless a different balance is explicitly justified.
6. Test the topic-only strategy.
7. Test the topic strategy plus the filter.
8. Test whether seed PMIDs are lost after adding the filter.
9. Report the filter source, version, interface, any adaptation, and recall risk.

## When not to use a methodological filter

Do not add a methodological filter by default.

Avoid or question a filter when:

- the review is a broad scoping review or evidence map and study design is not an inclusion criterion
- the protocol does not require a specific study design
- the evidence type is difficult to identify reliably through bibliographic metadata alone
- the topic search is already very small
- the user is searching CENTRAL or another pre-filtered trials source
- the filter would duplicate a database's curation purpose
- seed PMIDs are lost and the loss cannot be justified
- the available filter is for another interface and has not been properly translated

## Validated filter sources to consider

| Need | Preferred sources | Notes |
|---|---|---|
| Randomised or controlled trials in PubMed/MEDLINE | Cochrane Highly Sensitive Search Strategy (HSSS) for identifying randomised trials in MEDLINE; Cochrane PubMed format | Use sensitivity-maximising version for recall-first searches. Do not use in CENTRAL. |
| Therapy, diagnosis, prognosis, etiology/causation, clinical prediction, economics, qualitative studies, reviews | McMaster Health Information Research Unit (HIRU) Hedges / Clinical Queries | Choose the broad/sensitive version for evidence synthesis unless precision is explicitly required. |
| PubMed clinical-category filters | PubMed Clinical Queries | Useful for therapy, diagnosis, etiology, prognosis, and clinical prediction, but these are not a substitute for full systematic-review searching. |
| Systematic reviews | PubMed `systematic[sb]`, HIRU review hedge, ISSG-listed systematic-review filters, or validated published review filters | Be cautious: evidence-synthesis terminology is diverse and changes over time. Report the exact filter used. |
| Qualitative studies | HIRU qualitative hedge, ISSG Search Filters Resource, or published validated qualitative filters | Check database/interface and whether the filter was validated for PubMed. |
| Observational or non-randomised studies | ISSG Search Filters Resource and published validated filters | Often difficult. Document limitations and test seed PMIDs carefully. |
| Economic evaluations | HIRU economics/cost hedges, ISSG-listed economic filters, Canada's Drug Agency/CADTH-type filters where applicable | Use only when economic evidence is genuinely required. |
| Adverse effects / safety | ISSG-listed adverse-effects filters or domain-specific validated filters | Often requires careful balance; avoid generic ad hoc safety blocks unless justified. |
| Age groups, humans, animals, geography, ethnicity, sex/gender | ISSG Search Filters Resource or PubMed filter search strategies | Many rely on MeSH indexing and may exclude unindexed or recent records. |

## Cochrane HSSS for RCTs: PubMed format

Use only when an RCT or controlled-trial filter is genuinely appropriate.

### Sensitivity-maximising version, 2008 revision, PubMed format

```text
(
  randomized controlled trial[pt]
  OR controlled clinical trial[pt]
  OR randomized[tiab]
  OR placebo[tiab]
  OR drug therapy[sh]
  OR randomly[tiab]
  OR trial[tiab]
  OR groups[tiab]
)
NOT
(
  animals[mh] NOT humans[mh]
)
```

### Sensitivity- and precision-maximising version, 2008 revision, PubMed format

```text
(
  randomized controlled trial[pt]
  OR controlled clinical trial[pt]
  OR randomized[tiab]
  OR placebo[tiab]
  OR clinical trials as topic[mesh:noexp]
  OR randomly[tiab]
  OR trial[ti]
)
NOT
(
  animals[mh] NOT humans[mh]
)
```

For high-sensitivity evidence synthesis, prefer the sensitivity-maximising version unless there is a specific reason to use the balanced version.

Do not silently modify these filters. If you add, remove, or translate terms, say that the filter was adapted and that the published performance may no longer apply exactly.

## McMaster HIRU Hedges

The McMaster Health Information Research Unit Hedges Project provides methodological search filters for categories including therapy/treatment, diagnosis, prognosis, causation/etiology, clinical prediction guides, economics, qualitative studies, and reviews.

Use these when the question maps to a HIRU category and the filter is available in PubMed syntax.

Selection rules:

- Use the broad or sensitive version for evidence synthesis.
- Use the narrow or specific version only when the user explicitly prioritises precision or workload reduction.
- Do not assume a HIRU filter exists for every review question.
- Do not paste an Ovid MEDLINE hedge into PubMed without translation and checking.

## PubMed Clinical Queries

PubMed Clinical Queries are built-in category filters for clinical study categories. They can be useful for quick clinical searching, but systematic reviews usually require full transparent strategies rather than only clicking a Clinical Queries option.

If using a Clinical Queries-derived filter:

- state the category, such as therapy, diagnosis, etiology, prognosis, or clinical prediction
- state the scope, such as broad/sensitive or narrow/specific
- reproduce the filter logic where possible
- test whether seed PMIDs are lost
- report that it is a filter and not part of the topical concept block

## PubMed article-type and sidebar filters

Do not rely casually on PubMed sidebar filters for high-sensitivity evidence synthesis.

PubMed warns that many filters rely on assigned MeSH terms or publication type data. These can exclude records that are not yet indexed, ahead-of-print records, preprints, and records not fully indexed for MEDLINE.

If a sidebar filter or subset is used, convert it into reproducible search syntax where possible and report it under PRISMA-S Item 9 or Item 10 as appropriate.

Examples:

```text
systematic[sb]
```

```text
systematic review[pt]
```

`systematic[sb]` is broader than only `systematic review[pt]` because it uses a search strategy as well as publication type logic. Do not assume they are equivalent.

## ISSG Search Filters Resource

The ISSG Search Filters Resource is a discovery and appraisal source for methodological filters.

Use it to identify candidate filters for study designs or populations not covered by Cochrane HSSS or HIRU.

Important cautions:

- Inclusion in ISSG is not automatic endorsement.
- Check whether the filter has been validated.
- Check the database and interface.
- Check whether indexing and vocabulary have changed since publication.
- If you amend the filter, report it as adapted and warn that the published performance may change.

## Interface translation warning

Do not paste Ovid syntax into PubMed.

Examples of Ovid syntax that must be translated before PubMed use:

```text
.pt.
.ab.
.ti.
.tw.
.mp.
.fs.
.sh.
exp
/
$
?
adj
```

Typical PubMed equivalents may include:

```text
[pt]
[tiab]
[ti]
[sh]
[Mesh]
[Mesh:noexp]
*
"word1 word2"[tiab:~N]
```

These are not always one-to-one. If only an Ovid version is available, either find a PubMed version from a trusted source or explicitly state that translation is required and should be checked by an information specialist.

## Seed PMID testing when filters are used

When seed PMIDs are supplied and a methodological filter is added:

1. Test the topic-only strategy.
2. Test the topic strategy plus the filter.
3. Compare whether any seed PMIDs are lost after adding the filter.
4. If a seed is lost, inspect whether the record is poorly indexed, uses unexpected terminology, lacks abstract terms, lacks the expected publication type, or is outside the intended study design.
5. Do not automatically force the filter to retrieve every seed if the seed is out of scope.
6. If an in-scope seed is lost because of the filter, report this clearly and reconsider the filter choice.

Use this diagnostic pattern:

```text
(
  topic-only strategy
)
AND
(
  12345678[uid] OR 23456789[uid]
)
```

Then:

```text
(
  topic-only strategy
)
AND
(
  methodological filter
)
AND
(
  12345678[uid] OR 23456789[uid]
)
```

If a seed disappears only after the filter is added, the filter is the likely cause.

## Reporting template for filters and hedges

When a methodological filter is used, include this in the final output:

```markdown
## Methodological filters / hedges

- Filter used: [name or none]
- Purpose: [RCT / diagnosis / prognosis / qualitative / systematic review / observational / economic / other]
- Source: [Cochrane HSSS / McMaster HIRU Hedges / PubMed Clinical Queries / ISSG / other]
- Version: [sensitivity-maximising / specificity-maximising / balanced / not stated]
- Interface: PubMed
- Adapted: yes/no
- If adapted, what changed: [details]
- Reason for using filter: [protocol/design requirement]
- Recall risk: [brief note]
- Topic-only result count: [if tested]
- Topic-plus-filter result count: [if tested]
- Seed PMID impact: [none lost / lost PMIDs listed / not tested]
```

If no methodological filter is used, state:

```text
No methodological search filter was applied because [reason].
```

## Common failure modes

Avoid these:

- adding a home-made RCT block when the Cochrane HSSS would be more appropriate
- using only `randomized controlled trial[pt]` and calling it an RCT filter
- adding a review filter to a topic where primary studies are sought
- using PubMed sidebar filters without reporting exact syntax
- using a narrow Clinical Queries filter when the user asked for high sensitivity
- pasting Ovid syntax into PubMed
- applying a humans-only, age, sex, or language filter without explaining recall loss
- failing to test whether supplied seed PMIDs are lost after the filter is added

## Source notes and URLs

Use these source families when checking details. URLs are included so Claude can cite or revisit the source when browsing/tool access is available.

- Cochrane Handbook, Chapter 4, Searching for and selecting studies: https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04
- Cochrane PubMed HSSS page with PubMed-format RCT filters: https://work.cochrane.org/pubmed
- McMaster Health Information Research Unit Hedges Project: https://hiruweb.mcmaster.ca/hkr/hedges/
- McMaster HIRU MEDLINE/PubMed hedges: https://hiruweb.mcmaster.ca/hkr/hedges/medline/
- PubMed Clinical Queries: https://pubmed.ncbi.nlm.nih.gov/clinical/
- PubMed Help, filters and filter search strategies: https://pubmed.ncbi.nlm.nih.gov/help/
- ISSG Search Filters Resource: https://sites.google.com/a/york.ac.uk/issg-search-filters-resource/
- PRESS guideline statement: McGowan et al., 2016, Journal of Clinical Epidemiology. DOI: https://doi.org/10.1016/j.jclinepi.2016.01.021
- PRISMA-S reporting guideline: Rethlefsen et al., 2021, Systematic Reviews. DOI: https://doi.org/10.1186/s13643-020-01542-z
- Empirical comparison of RCT filters: Glanville et al., 2020, Journal of the Medical Library Association. DOI: https://doi.org/10.5195/jmla.2020.912

When using a filter from any source, copy the exact source, version, and interface into the final output. If the source page has changed since this skill was written, use the current source page rather than the embedded examples.
