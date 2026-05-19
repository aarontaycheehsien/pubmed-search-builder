# Seed PMID Validation

Seed PMIDs are optional but valuable.

Ask once for seed PMIDs. If none are provided, proceed.

When seed PMIDs are supplied before the concept gate, limited fetch/mining of those PMIDs is allowed before MeSH/PubMed exploration solely to inform concept analysis. Full seed validation still happens only after the draft strategy is built.

Seed PMIDs should be used for both term discovery and validation.

## Fetch and analyse seed records

Prefer `pubmed_tool.py mine --pmids ... --strategy-file strategy.txt` so the extracted terms, gap checks, and seed-record metadata are captured in reusable JSON. Export that JSON to the audit workbook when the search will be reviewed or handed off.

For each seed PMID, use the PubMed script to extract:

- PMID
- title
- abstract
- MeSH headings
- supplementary concepts
- publication types
- registry numbers or substance names, where relevant
- author keywords, where available
- acronyms
- synonyms
- phrase variants
- spelling variants
- singular/plural forms
- older or newer terminology
- indexing patterns

## Use seed papers for term discovery

Prioritise terms appearing in:

- titles
- abstracts
- MeSH headings
- MeSH entry terms
- multiple seed papers
- distinctive phrases
- common abbreviations
- older terminology
- recent terminology

Do not add every word from seed abstracts. Add terms that map to essential concepts and plausibly improve recall.

## Validate retrieval

Test whether the final strategy retrieves all in-scope seed PMIDs.

Use a query pattern equivalent to:

```text
(
  final strategy
)
AND
(
  12345678[uid] OR 23456789[uid] OR 34567890[uid]
)
```

Test for missed seed PMIDs:

```text
(
  12345678[uid] OR 23456789[uid] OR 34567890[uid]
)
NOT
(
  final strategy
)
```


## Validate filters separately

When a methodological filter or hedge is used, validate seed retrieval in two stages:

1. Topic-only strategy, without the filter.
2. Topic-plus-filter strategy.

This distinguishes topic-block failures from filter-caused failures.

Use patterns equivalent to:

```text
(
  topic-only strategy
)
AND
(
  12345678[uid] OR 23456789[uid]
)
```

and:

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

If a seed is retrieved by the topic-only strategy but lost after the filter is added, diagnose the filter before adding more topical terms.

Possible causes:

- seed is not actually the study design targeted by the filter
- seed lacks the expected publication type
- seed lacks expected methodological terms in the title or abstract
- seed is not fully indexed
- filter is too narrow for the intended review
- filter syntax was translated incorrectly
- an animal-only or humans-only component excluded the seed

Do not automatically distort a validated filter to force retrieval of an out-of-scope seed. If an in-scope seed is lost, reconsider filter choice, version, or whether a filter should be used.

## Diagnose missed PMIDs

If a seed PMID is missed, fetch the record and check:

- missing synonym
- missing acronym
- missing singular or plural form
- missing spelling variant
- missing hyphenation variant
- missing wildcard stem
- wrong MeSH heading
- article lacks expected MeSH indexing
- article is too recent to have MeSH indexing
- concept block is too narrow
- too many `AND` concepts
- phrase search is too restrictive
- field tag prevents Automatic Term Mapping
- filter excluded the record
- study-design filter excluded the record
- seed paper is outside scope

## Revise carefully

Possible fixes:

- add a synonym
- add an acronym
- add explicit singular/plural phrases
- add a spelling variant
- add a hyphenation variant
- add an older or newer term
- add a safe wildcard stem
- add broader or narrower MeSH
- loosen a phrase
- remove an unnecessary concept block
- remove or separate a filter

## Avoid overfitting

Seed PMIDs are validation aids, not the whole target set.

Do not overfit the strategy to retrieve only the language used in a small seed set.

If a seed paper is out of scope, report that rather than distorting the strategy.
