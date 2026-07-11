# No-Seed Heuristic Recall Estimation

Use this reference only after retrieval scope is locked, candidate anchors are screened, and a draft strategy exists. It estimates recall relative to a proxy set; it is not validated sensitivity or known-item recall.

## Why it is heuristic

With no supplied seeds there is no ground truth. One high-precision pilot can trap discovery inside one vocabulary cluster. Use orthogonal pilots to find plausible anchors through different representations, then expand them through mechanisms that do not depend on the final Boolean terms. The benchmark is still strategy-adjacent and may be noisy.

Interpret asymmetrically:

- high relative recall is weak positive evidence and does not prove completeness;
- low relative recall is a useful leak signal when missed candidate records appear in scope.

## Preconditions

- Seed gate resolved to no seeds.
- Retrieval scope version 1 or later is locked.
- Orthogonal pilot specifications are saved; their merged candidates will be screened before vocabulary mining or benchmark use.
- A draft strategy and blocks file exist.
- The recall check is accepted by the user/protocol, or the protocol authorizes it by default.

Record the outcome with `manifest_tool.py state resolve-recall-offer <done|declined|not-applicable>`.

## Required orthogonal discovery pipeline

Create `orthogonal_pilots.json` with exactly one deliberately different pilot from each family:

- `mesh-led`
- `exact-phrase-led`
- `operational-description-led`
- `prior-review-led`
- `citation-registry-led`
- `historical-terminology-led`

Each object supplies `type` and either `query` or `anchor_pmids`. Citation/registry pilots may also set `expand_links`, `links`, and `max_per_seed`.

```bash
# Discover and merge candidates; provenance is written separately.
python scripts/no_seed_discovery.py discover \
  --pilots-file orthogonal_pilots.json --scope-version 1 --round 1 \
  --screening-output screening_round_1.json \
  --provenance-output provenance_round_1.json

# Screen screening_round_1.json without opening provenance_round_1.json, then adjudicate.
python scripts/no_seed_discovery.py adjudicate \
  --screening-file screening_round_1.json \
  --provenance-file provenance_round_1.json \
  --scope-version 1 --state-output saturation_state_1.json \
  --ledger-output candidate_ledger.json

# Once saturation writes the frozen ledger, validate and record it normally.
python scripts/candidate_ledger.py candidate_ledger.json --output candidate_ledger_validation.json
```

For later rounds, pass `--previous-state saturation_state_<N>.json` to both commands. The screening file contains records and blinded candidate IDs but no per-record pilot provenance. The provenance map is opened only after screening decisions are saved.

Discovery stops only after the required consecutive rounds add neither a screened-in relevant study nor new vocabulary from screened-in records. A pilot retrieval safety cap is an operational ceiling, not a stopping rule; if reached, saturation is blocked until the pilot is narrowed or retrieval is completed. On saturation, the adjudicator deterministically freezes discovery and holdout roles and writes the candidate ledger before term mining.

Related neighbors used only for the benchmark may remain unscreened but must be called heuristic candidates, never relevant studies. Screen any neighbor before harvesting its vocabulary.

Record candidate, related, and recall artifacts in the manifest.

## Convenience one-liner

`recall --pilot-query-file --auto-expand` can chain pilot retrieval and related expansion, but it cannot insert candidate screening between them. Use it only as a heuristic smoke test. It does not satisfy candidate-screening integrity, and its raw anchors or neighbors must not feed term mining.

## Orthogonal pilot construction

Favor precision within each strand, but maximize representational difference across strands.

- MeSH-led: established descriptors/SCRs and, if justified, pilot-only major-topic focus.
- Exact-phrase-led: canonical named phrases and distinctive labels.
- Operational-description-led: actions, workflows, or procedures without requiring the preferred construct label.
- Prior-review-led: independently identified review titles, included-study identifiers, or review-specific anchors.
- Citation/registry-led: citation links, trial registrations, registry identifiers, or study-family anchors.
- Historical-terminology-led: obsolete, regional, disciplinary, or era-specific wording.

Pilots are discovery devices, not smaller versions of the final strategy. Do not let one pilot's vocabulary define screening scope.

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

Record every pilot query/anchor set, per-pilot counts and safety caps, the blinded screening artifact, separate provenance map, study/vocabulary novelty by round, saturation decision, frozen holdout allocation, benchmark size and screening status, reachable denominator, relative and per-block recall, missed-record screening, revisions, retest result, and whether the user/protocol accepted or declined the check.
