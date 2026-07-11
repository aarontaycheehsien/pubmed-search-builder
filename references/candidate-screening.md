# Candidate Evidence Screening

Use this reference after retrieval scope version 1 is locked and before candidate records influence objective term mining or validation.

## Purpose

Build a candidate evidence set without allowing seeds, PubMed neighbors, or a pilot query to redefine the review. Keep four evidence roles distinct:

- **User seed:** supplied as likely relevant, but still checked against the locked scope.
- **Discovery record:** screened in and permitted to contribute title/abstract, keyword, and MeSH candidates.
- **Held-out validation record:** screened in but frozen before term mining; use only to test retrieval.
- **Heuristic neighbor:** unscreened or uncertain related/citation record; may support a clearly labelled heuristic benchmark, never term mining or claims of relevance.

## Required sequence

1. Lock and save `retrieval_scope_v1.json` before fetching or mining candidate records.
2. Collect candidate PMIDs from supplied seeds, PubMed similar articles, citation links, or independently identified prior-review included studies. With no seeds, use the six orthogonal pilots below rather than one defining pilot.
3. Fetch candidate metadata to saved JSON. Inspect titles and abstracts where available; receipt-only stdout is not screening evidence.
4. Classify every candidate as `include`, `exclude`, or `uncertain` against the locked scope. Give a short eligibility reason.
5. Assign one use role: `discovery`, `holdout`, `both`, `heuristic`, or `neither`.
6. Save and validate `candidate_ledger.json` with `scripts/candidate_ledger.py`. When roles have not already been frozen, use `--allocate-holdout --ledger-output <path>` for a deterministic allocation.
7. Mine only records that the validator marks eligible for discovery.

After screening, use `active-vocabulary-learning.md`. Only newly included `discovery`/`both` records may generate proposals. Excluded records receive a separate diagnostic and never supply proposed search terms. Assign every included record to existing locked concepts before extraction; an unknown concept or changed eligibility interpretation requires scope re-entry.

Do not feed a related-record set directly to `term-rank` merely because a PMID has high seed overlap or similarity. Those scores prioritize screening; they do not establish eligibility.

For no-seed discovery, use `no_seed_discovery.py` and screen the generated file without opening its separate provenance map. Merge MeSH-led, exact-phrase-led, operational-description-led, prior-review-led, citation/registry-led, and historical-terminology-led candidates before screening. Reveal provenance only after decisions are saved. Continue rounds until both relevant-study and vocabulary novelty remain zero for the required consecutive rounds; a reached safety cap prevents a saturation claim.

## Ledger schema

```json
{
  "scope_version": 1,
  "records": [
    {
      "pmid": "12345678",
      "provenance": "user-seed",
      "decision": "include",
      "title_abstract_reviewed": true,
      "eligibility_reason": "Matches the locked population and intervention scope.",
      "use": "holdout"
    }
  ]
}
```

Allowed provenance values are `user-seed`, `pilot-anchor`, `similar`, `citedin`, `reference`, `prior-review`, and `other`.

Use roles mean:

- `discovery`: may contribute terms; not an independent validation record.
- `holdout`: may validate retrieval; never contribute terms before the final validation run.
- `both`: may contribute terms and validate, but validation is explicitly non-independent.
- `heuristic`: may appear only in a labelled heuristic benchmark.
- `neither`: retained for the screening audit but excluded from discovery and validation.

An `exclude` record must use `neither`. An `uncertain` record may use only `heuristic` or `neither`. A discovery, holdout, or both record must be screened `include`, have title/abstract review recorded, and carry a non-empty eligibility reason.

## Development and holdout allocation

Freeze the holdout before mining. When the confirmed relevant set is large and diverse enough, reserve a representative subset across eras, terminology, indexing status, and study types. As a practical heuristic, with at least six confirmed records reserve at least two records or about 20%, whichever is larger, unless that would make the discovery set unusably small.

After validation, pass the ledger itself to `pubmed_tool.py related`, `mine`, `term-rank`, `study-family`, `validate`, and `recall` with `--candidate-ledger`. The tool resolves role-safe PMIDs: discovery commands cannot consume holdouts, and validation prefers holdouts. Avoid copying PMID lists by hand.

Use `pubmed_tool.py study-family --candidate-ledger candidate_ledger.json` to discover candidate companion reports through similar/cited/reference links and group records sharing trial registration IDs. Every result remains `screening_status: pending`; family linkage is a discovery signal, not an inclusion decision.

When the set is too small, use `both` and state that known-item validation is non-independent. Never imply that re-finding records used for term discovery demonstrates sensitivity.

## Scope protection and re-entry

Classify a candidate against the current scope; do not widen the scope merely to include it. If several plausible records expose a structural mismatch, record a `scope-challenge` finding and route it through `references/press-critic.md`:

- lexical mismatch: revise vocabulary within the same scope version;
- block-role mismatch: reopen the concept gate and issue a new scope version;
- eligibility ambiguity: ask the user or follow the protocol before proceeding.

After a scope-version change, re-evaluate affected candidate decisions and record which ledger version supersedes the prior one.

## Audit requirements

Record candidate sources, counts by decision and use, evidence files reviewed, excluded/uncertain reasons, holdout allocation, whether validation is independent, and every ledger version. Keep heuristic neighbors separate from screened-in records throughout the audit.
