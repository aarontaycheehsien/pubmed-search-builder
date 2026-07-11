# Concept Ablation and Two-Strand Delivery

Use this reference after blocks are drafted and before the PRESS-informed critic.

## Automatic AND-block ablation

Run every build with two or more proposed `AND` blocks through:

```bash
python scripts/strategy_analysis.py concept-ablation \
  --blocks-file blocks.json \
  --candidate-ledger candidate_ledger.json \
  --scope-version 1 \
  --sample-size 10 \
  --output concept_ablation.json
```

Each block object may include `role`, `fragility`, and `parent_block`. The tool constructs the full strategy from all blocks and, for each block, records:

- the full count and count without the block;
- the additional screening workload when the block is removed;
- block, full-strategy, and leave-one-out retrieval across discovery and independent holdout records;
- exact `(without block) NOT (full)` differential counts and fetched samples;
- one recommendation: `keep-as-required`, `move-inside-another-or-block`, `handle-at-screening`, or `focused-variant-only`.

Recommendations are deterministic triage, not scope decisions. A known-item loss makes a block unsafe for the recall-first strand and routes it to screening unless the scope itself must be reopened. A `parent_block` or within-block role routes vocabulary inside the parent `OR` block. Optional/fragile blocks with useful workload reduction are focused-only. Stable, scope-essential blocks with no observed loss remain required. Inspect saved differential records before adoption.

Record `concept_ablation.json` in the manifest. The complete-loop gate requires coverage of every registered block and requires the critic to run after the ablation.

## Two-strand delivery for fragile topics

Mark fragility explicitly in the retrieval-scope artifact with `fragile_topic: true`, `topic_fragility: fragile|very-fragile`, or a fragile `essential_blocks[].fragility`. Then create a focused-block file:

```json
[
  {
    "label": "direct emergency-care allocation",
    "query": "...",
    "rationale": "Prioritize reports explicitly describing allocation in emergency care."
  }
]
```

Run:

```bash
python scripts/strategy_analysis.py two-strand \
  --main-strategy-file final_main_strategy.txt \
  --narrowing-blocks-file focused_blocks.json \
  --candidate-ledger candidate_ledger.json \
  --scope-version 1 \
  --output two_strand.json
```

The focused query is always `main AND (reasoned narrowing block[s])`. The artifact reports both counts, development/holdout losses, exact unique-record differentials with samples, workload reduction, and each narrowing rationale. Its safeguards declare the main strand authoritative and prohibit silent replacement.

Search and retain the recall-first main results. Use the focused strand only to prioritize screening or as an explicitly secondary search strand. Run the critic after both artifacts exist, and cite both in the audit.
