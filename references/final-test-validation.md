# Development validation and a sealed final test

Use when allocating records, evaluating search quality, or reporting independence.

| Role | May influence the search? | Use |
|---|---|---|
| `discovery` | Yes | Screened records for vocabulary mining |
| `development-validation` | Yes, through diagnostic results | Repeated recall checks, ablation, revisions, burden selection and critic evidence; no direct mining |
| Sealed final test | No, before strategy freeze | One final known-set recall measurement |

Legacy `holdout`, `holdout_pmids`, `--holdout-pmids`, `--heldout-pmids`, `--allocate-holdout` and related JSON keys refer to development validation. They do not name the final test. `candidate_ledger_pmids` reports `independent: false` and separately reports `disjoint_from_discovery`; a split may be disjoint and still influence development. New allocations use `development-validation`.

## Reserve records before development

A separate custodian or isolated evaluation harness screens the final-test records against the locked protocol. The custodian keeps their identifiers, titles, abstracts, MeSH, family identifiers and per-record results outside the builder's files/context. The builder receives only a public receipt with a random seal ID, hash, count, scope binding and attestation. Do not place final-test PMIDs in the protocol's seed list.

Allocate whole study families when known. Record `study_family_id` consistently in the private test ledger and development ledger. The evaluator rejects overlapping PMIDs and known families, but missing family identifiers cannot prove independence. Also account for related reports and review-derived sampling bias when reporting results.

The private input is a normal, protocol-bound, evidence-screened candidate ledger containing only confirmed relevant records. It must never have been used by the builder. Its temporary evidence roles describe custodian screening, not permission to mine it in the build.

Custodian command:

```bash
python scripts/final_test_tool.py seal \
  --candidate-ledger /custodian/test_candidates.json \
  --protocol review_protocol_v1.json \
  --custodian reviewer-or-harness-id --unseen-by-builder \
  --output /custodian/final_test.sealed.json \
  --receipt final_test_receipt.json
```

Keep the sealed file and its `.used.json` state together in persistent custodian storage. The seal is not encryption or an access-control system: the custodian attests non-exposure and enforces separation. Do not claim that a hash proves blindness. If the builder has already inspected the records, they are development evidence, even if their roles are renamed.

With too few records, no separately held set, or no isolated custodian, do not manufacture a final test. Complete the development workflow and report **independent final evaluation: not performed**, with the reason. Repeated known-item checks remain useful.

## Finish development and freeze one strategy

Use development validation for all iterative vocabulary, block, filter, workload and critic decisions. Finish the existing completion gate, including final QA and the development audit. Fix all development findings before final testing.

```bash
python scripts/final_test_tool.py freeze \
  --strategy final_main_strategy.txt --protocol review_protocol_v1.json \
  --development-ledger candidate_ledger.json \
  --receipt final_test_receipt.json --manifest run_manifest.json \
  --output final_strategy_freeze.json
```

The command checks the development completion gate, active ledger and executed/QA-tested strategy. It binds the strategy, protocol, development ledger, public receipt and manifest to exact hashes. Do not alter those files before evaluation. The candidate ledger must cover every record exposed during development, including excluded and uncertain records, so the overlap check covers those too.

## Evaluate once

Only the custodian uses the sealed file:

```bash
python scripts/final_test_tool.py evaluate \
  --sealed /custodian/final_test.sealed.json \
  --freeze final_strategy_freeze.json --output final_test_result.json
```

Evaluation checks the frozen inputs and overlap, then exclusively claims the set before any PubMed request. A consumed set cannot be rerun, including after a retrieval failure. Preserve the failed attempt and report evaluation unavailable; do not delete the claim to retry. This conservative policy prevents accidental reuse of partial feedback.

The public result contains aggregate retrieved, reachable, unreachable and missed counts, known-set recall, bindings and limitations. Detailed requests remain beside the sealed file in custodian storage. An empty reachable denominator yields `recall: null`; it never becomes a perfect score. No variant selection or per-block diagnosis is performed on final-test records.

Misses do not make the measurement invalid and are not a completion-loop instruction to revise until recall is perfect. Report them honestly. If the strategy changes after seeing the result, retain the old result for the old strategy only. The revised strategy needs a new untouched test set or an explicit statement that it lacks independent final evaluation. This applies even to changes that only add OR terms.

## Audit and handoff

Add the absolute path `final_test_result_file` to the audit input and regenerate the audit. The renderer verifies frozen strategy/protocol/ledger bindings and reports the result in a separate **Sealed final test** section. Without that field it explicitly says final testing was not performed. Do not author aggregate numbers directly into this section.

Record the aggregate result as an `artifact` in the manifest, then rerun the normal handoff gate. That gate checks the result against the strategy in the audit; final-test misses are reported rather than fed back into development validation. The manifest can gain reporting entries after evaluation, but the frozen query, protocol and development ledger must remain unchanged.

```bash
python scripts/final_test_tool.py verify final_test_result.json
```

Interpret this as a one-time evaluation against a custodian-attested, unexposed known set. It does not measure absolute sensitivity or establish that the set represents all eligible literature. Model memory and undiscovered study-family links remain limitations.
