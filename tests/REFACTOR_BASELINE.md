# Refactor baseline (Phase 0)

Captured before any Phase 1-4 deduplication. This is the "before" snapshot the
~40% instructional-overhead reduction is measured against. See
`tests/rule_inventory.json` for the rule-by-rule safety net and
`tests/test_rule_inventory.py` for enforcement.

## Instructional-prose word counts (SKILL.md + references)

| Doc | Words |
|---|---|
| references/wildcard-and-truncation.md | 663 |
| references/framework-selection.md | 746 |
| references/anti-patterns.md | 912 |
| references/goal-tracking.md | 985 |
| references/examples.md | 1,277 |
| references/prisma-s-reporting.md | 1,358 |
| references/seed-pmid-validation.md | 1,585 |
| references/validated-methodological-filters-and-hedges.md | 1,822 |
| SKILL.md | 1,826 |
| references/tiab-expansion.md | 1,993 |
| references/audit-template.md | 2,521 |
| references/concept-analysis-and-gating.md | 2,900 |
| references/workflow.md | 4,682 |
| references/mesh-and-pubmed-tools.md | 4,733 |
| **Total** | **28,003** |

Phase 2-3 targets, in priority order (loaded-on-every-invocation first):
- `SKILL.md`: 1,826 -> ~750 words (thin contract + routing table).
- `references/workflow.md`: collapse the ~21 inline banner restatements into one stage table.
- `references/mesh-and-pubmed-tools.md`: delete the duplicated "Suggested Operational Sequence".

Overall target: ~40% reduction of normative prose (~28,000 -> ~17,000 words) with
**zero** loss of normative rules (every rule keeps exactly one canonical home).

## Duplication metrics (from `test_rule_inventory.py`, pending targets)

Recorded, not yet failed on. Lower is better after Phase 1-4 collapses each cluster.

| Tracked rule | Signature | Docs containing it (before) |
|---|---|---|
| input.boolean-syntax-not-accepted | `boolean syntax` | 6 (SKILL, concept-analysis-and-gating, framework-selection, goal-tracking, mesh-and-pubmed-tools, workflow) |
| stage-banner.inline-restatements | `full banner required` | workflow.md (restated inline; collapse to one stage table) |
| operational-sequence.duplicate-of-workflow | `suggested operational sequence` | mesh-and-pubmed-tools.md (delete; workflow.md owns sequence) |

## Test baseline

- Existing suite before Phase 0: **191 passed, 15 subtests** (`python -m pytest -q`).
- Phase 0 adds `tests/test_rule_inventory.py`: **6 passed, 43 subtests**, against the
  unchanged docs (no prose moved in Phase 0).

## Phase 0 coverage added for previously-untested clusters

These reference docs had **no** doc-content test before Phase 0; they now have
presence coverage in the inventory so Phase 1-4 cannot drop them silently:

- `references/wildcard-and-truncation.md` (600-variant cap, truncation/proximity exclusion)
- `references/validated-methodological-filters-and-hedges.md` (Cochrane HSSS, McMaster HIRU, ISSG, Ovid warning)
- `references/prisma-s-reporting.md` (16-item mapping; Items 2, 8, 14)
- `references/examples.md` (PICO/PECO/PCC walk-throughs)
- plus mechanics in `references/tiab-expansion.md` (coverage/lift/background, proximity behaviour)

## How later phases use this

1. When moving a rule, update its inventory entry's `canonical_owner` /
   `pointer_locations` / `forbidden_locations` in the **same commit**.
2. When a `duplicated-pending` rule is collapsed, flip `status` to `canonical`,
   fill `forbidden_locations` with the docs that should now only link, and the
   `test_canonical_signatures_have_not_respread` check enforces it.
3. Re-run `python -m pytest tests/test_rule_inventory.py -s` to see the dedup
   meter drop, and re-measure word counts against this baseline.

---

## Progress - Phases 1-4 (outcome)

All three Phase-0 `duplicated-pending` clusters are now `canonical` and enforced;
the pending dedup meter reads "no pending dedup targets remain."

### Word counts: baseline -> now

| Doc | Baseline | Now | Δ |
|---|---|---|---|
| SKILL.md (always loaded) | 1,826 | 1,344 | **-482 (-26%)** |
| references/mesh-and-pubmed-tools.md | 4,733 | 4,689 | -44 (net; Phase 1 -196, Phase 4 docs +152) |
| references/workflow.md | 4,682 | 4,687 | +5 (net; Phase 1/3 dedup -41, Phase 4 pointer +46) |
| references/goal-tracking.md | 985 | 967 | -18 |
| **Total SKILL.md + references** | **28,003** | **27,464** | **-539 (-1.9%)** |

The headline win is the always-loaded contract (`SKILL.md`, -26%). Total prose
moved less than the original ~40% aspiration because the genuinely *duplicated*
content was a small fraction of the corpus, and Phase 4 deliberately added new
capability docs for `manifest_tool.py state`. The durable wins are structural,
not word-count: single-sourced rules, a leaner on-load contract, file-backed
build state, and an enforcement net that fails if a rule is dropped or re-spread.

### What each phase delivered

- **Phase 0** - `rule_inventory.json` + `test_rule_inventory.py` + this baseline.
  Non-vacuity proven by fault injection.
- **Phase 1** - collapsed the duplicated "Suggested Operational Sequence"
  (-> tool-to-stage map) and the triplicated Boolean-syntax intake policy
  (-> single-homed in SKILL.md).
- **Phase 2** - rewrote SKILL.md as a thinner contract with zero test changes
  (the ~10 guarding test methods prove no rule was lost).
- **Phase 3** - per-stage reference lists single-homed in workflow.md's stage map;
  inline triggers now say "references per the stage map."
- **Phase 4** - `manifest_tool.py state` externalises stage/gate tracking into
  `run_manifest.json`, with `state check-ready` as a machine handoff gate.

### Test suite: 191 -> 207 passing

Added `test_rule_inventory.py` (+6) and `test_manifest_state.py` (+13); all
existing tests still green.

### Phase 4 gate made binding

`manifest_tool.py show --validate --check-files --require-ready` folds the
readiness check into the manifest validation the workflow already mandates at
finish. It exits non-zero unless the build-state concept gate is resolved and no
user question is pending (an absent `build_state` also fails - the build must
track state). The stop-condition in `workflow.md` §10, `SKILL.md` Output Format,
the audit template, and the tool docs now require it, so handoff is blocked, not
merely advised.

### Not done (out of scope for #3)

- Further reduction toward 40% would require compressing *unique* normative
  content in the heavy reference docs - a content-judgment exercise, not dedup.
- The workflow points to `state show` but does not hard-require reading it at the
  top of every turn (still advisory); the binding enforcement is at handoff via
  `--require-ready`.
