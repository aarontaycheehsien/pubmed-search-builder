# No-Seed Heuristic Recall Estimation (Optional)

Load this reference only when building a **no-seed** strategy and the user has accepted
the optional recall check offered at the Validation stage. It is not needed on seeded
builds (use `seed-pmid-validation.md`) or when the user declines.

## When this applies

- The seed gate resolved to **no seeds** (the user has none or asked to proceed without them).
- A **draft strategy and concept blocks already exist** (this is a Validation-stage step, never pre-gate exploration).
- The user has **explicitly accepted** the offer (see *Offer protocol* below). It is optional and off by default.

It produces a **heuristic relative-recall percentage** plus a **bottleneck-block diagnosis**.
It is *not* validated sensitivity and *not* known-item recall. Report it as a heuristic, always.

## The idea, and the circularity warning

With no seeds there is no ground truth, so we manufacture a **proxy relevant set** and measure
how much of it the draft strategy retrieves. The danger is circularity: if the benchmark is built
from the same terms as the strategy, the strategy retrieves it by construction and the number is
meaningless (~100%).

The circularity-breaker is `related`: PubMed similar-articles and the citation graph (`citedin`,
`refs`) are computed by NCBI and the literature itself, **independent of your Boolean term choices**.
Expanding a few high-precision anchors that way yields a benchmark the strategy did not define.

Read the result asymmetrically:

- **High recall = weak positive evidence.** The benchmark is strategy-adjacent and *flatters* recall; it does not prove completeness.
- **Low recall = strong, actionable evidence.** Records the strategy misses but that are citation-neighbours of obviously relevant papers are real candidate misses, and `--blocks-file` localises which block leaked.

## Offer protocol

1. On a no-seed build, at the **Validation stage**, emit a **full stage banner** with `User decision needed`:
   > Run the optional heuristic no-seed recall check? It builds a high-precision pilot query,
   > expands it via PubMed similar-articles/citations, and measures how much of that set the
   > draft retrieves — giving a relative-recall % and the bottleneck block. It is a heuristic,
   > not validated sensitivity. Yes / No.
   Ask only this, and stop.
   If the draft or final topic-only strategy has a low-count plausibility warning (`<500` records), cite that as one reason the heuristic check is useful. Do not present `<500` as proof of low recall, and do not re-ask if the user already declined the optional check.
2. Record the outcome in the manifest build-state so handoff can confirm the user was offered the choice:
   - accepted and run: `manifest_tool.py state resolve-recall-offer done`
   - user declined: `manifest_tool.py state resolve-recall-offer declined`
   - not feasible (e.g. too few anchors/candidates): `manifest_tool.py state resolve-recall-offer not-applicable`
3. `manifest_tool.py show --require-recall-offer` is the opt-in handoff check for no-seed builds: it fails while `recall_offer` is still `pending`. It is **not** part of `--require-ready`.

## Pipeline

```bash
# 1. High-precision pilot query (favor precision; see "Pilot query construction" below). Save to pilot.txt.
python scripts/pubmed_tool.py search --query-file pilot.txt --retmax 30 --output pilot_search.json

# 2. Inspect the anchors. They are "probably relevant", not validated — eyeball them before trusting.
python scripts/pubmed_tool.py sample --query-file pilot.txt --retmax 10 --output pilot_sample.json

# 3. Expand the anchors into a strategy-independent candidate relevant set.
python scripts/pubmed_tool.py related --pmids <anchor PMIDs> --links similar,citedin,refs --output related.json

# 4. Measure how much of that set the DRAFT strategy retrieves, with per-block bottleneck diagnosis.
python scripts/pubmed_tool.py recall --query-file draft_strategy.txt \
  --benchmark-json related.json --min-seed-overlap 2 \
  --blocks-file blocks.json --output recall.json
```

`recall` reports `relative_recall_percent`, `retrieved_pmids`/`missed_pmids`, per-block `block_recall`
with a `bottleneck` flag, and `miss_diagnosis` (an `and_interaction` flag points to a `NOT`, filter,
or proximity problem rather than a weak block).

Record `related` and `recall` in the manifest with `manifest_tool.py add --kind related ...` and
`--kind recall ...` so the audit can cite them.

**Simpler fallback:** the pilot query *itself* as the benchmark via `recall --benchmark-query-file pilot.txt`.
This is weaker — if the pilot's terms are a subset of the strategy's `OR` blocks it is circular — so prefer
the `related`-expansion route and label this fallback explicitly when used.

### Convenience one-liner

`recall --pilot-query-file` chains the pipeline above in a single call so you do not orchestrate three commands:

