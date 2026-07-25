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
# Force the reduced-fidelity fallback backend only for an intentional availability workaround.
python scripts/mesh_tool.py lookup --label "pressure ulcer" --match exact --backend eutils
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

The sweep searches both descriptor labels and entry terms with exact, startswith, and contains matching. It also resolves entry-term hits upward to their parent descriptors or supplementary concepts where MeSH RDF exposes that relation. To keep broad sweeps practical, unique term resources are resolved in bounded `VALUES` batches (40 by default; adjust with `--term-mapping-batch-size`) rather than one RDF request per term. Output candidates are ranked by match specificity, direct descriptor hits before term-derived hits, MeSH descriptors before supplementary concepts, then query-label order and label. Treat the output as a candidate table, not as final truth.

To prevent broad sweeps from becoming unbounded, `sweep` caches identical MeSH backend responses both in memory and in a user-level persistent cache, and applies default budgets: 40 unique term-to-descriptor resources (resolved in one or more batches) and 30 detailed candidate enrichments when `--details` is used. The persistent cache is shared across CLI processes, so splitting a cold sweep into smaller commands does not discard successful work. Its default location is `$CODEX_HOME/cache/pubmed-search-builder/mesh-rdf` (or `~/.codex/cache/pubmed-search-builder/mesh-rdf` when `CODEX_HOME` is unset), outside the skill checkout. Entries expire after 24 hours by default because the MeSH RDF dataset is published on a daily cadence. Use `--max-term-descriptor-lookups`, `--term-mapping-batch-size`, and `--max-detail-candidates` to adjust sweep limits deliberately. `network_budget` records the number of batch requests and the estimated per-term requests avoided. If a batch reaches its result/candidate safeguard, the sweep remains explicitly partial rather than silently treating truncated mappings as complete; reduce the batch size and rerun. Exhausting the term-mapping budget also produces `status: "partial"`; unresolved term-to-descriptor lookups are listed explicitly and must be resumed before the candidate ledger is complete.

Long variant lists are additionally hardened against timeouts and repeated host failures. A wall-clock budget (`--max-seconds`, default 120; `0` = unlimited) bounds the whole run, the highest-value matches run first (exact, then startswith, then contains), and ordinary per-request failures are recorded in `errors` and skipped. MeSH RDF commands share a conservative cross-process request pace (2 requests/second by default). HTTP 429, HTTP 403 with `Retry-After`, and connection resets are treated as **rate-limit-like** signals; a reset may also mean host or network unavailability and is not proof that NLM throttled the client. Rate-limit-like failures get fewer retries than ordinary transient failures. After three consecutive logical requests end in a rate-limit-like failure, a disk-backed circuit breaker stops new requests for 120 seconds. Only one process is allowed to make the half-open probe after cooldown; a successful probe closes the circuit, while another rate-limit-like or transient host failure reopens it with a longer bounded cooldown.

When the circuit opens in RDF-only mode, `sweep` stops once instead of generating an error for every remaining variant. It returns `status: "partial"`, includes `circuit_open` in `stop_reason`, preserves unswept search units in `pending`, and preserves unfinished detail work in `pending_detail_descriptors`. In the default auto backend, an eligible RDF circuit, rate-limit-like exhaustion, or transient exhaustion instead switches the rest of that process to E-utilities; permanent/hard RDF errors never trigger fallback. Fresh cached responses remain usable while a circuit is open. Always run long sweeps with `--output <path>`: the full JSON (including `raw_searches` and per-candidate `details`) is written there and **checkpointed after each label**, so even a killed process leaves useful partial output, while stdout shows a compact, token-cheap summary (ranked candidate descriptors with their sources, plus `status`, `coverage`, `network_budget`). Add `--pending-output <pending_variants.txt>` to write newline-delimited pending variant labels compatible with `--variants-file` on a follow-up run. `--summary` prints that same compact summary without writing a file.

