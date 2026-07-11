# Screening Burden From Labelled Samples

Use when comparing a recall-first strategy with focused, filter, or prioritization variants. Burden may choose between variants only after each variant meets the declared independent held-out recall requirement.

## Build a reproducible sample

Prepare the normal variants file, then run:

```bash
python scripts/screening_burden.py sample \
  --variants-file variants.json \
  --baseline-label main \
  --scope-version 1 \
  --sample-size 60 \
  --rank-bands 3 \
  --seed review-2026-v1 \
  --output burden_sample.json
```

The tool requires a complete ranked PMID frame for every variant. It retrieves frames automatically only up to `--auto-retrieval-limit` (default 10,000). For larger sets, provide `--retrieval-sets-file`; never estimate precision from a capped top-results frame.

```json
{
  "variants": {
    "main": {
      "complete": true,
      "total_count": 12345,
      "ranked_pmids": ["...complete ordered export..."]
    }
  }
}
```

Sampling strata combine shared-versus-variant-unique retrieval with rank bands. Within every stratum, SHA-256 ordering of the declared seed and PMIDs produces a reproducible simple random sample. If the requested size is smaller than the number of non-empty strata, the tool increases it so no population stratum is omitted. Shared PMIDs are labelled once and reused across variants.

## Label and estimate

Edit every `label_queue` record with one label and a reason:

- `likely-relevant`
- `irrelevant`
- `uncertain`

Then run:

```bash
python scripts/screening_burden.py estimate \
  --sample-file burden_sample.json \
  --candidate-ledger candidate_ledger.json \
  --minimum-heldout-recall 1.0 \
  --scope-version 1 \
  --output screening_burden.json
```

The estimator reports weighted precision, a 95% Wilson interval using Kish effective sample size, bounds treating uncertain labels as all irrelevant versus all relevant, estimated relevant reports, and estimated records screened per relevant report with an inverted confidence interval. It also reports exact total workload, held-out retrieval, and incremental workload/recall relative to the baseline.

An independent holdout is mandatory. A reused `both` set is rejected. `minimum-heldout-recall` is a proportion from 0 to 1 and defaults to 1.0.

The selection rule is binding: burden is used only when at least two variants meet the recall requirement and have estimable precision. A recall-failing variant is never recommended because it appears cheaper. If fewer than two qualify, `burden_used_for_selection` is false and no strategy is recommended from burden evidence.

For fragile multi-strand deliverables, record the final artifact in the manifest and include it in critic evidence and the audit. The completion gate checks labels, confidence intervals, held-out comparisons, eligible variants, and the selection rule.
