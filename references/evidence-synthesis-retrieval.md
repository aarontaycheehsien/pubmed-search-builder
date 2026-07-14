# Evidence-Synthesis Retrieval

Use this route only when the locked protocol explicitly sets `evidence_target.mode` to `evidence-syntheses` or `mixed`. It retrieves reports about the topic; it does not answer the review question or replace title/abstract screening.

## Set the target before searching

State which completed report types are eligible: systematic review, meta-analysis, network meta-analysis, scoping review, umbrella review, rapid review, living systematic review, qualitative evidence synthesis, or evidence map. State how protocols, narrative reviews, and methods papers are handled. A primary-study protocol must not silently acquire a review-report filter.

Publication types and text labels are retrieval signals, not eligibility evidence. In particular, methods-topic headings such as `Meta-Analysis as Topic` are for papers about methods and are deliberately excluded from the completed-review profile. Screen every retrieved candidate against the locked protocol.

## Build a transparent profile

Compile the deterministic, scope-bound profile and save its source snapshot:

```bash
python scripts/review_discovery.py profile --protocol review_protocol_v1.json --output review_retrieval_profile_v1.json
python scripts/review_discovery.py sources --output review_retrieval_sources.json
```

The profile combines independently reported branches rather than claiming that the composite is a validated hedge. For example, `systematic[sb]` is the official NLM systematic-review subset component, but it is not a universal filter for meta-analysis, scoping reviews, umbrella reviews, or other report types. Publication-type branches can lag indexing; title/abstract rescue branches are broader and require screening. Preserve every branch's query, source, and indexing dependency.

## Discover, classify, and evaluate

Keep the topical query in a separate plain-text file. Discovery records branch provenance but does not assign eligibility.

```bash
python scripts/review_discovery.py discover \
  --profile review_retrieval_profile_v1.json --topic-query-file topic_query.txt \
  --output review_candidates_v1.json

# Review every candidate's title/abstract. The decisions file mirrors records,
# supplies decision, title_abstract_reviewed, eligibility_reason, record_kind,
# and declared_synthesis_type.
python scripts/review_discovery.py classify \
  --profile review_retrieval_profile_v1.json --candidates review_candidates_v1.json \
  --decisions review_decisions_v1.json --output review_classification_v1.json

# Compare the final strategy's PMIDs with screened-in eligible report PMIDs.
python scripts/review_discovery.py evaluate \
  --profile review_retrieval_profile_v1.json --classification review_classification_v1.json \
  --retrieved-pmids-file final_strategy_pmids.json --topic-only-count 123 \
  --output review_filter_evaluation_v1.json
```

`classify` rejects partial coverage, unreviewed records, and an included report that is not a completed synthesis of an eligible type. `evaluate` reports recall overall and by declared synthesis type. A missed screened-in report is a retrieval leak to investigate; a perfect result is only relative recall against that screened set, not evidence of completeness.

## Prior-review benchmarks are a different evidence stream

Adjacent reviews can provide a semi-independent external benchmark, but they remain non-independent because they import the prior review's scope and inclusion decisions. Do not combine them with review-report candidates or mine their terms. `benchmark-harvest` records provenance tiers:

- `declared-included-study-list` — a supplied included-study list from a prior review;
- `machine-extracted-pending-confirmation` — mechanically extracted content that still needs confirmation;
- `screened-cited-reference` — a citation linked from a prior review and screened here;
- `legacy-unclassified` — retained only for backwards-compatible old artifacts.

Freeze only a complete, screened benchmark for an evaluative recall check. An unscreened freeze is an indicative smoke test, never a validation set. Report the benchmark kind and tier counts in the audit.

## Handoff requirements

For a review-targeted protocol, the conditional `review-discovery` workflow gate requires the profile, candidate artifact, complete classification, and final retrieval evaluation. Include branch provenance, the source snapshot, screening decisions, per-type retrieval results, and every miss/resolution in the audit. Do not present this automated work as human information-specialist review or human PRESS peer review.