A sweep that hits the time or term-lookup budget, opens the circuit, or has request errors returns `status: "partial"` with a `stop_reason` and the exact deferred work in `pending`, `pending_term_descriptor_lookups`, and/or `pending_detail_descriptors`. Treat a partial sweep as **incomplete MeSH/entry-term recall**: rerun the pending and failed work (a separate sweep is fine) and merge candidates before finalising the concept block. If `--pending-output` was used, pass the saved file to the rerun via `--variants-file`; still review `errors`, pending descriptor lookups, and pending details separately because failed or deferred lookups are not the same as unswept labels. Token savings come only from the compact stdout projection; every completed candidate remains present, while deferred work is explicit. For very long variant lists, prefer splitting the work into several smaller sweeps (see *Separate MeSH Lookups* below).

### MeSH backend, cache, and resilience controls

Inspect the persistent cache and shared circuit state before rerunning a partial sweep:

```bash
python scripts/mesh_tool.py cache stats
python scripts/mesh_tool.py circuit status
```

Use `cache clear` to remove response entries, or `circuit reset` for an intentional manual breaker reset after checking that the host/network is healthy. Every network command accepts `--no-cache` for a one-command fresh fetch; it bypasses both cache reads and writes but keeps pacing and circuit protection active.

The following environment variables tune Phase 1 behavior. Defaults are deliberately conservative; change them only for a documented operational reason:

| Variable | Default | Effect |
|---|---:|---|
| `MESH_CACHE` | `on` | Set to `off`, `false`, `no`, `0`, or `disabled` to bypass response caching globally. |
| `MESH_CACHE_DIR` | user cache path above | Override the response-cache and shared-state directory. |
| `MESH_CACHE_TTL_DAYS` | `1` | Freshness lifetime for successful RDF JSON or E-utilities XML/JSON responses. |
| `MESH_BACKEND` | `auto` | `auto` uses RDF first and falls back only for eligible availability failures; `rdf` disables fallback; `eutils` intentionally uses the reduced-fidelity fallback. A per-command `--backend` overrides this. |
| `MESH_RATE_LIMIT` | `2` | Shared requests per second across concurrent CLI processes; `0` disables pacing. |
| `NCBI_API_KEY` | unset | When using MeSH E-utilities, raises its shared NCBI pacing ceiling from 3 to 10 requests/second. Keep this private; it is sent only to NCBI and is never part of a cache key. |
| `NCBI_EMAIL` / `NCBI_TOOL` | existing defaults | Identifies MeSH E-utilities traffic to NCBI. |
| `MESH_THROTTLE_RETRIES` | `1` | Retries after a rate-limit-like signal, per logical request. |
| `MESH_TRANSIENT_RETRIES` | `3` | Retries after timeouts, DNS failures, 408/5xx responses, or invalid/empty JSON. |
| `MESH_CIRCUIT_THRESHOLD` | `3` | Consecutive logical rate-limit-like failures before opening. |
| `MESH_CIRCUIT_COOLDOWN` | `120` | Initial open-circuit cooldown in seconds. |
| `MESH_CIRCUIT_MAX_COOLDOWN` | `900` | Maximum exponential cooldown in seconds. |

The `network_budget.transport` object reports cache hits/misses, network attempts, classified failure events, retries, retry/pacing sleep, circuit-open events, and RDF-to-E-utilities fallback events for that sweep. These are operational diagnostics, not evidence that a particular failure was deliberate NLM throttling. Cache writes are atomic, corrupt/stale entries become safe misses, and only successful backend responses are cached. The cache, pacing, and breaker apply to both `mesh_tool.py` RDF and MeSH E-utilities traffic; PubMed E-utilities continue to use `pubmed_tool.py` and its separate NCBI controls.

The default is `--backend auto`: RDF remains primary because its lookup match semantics and graph relations support the full sweep workflow. E-utilities uses `ESearch` plus MeSH `ESummary` v2 XML, never the formatted `EFetch` output. E-utilities can provide exact descriptor lookup after preferred-heading verification, but its startswith/contains searches, flattened entry terms, and descriptor details are **reduced fidelity**. These results include `source_backend`, `fidelity`, and `provenance`; sweep aggregates them in `backend_provenance` and adds a review warning. Confirm reduced-fidelity candidates against RDF before accepting or rejecting them. `tree` can reconstruct bounded **descriptor** context from E-utilities tree-number searches when RDF is unavailable, but omits RDF-only annotations/history and does not support Supplementary Concept Records; its output is explicitly `reduced` fidelity and must be confirmed against RDF. Raw `sparql` remains RDF-only.

