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

## Volume-discrimination gate for an empty screened-in set

Novelty saturation with **zero screened-in records** is ambiguous: it can mean the topic is genuinely sparse, or that the pilots are weak or an essential block is over-narrow and the search is broken. These look identical from the discovery signal alone, and the broken case is self-concealing — a search that misses the literature also finds nothing to screen in, so it cannot detect its own leak.

The adjudicator therefore refuses to accept a zero-screened-in saturation until a broad-concept volume probe shows the topic really is small. Run `discriminate` with a **topic-core** probe (the essential concepts AND-ed together, with fragile/optional blocks stripped) — this is the high-confidence basis. Fall back to one or more **essential-concept** probes (each essential concept alone, no AND) only when a topic-core probe is impractical; a single-concept proxy can rule sparsity out but cannot confirm a bottleneck on its own.

```bash
# Measure broad topic volume (essentials only; no fragile/optional blocks).
python scripts/no_seed_discovery.py discriminate \
  --probes-file volume_probes.json --scope-version 1 \
  --output discrimination_round_N.json

# Feed the verdict into adjudication; required whenever the screened-in set is empty.
python scripts/no_seed_discovery.py adjudicate \
  --screening-file screening_round_N.json --provenance-file provenance_round_N.json \
  --scope-version 1 --discrimination-file discrimination_round_N.json \
  --state-output saturation_state_N.json --ledger-output candidate_ledger.json
```

`volume_probes.json` is a JSON list of `{ "label", "role", "query" }` where `role` is `topic-core` or `essential-concept`. The gate maps the measured volume to a verdict against two heuristic (not validated) triggers, `--sparse-volume-ceiling` (default 500) and `--bottleneck-volume-floor` (default 1000):

- **genuinely-sparse** (volume ≤ ceiling): the empty set is credible; saturation is accepted with no included candidates.
- **discovery-bottleneck** (volume ≥ floor): substantial literature exists but discovery surfaced nothing. Saturation is **blocked**. Repair or broaden the pilots, or reconsider an over-narrow essential block, then run another round. Do not narrow scope — a low screened-in count is never evidence the topic is small.
- **indeterminate** (between the two): add a topic-core probe, widen the pilots, or obtain a human decision before declaring saturation.

Without a discrimination artifact the empty-set verdict is `pending-discrimination` and saturation stays blocked, exactly like an unresolved safety cap. The gate applies only at or below `--min-screened-in-for-saturation` (default 1, i.e. only the empty set), so a single screened-in record still freezes a small non-independent (`both`-role) ledger as before.

## Surface the decision to the user early

Do not silently route an empty screened-in result to the record-free path and leave the confidence gap for the final peer-review label. Whenever the gate fires, `adjudicate` writes a `saturation_gate.user_decision` object and a ready-to-show `saturation_gate.user_decision_text`; the CLI receipt also sets `user_decision_required` and echoes the text. **Stop and present it to the user before continuing.** It states, in plain language:

- **what happened** — how many relevant records screened in and the measured topic volume;
- **why it matters** — whether the empty set is credible (sparse topic) or a red flag (literature exists but discovery missed it);
- **the choices**, each with its consequence: (i) supply known-relevant seed PMIDs, (ii) name adjacent/prior systematic reviews to benchmark against, (iii) repair/broaden the pilots and retry discovery, or (iv) proceed with a protocol-only, empirically-unvalidated search.

The recommended option follows the verdict: `discovery-bottleneck` and `indeterminate` recommend repairing discovery (and flag option (iv) as high-risk); `genuinely-sparse` recommends explicitly accepting the unvalidated search; `pending-discrimination` recommends measuring topic volume first. Accepting an empirically-unvalidated search is an **adoption-confidence decision the user makes up front**, not an automatic fallback the build takes on its own.

Related neighbors used only for the benchmark may remain unscreened but must be called heuristic candidates, never relevant studies. Screen any neighbor before harvesting its vocabulary.

Record candidate, related, and recall artifacts in the manifest.

## Capture-recapture completeness estimate

When discovery *does* screen in a handful of relevant records but you have **no external benchmark**, the volume gate (empty-set only) and benchmark relative-recall (needs a known relevant set) both go quiet — yet the search may still be missing studies. Capture-recapture fills that gap using data discovery already produced: the provenance map records, per candidate, *which pilot families found it*. Treat each of the six orthogonal families as an independent capture occasion over the screened-in relevant set. Records re-found across many families mean the union has converged; a set dominated by singletons means the families retrieve largely **disjoint** relevant records and the union is undersaturated — a recall risk that holds even without a benchmark.

