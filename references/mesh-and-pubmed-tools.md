# MeSH And PubMed Tool Use

Use the bundled scripts heavily. Do not rely only on model memory.

## MeSH Tool

For every essential concept, use `scripts/mesh_tool.py` to:

- search candidate descriptors
- inspect preferred headings
- inspect entry terms
- inspect allowable qualifiers when relevant
- inspect related descriptors
- inspect tree positions, broader/narrower context, descendants, and sibling descriptors with `tree`
- check whether explosion is appropriate
- check whether a concept has its own descriptor
- check whether terminology is recent or older

Useful commands:

```bash
python scripts/mesh_tool.py lookup --label "pressure ulcer" --match contains
python scripts/mesh_tool.py details --descriptor D003668 --include terms,seealso,qualifiers
python scripts/mesh_tool.py tree --descriptor D003668
python scripts/mesh_tool.py terms --label "bed sore" --match contains
python scripts/mesh_tool.py sweep --concept "pressure ulcer" --variant "bed sore" --variant "decubitus ulcer" --details
```

## Aggressive MeSH Sweep

Do not choose MeSH from a single descriptor lookup. For each essential concept, run a sweep before finalising the MeSH layer.

Build the sweep variant list from the pre-MeSH brainstorm and:

- the user's phrase
- brainstormed social-science, psychosocial, behavioral, qualitative, health-services, or weak-MeSH vocabulary families
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

The sweep searches both descriptor labels and entry terms with exact, startswith, and contains matching. It also resolves entry-term hits upward to their parent descriptors or supplementary concepts where MeSH RDF exposes that relation. Output candidates are ranked by match specificity, direct descriptor hits before term-derived hits, MeSH descriptors before supplementary concepts, then query-label order and label. Treat the output as a candidate table, not as final truth.

To prevent broad sweeps from becoming unbounded, `sweep` caches identical network requests during one run and applies default budgets: 40 unique term-to-descriptor lookups and 30 detailed candidate enrichments when `--details` is used. Use `--max-term-descriptor-lookups` and `--max-detail-candidates` to adjust those limits deliberately.

After each sweep, do not immediately write the concept block. First complete a MeSH candidate ledger:

- list sweep inputs separately from sweep outputs
- add candidates from MeSH sweep output, seed-assigned MeSH, PubMed ATM/query translations, and sample-record indexing
- inspect each plausible descriptor or supplementary concept record (SCR): preferred label, scope, entry terms, related descriptors, qualifiers, and `tree` context where relevant
- run `tree --descriptor ...` for every included descriptor and for every plausible rejected descriptor where scope, sibling context, descendants, SCR mapping, or explosion/noexp may matter
- accept, reject, or defer each candidate with a reason
- harvest non-ambiguous entry terms from accepted descriptors/SCRs as `[tiab]` candidates and document omitted entry terms
- run separate sweeps for important subtypes, procedures, devices, drugs, acronyms, older terms, and newer terms, or state why they were not needed
- test accepted descriptors in PubMed and test plausible rejected descriptors when recall or noise decisions depend on them
- test MeSH-only, text-word-only, and combined concept-block counts
- resolve or document all MeSH/SCR mappings surfaced by PubMed ATM before finalising the block

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
- mine seed PMID titles, abstracts, MeSH headings, keywords, acronyms, phrases, and strategy gaps
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
- compare labelled sensitive/focused/precision strategy variants
- export an `.xlsx` audit workbook from mining and variant JSON outputs

Useful commands:

```bash
python scripts/pubmed_tool.py search "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --retmax 5
python scripts/pubmed_tool.py search --query-file query.txt --retmax 0
python scripts/pubmed_tool.py search --query-stdin --retmax 0
python scripts/pubmed_tool.py sample "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --retmax 5
python scripts/pubmed_tool.py fetch --pmids 24102982 21171099
python scripts/pubmed_tool.py mine --pmids 24102982 21171099 --strategy-file strategy.txt
python scripts/pubmed_tool.py validate "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --pmids 24102982
python scripts/pubmed_tool.py batch queries.json
python scripts/pubmed_tool.py variants variants.json --retmax 0
python scripts/pubmed_tool.py variants variants.json --seed-pmids 24102982 21171099 --labelled-samples labelled_samples.json --retmax 0
python scripts/pubmed_tool.py audit-workbook --mine-json mine.json --variants-json variants.json --output search_audit.xlsx
python scripts/pubmed_tool.py doctor
```

Use inline query arguments only for short single-concept checks, simple descriptor checks, or quick exploratory terms. For full strategies, multi-line strategies, combined concept blocks, validation queries, and topic-plus-filter searches, write the query to a temporary UTF-8 text file and call `pubmed_tool.py` with `--query-file`. `--query-stdin` is also acceptable when a pipeline is simpler. Avoid passing full PubMed strategies as shell arguments; file-based querying prevents shell quoting, parenthesis, wildcard, and line-break errors.

Use `batch` for count tables when comparing concept blocks, acronym variants, outcome filters, topic-only strategies, and topic-plus-filter strategies. Use `variants` when the comparison is between labelled alternative full strategies, especially sensitive/main versus focused/precision-supporting versions. Rich variant JSON can preserve role, hypothesis, changes from baseline, recall risk, workload rationale, decision status, and decision reason. Add `--seed-pmids` to attach known-item retrieval to each design, and `--labelled-samples` to estimate pilot precision and NNR from relevance-labelled PMIDs. Use `audit-workbook` when a spreadsheet handoff will help peer review or documentation; it includes a Design Ledger sheet when variants output is supplied. The workbook is optional: always create the required audit Markdown file structured by `audit-template.md` and required by `workflow.md`, even when an `.xlsx` workbook is also exported.

