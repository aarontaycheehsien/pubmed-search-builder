# Active Vocabulary Learning Without Scope Drift

Use after candidate screening and holdout allocation, before final block testing and critic review.

## Configure locked-concept assignments

Create `vocabulary_config.json` against the current scope version:

```json
{
  "scope_version": 1,
  "concepts": [
    {"label": "condition", "existing_terms": ["asthma", "bronchial asthma"]}
  ],
  "record_concept_assignments": {
    "12345678": ["condition"]
  }
}
```

Every assignment label or ID must already exist in `review_protocol_v<N>.json` as an essential searchable concept. Assigning a new concept produces a scope challenge, not a vocabulary proposal. Record new eligibility interpretations in the candidate ledger as `scope_challenge` or `eligibility_interpretation_change`; either requires a new protocol version.

## Extract

```bash
python scripts/vocabulary_learning.py extract \
  --scope-file review_protocol_v1.json \
  --candidate-ledger candidate_ledger.json \
  --records-file screened_records.json \
  --config-file vocabulary_config.json \
  --scope-version 1 \
  --output vocabulary_extract_1.json
```

The tool extracts phrases, acronyms, keywords, and MeSH from newly included discovery records only. It excludes existing and previously proposed terms. Excluded records are summarized separately with exclusion reasons and frequent terminology; `used_for_proposals` is always false. Unassigned included records and missing record content block adjudication.

### The bounded review shortlist

Generation is unbounded by nature: every 2-3 gram, acronym, keyword, and MeSH heading in every newly included record, for each concept that record is assigned to. A real build produces six figures of candidates, which no reviewer or critic can work through — so a per-candidate disposition requirement would be satisfiable only by a bulk reason, and the audit would then imply a review that never happened.

The tool therefore ranks candidates and promotes a bounded shortlist:

- **`proposals`** — the review shortlist, and the only list requiring a per-term disposition. Selection runs per locked concept and splits the budget round-robin across the MeSH, keyword, acronym, and phrase layers, preferring terms that cover records not yet represented. One concept or one phrase class cannot consume the allowance. Set the size with `--max-review-terms-per-concept` (default 60).
- **`below_review_threshold`** — everything else, kept as measurements: threshold policy, counts by concept/layer/supporting-record count, and compact normalized-term fingerprints. Nothing here was reviewed, accepted, or rejected. Failing a mechanical ranking threshold is not a relevance judgement, and the tool never labels it one. The fingerprints let a later round skip the same tail instead of re-proposing it.
- **`candidate_generation`** — `total_generated`, `promoted_for_review`, `below_review_threshold`, and `reconciled`. The completion gate checks that the shortlist and the retained tail reconcile with total generated candidates, and that the saved proposal count matches what was promoted.

Ranking uses local supporting-record coverage only. PubMed background lift costs one query per term, so it belongs on the bounded set — run `pubmed_tool.py term-rank` against the shortlist when lift is needed.

Candidate terms are attributed per record rather than per term, so a record assigned to several concepts proposes all of its terms under each. Shortlisted terms in that position carry `also_proposed_for_concepts`; deciding which concept a term actually belongs to is a review decision, not something the extractor can infer.

For later rounds, pass the prior final vocabulary-learning artifact with `--previous-learning` so only newly included records contribute new proposals, and so the previous round's retained tail is not proposed again.

Every authored `accepted` proposal then passes the seven checks in `no-harm-revisions.md`. The tool adopts only changes that fix the vocabulary gap, preserve prior held-out retrieval, stay inside the locked concept, avoid syntax/translation drift, preserve protocol scope, and report before/after workload. Failed proposals automatically revert or remain a labelled experimental-only variant.

## Adjudicate and retest

Edit each proposal in the extraction artifact's `proposals` shortlist. Do not add decisions to `below_review_threshold`; the gate rejects an artifact that dispositions unreviewed candidates.

```json
{
  "decision": "accepted",
  "decision_reason": "Observed in a newly included report and remains a synonym for the locked condition concept.",
  "within_locked_concept_attested": true
}
```

Allowed decisions are `accepted`, `rejected`, and `deferred`; every decision requires a reason. An accepted term may optionally replace `suggested_query` with a reviewed `query`, but it cannot target a new block.

```bash
python scripts/vocabulary_learning.py retest \
  --extraction-file vocabulary_extract_1.json \
  --blocks-file blocks.json \
  --scope-version 1 \
  --output vocabulary_learning_1.json
```

Every accepted term is tested as `current block OR term` against the frozen independent holdout when available and through an exact `(expanded block) NOT (current block)` differential with fetched records. If no independent holdout exists, the artifact records that limitation; the differential remains mandatory.

Do not retest or adopt proposals while `scope_reentry_required` is true. Reopen scope, issue a new scope version, revisit affected screening decisions and block roles, then rerun extraction. Vocabulary learning may add coverage inside a locked `OR` block; it may not add a concept, reinterpret eligibility, or promote excluded-record language into the search.

Record the final artifact in the manifest and include it in the critic evidence bundle. The completion gate requires a resolved vocabulary-learning artifact whenever candidate screening is complete.