The estimator (Chao1 richness over the pilot-family capture-frequency distribution) reports an estimated total relevant count `N_hat`, an estimated completeness `S_obs / N_hat` with a log-normal 95% CI, per-family capture counts, and pairwise Jaccard overlap.

```bash
# After adjudicating a round that screened in relevant records:
python scripts/no_seed_discovery.py recapture \
  --provenance-file provenance_round_N.json \
  --state-file saturation_state_N.json \
  --scope-version 1 --output completeness_round_N.json
```

`adjudicate` also computes the estimate automatically whenever the screened-in set is non-empty and attaches it as `completeness_estimate`; an `undersaturated` verdict additionally writes a `recall_risk` object with `critic_must_clear: true`.

Interpret it **asymmetrically**, exactly like relative recall — a high estimate is weak positive evidence, a low one is a real leak signal — and note it is a **soft** signal: it never blocks saturation or widens eligibility on its own (the orthogonal families are deliberately precision-focused, so some disjointness is expected). The verdict maps against heuristic (not validated) triggers exposed as CLI flags:

- **converged** (completeness ≥ `--converged-completeness`, default 0.85): the union appears close to complete; weak positive evidence only.
- **undersaturated** (completeness < `--undersaturated-completeness`, default 0.60): largely disjoint pilots, recall risk. Surfaced to the user and flagged for the critic/peer review to clear (add an adjacent-review benchmark, broaden a pilot family, or supply seeds). It does **not** stop the build automatically.
- **indeterminate**: completeness between the thresholds, or the sample is too thin to estimate.

To avoid false precision the estimator stays `indeterminate` below `--min-screened-in-for-estimate` (default 5 records) and reports only an *indicative* verdict below `--min-screened-in-for-firm-verdict` (default 15). With no doubleton (no record found by exactly two families) overlap is undefined: it returns the bias-corrected point estimate with no CI and an `indeterminate` / `no-recaptures` verdict. This is the same "below ~15–20 reachable candidates, indicative only" guardrail applied to the capture-recapture denominator.

## Semi-independent benchmark from adjacent prior reviews

"No seeds" is not the same as "no ground truth." Standard SR practice harvests the **included/cited studies of adjacent systematic reviews** as a weak external recall check. It is imperfect — it imports the prior review's scope bias — but a noisy external check beats MeSH/structural checks alone when discovery comes up empty or thin, and it is the concrete action behind the "name adjacent reviews to benchmark against" option in the empty-set `user_decision` and the capture-recapture `recall_risk`.

It is **semi-independent: non-independent and external**, never an independent gold standard. Two rules keep it honest: the harvested records must be **screened against the locked scope before they count** (unscreened citations would deflate recall spuriously), and benchmark records **must never feed term mining** (only internal screened-in discovery records do).

```bash
# 1. Harvest cited references of named reviews (and/or an included-study PMID list) into a screenable set.
python scripts/no_seed_discovery.py benchmark-harvest \
  --review-pmids 34567890 33112233 --scope-version 1 \
  --screening-output benchmark_screening.json --provenance-output benchmark_provenance.json
#    (or --included-pmids-file review_included.json when you have the review's appendix list)

# 2. Screen benchmark_screening.json against the locked scope (decision/title_abstract_reviewed/eligibility_reason),
#    then freeze the screened-in set as a labelled benchmark.
python scripts/no_seed_discovery.py benchmark-freeze \
  --screening-file benchmark_screening.json --scope-version 1 \
  --output prior_review_benchmark.json

# 3. Run relative recall against it. The source label flows into the audit.
python scripts/pubmed_tool.py recall --query-file strategy.txt \
  --benchmark-json prior_review_benchmark.json --blocks-file blocks.json \
  --output recall_prior_review.json
```

`benchmark-harvest` merges two sources — the cited references of the review PMIDs (via the `refs` elink) and any user-supplied included-study PMID list — excludes the review PMIDs themselves, and writes a provenance-blinded screening artifact on a track separate from discovery. `benchmark-freeze` keeps only screened-in `include` records and labels the artifact `prior-review-semi-independent` with `confidence: semi-independent`. Passing `--unscreened` freezes every harvested candidate as `confidence: indicative` (it then also imports citation noise) — use it only as a quick smoke test.

Interpret the result **asymmetrically**, exactly like every other no-seed recall signal: low recall against the benchmark is a real leak signal (inspect and screen the missed records, then route lexical gaps to block revision and structural gaps to scope re-entry); high recall is weak positive evidence only. A prior-review benchmark is *less* strategy-adjacent than a seed-expansion benchmark, so it flatters recall less, but it still cannot prove absolute sensitivity. Record the outcome with `manifest_tool.py state resolve-recall-offer done`.

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
