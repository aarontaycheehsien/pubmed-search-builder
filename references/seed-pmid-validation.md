# Seed PMID Validation

Seed PMIDs are optional but valuable.

Ask once for seed PMIDs only after an independently stated plain-language research/review question has been confirmed. If none are provided, proceed.

When seed PMIDs are supplied before the concept gate, limited fetch/mining of those PMIDs is allowed before MeSH/PubMed exploration solely to inform concept analysis. Full seed validation still happens only after the draft strategy is built.

Seed PMIDs should be used for both term discovery and validation.

## Pre-gate seed triage

Before the concept gate, triage supplied seeds without broad PubMed exploration:

1. Normalize and deduplicate numeric PMIDs while preserving the user's order.
2. Record malformed seed entries separately and do not pass them to PubMed.
3. Run `pubmed_tool.py mine --pmids ... --output seed_mine.json` on the normalized numeric PMIDs. Inspect the saved JSON for `requested_pmids`, `found_pmids`, `missing_pmids`, fetched seed records, titles, abstract text where available, publication types, MeSH headings, keywords, and other returned metadata. If a separate fetch artifact is needed for scope decisions, run `pubmed_tool.py fetch --pmids ... --output seed_fetch.json` for the found PMIDs; this remains limited seed fetch/mining.
4. Document missing or not-found PMIDs, exclude them from seed evidence and later known-item validation unless the user supplies corrected PMIDs, and continue with any found records.
5. If no usable seed records remain, proceed under the no-seed workflow and state that seed-derived evidence and known-item recall are not available.
6. Pause before the concept gate only when a fetched seed is retracted or appears materially out of scope. Ask only whether to exclude it, replace it, or retain it as a special validation seed, then stop.

Treat a seed as retracted when PubMed metadata or publication types indicate a retracted publication or retraction status. Treat a seed as likely out of scope only when the fetched title, abstract, or publication type clearly conflicts with the stated review question. Ordinary uncertainty is recorded in the audit and does not block the concept gate.

Do not use malformed, missing, excluded, or unresolved seed records as term evidence. If the user retains a questionable record as a special validation seed, record it separately from normal in-scope seed evidence.

## Expand the seed set (optional)

When at least one usable in-scope seed remains, optionally expand the seed set before the concept gate to discover terms more objectively. Real searchers rarely stop at the pasted PMIDs; PubMed "Similar articles" and citation chaining surface neighboring relevant papers that carry additional vocabulary and indexing.

1. Run `pubmed_tool.py related --pmids <usable seeds> --links similar,citedin,refs` (drop link types you do not want). `similar` follows PubMed neighbors, `citedin` follows papers citing the seeds, `refs` follows papers the seeds cite.
2. Prefer high-overlap candidates (`seed_overlap_count` > 1) and, for `similar`, high `similarity_score`. Treat single-seed, single-link hits as weaker.
3. Feed the high-overlap candidate PMIDs to `pubmed_tool.py term-rank --pmids ...` so coverage/lift are scored against a richer relevant set than the raw seeds alone (see `mesh-and-pubmed-tools.md`).
4. Optionally use the high-overlap set as a recall **heuristic** for the draft strategy. This is not validated sensitivity.

Guardrails:

- The expanded set is a **candidate relevant set, not a gold standard**. Expanded PMIDs are candidate evidence, never auto-added terms; classify each harvested term by concept role.
- Record related-set evidence (links used, counts, caps, high-overlap PMIDs) **separately from user-confirmed seed evidence** in the audit ledger.
- Never report neighbor retrieval as true search sensitivity, and do not let expansion pull the strategy toward overfitting (see "Avoid overfitting" below).
- Pre-gate expansion is term-discovery support only; it does not authorize broad PubMed exploration, block testing, or variant comparison before the gate is resolved.

## Fetch and analyse seed records

Prefer `pubmed_tool.py mine --pmids ... --strategy-file strategy.txt --output seed_mine.json` so the extracted terms, gap checks, abstracts, and seed-record metadata are captured in reusable JSON while stdout stays receipt-only. `fetch` and `mine` do not support `--summary`; inspect the saved JSON before making scope, relevance, term-discovery, seed-validity, or concept-role decisions. Export that JSON to the audit workbook when the search will be reviewed or handed off.

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

To prioritise objectively rather than by eye, run `pubmed_tool.py term-rank --pmids ...` (or `--mine-json` from a prior mine run) to score candidate `[tiab]` and MeSH terms by enrichment in the seed set versus PubMed background. Favour high-coverage, high-lift terms and treat high-coverage but low-lift terms as likely noise. See `tiab-expansion.md` and `mesh-and-pubmed-tools.md`. Term-rank scores are term-discovery aids, not validated recall, and do not replace overfitting safeguards. When reusing a prior `mine` run via `--mine-json`, pass `--exclude-pmids <PMID ...>` for any seed excluded at pre-gate triage (out-of-scope, retracted, malformed), so excluded records never become term evidence.

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


## Estimate relative recall (optional)

Known-item validation only confirms the strategy finds papers you already have. To ask "is this strategy actually sensitive?", estimate **relative recall** against a larger benchmark relevant set with `pubmed_tool.py recall`.

This section covers the **seeded** route. When no seeds were supplied, the same `recall` machinery can be driven from a high-precision pilot query expanded via `related`; that no-seed route is optional, user-offered, and documented separately in `references/no-seed-recall-estimation.md`.

1. Choose a benchmark:
   - **Independent gold standard** (strongest): an externally defined relevant set, such as the included studies of a prior systematic review on the topic. Pass via `--benchmark-pmids` or `--benchmark-query-file`.
   - **Seed-expansion benchmark** (heuristic): the `related` candidate set from the "Expand the seed set" step, ideally filtered to high overlap. Pass the `related` JSON via `--benchmark-json --min-seed-overlap 2`.
2. Pass the concept blocks via `--blocks-file` (JSON `{label, query}` list). The output reports overall `relative_recall_percent`, per-block `block_recall` with a `bottleneck` flag, and `miss_diagnosis` naming the `culprit_blocks` for each missed record.
3. Use the bottleneck block to target revision: the lowest-recall block is usually where MeSH or text-word coverage is too narrow. An `and_interaction` flag points to a `NOT`, filter, or proximity problem rather than a weak block.

Interpretation and guardrails:

- Relative recall is **relative to the benchmark, not absolute search sensitivity**. Report it as such.
- A seed-expansion benchmark is strategy-adjacent and can **flatter** recall; an independent hand-screened gold standard gives a more honest relative-recall estimate but still does not measure absolute sensitivity (no irrelevant records are screened).
- A benchmark PMID that is not in PubMed is indistinguishable from a genuine miss.
- Never use a recall number to silently narrow a recall-first strategy. Record the benchmark source, size, relative recall, and bottleneck block in the audit, labelled separately from known-item seed validation.

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
