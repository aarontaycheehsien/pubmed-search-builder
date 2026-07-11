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

For later rounds, pass the prior final vocabulary-learning artifact with `--previous-learning` so only newly included records contribute new proposals.

## Adjudicate and retest

Edit each proposal in the extraction artifact:

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
