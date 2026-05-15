# MeSH And PubMed Tool Use

Use the bundled scripts heavily. Do not rely only on model memory.

## MeSH Tool

For every essential concept, use `scripts/mesh_tool.py` to:

- search candidate descriptors
- inspect preferred headings
- inspect entry terms
- inspect allowable qualifiers when relevant
- inspect related descriptors
- inspect tree positions or descendants with SPARQL when needed
- check whether explosion is appropriate
- check whether a concept has its own descriptor
- check whether terminology is recent or older

Useful commands:

```bash
python scripts/mesh_tool.py lookup --label "pressure ulcer" --match contains
python scripts/mesh_tool.py details --descriptor D003668 --include terms,seealso,qualifiers
python scripts/mesh_tool.py terms --label "bed sore" --match contains
python scripts/mesh_tool.py sweep --concept "pressure ulcer" --variant "bed sore" --variant "decubitus ulcer" --details
```

## Aggressive MeSH Sweep

Do not choose MeSH from a single descriptor lookup. For each essential concept, run a sweep before finalising the MeSH layer.

Build the sweep variant list from:

- the user's phrase
- synonyms and near-synonyms
- acronyms and abbreviations
- singular/plural and spelling variants
- hyphenation variants
- older and newer terminology
- lay and technical terminology
- seed-paper title/abstract terms
- seed-paper MeSH headings
- PubMed query translations and Automatic Term Mapping clues

Use:

```bash
python scripts/mesh_tool.py sweep --concept "concept phrase" --variant "synonym" --variant "acronym" --details
```

The sweep searches both descriptor labels and entry terms with exact, contains, and startswith matching. It also resolves entry-term hits upward to their parent descriptors or supplementary concepts where MeSH RDF exposes that relation. Treat the output as a candidate table, not as final truth.

For each plausible candidate descriptor or supplementary concept:

- inspect preferred label, entry terms, related descriptors, and qualifiers
- check broader/narrower tree context with SPARQL when explosion may matter
- test the descriptor in PubMed with `pubmed_tool.py search '"Descriptor"[Mesh]' --retmax 0`
- decide `[Mesh]` versus `[Mesh:noexp]`
- add useful entry terms to the `[tiab]` layer
- document accepted and rejected descriptors

Rejected descriptors/supplementary concepts should have an explicit reason: too broad, too narrow, wrong sense, obsolete, duplicate, noisy, or outside scope.

Use `[Mesh]` for exploded MeSH headings unless there is a clear reason not to.

Use `[Mesh:noexp]` only when deliberately avoiding narrower terms.

Avoid `[Majr]` for high-sensitivity searches unless the user explicitly wants a narrower search.

Avoid MeSH subheadings unless strongly justified.

## Separate MeSH Lookups

Do not assume a parent descriptor covers every clinically meaningful synonym.

Run separate MeSH sweeps or lookups for:

- disease subtypes
- syndromes
- device names
- procedures
- intervention families
- drug classes
- generic drug names
- common acronyms
- newer terminology
- older terminology

## PubMed Tool

Use `scripts/pubmed_tool.py` to:

- fetch seed PMIDs
- inspect titles and abstracts
- inspect MeSH headings assigned to seed papers
- run candidate MeSH terms
- run text-word clusters
- run wildcard candidates
- test concept blocks
- test the topic-only full strategy
- test the topic-plus-filter full strategy, if a methodological filter is used
- get hit counts
- inspect sample records
- check recent records that may lack MeSH
- validate seed PMIDs
- diagnose missed seed PMIDs

Useful commands:

```bash
python scripts/pubmed_tool.py search "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --retmax 5
python scripts/pubmed_tool.py search --query-file query.txt --retmax 0
python scripts/pubmed_tool.py search --query-stdin --retmax 0
python scripts/pubmed_tool.py sample "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --retmax 5
python scripts/pubmed_tool.py fetch --pmids 24102982 21171099
python scripts/pubmed_tool.py validate "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --pmids 24102982
python scripts/pubmed_tool.py batch queries.json
python scripts/pubmed_tool.py doctor
```

For long strategies, prefer `--query-file` or `--query-stdin` to avoid shell quoting problems. Use `batch` for count tables when comparing concept blocks, acronym variants, outcome filters, topic-only strategies, and topic-plus-filter strategies.

`pubmed_tool.py` runs a pre-command hook and post-search logging hook automatically:

- Pre-command hook blocks API keys on the command line, warns about long inline queries, warns on very large `retmax`, and reminds count-only block testing to use `--retmax 0`.
- Post-search logging writes a local JSONL line for `search`, `sample`, `validate`, and `batch` commands. The log includes timestamp, query, count, query translation, warnings, email/API-key configured status, and rate limit. It does not write the NCBI email or API-key value. Default path: `%USERPROFILE%\.codex\pubmed-search-builder\logs\pubmed-search-log.jsonl`.

Use `PUBMED_SEARCH_BUILDER_LOG` to override the log path. Use `PUBMED_SEARCH_BUILDER_LOG_DISABLED=1` to disable logging for a sensitive session.

## Strategy Hooks

Use `scripts/hooks_tool.py` for pre-final, non-network checks:

```bash
python scripts/hooks_tool.py final-qa --strategy-file final_strategy.txt
python scripts/hooks_tool.py filter-check --text-file protocol_or_strategy.txt
```

Run `final-qa` before presenting a draft strategy. It flags recall risks such as `[Majr]`, `NOT`, language/date/species/age/publication-type/full-text limits, short wildcards, proximity with truncation, and missing MeSH or `[tiab]` layers.

Run `filter-check` whenever the protocol, request, or strategy mentions a study-design/evidence-type intent such as RCTs, systematic reviews, qualitative studies, diagnostic accuracy, prognosis, observational studies, or economic evaluations. If it reports that validated filter review is needed, read `validated-methodological-filters-and-hedges.md`, use `pubmed_tool.py batch` for topic-only versus topic-plus-filter counts, and validate seed PMID impact when seeds exist.

## Suggested Operational Sequence

1. PubMed tool: fetch seed PMIDs, if any, and mine assigned MeSH plus title/abstract terms.
2. PubMed tool: run exploratory PubMed searches to inspect query translations and ATM clues.
3. MeSH tool: build variant lists for each essential concept.
4. MeSH tool: run `sweep --details` for each essential concept.
5. MeSH tool: run separate sweeps for subtypes, acronyms, procedures, drugs, devices, and older/newer terminology.
6. MeSH tool: use SPARQL for tree, broader/narrower, or descendant checks when explosion matters.
7. PubMed tool: test accepted and rejected MeSH descriptors with `--retmax 0`.
8. PubMed tool: test text-word clusters.
9. PubMed tool: test wildcard stems.
10. PubMed tool: test each concept block.
11. PubMed tool: test combined topic blocks.
12. PubMed tool: if a methodological filter is used, test the topic-only and topic-plus-filter strategies separately.
13. PubMed tool: validate seed PMID retrieval.
14. PubMed tool: diagnose missed PMIDs, including whether misses were caused by the filter.
15. Hook tool: run `final-qa` before presenting the final draft.
16. Hook tool: run `filter-check` if any methodological filter or evidence-type intent is present.

## Do Not Fabricate

Never invent:

- MeSH descriptors
- entry terms
- PubMed counts
- PMIDs
- validation results
- whether a PMID was retrieved