Every `lookup`, `terms`, `details`, `tree`, and `sweep` receipt also carries a deterministic `mesh_evidence` object. It records the operation and status, full/reduced/mixed fidelity, backend methods and fallback reasons, candidate-level fidelity counts, and required follow-up. Preserve this object when registering the saved JSON with `manifest_tool.py add`: the manifest derives and hash-binds the same summary automatically. A block's `mesh_sweep` coverage requirement is satisfied only by an artifact whose `mesh_evidence` says `operation: sweep` and `status: complete`; a tree lookup, a command-shaped placeholder, or a partial sweep never qualifies. A reduced-fidelity fallback is allowed, but its saved artifact and RDF-confirmation warning must be carried into the final audit.

After each sweep, do not immediately write the concept block. First complete the **MeSH candidate ledger** defined in `workflow.md` section 4: separate sweep inputs from outputs; add candidates from sweep output, screened discovery-record MeSH, PubMed ATM/query translations, and sample-record indexing; inspect plausible descriptors/SCRs for scope, entry terms, related descriptors, qualifiers, and tree context; accept/reject/defer with reasons; test accepted and recall-relevant rejected descriptors; and resolve ATM mappings before finalising the block.

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
- discover candidate PMIDs from screened anchors via PubMed eLink (similar articles, cited-by, references); screen before mining
- mine seed PMID titles, abstracts, MeSH headings, keywords, acronyms, phrases, and strategy gaps
- rank candidate tiab/MeSH terms by enrichment in a relevant/seed set versus PubMed background
- inspect titles and abstracts
- inspect MeSH headings assigned to seed papers
- run candidate MeSH terms
- run text-word clusters
- run wildcard candidates
- run the Bramer reciprocal gap analysis for a block in one call (`term-diff`)
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
python scripts/strategy_analysis.py concept-ablation --blocks-file blocks.json --candidate-ledger candidate_ledger.json --scope-version 1 --output concept_ablation.json
python scripts/strategy_analysis.py two-strand --main-strategy-file final_main_strategy.txt --narrowing-blocks-file focused_blocks.json --candidate-ledger candidate_ledger.json --scope-version 1 --output two_strand.json
python scripts/strategy_analysis.py fragility-score --concepts-file fragility_concepts.json --candidate-ledger candidate_ledger.json --concept-ablation-json concept_ablation.json --scope-version 1 --output fragility_score.json
python scripts/no_seed_discovery.py discover --pilots-file orthogonal_pilots.json --scope-version 1 --round 1 --screening-output screening_1.json --provenance-output provenance_1.json
python scripts/vocabulary_learning.py extract --scope-file review_protocol_v1.json --candidate-ledger candidate_ledger.json --records-file screened_records.json --config-file vocabulary_config.json --scope-version 1 --output vocabulary_extract_1.json
python scripts/vocabulary_learning.py retest --extraction-file vocabulary_extract_1.json --blocks-file blocks.json --scope-version 1 --output vocabulary_learning_1.json
python scripts/screening_burden.py sample --variants-file variants.json --baseline-label main --scope-version 1 --sample-size 60 --output burden_sample.json
python scripts/screening_burden.py estimate --sample-file burden_sample.json --candidate-ledger candidate_ledger.json --minimum-heldout-recall 1.0 --scope-version 1 --output screening_burden.json
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

Or run the whole reciprocal gap analysis for one block in a single call with `term-diff`: it builds both `(MeSH) NOT (text-word)` and `(text-word) NOT (MeSH)`, reports `counts` (mesh, tiab, overlap, combined, mesh_only, tiab_only), and fetches a sample of each side to inspect. It is a record-content command (requires `--output`, prints a receipt; tolerates a stray `--summary`):

