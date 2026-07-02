# Low-Count Plausibility Review

Use this reference when the final topic-only PubMed strategy retrieves fewer than 500 records. This is a generic search-logic safeguard, not a topic-specific rule.

## Core Rule

A final topic-only count below 500 is a trigger for review, not proof of poor recall and not a command to expand automatically. Do not expand automatically just to exceed 500 records.

Before handoff, diagnose whether the count is expected or caused by avoidable narrowing. Record one of these outcomes:

- `expanded-and-retested`: a broader or relaxed variant was adopted, and the delivered final count was rerun.
- `relaxed-variant-rejected`: a broader or relaxed variant was tested but rejected because it mainly added out-of-scope noise or violated the protocol.
- `low-count-plausible`: the low count is plausible for a rare, new, tightly scoped, or protocol-limited topic, with rationale.
- `blocked-pending-decision`: the strategy needs user/protocol input before handoff.

Do not hand off a low-count strategy with only a bare caveat.

## Diagnostics

When count is below 500, review the final query for these generic recall risks:

- too many required `AND` blocks
- one block suppressing retrieval compared with the others
- outcome, comparator, setting, subgroup, or screening-only concepts used as required blocks
- narrow exact-phrase-only wording
- heavy proximity expressions
- missing acronym, singular/plural, spelling, hyphenation, or broader wording variants
- weak MeSH/free-text dual coverage where a dual layer is feasible
- `[Majr]`, `NOT`, date, language, species, age, publication-type, or full-text limits
- PubMed translation warnings, zero-hit phrases, or parse drift

Run the relevant count checks when feasible:

- individual block counts
- pairwise block counts
- leave-one-block-out counts
- final topic-only count
- a relaxed or broader variant for the likely bottleneck block when the diagnostics suggest avoidable narrowing

The relaxed variant is a test, not an adoption requirement. If it retrieves mostly out-of-scope noise, reject it and document why.

## Hook

Run:

```bash
python scripts/hooks_tool.py low-count-review \
  --strategy-file final_strategy.txt \
  --final-count <COUNT> \
  --decision <DECISION> \
  --rationale "<RATIONALE>" \
  --relaxed-variant-tested \
  --relaxed-variant-count <COUNT> \
  --output low_count_review.json
```

If no relaxed variant is appropriate, replace `--relaxed-variant-tested` with:

```bash
--no-relaxed-variant-reason "<WHY A VARIANT TEST WAS NOT APPLICABLE>"
```

The hook does not run PubMed, rewrite the strategy, or decide relevance. It checks that the low-count review was documented and flags generic search-logic risks to inspect.

## Manifest Gate

Record the hook output as a `qa` entry:

```bash
python scripts/manifest_tool.py add --manifest run_manifest.json --kind qa \
  --command "python scripts/hooks_tool.py low-count-review ..." \
  --output low_count_review.json \
  --label "Low-count plausibility review"
```

At handoff, use:

```bash
python scripts/manifest_tool.py show --manifest run_manifest.json \
  --validate --check-files --require-low-count-review
```

The manifest gate only applies when it can identify a final topic-only search count below 500. For counts of 500 or higher, it passes without requiring a review artifact.

## Audit Reporting

In the audit, report:

- final topic-only count
- low-count diagnostics performed
- relaxed variant tested, if any
- before/after or baseline/variant counts
- final decision and rationale