```bash
# Recommended: expand the pilot anchors via related (the less-circular benchmark).
python scripts/pubmed_tool.py recall --query-file draft_strategy.txt \
  --pilot-query-file pilot.txt --auto-expand --min-seed-overlap 2 \
  --blocks-file blocks.json --anchor-sample-output pilot_anchors.json --output recall.json

# Weaker fallback: the pilot's own hits as the benchmark (omit --auto-expand). Circular if pilot ⊂ strategy.
python scripts/pubmed_tool.py recall --query-file draft_strategy.txt \
  --pilot-query-file pilot.txt --blocks-file blocks.json --output recall.json
```

`--auto-expand` runs the `related` expansion (tune with `--links`, `--max-per-seed`, `--max-total`, `--pilot-retmax`); without it the pilot hits are the benchmark directly. `--anchor-sample-output <path>` saves a small fetched sample of the anchors. The result carries a `pilot_expansion` block (anchors, link types, candidate count) and a `note`: **the anchors are probably-relevant, not validated — inspect the saved sample before trusting the number.** Inspecting the anchor sample is still required (No reviewed JSON, no decision); the one-liner does not remove that step.

## Pilot query construction

Favor precision over recall; you want a clean anchor set, not coverage. Even 5–20 solid anchors are enough
to seed `related`.

- Use the most specific MeSH (a `[Majr]` major-topic restriction is acceptable **for the pilot only**).
- Tight exact phrases; the 1–2 most essential concepts only; no broad wildcards.
- Where possible, reach for vocabulary the main strategy may *under*-cover, so the expansion can surface gaps.

See `tiab-expansion.md` for the same pilot-construction guidance used by `term-rank --relevant-query-file`.

## Act on the result

Low heuristic recall is an action gate, not just a caveat. If overall heuristic recall is below `70%`, or any essential block is below `60%`, do not proceed to final handoff until missed records have been inspected and a revised draft has been retested, or every miss has been documented as out of scope.

1. Inspect `missed_pmids` — are they truly relevant? (No reviewed JSON, no decision: inspect the saved records.)
2. For genuine misses, the `bottleneck` block is usually where MeSH or text-word coverage is too narrow — widen that block, then re-run.
3. Classify any term harvested from missed records by concept role like any other candidate; **never auto-add**, and respect the overfitting rules in `seed-pmid-validation.md`.
4. If missed records are broader than the current draft but plausibly in scope, widen the bottleneck block before handoff. For methodological or automation topics, this may mean replacing a narrow action block with a broader workflow block.
5. If missed records are out of scope, document each out-of-scope PMID explicitly and keep it out of the strategy rather than distorting the query.
6. Do not proceed to audit output until the revised query has been retested and the audit can report the bottleneck-block diagnosis, revision decision, out-of-scope PMID table if applicable, and final heuristic retrieval result.

## Guardrails

- **Heuristic, never absolute.** Report it as relative to a no-seed pilot-expansion benchmark, never as search sensitivity. `recall` carries this caveat in its `note`.
- **Minimum benchmark size.** Below ~15–20 reachable candidates the percentage is too noisy — report "indicative only" or set `recall_offer = not-applicable` with a documented reason rather than printing a confident number.
- **Reachability.** A benchmark PMID not in PubMed is indistinguishable from a genuine miss. Report recall against the reachable benchmark and note the unreachable count.
- **Never narrow on the number.** A recall figure can drive *adding* coverage to a bottleneck block; it never justifies *removing* terms from a recall-first strategy.
- **Low-recall handoff gate.** The `70%` overall and `60%` per-essential-block thresholds are not validated sensitivity targets, but they are strong enough to block handoff until missed-record inspection, revision, and retesting are complete or the misses are documented as out of scope.
- **Low final count is a trigger, not evidence.** A final topic-only count below `<500` should strengthen the case for running the optional no-seed heuristic recall check when it has not yet been accepted or declined, but it is not itself a sensitivity estimate and never requires automatic expansion.

## Audit

Record in the relative-recall section of the audit (see `audit-template.md`), labelled **separately from
known-item seed validation**:

- benchmark source = **no-seed pilot-expansion heuristic**, the pilot query, link types, caps, and benchmark size;
- `relative_recall_percent`, per-block recall, and the bottleneck block;
- missed-record inspection outcome, revision decision, out-of-scope PMID table if applicable, and final retest result after any revision;
- the offer outcome: run / `offered; declined by user` / `not-applicable (reason)`.

`pubmed_tool.py audit-scaffold --recall-json recall.json --seed-status no --manifest run_manifest.json`
fills these mechanically and labels the benchmark source from the recorded `recall_offer`.

## Advanced (future)

For a statistically grounded no-seed estimate rather than a heuristic, **capture–recapture** — build two
deliberately independent strategies and estimate the unseen relevant pool from their disagreement — reuses
`recall`/`variants` for the overlap math. Higher rigour, stronger independence assumptions; treat the
pilot-expansion leak-detector above as the default.