```bash
python scripts/pubmed_tool.py term-diff --mesh-query-file concept_mesh.txt --tiab-query-file concept_text.txt --retmax 15 --output diff_concept.json
```

The `(... NOT ...)` queries are temporary diagnostics; do not copy them into the final strategy. Treat both directions as term-discovery candidates (not validated recall), inspect the saved records, classify each by concept role, and never auto-add. Record the analysis per `references/bramer-reciprocal-gap-analysis.md` (`performed` / `waived` / `not applicable` / `not performed`).

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

Use `related` after scope lock to expand screened-in anchors into a larger candidate set via PubMed eLink. `--links` selects `similar`, `citedin`, and `refs`. Output is a deduplicated PMID list with provenance, similarity score, and seed-overlap count. Those scores prioritize screening; they do not establish eligibility. Bound expansion with `--max-per-seed` and `--max-total`.

The expanded set is a **candidate set, not a relevant set or gold standard**:

- Fetch and screen records before assigning `discovery` or `holdout` use.
- Feed only screened-in discovery PMIDs to `term-rank --pmids ...`.
- Unscreened related records may support a separately labelled heuristic recall check only.

Validate `candidate_ledger.json` with `candidate_ledger.py`. Never harvest terms from excluded, uncertain, or unscreened records. Keep user seeds, discovery records, holdouts, and heuristic neighbors distinct in the audit.

### Relative-recall estimation

Use `recall` to answer "is this strategy actually sensitive?" beyond known-item seed checks. It measures how much of a **benchmark relevant set** the draft strategy retrieves and, with `--blocks-file`, pinpoints which concept block leaks recall.

- Strategy comes from the positional query, `--query-file`, or `--query-stdin` (file-based for full strategies).
- Benchmark comes from exactly one of: `--benchmark-pmids` (e.g. an independent gold standard such as a prior review's included studies), `--benchmark-json` (reuse a `related` run's `candidate_pmids`, optionally filtered by `--min-seed-overlap`, or a `mine` run, or a bare PMID list), or `--benchmark-query-file` (a query defining the set, capped by `--benchmark-retmax`).
- `--exclude-pmids <PMID ...>` drops records excluded during post-scope screening or noisy related candidates; `--only-pmids <PMID ...>` restricts the benchmark to an accepted whitelist. The run records both lists for audit.
- `--blocks-file` is a JSON list of `{label, query}` concept blocks (or a `{label: query}` map). Each block query must be plain text; recall fails fast with a clear error if a block value is a serialized object/file-metadata blob instead of a query string (a common PowerShell `ConvertTo-Json` pitfall). Output reports `relative_recall_percent`, `retrieved_pmids`/`missed_pmids`, per-block `block_recall` with a `bottleneck` flag (lowest-recall block), and `miss_diagnosis` listing the `culprit_blocks` for each missed PMID (`and_interaction` marks a record retrieved by every block alone but lost by the full strategy — check `NOT`, filters, or proximity).
- The `related` → `recall` chain is the common path: expand seeds, then test the draft strategy against the high-overlap candidates.

Interpretation and guardrails: relative recall is **relative to the benchmark, not absolute search sensitivity**. Against a seed-expansion benchmark it is a heuristic that can flatter recall (the benchmark is strategy-adjacent); against an independent hand-screened gold standard it is a legitimate relative-recall estimate but still not absolute sensitivity. A benchmark PMID not in PubMed is indistinguishable from a genuine miss. The output carries these caveats in its `note`. Never use a recall number to silently narrow a recall-first strategy. Use `block_recall` to revise the bottleneck concept (see `seed-pmid-validation.md`).

### Objective term ranking

Use `term-rank` to turn a **screened-in discovery set** into a discrimination-scored candidate list. Prefer `--candidate-ledger candidate_ledger.json`; this enforces discovery-only roles. `--fields` accepts `tiab` and/or `mesh`; scores include coverage, PubMed background count, lift, supporting PMIDs, selection layer, and marginal record coverage. The bounded `--max-terms` budget is selected across MeSH, author-keyword, acronym, and phrase layers so one layer cannot crowd out the others. Treat every ranked term as a candidate and classify it within the locked scope.

