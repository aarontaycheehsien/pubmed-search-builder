# Revision No-Harm Gate

Use this gate for every critic-driven strategy revision and every accepted vocabulary revision. A revision is not adopted merely because it addresses a critic recommendation or adds plausible terminology.

## Required checks

Prove and save all seven checks:

1. **Named defect fixed:** identify the critic finding or vocabulary gap and cite before/after evidence showing the change addresses it.
2. **Held-out retrieval preserved:** every held-out PMID retrieved by the baseline remains retrieved after revision. Record the tested baseline and revised PMID sets even when the set is empty.
3. **No unjustified required block:** compare required block IDs and identify the protocol authorization for every addition. Vocabulary additions must remain inside an existing `OR` block.
4. **Syntax and translation stable:** rerun the revised query and record syntax status, PubMed translation, warnings, and drift issues. A warning or unrecognized field fails the check until resolved.
5. **Scope unchanged or explicitly versioned:** the protocol hash and scope version remain unchanged, or an authorized protocol re-entry increments the scope version and records the reason.
6. **Workload effect recorded:** save exact before/after counts, absolute change, and percentage change where the baseline count is nonzero.
7. **No narrowing under a low signal:** the search must not lose block breadth just because retrieval is low or discovery surfaced few relevant records. This is a mechanical tripwire, not only an instruction.

### No narrowing under a low-count / empty-discovery signal

A low retrieval count and an empty screened-in set are *triggers to investigate*, never evidence that the topic is small — so they must not be used to justify dropping terms or narrowing a block. When such a state exists, record it in the guard input as a `low_signal` object so the check can enforce this:

```json
"low_signal": {
  "low_count": true,
  "topic_only_count": 120,
  "no_included_candidates": false,
  "discovery_verdict": "discovery-bottleneck",
  "authorized_narrowing": {"authorized": false, "reason": ""}
}
```

The signal is **active** when `low_count`, `no_included_candidates`, or an untrusted `discovery_verdict` (`discovery-bottleneck`, `indeterminate`, `pending-discrimination` from `no_seed_discovery.py`) is set (or `active: true` is given explicitly). While it is active, the guard **requires** `search_term_count` on both baseline and revised (optionally per-block `block_term_counts`) and **fails** the check if the revised search reduces total or any per-block breadth — unless the reduction is an authorized scope re-entry (checks 5 passes with `scope_change.changed`) or an explicit `authorized_narrowing` with a recorded reason (e.g. the user confirmed a term is genuinely out of scope). Absent a `low_signal`, the check is not applicable and passes, so ordinary revisions are unaffected. This converts "never narrow on a low count" from a soft norm the model could violate silently into a checked invariant that reverts the revision to baseline.

## Critic revisions

Create a version-1 no-harm input containing hashed baseline/revised strategy files, held-out retrieval sets, required block IDs, syntax/translation status, scope bindings, counts, the named finding, and any experimental fallback. Run:

```bash
python scripts/revision_guard.py revision_no_harm_input_1.json \
  --output revision_no_harm_1.json \
  --selected-strategy-output strategy_after_guard_1.txt
```

The result disposition is:

- `adopt` only when all checks pass;
- `revert-to-baseline` when any check fails; or
- `experimental-only` when a failing revision explicitly supplies both an experimental variant ID and label.

Set the revision-cycle `strategy_file` to the guard's `authoritative_strategy_file`, include `no_harm_file`, and make its disposition match the guard. `manifest_tool.py state record-revision` rejects mismatches and the completion gate rechecks the guard hash.

## Vocabulary revisions

`vocabulary_learning.py retest` runs the same checks for every authored `accepted` proposal. It records the effective decision separately:

- `adopted`: the expanded block becomes authoritative;
- `revert-to-baseline`: the original block remains authoritative; or
- `experimental-only`: the original block remains authoritative and the expanded query is retained only under a supplied experimental ID and label.

Never count reverted or experimental-only terms as accepted main-strategy vocabulary. Route a new concept, new required block, or changed eligibility interpretation through protocol scope re-entry instead.
