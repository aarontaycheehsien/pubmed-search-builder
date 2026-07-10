# No-Seed Heuristic Recall Estimation

Use this reference only after retrieval scope is locked, candidate anchors are screened, and a draft strategy exists. It estimates recall relative to a proxy set; it is not validated sensitivity or known-item recall.

## Why it is heuristic

With no supplied seeds there is no ground truth. A high-precision pilot can find plausible anchors, and PubMed similar-article/citation links can expand them through mechanisms that do not depend on the final Boolean terms. The benchmark is still strategy-adjacent and may be noisy.

Interpret asymmetrically:

- high relative recall is weak positive evidence and does not prove completeness;
- low relative recall is a useful leak signal when missed candidate records appear in scope.

## Preconditions

- Seed gate resolved to no seeds.
- Retrieval scope version 1 or later is locked.
- Pilot anchors that will seed expansion are screened in `candidate_ledger.json`.
- A draft strategy and blocks file exist.
- The recall check is accepted by the user/protocol, or the protocol authorizes it by default.

Record the outcome with `manifest_tool.py state resolve-recall-offer <done|declined|not-applicable>`.

## Recommended manual pipeline

```text
# 1. Save a high-precision pilot query and retrieve bounded candidate anchors.
python scripts/pubmed_tool.py search --query-file pilot.txt --retmax 30 --output pilot_search.json

# 2. Fetch/sample and screen the anchors against the locked scope.
python scripts/pubmed_tool.py sample --query-file pilot.txt --retmax 30 --output pilot_sample.json

# 3. Save discovery/holdout/heuristic roles, then validate the ledger.
python scripts/candidate_ledger.py candidate_ledger.json --output candidate_ledger_validation.json

# 4. Expand only screened-in anchor PMIDs.
python scripts/pubmed_tool.py related --pmids <screened-in anchors> --links similar,citedin,refs --output related.json

# 5. Measure draft retrieval against the related candidate set.
python scripts/pubmed_tool.py recall --query-file draft_strategy.txt --benchmark-json related.json --min-seed-overlap 2 --blocks-file blocks.json --output recall.json
```

Inspect the saved anchor sample before expansion. Related neighbors used only for the benchmark may remain unscreened but must be called heuristic candidates, never relevant studies. Screen any neighbor before harvesting its vocabulary.

Record candidate, related, and recall artifacts in the manifest.

## Convenience one-liner

`recall --pilot-query-file --auto-expand` can chain pilot retrieval and related expansion, but it cannot insert candidate screening between them. Use it only as a heuristic smoke test. It does not satisfy candidate-screening integrity, and its raw anchors or neighbors must not feed term mining.

## Pilot construction

Favor precision rather than coverage. Even a small clean anchor set can seed related-record discovery.

- Use the most distinctive one or two locked concepts.
- Tight phrases and specific MeSH are acceptable for the pilot.
- A pilot-only `[Majr]` restriction may be used with explicit labelling.
- Avoid broad wildcards and optional eligibility concepts.
- Where possible, include vocabulary the main draft might under-cover.

The pilot query is a discovery device, not a smaller version of the final strategy.

## Act on results

The tool reports overall relative recall, per-block recall, bottleneck blocks, missed PMIDs, and `AND`-interaction problems.

1. Fetch and screen missed candidates against the locked scope.
2. For screened-in misses, identify the failing block or interaction.
3. Route lexical gaps to block revision and structural gaps through scope re-entry.
4. Do not harvest terms from unscreened or uncertain misses.
5. Document out-of-scope candidates rather than distorting the query.
6. Retest the revised strategy and run another critic round.

As a development heuristic, overall recall below 70% or any essential block below 60% should trigger missed-record inspection. These are not validated sensitivity targets and cannot widen eligibility automatically.

## Guardrails

- Report recall only relative to the named proxy benchmark.
- Below roughly 15-20 reachable candidates, describe the percentage as indicative only.
- Report PubMed-unreachable PMIDs separately.
- Never use a high number to justify removing terms.
- Never use a low number to change scope without conceptual re-entry.
- A final topic-only count below 500 strengthens the case for the check but is not evidence of low recall.

## Audit

Record the pilot query, screened anchor ledger, link types and caps, benchmark size and screening status, reachable denominator, relative and per-block recall, missed-record screening, revisions, retest result, and whether the user/protocol accepted or declined the check.