`pubmed_tool.py` runs pre-command and query-translation hooks automatically:

- Pre-command hook blocks API keys on the command line and in query text from arguments, files, stdin, or batch input; warns about long inline queries; warns on very large `retmax`; and reminds batch count comparisons to use `--retmax 0` unless PMID samples are needed.
- Query translation drift hook runs after each PubMed ESearch response for `search`, `sample`, `validate`, `batch`, `variants`, and `doctor`. It inspects PubMed's returned `query_translation`, translation set, warning list, and error list for zero-hit terms not found in PubMed (`phrases_not_found`, deduplicated with an occurrence count), unrecognized field tags (`fields_not_found`), ignored phrases, quoted phrases not found, broad `[All Fields]` fallback, untagged acronym-like terms, large ATM expansion, and mixed tagged/untagged queries. It is warning-only, never blocks execution, makes no extra NCBI calls, and consumes no LLM/API tokens because it is local Python string analysis. The only practical token cost is the extra JSON shown to Codex: about 20-40 JSON tokens when quiet and about 60-120 per warning, capped per query. False positives are expected for intentional ATM use, valid broad MeSH explosions, correctly handled acronyms, and broad concepts with naturally long translations, so treat issues as review prompts rather than proof of an error.

## Strategy Hooks

Use `scripts/hooks_tool.py` for pre-final, non-network checks:

```bash
python scripts/hooks_tool.py final-qa --strategy-file final_strategy.txt
python scripts/hooks_tool.py filter-check --text-file protocol_or_strategy.txt
python scripts/hooks_tool.py low-count-review --strategy-file final_strategy.txt --final-count 142 --decision low-count-plausible --rationale "rare/new topic; relaxed variant mostly off-scope" --relaxed-variant-tested --relaxed-variant-count 983 --output low_count_review.json
```

Run `final-qa` before presenting a draft strategy. It flags recall risks such as `[Majr]`, `NOT`, language/date/species/age/publication-type/full-text limits, short wildcards, proximity with truncation, missing MeSH or `[tiab]` layers, unreviewed phrase-like concepts as `proximity_review_needed`, and unreviewed quoted `[tiab]` singular/plural phrase pairs as `singular_plural_wildcard_review`. Resolve `proximity_review_needed` by comparing exact phrases, Boolean `AND`, and PubMed proximity widths or documenting rejected/not-applicable rationale; resolve `singular_plural_wildcard_review` by testing the phrase-final, phrase-anchored/concept-specific wildcard candidate or documenting explicit-form retention. It reports exact duplicate terms as `duplicate_term` (recall-neutral cleanup; it detects an atom repeated across the flat `OR` list and nested `MeSH AND (...)` sub-clauses, which is the usual source of duplicated zero-hit terms). For multi-block strategies, it checks top-level concept blocks separately so one block's MeSH does not hide another block's missing controlled-vocabulary layer.

Every warning remains unresolved unless `--warning-dispositions-file` supplies a JSON object mapping its warning code to a non-empty authored rationale. The final-QA artifact records the exact strategy hash, and the completion gate requires that hash to match the final strategy evidence.

Run `filter-check` whenever the protocol, request, or strategy mentions a study-design/evidence-type intent such as RCTs, systematic reviews, qualitative studies, diagnostic accuracy, prognosis, observational studies, or economic evaluations. If it reports that validated filter review is needed, read `validated-methodological-filters-and-hedges.md`, use `pubmed_tool.py batch` for topic-only versus topic-plus-filter counts, and validate seed PMID impact when seeds exist.

Run `low-count-review` when the final topic-only PubMed count is below 500. Read `references/low-count-plausibility.md` first. The hook does not run PubMed or rewrite the query; it checks that the low-count decision, rationale, and relaxed-variant evidence (or reason not applicable) are documented, and it flags generic search-logic risks for audit follow-up.

## Audit Scaffold

Use `scripts/pubmed_tool.py audit-scaffold` to assemble most of the audit JSON from files the build already wrote - the per-command `--output` JSONs and `run_manifest.json` - instead of re-transcribing counts and lists by hand. It makes no network calls and prints a receipt listing the source files used.

