# Search Updates

Use this reference to re-run a finished strategy for a review update or a living review. An update re-runs the frozen strategy. It is not a rebuild, and it never edits the strategy.

## Why re-running is not enough

A validated strategy can change meaning while its text stays the same. Annual MeSH revisions add, split, and retire descriptors and move entry terms. Automatic Term Mapping changes what untagged words expand to. The count alone does not show this: PubMed can return a plausible number for a search that no longer means what was reviewed.

## Inputs

- the frozen final strategy file that was searched at handoff;
- the build's saved final `pubmed_tool.py search --output` JSON (the baseline), which holds PubMed's translation at build time;
- the date of the last search, from the audit's PRISMA-S dates;
- optionally, the build's candidate ledger, so development-validation records are re-tested.

## Run

```bash
python scripts/workflow_tool.py --manifest run_manifest.json --kind search --label "search update 2026-09-25" \
  --input final_strategy.txt --input final_search.json --output search_update_2026-09-25.json -- \
  python scripts/search_update.py check --strategy-file final_strategy.txt --baseline-search final_search.json \
  --last-searched 2026-03-01 --candidate-ledger candidate_ledger.json \
  --output search_update_2026-09-25.json --report search_update_2026-09-25.md
```

The update is always retrieved live, never from the response cache. The label must not contain "final", so the update is never mistaken for the build's final topic search.

## What it checks

- **Same strategy.** The strategy text must match the baseline query exactly; otherwise it is refused.
- **Translation drift.** It compares today's PubMed translation, term mappings, error and warning notices, and translation warnings with the baseline.
- **Validation.** When validation records are supplied, it reports any the strategy no longer retrieves.
- **New records.** It retrieves the records in the update window for screening. The window starts on the last search date, so a one-day overlap is removed at deduplication instead of a gap losing records. The default date field is `crdt` (create date), which also catches older citations added to PubMed late. `edat` is available, but it is set to the publication date for records added long after publication. A window with 10,000 or more records must be split into shorter periods.

## Verdicts

- `no-drift`: PubMed reads the strategy as it did at build time, and no validation record is lost. Screen the new records against the locked protocol and use the report's PRISMA-S update statement.
- `review-required`: the translation changed, a notice appeared (for example a retired heading now not found), or a validation record is missed. Do not edit the strategy inside the update. Take the drift report into an existing-strategy review, with the protocol's plain-language question as the scope authority. Any revision then follows the no-harm revision rules and is versioned.

The update never judges relevance. New records go to screening, and the evidence question stays out of scope.
