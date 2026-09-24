# Empirical Fragility Scoring

Use after screened relevant records and concept layers exist, before concept ablation and critic review.

Create `fragility_concepts.json` with one object per registered block:

```json
[
  {
    "label": "allocation method",
    "mesh_query": "...",
    "exact_query": "... [tiab]",
    "descriptive_query": "... [tiab]",
    "safety_query": "(exact) OR (descriptive)",
    "terminology_terms": ["random allocation", "quasi-random", "alternate allocation"],
    "human_override": "fragile",
    "override_reason": "Protocol expertise indicates implicit reporting despite the small development sample."
  }
]
```

Run:

```bash
python scripts/strategy_analysis.py fragility-score \
  --concepts-file fragility_concepts.json \
  --candidate-ledger candidate_ledger.json \
  --concept-ablation-json concept_ablation.json \
  --scope-version 1 \
  --output fragility_score.json
```

The tool measures exact title/abstract naming, MeSH coverage, exact-label coverage, descriptive rescue, safety-layer noise, held-out misses attributable to the block, and terminology variation across publication eras. Supply `terminology_terms` when query parsing would not capture the intended historical/regional families; otherwise terms are extracted from the layer queries. It maps those measurements to the five rubric dimensions in `concept-analysis-and-gating.md` and recommends `stable`, `fragile`, or `very-fragile` handling.

If there is no disjoint development-validation set or only one publication era, that dimension scores as uncertain rather than stable. Hard red flags include very low explicit naming, relevant records missed by the full safety layer, extreme safety-layer noise, and combined weak MeSH/exact coverage.

Human expertise remains authoritative, but every `human_override` requires `override_reason`. Preserve both the empirical and final recommendations in the audit. The complete-loop gate requires this artifact whenever screened relevant records exist and requires coverage of every registered block.