```bash
python scripts/pubmed_tool.py audit-scaffold --manifest run_manifest.json --final-search-json final_search.json --strategy-file full_strategy.txt --validate-json seed_validation.json --seed-fetch-json seed_fetch.json --seed-mine-json seed_mine.json --related-json related.json --recall-json recall.json --date-searched 2026-05-31 --output audit_pressure-ulcer_2026-05-31.json
```

It fills mechanical fields from saved outputs and manifest state: final counts/strategy, scope versions, candidate-screening summary, critic rounds, revision cycles, seed validation, related-set counts, relative-recall diagnostics, ATM translation, block line set, and provenance paths. Judgment fields remain placeholders until authored. Counts come from saved output files rather than hand-typed manifest values.

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

Start the build in its own run workspace. Because every tool writes its `--output`
artifacts relative to the working directory, a build run from the skill directory leaves
run state in the installation where a later build can resolve it as evidence. `init`
refuses that location; `--workspace` creates the run directory and places the manifest in
it. Run the remaining commands from inside that directory (`--allow-skill-root` or
`PUBMED_SEARCH_BUILDER_ALLOW_SKILL_ROOT=1` overrides the guard).

```bash
python scripts/manifest_tool.py init --workspace runs/pressure-ulcer --topic-slug pressure-ulcer
python scripts/workflow_tool.py --manifest run_manifest.json --kind search --label "main strategy" --output final_search.json --input full_strategy.txt --scope-version 1 -- python scripts/pubmed_tool.py search --query-file full_strategy.txt --retmax 0 --output final_search.json
python scripts/manifest_tool.py add --manifest run_manifest.json --kind search --command "python scripts/pubmed_tool.py search --query-file full_strategy.txt --retmax 0" --count 192246 --label "main strategy" --note "final topic-only count"
python scripts/manifest_tool.py add --manifest run_manifest.json --kind sample --command "python scripts/pubmed_tool.py sample --query-file draft_strategy.txt --retmax 5 --output sample.json" --output sample.json --label "draft sample"
python scripts/manifest_tool.py add --manifest run_manifest.json --kind artifact --command "python scripts/audit_markdown.py audit_pressure-ulcer_2026-05-31.json --output audit_pressure-ulcer_2026-05-31.md" --output audit_pressure-ulcer_2026-05-31.md --note "audit markdown"
python scripts/manifest_tool.py add --manifest run_manifest.json --kind artifact --command "python scripts/audit_markdown.py audit_pressure-ulcer_2026-05-31.json --output audit_pressure-ulcer_2026-05-31.md --if-exists suffix" --output audit_pressure-ulcer_2026-05-31_2.md --supersedes audit_pressure-ulcer_2026-05-31.md --note "re-rendered after cleanup"
python scripts/manifest_tool.py show --manifest run_manifest.json --validate --check-files --require-complete-loop
python scripts/manifest_tool.py report --manifest run_manifest.json
```

Use `workflow_tool.py` for executable stages. It resolves and hashes every declared input before launch, runs the command without a shell, rejects input mutation, failed commands, payloads with `ok: false`, and unchanged pre-existing outputs, then records return code, scope version, and input/output SHA-256 hashes. Use `--allow-unchanged-output` only for an intentionally idempotent stage. Direct `manifest_tool.py add` remains for already-created/manual artifacts. `show --validate --check-files` detects later file mutation; `--require-complete-loop` also parses validation and final-QA contents rather than accepting file existence alone.

### Build-state tracking

`manifest_tool.py state` keeps a live `build_state` block inside `run_manifest.json` so the current stage, gate decisions, and the one open user question are read from a file instead of reconstructed from the conversation each turn. It is lazily created on first use, so manifests written only with `init`/`add` are unchanged.

