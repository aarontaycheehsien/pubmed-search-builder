# Seed PMID Discovery and Validation

Seed PMIDs are optional. Use them only after retrieval scope version 1 is locked.

Seeds may support candidate discovery, objective vocabulary, and validation, but those roles must be assigned explicitly. A user-supplied PMID is likely relevant, not automatically eligible under the final locked scope.

## Intake before scope lock

After the plain-language question is confirmed, ask once whether the user has known-relevant seed PMIDs and stop for the answer. Do not treat silence, or your own inference that none exist, as a "no seeds" decision; seed status is resolved only by the user supplying PMIDs, stating there are none, asking to proceed without them, or by a valid locked protocol that encodes `seeds.records`. Before scope lock:

1. Normalize and deduplicate numeric PMIDs while preserving order.
2. Record malformed entries and do not pass them to PubMed.
3. Do not fetch, mine, inspect, expand, or use the PMIDs as concept evidence.
4. Validate, compile, and lock `review_protocol_v1.json` from question/protocol evidence.

This separation prevents the seed set from anchoring which eligibility elements become required search blocks.

## Fetch and screen after scope lock

Read `references/candidate-screening.md`.

1. Fetch normalized PMIDs to `seed_fetch.json` or mine them to `seed_mine.json` only after scope lock. `fetch` and `mine` require `--output`; stdout is a receipt, not record evidence.
2. Inspect titles, abstracts where available, publication types, retraction status, MeSH headings, keywords, and other returned metadata.
3. Record not-found PMIDs and exclude them unless corrected.
4. Screen each found record against the locked scope as `include`, `exclude`, or `uncertain`, with a reason.
5. Assign `discovery`, `holdout`, `both`, `heuristic`, or `neither` use in `candidate_ledger.json`.
6. Validate the ledger with `scripts/candidate_ledger.py` before mining terms.

Treat a record as retracted when PubMed metadata or publication types indicate retraction. A retracted record may remain in the audit but normally uses `neither`. Do not pause for ordinary uncertainty; mark it `uncertain` and keep it out of discovery/holdout use. Ask the user only when the PMID exposes a genuine eligibility ambiguity or they explicitly want an out-of-scope record retained as a special diagnostic.

## Expand the screened set

After at least one screened-in record exists, use PubMed similar articles and citation links to discover more candidates:

```text
python scripts/pubmed_tool.py related --pmids <screened-in PMIDs> --links similar,citedin,refs --output related.json
```

Similarity score and seed-overlap count prioritize screening; they do not establish relevance.

1. Fetch candidates that may contribute vocabulary.
2. Screen them against the same scope version.
3. Add them to a new candidate-ledger version with provenance.
4. Use only `include` records assigned `discovery` or `both` for `term-rank`.
5. Preserve unscreened or uncertain neighbors as `heuristic` or `neither` only.

Record link types, caps, candidate counts, screened decisions, and which ledger version supersedes the prior one.

## Objective term discovery

For screened-in discovery records, extract candidate evidence from:

- titles and abstracts;
- assigned MeSH and supplementary concepts;
- author keywords;
- publication types where relevant;
- acronyms, phrase variants, spelling/morphology variants, and historical terminology.

Run `pubmed_tool.py term-rank --pmids <eligible discovery PMIDs>` or pass an accepted whitelist. Do not feed the raw `related.json` candidate array or a mixed `mine` artifact to term ranking without restricting it to screened-in discovery PMIDs.

Rank by coverage and lift rather than raw frequency. Treat output as candidate terms; classify each by the locked concept roles, check PubMed behavior, and reject noise. Seed-derived language may expand an existing `OR` layer but cannot create a new essential block without structural re-entry.

## Development and validation separation

Freeze held-out records before term mining. Prefer a representative holdout across eras, terminology, indexing status, and study types when the set is large enough.

Report validation type explicitly:

- **Independent holdout:** the PMID did not contribute vocabulary or scope decisions.
- **Non-independent reused seed:** the PMID contributed terms and was later re-found.
- **Heuristic benchmark:** the PMID is an unscreened/uncertain related neighbor.

Known-item retrieval against reused seeds is a smoke test, not independent evidence of sensitivity.

## Validate retrieval

Test the topic-only strategy against all screened-in validation records. Use `pubmed_tool.py validate` or equivalent UID intersections. Pass concept blocks to `pubmed_tool.py recall` when a larger independently defined benchmark exists, so bottleneck-block diagnosis is available.

For each missed in-scope record:

1. Identify the failing block or `AND` interaction.
2. Inspect title, abstract, MeSH, publication type, and indexing recency.
3. Classify the problem as lexical, structural, filter, syntax, or out of scope.
4. Route it through the current critic round and required re-probes.

Do not hand off a final strategy with an unexplained missed in-scope holdout, seed, or gold-standard PMID.

## Validate filters separately

When a filter or hedge is used, validate in two stages:

1. topic-only strategy;
2. topic-plus-filter strategy.

If a record is retrieved topic-only but lost after the filter, diagnose the filter before adding topical terms. Check publication-type/indexing gaps, syntax translation, study-design mismatch, species/age limits, and whether a filter is justified at all.

Do not distort a validated filter to retrieve an out-of-scope record. Reconsider the filter when it loses an in-scope holdout.

## Relative recall

An independent hand-screened relevant set, such as included studies from a prior review, is the strongest available benchmark but still measures recall only relative to that set.

A screened seed-expansion set is weaker. An unscreened related set is a heuristic and can flatter recall. Report benchmark source, screening status, size, reachable denominator, overall and per-block recall, missed-record inspection, and whether validation was independent.

Never use a recall percentage to silently narrow a recall-first strategy.

## Avoid overfitting

- Do not bound vocabulary to a small discovery set.
- Do not exclude conceptual synonyms merely because discovery records did not use them.
- Do not use holdout records for mining after results are seen; if that happens, reclassify them as `both` and disclose non-independence.
- Do not widen scope merely to retrieve a supplied seed.
- Do not call related neighbors relevant until they are screened.

When objective evidence exposes a lexical gap, revise within the current scope. When it exposes a block-role or eligibility problem, reopen the concept gate and issue a new scope version.