`pubmed_tool.py` runs pre-command and query-translation hooks automatically:

- Pre-command hook blocks API keys on the command line and in query text from arguments, files, stdin, or batch input; warns about long inline queries; warns on very large `retmax`; and reminds batch count comparisons to use `--retmax 0` unless PMID samples are needed.
- Query translation drift hook runs after each PubMed ESearch response for `search`, `sample`, `validate`, `batch`, `variants`, and `doctor`. It inspects PubMed's returned `query_translation`, translation set, and warning list for ignored phrases, quoted phrases not found, broad `[All Fields]` fallback, untagged acronym-like terms, large ATM expansion, and mixed tagged/untagged queries. It is warning-only, never blocks execution, makes no extra NCBI calls, and consumes no LLM/API tokens because it is local Python string analysis. The only practical token cost is the extra JSON shown to Codex: about 20-40 JSON tokens when quiet and about 60-120 per warning, capped per query. False positives are expected for intentional ATM use, valid broad MeSH explosions, correctly handled acronyms, and broad concepts with naturally long translations, so treat issues as review prompts rather than proof of an error.

## Strategy Hooks

Use `scripts/hooks_tool.py` for pre-final, non-network checks:

```bash
python scripts/hooks_tool.py final-qa --strategy-file final_strategy.txt
python scripts/hooks_tool.py filter-check --text-file protocol_or_strategy.txt
```

Run `final-qa` before presenting a draft strategy. It flags recall risks such as `[Majr]`, `NOT`, language/date/species/age/publication-type/full-text limits, short wildcards, proximity with truncation, and missing MeSH or `[tiab]` layers. For multi-block strategies, it checks top-level concept blocks separately so one block's MeSH does not hide another block's missing controlled-vocabulary layer.

Run `filter-check` whenever the protocol, request, or strategy mentions a study-design/evidence-type intent such as RCTs, systematic reviews, qualitative studies, diagnostic accuracy, prognosis, observational studies, or economic evaluations. If it reports that validated filter review is needed, read `validated-methodological-filters-and-hedges.md`, use `pubmed_tool.py batch` for topic-only versus topic-plus-filter counts, and validate seed PMID impact when seeds exist.

## Audit Markdown Tool

Use `scripts/audit_markdown.py` when structured audit notes are available. For completed strategy builds, first save the structured audit notes as a UTF-8 JSON file, preferably `audit_<topic>_<date>.json`, then render the Markdown from that file:

```bash
python scripts/audit_markdown.py audit_adhd_bipolar_2026-05-18.json --output audit_2026-05-18.md
```

Use `references/audit-example.json` as a starter input and `references/audit-json-schema.md` as the field reference for the JSON object consumed by `audit_markdown.py`.

The default command output is a compact JSON receipt rather than the full audit
Markdown. It includes the saved path, byte count, placeholder count, and section
count. Use `--print-report` only when the terminal output itself must include
the full report. The tool refuses unresolved placeholder-like text by default
and refuses to overwrite existing files unless `--if-exists overwrite` is
selected. When a matching output file exists, it writes to a clear numeric
suffix by default; use `--if-exists fail` when a collision should stop the run.

Stdin input (`python scripts/audit_markdown.py - ...`) is acceptable only for tiny smoke tests. Do not pipe large structured audit objects from shells such as PowerShell `ConvertTo-Json | python scripts/audit_markdown.py -`; file-based JSON avoids stdin buffering, quoting, and timeout failures. If rendering times out or fails, keep the audit JSON, rerun the renderer from the saved file, and use direct Markdown from `references/audit-template.md` only as a final fallback. Document any fallback in Reporting notes.

## Suggested Operational Sequence

1. PubMed tool: fetch seed PMIDs, if any, and mine assigned MeSH plus title/abstract terms.
2. Run the pre-MeSH vocabulary/domain brainstorm where required; ask the domain-framing question before MeSH lookup when framing can materially change the strategy.
3. PubMed tool: run exploratory PubMed searches to inspect query translations and ATM clues.
4. MeSH tool: build variant lists for each essential concept from the brainstormed vocabulary plus seed, user, and ATM clues.
5. MeSH tool: run `sweep --details` for each essential concept.
6. MeSH/PubMed tools: complete the MeSH candidate ledger before drafting each concept block.
7. MeSH tool: use raw `sparql` only for unusual follow-up questions not covered by `tree`.
8. PubMed tool: test remaining text-word clusters, proximity expressions, and wildcard stems.
9. PubMed tool: test combined topic blocks.
10. PubMed tool: if a methodological filter is used, test the topic-only and topic-plus-filter strategies separately.
11. PubMed tool: validate seed PMID retrieval.
12. PubMed tool: diagnose missed PMIDs, including whether misses were caused by the filter.
13. PubMed tool: run final query hygiene with `search --query-file ... --retmax 0`; resolve or document PubMed parse/translation warnings and rerun the selected final variant if variants were tested.
14. Hook tool: run `final-qa` after the final query text stabilizes.
15. Hook tool: run `filter-check` if any methodological filter or evidence-type intent is present.
16. Audit Markdown tool: render structured audit notes to the required Markdown file and report the saved path.

## Do Not Fabricate

Never invent:

- MeSH descriptors
- entry terms
- PubMed counts
- PMIDs
- validation results
- whether a PMID was retrieved