```bash
python scripts/manifest_tool.py state set-stage scope-lock
python scripts/manifest_tool.py state resolve-gate framework PECO
python scripts/manifest_tool.py state resolve-gate seed provided
python scripts/manifest_tool.py state resolve-gate filter none
python scripts/manifest_tool.py state lock-protocol --protocol-file review_protocol_v1.json --compile-receipt protocol_compile_v1.json
python scripts/candidate_ledger.py candidate_ledger.json --output candidate_ledger_validation.json
python scripts/manifest_tool.py state record-candidate-screen --ledger-file candidate_ledger.json --validation-file candidate_ledger_validation.json
python scripts/critic_tool.py --build-bundle --evidence strategy=strategy_v1.txt --evidence critic_packet=critic_packet_v1.json --output critic_evidence_1.json
python scripts/critic_tool.py --run-independent --bundle critic_evidence_1.json --round 1 --output critic_round_1.json
python scripts/critic_tool.py critic_round_1.json --output critic_round_1_validation.json
python scripts/manifest_tool.py state record-critic --critic-file critic_round_1.json --validation-file critic_round_1_validation.json
python scripts/manifest_tool.py state check-complete
```

The candidate-ledger validation receipt is bound to the exact ledger path and SHA-256. `record-candidate-screen` rejects a receipt for another or subsequently edited ledger, and the completion gate rechecks that binding. Resolve manifest decision entries explicitly (use `add --resolves-decision-seq <SEQ>` on the evidence that closes them); an open decision blocks completion.

Canonical stages are `intake`, `scope-lock`, `candidate-discovery`, `candidate-screening`, `objective-evidence`, `block-testing`, `validation`, `critic-review`, `revision`, `final-qa`, `audit-output`, and `peer-review-handoff`. Gates are `framework`, `seed`, `concept`, and `filter`. `--require-ready` remains a lightweight compatibility check; completed builds must use `--require-complete-loop` or `state check-complete`.

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

Each registered block needs two requirements satisfied: `mesh_sweep` (a successful `--kind mesh` entry, or successful command containing `mesh_tool.py sweep`, tagged to the block, with a non-empty hashed output) and `block_count` (a successful `--kind search` or `--kind batch` entry tagged to the block, with a non-negative count and non-empty hashed output). Entry-to-block matching prefers the explicit `--block` tag and falls back to the free-text `--label` (so a label like `malaria block` still counts for block `malaria`). Failed commands, missing outputs, and unhashed outputs are not evidence. When a requirement genuinely does not apply — a concept with no MeSH descriptor, or one deliberately kept text-word-only — record a **reasoned waiver** instead of leaving it pending; the reason is mandatory and is surfaced in `state coverage`, `report`, and the audit:

```bash
python scripts/manifest_tool.py state waive-requirement "rapid diagnostic test" mesh_sweep "no MeSH descriptor exists; SCR/text-word coverage only"
```

`show --require-coverage` remains available as a targeted diagnostic. The combined `--require-complete-loop` handoff gate includes the same coverage requirements automatically.

#### Conditional Bramer gap-analysis gate

The **Bramer reciprocal gap analysis** is tracked per block too, but because it is *conditional* (run it where it aids term discovery; waive it for simple, stable-MeSH concepts) it is **separate from `--require-coverage`** and has its own opt-in gate. The `bramer_gap` requirement is satisfied by a `term-diff` run (or a manual reciprocal gap query) tagged to the block, or by a reasoned waiver:

```bash
python scripts/manifest_tool.py add --kind sample --block "malaria" --command "python scripts/pubmed_tool.py term-diff --mesh-query-file malaria_mesh.txt --tiab-query-file malaria_text.txt --output diff_malaria.json" --output diff_malaria.json
python scripts/manifest_tool.py state waive-requirement "rapid diagnostic test" bramer_gap "simple concept, well covered by MeSH and text words"
python scripts/manifest_tool.py show --require-gap-analysis   # opt-in; exit 1 while any block lacks a recorded gap analysis or waiver
```

`state coverage` and `report` show `gap_coverage`; `show --require-gap-analysis` remains a targeted gate. The combined completion gate requires every registered block to have a gap analysis or a reasoned waiver.

### No-seed recall offer

