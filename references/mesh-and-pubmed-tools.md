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
# short single-concept check (full JSON to stdout)
python scripts/mesh_tool.py sweep --concept "concept phrase" --variant "synonym" --details
# long variant lists (recommended): full JSON + per-label checkpoints to the file, compact summary to stdout
python scripts/mesh_tool.py sweep --concept "concept phrase" --variants-file variants.txt --details --output sweep_concept.json --pending-output sweep_concept_pending.txt
```

The sweep searches both descriptor labels and entry terms with exact, startswith, and contains matching. It also resolves entry-term hits upward to their parent descriptors or supplementary concepts where MeSH RDF exposes that relation. Output candidates are ranked by match specificity, direct descriptor hits before term-derived hits, MeSH descriptors before supplementary concepts, then query-label order and label. Treat the output as a candidate table, not as final truth.

To prevent broad sweeps from becoming unbounded, `sweep` caches identical network requests during one run and applies default budgets: 40 unique term-to-descriptor lookups and 30 detailed candidate enrichments when `--details` is used. Use `--max-term-descriptor-lookups` and `--max-detail-candidates` to adjust those limits deliberately.

Long variant lists are additionally hardened against timeouts. A wall-clock budget (`--max-seconds`, default 120; `0` = unlimited) bounds the whole run, the highest-value matches run first (exact, then startswith, then contains), and per-request failures are recorded in `errors` and skipped rather than aborting the sweep. Always run long sweeps with `--output <path>`: the full JSON (including `raw_searches` and per-candidate `details`) is written there and **checkpointed after each label**, so even a killed process leaves useful partial output, while stdout shows a compact, token-cheap summary (ranked candidate descriptors with their sources, plus `status`, `coverage`, `network_budget`). Add `--pending-output <pending_variants.txt>` to write newline-delimited pending variant labels compatible with `--variants-file` on a follow-up run. `--summary` prints that same compact summary without writing a file.

A sweep that hits the time budget or has request errors returns `status: "partial"` with a `stop_reason` and the exact unswept `pending` units (and any `errors`). Treat a partial sweep as **incomplete MeSH/entry-term recall**: rerun the `pending` and failed labels (a separate sweep is fine) and merge candidates before finalising the concept block. If `--pending-output` was used, pass the saved file to the rerun via `--variants-file`; still review `errors` separately because failed labels are not the same as unswept labels. Token savings come only from the compact stdout projection - the candidate set is never trimmed and shortened runs are always explicit, so recall is not silently reduced. For very long variant lists, prefer splitting the work into several smaller sweeps (see *Separate MeSH Lookups* below).

After each sweep, do not immediately write the concept block. First complete the **MeSH candidate ledger** defined canonically in `workflow.md` step 5: list sweep inputs separately from outputs; add candidates from sweep output, seed-assigned MeSH, PubMed ATM/query translations, and sample-record indexing; inspect each plausible descriptor or supplementary concept record (SCR) for label, scope, entry terms, related descriptors, qualifiers, and `tree` context; run `tree --descriptor ...` for every included descriptor and every plausible rejected one where scope, siblings, descendants, SCR mapping, or explosion/noexp matters; accept/reject/defer each candidate with a reason; harvest non-ambiguous entry terms as `[tiab]` candidates; run separate sweeps for subtypes, procedures, devices, drugs, and older/newer terms; PubMed count-test accepted and plausible-rejected descriptors (MeSH-only, text-word-only, and combined); and resolve all MeSH/SCR mappings surfaced by ATM before finalising the block.

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
- expand seed PMIDs into a candidate relevant set via PubMed eLink (similar articles, cited-by, references)
- mine seed PMID titles, abstracts, MeSH headings, keywords, acronyms, phrases, and strategy gaps
- rank candidate tiab/MeSH terms by enrichment in a relevant/seed set versus PubMed background
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
- estimate relative recall against a benchmark relevant set, with per-concept-block miss diagnosis
- compare labelled sensitive/focused/precision strategy variants
- export an `.xlsx` audit workbook from mining and variant JSON outputs

Useful commands:

```bash
python scripts/pubmed_tool.py search "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --retmax 5
python scripts/pubmed_tool.py search --query-file query.txt --retmax 0
python scripts/pubmed_tool.py search --query-stdin --retmax 0
python scripts/pubmed_tool.py sample --query-file pressure_ulcer_block.txt --retmax 5 --output sample_pressure_ulcer_block.json
python scripts/pubmed_tool.py fetch --pmids 24102982 21171099 --output seed_fetch.json
python scripts/pubmed_tool.py related --pmids 24102982 21171099 --links similar,citedin
python scripts/pubmed_tool.py mine --pmids 24102982 21171099 --strategy-file strategy.txt --output seed_mine.json
python scripts/pubmed_tool.py term-rank --pmids 24102982 21171099 --fields tiab,mesh --max-terms 40
python scripts/pubmed_tool.py term-rank --mine-json mine.json --strategy-file strategy.txt
python scripts/pubmed_tool.py term-rank --relevant-query-file pilot.txt --fields tiab,mesh --relevant-retmax 150
python scripts/pubmed_tool.py validate "(Pressure Ulcer[Mesh] OR pressure ulcer*[tiab])" --pmids 24102982
python scripts/pubmed_tool.py recall --query-file strategy.txt --benchmark-json related.json --blocks-file blocks.json
python scripts/pubmed_tool.py recall --query-file strategy.txt --benchmark-pmids 24102982 21171099
python scripts/pubmed_tool.py batch queries.json
python scripts/pubmed_tool.py variants variants.json --retmax 0
python scripts/pubmed_tool.py variants variants.json --seed-pmids 24102982 21171099 --labelled-samples labelled_samples.json --retmax 0
python scripts/pubmed_tool.py audit-workbook --mine-json mine.json --variants-json variants.json --output search_audit.xlsx
python scripts/pubmed_tool.py doctor
```

Use inline query arguments only for short single-concept checks, simple descriptor checks, or quick exploratory terms. For full strategies, multi-line strategies, combined concept blocks, validation queries, and topic-plus-filter searches, write the query to a temporary UTF-8 text file and call `pubmed_tool.py` with `--query-file`. `--query-stdin` is also acceptable when a pipeline is simpler. Avoid passing full PubMed strategies as shell arguments; file-based querying prevents shell quoting, parenthesis, wildcard, and line-break errors.

Use `batch` for count tables when comparing concept blocks, acronym variants, outcome filters, topic-only strategies, and topic-plus-filter strategies. Use `variants` when the comparison is between labelled alternative full strategies, especially sensitive/main versus focused/precision-supporting versions. Rich variant JSON can preserve role, hypothesis, changes from baseline, recall risk, workload rationale, decision status, and decision reason. Each `query` value in a batch or variants JSON file must be plain text; the parsers fail fast with a clear error if a query is a serialized object/file-metadata blob (a PowerShell `ConvertTo-Json` pitfall), and `recall --benchmark-json` likewise rejects non-numeric PMIDs. Add `--seed-pmids` to attach known-item retrieval to each design, and `--labelled-samples` to estimate pilot precision and NNR from relevance-labelled PMIDs. Use `audit-workbook` when a spreadsheet handoff will help peer review or documentation; it includes a Design Ledger sheet when variants output is supplied. The workbook is optional: always create the required audit Markdown file structured by `audit-template.md` and required by `workflow.md`, even when an `.xlsx` workbook is also exported.

### Bramer reciprocal gap analysis

Use existing `search`, `sample`, and `batch` commands for the conditional diagnostic checks described in `references/bramer-reciprocal-gap-analysis.md`. Keep the controlled-vocabulary layer and text-word layer in separate query files, then create temporary gap-query files:

```text
(<mesh_or_scr_layer>) NOT (<text_word_layer>)
(<text_word_layer>) NOT (<mesh_or_scr_layer>)
```

Count both directions, and sample only when record inspection will inform term discovery or rejection:

```bash
python scripts/pubmed_tool.py search --query-file concept_mesh_not_text.txt --retmax 0 --summary
python scripts/pubmed_tool.py search --query-file concept_text_not_mesh.txt --retmax 0 --summary
python scripts/pubmed_tool.py sample --query-file concept_mesh_not_text.txt --retmax 5 --output sample_concept_mesh_not_text.json
python scripts/pubmed_tool.py batch bramer_gap_queries.json --summary
```

These `NOT` queries are temporary diagnostics. Do not copy them into the final strategy unless the protocol independently requires an exclusion and final QA documents the recall risk.

### Windows and PowerShell input

On Windows, pass the file *path*, not the file contents: use `--query-file query.txt` (or `--query-stdin`), and do not read a query into a variable to splice onto the command line. PowerShell re-parses inline arguments, so long Boolean strategies lose brackets, parentheses, and wildcards (`[tiab]`, `(...)`, `*`), and Windows PowerShell 5.1 can corrupt non-ASCII characters the same way.

- The tool decodes UTF-8, UTF-8-with-BOM, and UTF-16, so query and JSON files written by Notepad, VS Code, `Set-Content`, or `Out-File` all load correctly. Prefer `Set-Content -Encoding utf8` when authoring a file for portability.
- Do not build a blocks/benchmark JSON file with `ConvertTo-Json` piped from `Get-Item`/`Get-ChildItem` or other objects; that serializes file metadata into the `query` field and is rejected with a clear error. Write plain query text, or hand-write `{"label": "...", "query": "<query text>"}`.
- If you must read a file into a variable, use `Get-Content -Raw -Encoding utf8 query.txt` or `[System.IO.File]::ReadAllText((Resolve-Path query.txt).Path)` — but passing `--query-file query.txt` is simpler and sidesteps the quoting problem entirely.

### Compact output and record-content commands

Compact output controls context. Record-content commands preserve evidence.

Compact output is appropriate for count, translation, validation, recall, variant, related-record, and term-rank dashboards. For `search`, `batch`, `variants`, `validate`, `recall`, `related`, and `term-rank`, use `--summary` for compact stdout or `--output <path>` to save the full JSON while stdout shows the compact summary. When PubMed reports zero-hit or quoted phrases not found, the compact summary lists the actual phrases in `phrases_not_found` (with per-issue `drift_details`), so the §9 cleanup can remove or fix them without rerunning full output; the audit scaffold also records dropped zero-hit phrases for documentation.

`fetch`, `mine`, and `sample` are record-content commands. They require `--output`, always save full JSON, and print only a receipt; a stray `--summary` is tolerated as a no-op (record-content output is always receipt + saved JSON) and noted in the receipt rather than aborting with a parse error. Use the receipt only to confirm execution, counts/status, and output path. Inspect the saved JSON before making relevance, scope, noise, term-discovery, or concept-role decisions.

```bash
python scripts/pubmed_tool.py search --query-file full_strategy.txt --retmax 0 --summary
python scripts/pubmed_tool.py fetch --pmids 24102982 21171099 --output seed_fetch.json
python scripts/pubmed_tool.py mine --pmids 24102982 21171099 --strategy-file strategy.txt --output seed_mine.json
python scripts/pubmed_tool.py sample --query-file draft_strategy.txt --retmax 5 --output sample.json
python scripts/pubmed_tool.py batch queries.json --summary
python scripts/pubmed_tool.py recall --query-file strategy.txt --benchmark-json related.json --blocks-file blocks.json --output recall.json
python scripts/pubmed_tool.py term-rank --relevant-query-file pilot.txt --output term_rank.json
```

The compact summary always preserves the QA signal for supported dashboard commands: `ok`, result `count`, warning/error counts and codes, `query_translation` drift status and issue codes, pre-command issue codes, seed PMIDs retrieved/missed (validate, variants), term-rank totals, related-set counts, and relative recall percentage, missed count, and bottleneck block (recall). It omits full query text, `query_translation`, and long PMID/term arrays. Compact summaries are dashboards, not evidence stores. Chaining commands (for example feeding a `related` set to `recall --benchmark-json` or `term-rank --mine-json`) reads the full `--output` file, not stdout.

Record every material `--output` path in the run manifest with `manifest_tool.py add --output ...`. `manifest_tool.py show --validate` fails if `fetch`, `mine`, or `sample` entries lack an output path, use `--summary`, or record a `pubmed_tool.py fetch|mine|sample` command without `--output`.

### Seed-set expansion

Use `related` to expand a small set of confirmed seed PMIDs into a larger candidate relevant set via PubMed eLink, the way expert searchers chain from known papers. `--links` selects the link types: `similar` (PubMed "Similar articles" neighbors, with similarity scores), `citedin` (papers that cite the seeds), and `refs` (papers the seeds cite). Output is a deduplicated `candidate_pmids` list with provenance per PMID (`via`, `seed_sources`, `similarity_score`, `seed_overlap_count`), ranked so neighbors corroborated by multiple seeds surface first. The original seeds are excluded from the candidate list. `--max-per-seed` and `--max-total` bound the set to keep NCBI calls and downstream work in check.

The expanded set is a **candidate relevant set, not a validated gold standard**. Use it two ways, both pre-gate and term-discovery only:

- Feed high-overlap candidate PMIDs to `term-rank --pmids ...` so coverage/lift are computed against a richer relevant set than the raw seeds alone.
- Optionally sanity-check draft-strategy recall against the high-overlap candidates as a heuristic.

Guardrails: expanded PMIDs are candidate evidence, never auto-added terms; classify any harvested term by concept role like any other candidate. Label related-set evidence as **distinct from user-confirmed seed evidence** in the ledger and audit, and never report neighbor retrieval as validated search sensitivity (the output carries this caveat in its `note` field). Respect the overfitting rules in `seed-pmid-validation.md`.

### Relative-recall estimation

Use `recall` to answer "is this strategy actually sensitive?" beyond known-item seed checks. It measures how much of a **benchmark relevant set** the draft strategy retrieves and, with `--blocks-file`, pinpoints which concept block leaks recall.

- Strategy comes from the positional query, `--query-file`, or `--query-stdin` (file-based for full strategies).
- Benchmark comes from exactly one of: `--benchmark-pmids` (e.g. an independent gold standard such as a prior review's included studies), `--benchmark-json` (reuse a `related` run's `candidate_pmids`, optionally filtered by `--min-seed-overlap`, or a `mine` run, or a bare PMID list), or `--benchmark-query-file` (a query defining the set, capped by `--benchmark-retmax`).
- `--exclude-pmids <PMID ...>` drops PMIDs from the resolved benchmark (e.g. a seed excluded at pre-gate triage as out-of-scope/retracted, or noise from a `related` expansion) so they do not distort the benchmark denominator; `--only-pmids <PMID ...>` restricts it to an accepted whitelist. The run records `excluded_pmids` for the audit.
- `--blocks-file` is a JSON list of `{label, query}` concept blocks (or a `{label: query}` map). Each block query must be plain text; recall fails fast with a clear error if a block value is a serialized object/file-metadata blob instead of a query string (a common PowerShell `ConvertTo-Json` pitfall). Output reports `relative_recall_percent`, `retrieved_pmids`/`missed_pmids`, per-block `block_recall` with a `bottleneck` flag (lowest-recall block), and `miss_diagnosis` listing the `culprit_blocks` for each missed PMID (`and_interaction` marks a record retrieved by every block alone but lost by the full strategy — check `NOT`, filters, or proximity).
- The `related` → `recall` chain is the common path: expand seeds, then test the draft strategy against the high-overlap candidates.

Interpretation and guardrails: relative recall is **relative to the benchmark, not absolute search sensitivity**. Against a seed-expansion benchmark it is a heuristic that can flatter recall (the benchmark is strategy-adjacent); against an independent hand-screened gold standard it is a legitimate relative-recall estimate but still not absolute sensitivity. A benchmark PMID not in PubMed is indistinguishable from a genuine miss. The output carries these caveats in its `note`. Never use a recall number to silently narrow a recall-first strategy. Use `block_recall` to revise the bottleneck concept (see `seed-pmid-validation.md`).

### Objective term ranking

Use `term-rank` to turn a relevant/seed set into a discrimination-scored term list instead of eyeballing raw frequencies. `--fields` selects the scoring layers and accepts only `tiab` and/or `mesh` (default `tiab,mesh`): the `tiab` layer scores free-text candidates harvested together from titles, abstracts, acronyms, and author keywords, and the `mesh` layer scores assigned MeSH headings — there is no separate `keywords`, `acronym`, or `phrase` field. It computes per-record document frequency for these candidates, then fetches one PubMed background count per candidate to compute `coverage`, `background_count`, and `lift` (see `tiab-expansion.md` for interpretation). Before scoring, it drops obvious non-topical noise so junk neither crowds the ranked list nor consumes background lookups: structured-abstract section labels (OBJECTIVE/METHODS/RESULTS/CONCLUSIONS), statistical fragments (e.g. `p 0`, `95 ci`), and non-topical MeSH (check tags and common geographic descriptors such as Queensland; the geographic list is curated, so a rare place name may still appear). The relevant-set inputs are mutually exclusive: `--pmids`, `--mine-json` (reuses a prior `mine` run's found PMIDs), or `--relevant-query-file` (a pilot relevant set defined by a query). Because `--mine-json` reuses *all* of the prior run's found PMIDs, add `--exclude-pmids <PMID ...>` to drop any seed excluded at pre-gate triage (out-of-scope, retracted, malformed) so it never pollutes the enrichment, or `--only-pmids <PMID ...>` to restrict to an accepted whitelist (a pure accepted-seed whitelist is also just `--pmids <accepted>`); the run records `relevant_pmids` and `excluded_pmids` for the audit. When no seeds are available - the common case - `--relevant-query-file` is the route into `term-rank`: after the concept gate, build a small, deliberately high-precision pilot query (favor precision over recall so the relevant set is not polluted), bound it with `--relevant-retmax` (default 200), and treat the output as candidate evidence labelled separately from seeds, never validated recall. See `tiab-expansion.md` for how to construct the pilot query. To bound NCBI calls, only the top `--max-terms` candidates by document frequency are scored (default 40); raise it deliberately, or restrict `--fields` to one layer, for exhaustive scoring. Feed the JSON to `audit-workbook --term-rank-json` for a Term Ranking sheet. Treat scores as term-discovery aids, not validated recall.

`pubmed_tool.py` runs pre-command and query-translation hooks automatically:

- Pre-command hook blocks API keys on the command line and in query text from arguments, files, stdin, or batch input; warns about long inline queries; warns on very large `retmax`; and reminds batch count comparisons to use `--retmax 0` unless PMID samples are needed.
- Query translation drift hook runs after each PubMed ESearch response for `search`, `sample`, `validate`, `batch`, `variants`, and `doctor`. It inspects PubMed's returned `query_translation`, translation set, warning list, and error list for zero-hit terms not found in PubMed (`phrases_not_found`, deduplicated with an occurrence count), unrecognized field tags (`fields_not_found`), ignored phrases, quoted phrases not found, broad `[All Fields]` fallback, untagged acronym-like terms, large ATM expansion, and mixed tagged/untagged queries. It is warning-only, never blocks execution, makes no extra NCBI calls, and consumes no LLM/API tokens because it is local Python string analysis. The only practical token cost is the extra JSON shown to Codex: about 20-40 JSON tokens when quiet and about 60-120 per warning, capped per query. False positives are expected for intentional ATM use, valid broad MeSH explosions, correctly handled acronyms, and broad concepts with naturally long translations, so treat issues as review prompts rather than proof of an error.

## Strategy Hooks

Use `scripts/hooks_tool.py` for pre-final, non-network checks:

```bash
python scripts/hooks_tool.py final-qa --strategy-file final_strategy.txt
python scripts/hooks_tool.py filter-check --text-file protocol_or_strategy.txt
```

Run `final-qa` before presenting a draft strategy. It flags recall risks such as `[Majr]`, `NOT`, language/date/species/age/publication-type/full-text limits, short wildcards, proximity with truncation, missing MeSH or `[tiab]` layers, and unreviewed quoted `[tiab]` singular/plural phrase pairs as `singular_plural_wildcard_review`; resolve that warning by testing the phrase-final, phrase-anchored/concept-specific wildcard candidate or documenting explicit-form retention. It reports exact duplicate terms as `duplicate_term` (recall-neutral cleanup; it detects an atom repeated across the flat `OR` list and nested `MeSH AND (...)` sub-clauses, which is the usual source of duplicated zero-hit terms). For multi-block strategies, it checks top-level concept blocks separately so one block's MeSH does not hide another block's missing controlled-vocabulary layer.

Run `filter-check` whenever the protocol, request, or strategy mentions a study-design/evidence-type intent such as RCTs, systematic reviews, qualitative studies, diagnostic accuracy, prognosis, observational studies, or economic evaluations. If it reports that validated filter review is needed, read `validated-methodological-filters-and-hedges.md`, use `pubmed_tool.py batch` for topic-only versus topic-plus-filter counts, and validate seed PMID impact when seeds exist.

## Audit Scaffold

Use `scripts/pubmed_tool.py audit-scaffold` to assemble most of the audit JSON from files the build already wrote - the per-command `--output` JSONs and `run_manifest.json` - instead of re-transcribing counts and lists by hand. It makes no network calls and prints a receipt listing the source files used.

```bash
python scripts/pubmed_tool.py audit-scaffold --manifest run_manifest.json --final-search-json final_search.json --strategy-file full_strategy.txt --validate-json seed_validation.json --seed-fetch-json seed_fetch.json --seed-mine-json seed_mine.json --related-json related.json --recall-json recall.json --date-searched 2026-05-31 --output audit_pressure-ulcer_2026-05-31.json
```

It fills mechanical fields from the saved outputs: result count and final strategy (from `--final-search-json`/`--strategy-file`), the PubMed CLI-checks table and search date (from the manifest's labelled `search`/`batch` entries, or `--date-searched` when local/reporting date alignment matters), seed retrieved/missed (from `--validate-json`), pre-gate seed triage facts (from `--seed-fetch-json` or `--seed-mine-json`), seed-set expansion counts and candidate labels (from `--related-json`), relative-recall metrics and block diagnosis (from `--recall-json`), the ATM translation, the run manifest path, and the chosen/focused variant (from `--variants-json`). Pass `--blocks-file` (the same `{label, query}` JSON used by `recall`) to populate `concept_blocks` for the numbered line set; per-block counts are matched from labelled manifest `search` entries and the combination defaults to all blocks AND-ed (override in an overlay for non-trivial logic). Counts come from the saved `--output` file content, not the manifest's hand-typed `--count`. `result_count` and the final strategy are filled only from an explicitly supplied final/post-hygiene search; with none supplied the scaffold leaves a placeholder rather than guess the headline count.

It leaves every judgment field - the decision ledger, rationale, peer-review points, the search-structure framing, seed-scope/retraction judgments, record-content review attestations, and related-set use decisions - as bracketed placeholders that `audit_markdown.py` refuses to render until you author them, so the scaffold never invents reasoning. For `fetch`, `mine`, and `sample` evidence it records only that the saved JSON file exists and that receipt-only stdout was not used; it never fills `record content reviewed` or `decision supported`, because you must inspect the saved JSON yourself (No reviewed JSON, no decision). `related` evidence is labelled separately from user-confirmed seed evidence and is not validated recall; `recall` output is reported as relative recall, not absolute sensitivity. It defaults to `--if-exists fail` so a re-run never clobbers an audit you have already filled in. Then complete the remaining `audit-template.md` sections, fill the placeholders, and render with `audit_markdown.py`.

## Audit Markdown Tool

Use `scripts/audit_markdown.py` when structured audit notes are available. For completed strategy builds, first save the structured audit notes as a UTF-8 JSON file, preferably `audit_<topic>_<date>.json`, then render the Markdown from that file:

```bash
python scripts/audit_markdown.py audit_adhd_bipolar_2026-05-18.json --output audit_2026-05-18.md --if-exists suffix
python scripts/audit_markdown.py audit_pressure-ulcer_2026-05-31.json --overlay-json audit_pressure-ulcer_decisions.json --output audit_pressure-ulcer_2026-05-31.md --if-exists suffix
```

The default command output is a compact JSON receipt rather than the full audit
Markdown. It includes the saved path, byte count, placeholder count, and section
count. Use `--print-report` only when the terminal output itself must include
the full report. The tool refuses unresolved placeholder-like text by default
and refuses to overwrite existing files unless `--if-exists overwrite` or
`--if-exists suffix` is selected.

Supply a `concept_blocks` list (`[{label, query, count}]`, plus an optional `combination` like `"1 AND 2"` and a `methodological_filter` object) to render a submission-ready **numbered line set** (PubMed Advanced Search history style) inside the audit report; `audit_markdown.py` numbers the lines, adds the combination/filter lines, and flags any block whose query is absent from `final_strategy`. A **PRISMA-S appendix** block (Items 1-16, in-scope items filled from reporting fields) is always rendered. Pass `--emit-appendix <path>` to also write just the line set + PRISMA-S appendix as a standalone paste-ready file for a manuscript:

```bash
python scripts/audit_markdown.py audit_demo.json --output audit_demo.md --emit-appendix appendix_demo.md
```

When using an audit scaffold, keep the scaffold JSON as the mechanical base and put authored judgment fields in a small overlay JSON. `--overlay-json` deep-merges dictionaries recursively while lists and scalars replace scaffold values; this avoids large PowerShell command payloads and preserves scaffold-filled counts, dates, seed lists, and evidence paths.

Stdin input (`python scripts/audit_markdown.py - ...`) is acceptable only for tiny smoke tests. Do not pipe large structured audit objects from shells such as PowerShell `ConvertTo-Json | python scripts/audit_markdown.py -`; file-based JSON plus `--overlay-json` avoids stdin buffering, quoting, command-length, and `ConvertFrom-Json` property-addition failures. If rendering times out or fails, keep the audit JSON, rerun the renderer from the saved file, and use direct Markdown from `references/audit-template.md` only as a final fallback. Document any fallback in Reporting notes.

## Run Manifest Tool

Use `scripts/manifest_tool.py` to maintain a canonical `run_manifest.json` provenance ledger for the build. It makes no network calls and is the single machine-readable record of every material command run, its output path, the date, the PubMed result count where relevant, and any superseded file. Only the agent can maintain it, because the PubMed and MeSH tools stream JSON to stdout and never see agent-written artifacts such as concept-block `.txt` files or `audit_*.md`.

```bash
python scripts/manifest_tool.py init --manifest run_manifest.json --topic-slug pressure-ulcer
python scripts/manifest_tool.py add --manifest run_manifest.json --kind search --command "python scripts/pubmed_tool.py search --query-file full_strategy.txt --retmax 0" --count 192246 --label "main strategy" --note "final topic-only count"
python scripts/manifest_tool.py add --manifest run_manifest.json --kind sample --command "python scripts/pubmed_tool.py sample --query-file draft_strategy.txt --retmax 5 --output sample.json" --output sample.json --label "draft sample"
python scripts/manifest_tool.py add --manifest run_manifest.json --kind artifact --command "python scripts/audit_markdown.py audit_pressure-ulcer_2026-05-31.json --output audit_pressure-ulcer_2026-05-31.md" --output audit_pressure-ulcer_2026-05-31.md --note "audit markdown"
python scripts/manifest_tool.py add --manifest run_manifest.json --kind artifact --command "python scripts/audit_markdown.py audit_pressure-ulcer_2026-05-31.json --output audit_pressure-ulcer_2026-05-31.md --if-exists suffix" --output audit_pressure-ulcer_2026-05-31_2.md --supersedes audit_pressure-ulcer_2026-05-31.md --note "re-rendered after cleanup"
python scripts/manifest_tool.py show --manifest run_manifest.json --validate --check-files
python scripts/manifest_tool.py report --manifest run_manifest.json
```

`add` auto-creates the manifest if it is missing, stamps each entry with a UTC timestamp and a sequence number, and, when `--supersedes` is given, records the old path as superseded by the new `--output`. `--kind` is one of `search`, `fetch`, `related`, `mine`, `sample`, `term-rank`, `recall`, `batch`, `variants`, `validate`, `qa`, `mesh`, `artifact`, or `other`; tag entries with `--label` (e.g. `main strategy`, `robopet block`) so main/block/variant counts are distinguishable, tag sweeps and block counts with `--block <label>` to feed the per-block coverage gate (see *Per-block evidence coverage* below), and flag unresolved choices with `--open-decision`. For record-content commands, prefer the matching `fetch`, `mine`, or `sample` kind and record the saved JSON with manifest-level `--output`. Record material commands (count checks, block and full-strategy tests, validate, recall, variants, audit render) and every artifact write or supersession; exploratory throwaway lookups may be summarized or omitted, and entries must reflect commands that were actually run. `show --validate` checks the manifest is well-formed (valid JSON, required keys, integer-or-null counts, known kinds, no duplicate sequence numbers); add `--check-files` before final handoff to flag recorded output paths that do not exist. `report` prints a read-only build dashboard from the manifest (entries grouped by kind, the current audit path, superseded files, and open decisions) and never reruns searches. Report the saved `run_manifest.json` path with the audit files. Adds are normally sequential, but `add` is safe under accidental concurrency: each writes atomically and holds a short-lived `run_manifest.json.lock`, so parallel adds get unique sequence numbers and never corrupt the ledger.

### Build-state tracking

`manifest_tool.py state` keeps a live `build_state` block inside `run_manifest.json` so the current stage, gate decisions, and the one open user question are read from a file instead of reconstructed from the conversation each turn. It is lazily created on first use, so manifests written only with `init`/`add` are unchanged.

```bash
python scripts/manifest_tool.py state set-stage concept-gate
python scripts/manifest_tool.py state resolve-gate framework PECO
python scripts/manifest_tool.py state resolve-gate concept resolved
python scripts/manifest_tool.py state set-question "Promote outcome to an AND block?"
python scripts/manifest_tool.py state clear-question
python scripts/manifest_tool.py state show          # read-only
python scripts/manifest_tool.py state check-ready    # exit 1 until the concept gate is resolved and no question is pending
```

Stages are the workflow stage slugs (`question-intake`, `seed-intake`, `concept-gate`, `mesh-exploration`, `block-testing`, `validation`, `final-qa`, `audit-output`, ...); gates are `framework`, `seed`, `concept`, and `filter`. The same readiness check is folded into the final manifest validation: `manifest_tool.py show --validate --check-files --require-ready` is the binding handoff gate and exits non-zero while the concept gate is unresolved or a user question is still pending (`state check-ready` runs it standalone).

Gate values are free-form, but record the **seed gate** as one of `provided`, `none`, or `partial` (`state resolve-gate seed none`). A `none` (no-seed) build is then auto-detected: read-only views (`state show`, `show`, `report`) surface a non-blocking `reminders` entry telling you to offer the optional heuristic recall check and gate handoff with `--require-recall-offer`. The reminder never affects exit codes; it just prevents the no-seed recall offer from being forgotten.

### Per-block evidence coverage

Beyond the stage/gate readiness check, `build_state` also tracks **per-essential-block evidence coverage**, so the manifest can confirm each essential concept actually got an aggressive MeSH sweep and a block count rather than relying on the model's recollection. Register the essential blocks once (reuse the same `--blocks-file` built for `recall`/`audit-scaffold`), tag each sweep/count entry with `--block <label>`, and check coverage before handoff:

```bash
python scripts/manifest_tool.py state register-blocks --blocks-file blocks.json   # seed blocks from the blocks-file labels
python scripts/manifest_tool.py state register-block "malaria"                    # or register one label at a time
python scripts/manifest_tool.py add --kind mesh   --block "malaria" --command "python scripts/mesh_tool.py sweep --concept malaria --output sweep_malaria.json" --output sweep_malaria.json
python scripts/manifest_tool.py add --kind search --block "malaria" --command "python scripts/pubmed_tool.py search --query-file malaria_block.txt --retmax 0" --count 192246
python scripts/manifest_tool.py state coverage                                    # read-only; exit 1 while any block has a pending requirement
python scripts/manifest_tool.py show --require-coverage --validate               # opt-in coverage gate (exits non-zero on a coverage gap)
```

Each registered block needs two requirements satisfied: `mesh_sweep` (a `--kind mesh` entry, or any command containing `mesh_tool.py sweep`, tagged to the block) and `block_count` (a `--kind search` or `--kind batch` entry tagged to the block). Entry-to-block matching prefers the explicit `--block` tag and falls back to the free-text `--label` (so a label like `malaria block` still counts for block `malaria`). When a requirement genuinely does not apply — a concept with no MeSH descriptor, or one deliberately kept text-word-only — record a **reasoned waiver** instead of leaving it pending; the reason is mandatory and is surfaced in `state coverage`, `report`, and the audit:

```bash
python scripts/manifest_tool.py state waive-requirement "rapid diagnostic test" mesh_sweep "no MeSH descriptor exists; SCR/text-word coverage only"
```

The coverage gate is currently **opt-in** (`show --require-coverage` / `state coverage`); it is not yet part of `--require-ready`. Run it at Final QA alongside `--require-ready` so a block that was never swept or count-tested surfaces as a hard `coverage gap` before handoff rather than as a silent omission.

### No-seed recall offer

On a **no-seed build**, `build_state` also tracks whether the optional heuristic recall check was offered. The Validation stage must offer it once (see `references/no-seed-recall-estimation.md`); record the user's choice so handoff can confirm the offer was actually made:

```bash
python scripts/manifest_tool.py state resolve-recall-offer done            # accepted and run
python scripts/manifest_tool.py state resolve-recall-offer declined        # user declined
python scripts/manifest_tool.py state resolve-recall-offer not-applicable  # too few anchors/candidates to be meaningful
python scripts/manifest_tool.py show --require-recall-offer                 # opt-in no-seed gate; exit 1 while recall_offer is pending
```

`recall_offer` defaults to `pending` and is only meaningful on no-seed builds. `--require-recall-offer` is **opt-in and separate from `--require-ready`**: pass it at handoff only when no seeds were supplied. Seeded builds use known-item validation and ignore this gate.

If the user accepts, `pubmed_tool.py recall --pilot-query-file pilot.txt --auto-expand --blocks-file blocks.json` runs the pilot → `related` → recall pipeline in one call (add `--anchor-sample-output` to save anchors for inspection); without `--auto-expand` the pilot's own hits are the benchmark (weaker/circular). See `references/no-seed-recall-estimation.md` for the full pipeline, guardrails, and the manual three-step form.

## Tool-to-stage quick map

`references/workflow.md` owns the canonical build sequence and stage order; this section does not restate it. The map below only says which bundled command belongs to each workflow stage. Throughout, maintain the run manifest with `scripts/manifest_tool.py`: run `init` once at the start, `add` after each material command or artifact, and `show --validate --check-files --require-ready` at the end (see the Run Manifest Tool section above).

| Workflow stage | Bundled command(s) | Tool note |
|---|---|---|
| Limited seed evidence (pre-gate) | `pubmed_tool.py fetch` / `mine`; optional `related` → `term-rank` | Seed records only, to inform concept analysis. Label `related` output as related-set evidence, distinct from seed-derived; it is term-discovery support, not broad PubMed exploration or block testing. |
| Concept gate | (no tools) | Resolve the Phase 1 concept gate before MeSH lookup, PubMed exploration, block construction, variants, final QA, or filter checks. |
| MeSH/PubMed exploration | `pubmed_tool.py search` (ATM/translation clues); `mesh_tool.py sweep --details`, `tree` | Build variant lists from brainstormed vocabulary plus seed/user/ATM clues, then run an aggressive sweep per essential concept and complete the MeSH candidate ledger before drafting a block. Use `mesh_tool.py sparql` only for unusual follow-ups not covered by `tree`. |
| Text-word / block testing | `pubmed_tool.py search`, `batch` | Test text-word clusters, proximity, wildcard stems, and conditional Bramer reciprocal gap queries, then single blocks, pairwise blocks, and the full topic-only strategy; test topic-plus-filter separately when a filter is used. |
| Validation | `pubmed_tool.py validate`; optional `recall --blocks-file`; no-seed: `state resolve-recall-offer` | Known-item seed retrieval; optionally estimate relative recall against a benchmark to find the bottleneck block (relative, not absolute). Diagnose missed seeds, including filter-caused misses. On a no-seed build, offer the optional heuristic recall check (`references/no-seed-recall-estimation.md`) and record the outcome. |
| Final QA | `pubmed_tool.py search --retmax 0`; `hooks_tool.py final-qa`, `filter-check`; `manifest_tool.py state coverage` | Run hygiene, then the final validation and cleanup offer (`workflow.md` §9). Check per-block coverage so no essential block was left unswept or untested. |
| Audit output | `pubmed_tool.py audit-scaffold` → `audit_markdown.py`; `manifest_tool.py show --validate --check-files --require-ready` | Assemble the audit JSON from saved outputs, author the judgment placeholders, render the Markdown, and report the saved audit and `run_manifest.json` paths. `--require-ready` blocks handoff until the concept gate is resolved and no question is pending. |

## Do Not Fabricate

Never invent:

- MeSH descriptors
- entry terms
- PubMed counts
- PMIDs
- validation results
- whether a PMID was retrieved
- run-manifest entries for commands that were not run or files that were not written