On a **no-seed build**, `build_state` also tracks whether the optional heuristic recall check was offered. The Validation stage must offer it once (see `references/no-seed-recall-estimation.md`); record the user's choice so handoff can confirm the offer was actually made:

```bash
python scripts/manifest_tool.py state resolve-recall-offer done            # accepted and run
python scripts/manifest_tool.py state resolve-recall-offer declined        # user declined
python scripts/manifest_tool.py state resolve-recall-offer not-applicable  # too few anchors/candidates to be meaningful
python scripts/manifest_tool.py show --require-recall-offer                 # opt-in no-seed gate; exit 1 while recall_offer is pending
```

`recall_offer` defaults to `pending` and is only meaningful on no-seed builds. The targeted `--require-recall-offer` flag remains available; `--require-complete-loop` applies it automatically only when the seed gate is `none`.

If the no-seed saturation gate offers an empirically-unvalidated route, record the user decision with `state resolve-unvalidated-handoff <accepted|declined> --reason "..."`. Acceptance does not erase the evidence gap: the decision artifact must be recorded and the final audit must state the limitation explicitly.

If the user accepts, `pubmed_tool.py recall --pilot-query-file pilot.txt --auto-expand --blocks-file blocks.json` runs the pilot → `related` → recall pipeline in one call (add `--anchor-sample-output` to save anchors for inspection); without `--auto-expand` the pilot's own hits are the benchmark (weaker/circular). See `references/no-seed-recall-estimation.md` for the full pipeline, guardrails, and the manual three-step form.

## Tool-to-stage quick map

`references/workflow.md` owns the canonical loop. Maintain the manifest from intake through `show --validate --check-files --require-complete-loop` at handoff.

| Workflow stage | Bundled command(s) | Tool note |
|---|---|---|
| Scope lock | `manifest_tool.py state lock-scope` | Validate and save protocol-only retrieval scope before record evidence. |
| Candidate discovery/screening | `fetch`, `sample`, `related`; `candidate_ledger.py`; `state record-candidate-screen` | Screen before mining; freeze discovery and holdout roles. |
| Objective evidence | `term-rank --pmids`; `mesh_tool.py sweep --details`, `tree`; PubMed ATM checks | Use screened discovery records and complete the MeSH candidate ledger. |
| Empirical fragility | `strategy_analysis.py fragility-score` | Measure naming, MeSH, safety-layer, validation, noise, and era variation; reason every override. |
| No-seed discovery | `no_seed_discovery.py discover`, `adjudicate` | Merge six orthogonal pilots, blind provenance, stop on study/vocabulary saturation, then freeze holdout. |
| Active vocabulary learning | `vocabulary_learning.py extract`, `retest` | Learn only inside locked concepts; quarantine scope challenges and run the seven no-harm checks for every accepted term. |
| Screening burden | `screening_burden.py sample`, `estimate` | Use complete-frame stratified labels and precision intervals; compare only recall-qualified variants. |
| Block testing/validation | `search`, `batch`, `variants`, `term-diff`, `validate`, `recall` | Run reversible comparisons, diagnose bottlenecks, and label validation independence. |
| AND-block admission | `strategy_analysis.py concept-ablation` | Test every proposed required block against workload, differential samples, and development/holdout retrieval. |
| Fragile-topic strands | `strategy_analysis.py two-strand` | Preserve the recall-first main strategy and add a reasoned focused prioritization strand. |
| Critic/revision | `critic_tool.py`; `revision_guard.py`; `state record-critic`, `record-revision`, `reopen-scope` | Route findings, run the seven no-harm checks, restore the baseline on failure, and rerun affected probes. |
| Final QA | `search --retmax 0`; `hooks_tool.py final-qa`, `filter-check`, `low-count-review` | Run after the passing critic round and save QA output. |
| Audit output | `audit-scaffold` → `audit_markdown.py`; `show --require-complete-loop` | Author judgment placeholders, render the audit, and pass the combined gate. |

## Do Not Fabricate

Never invent:

- MeSH descriptors
- entry terms
- PubMed counts
- PMIDs
- validation results
- whether a PMID was retrieved
- run-manifest entries for commands that were not run or files that were not written
