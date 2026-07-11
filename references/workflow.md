# Canonical Workflow

Use this workflow to build, resume, or internally review a high-sensitivity PubMed strategy. The task is search construction and QA, not answering the evidence question.

## Stage map

Track the detailed stages in `run_manifest.json`, but show users only four concise markers: `Intake`, `Scope lock`, `Empirical build and critic loop`, and `Handoff`.

1. `intake` - confirm the plain-language question, build/review mode, and optional seed status.
2. `scope-lock` - save retrieval scope version 1 before record evidence is mined.
3. `candidate-discovery` - fetch supplied seeds and discover pilot/related/prior-review candidates.
4. `candidate-screening` - screen candidates and freeze discovery/holdout roles.
5. `objective-evidence` - mine accepted discovery records, sweep MeSH, and inspect PubMed behavior.
6. `block-testing` - build blocks and run reversible counts, samples, gaps, variants, and filter comparisons.
7. `validation` - test held-out records, or label reused-seed/heuristic checks as non-independent.
8. `critic-review` - run a fresh-context PRESS-informed critic against the current artifacts.
9. `revision` - route findings, reopen scope when structural, and rerun affected evidence.
10. `final-qa` - confirm PubMed translation, syntax, hygiene, and final counts.
11. `audit-output` - render the audit and append every final artifact to the manifest.
12. `peer-review-handoff` - deliver the draft for human PRESS peer review.

Stages 5-9 form a loop. Do not proceed to final QA until a critic round passes with no open actionable finding.

High-sensitivity blocks normally use both controlled vocabulary and author language:

```text
(MeSH/SCR layer OR title/abstract layer OR tested proximity/wildcard layer)
AND
(MeSH/SCR layer OR title/abstract layer OR tested proximity/wildcard layer)
```

Prefer fewer required `AND` blocks. MeSH does not replace free text, and free text does not replace MeSH.

## 1. Intake

Require an independently stated plain-language review question. Pasted Boolean syntax, line sets, field tags, or a prior strategy cannot supply scope evidence.

For a new build, ask once whether known-relevant seed PMIDs exist. Seeds are optional. Normalize and deduplicate supplied numeric PMIDs, but do not fetch, mine, or expand them until scope version 1 is locked.

For an existing-strategy review, confirm the plain-language question first. Then accept the draft as a review object and preserve it as version 0; do not infer eligibility, essential concepts, or filters from its structure.

Resolve and record the framework, seed, concept, and filter gates. Use `references/goal-tracking.md` when `/goal` is requested; do not start a tracked goal while a scope-changing decision is unresolved.

## 2. Lock conceptual scope

Read `references/framework-selection.md`, `references/concept-analysis-and-gating.md`, and `references/anti-patterns.md`.

Before any PubMed record fetch, MeSH lookup, term mining, or block drafting:

1. Choose the appropriate framework.
2. Map candidate concepts from the question/protocol.
3. Apply the fragility rubric and `AND`-block admission test.
4. Decide which eligibility elements are searchable anchors, within-block term families, screening-only elements, optional/focused concepts, or filter decisions.
5. Resolve high-impact ambiguities with the user or protocol.
6. Save `retrieval_scope_v1.json` and record it with `manifest_tool.py state lock-scope`.

The scope artifact must contain:

- `scope_version` and the plain-language question;
- framework and question type;
- essential `AND` blocks;
- within-block term families;
- screening-only and omitted elements with recall-risk reasons;
- optional/focused concepts and filters;
- unresolved ambiguities, which must be empty before locking;
- user/protocol decisions and rationale.

Objective evidence may expand or correct vocabulary within a locked concept. It may not silently add, remove, or redefine an essential concept.

## 3. Discover and screen candidate evidence

Read `references/candidate-screening.md`. When supplied seeds exist, also read `references/seed-pmid-validation.md`.

After the scope is locked:

1. Fetch supplied seeds and inspect saved record JSON for identity, retraction, scope, title, abstract, publication type, and indexing.
2. With supplied seeds, discover additional candidates through related/citation/prior-review methods. With no seeds, run the six-family orthogonal-pilot workflow in `no-seed-recall-estimation.md` and keep provenance hidden during screening.
3. Screen every record that may influence term mining as `include`, `exclude`, or `uncertain` against the locked scope.
4. Assign `discovery`, `holdout`, `both`, `heuristic`, or `neither` roles.
5. Save and validate `candidate_ledger.json` with `scripts/candidate_ledger.py`; use deterministic `--allocate-holdout` when roles are not already frozen.
6. Record the ledger with `manifest_tool.py state record-candidate-screen`.

Only screened-in `discovery` or `both` records may feed term mining. Do not feed high-overlap related records directly into `term-rank`. Unscreened neighbors may remain a separately labelled heuristic benchmark.

Freeze held-out records before mining. When no independent holdout is feasible, record validation as non-independent.

For no-seed builds, do not begin term mining until repeated rounds add neither screened-in relevant studies nor vocabulary, no retrieval safety cap remains unresolved, and `no_seed_discovery.py adjudicate` has frozen discovery/holdout roles.

## 4. Build objective evidence and concept blocks

Run the pre-MeSH vocabulary/domain brainstorm from `references/concept-analysis-and-gating.md` for social-science, behavioral, qualitative, health-services, or weakly indexed concepts. Do not turn adjacent vocabulary into a new `AND` block.

For each essential concept:

1. Build a variant list from the scope artifact, accepted brainstorm families, accepted discovery records, MeSH entry terms, acronyms, spelling/hyphenation/morphology variants, older/newer terms, and PubMed ATM clues.
2. Run `mesh_tool.py sweep --details` and complete the MeSH/SCR candidate ledger before drafting the block. Inspect scope, entry terms, tree/explosion context, and plausible rejected descriptors.
3. Run `pubmed_tool.py term-rank --candidate-ledger candidate_ledger.json` only on screened-in discovery records. Review its diverse MeSH/keyword/acronym/phrase selection and marginal-record coverage; treat coverage/lift output as candidate evidence, never automatic inclusion.
4. Run `strategy_analysis.py fragility-score` for every block when screened relevant records exist. Use the measured stable/fragile/very-fragile recommendation; require a reason for any human override. Use the exact-label plus descriptive/action safety layer for fragile concepts; offer the sensitive leave-out design for very fragile concepts.
5. Draft MeSH/SCR, title/abstract, proximity, and wildcard layers. Read `references/tiab-expansion.md` and `references/wildcard-and-truncation.md` when those features are reached.
6. Test accepted descriptors, plausible rejected descriptors when recall may be affected, major text-word clusters, MeSH-only, text-word-only, and combined blocks.
7. Use `references/bramer-reciprocal-gap-analysis.md` when reciprocal gap analysis can reveal vocabulary or indexing gaps; otherwise record a reasoned waiver.
8. Save the blocks file and register its essential block labels against the current scope version.

Use `references/validated-methodological-filters-and-hedges.md` to choose a validated PubMed filter where available. Never translate an Ovid/Embase/CINAHL hedge by imitation. Preserve topic-only and topic-plus-filter strategies separately.

## 5. Probe before asking for adoption

Read `references/concept-ablation-and-strands.md`. After ordinary block probes, run `strategy_analysis.py concept-ablation` across every proposed `AND` block. The critic must receive the saved ablation artifact and differential samples. Reconcile each recommendation with the locked scope; empirical retrieval cannot by itself make a concept essential.

Run reversible, read-only diagnostic comparisons without requiring advance authorization:

- individual block and pairwise counts;
- full sensitive strategy;
- with/without optional block comparisons;
- topic-only versus topic-plus-filter;
- exact phrase, Boolean, proximity-width, and wildcard alternatives;
- sensitive, focused, precision, filter, and reserve variants;
- differential samples and labelled samples when available.

Counts are workload proxies, not precision. A focused or filtered design may be adopted only after the user/protocol accepts its recall trade-off. Gather the comparison evidence before asking.

Inspect saved samples whenever relevance, scope, noise, or term discovery informs a decision. Receipt-only stdout is insufficient.

For a fragile or very-fragile topic, also run `strategy_analysis.py two-strand`. Keep the recall-first strategy as the authoritative main search and add reasoned narrowing blocks only to the focused prioritization strand. Report both counts, known-item losses, exact unique-record differentials, workload estimates, and narrowing rationales.

## 6. Validate

Prefer held-out screened-in records that did not contribute vocabulary. Report:

- holdout retrieval overall and by block;
- missed-record diagnosis and bottleneck blocks;
- topic-only versus filtered losses;
- whether validation is independent, non-independent reused-seed, or heuristic.

When no seeds or holdout exist, the pilot-related recall check in `references/no-seed-recall-estimation.md` may identify leaks, but it is not validated sensitivity. Low heuristic recall is evidence to inspect misses, not permission to widen scope automatically.

Never hand off a final strategy with an unexplained missed in-scope holdout, seed, or gold-standard PMID. Classify every miss as query failure or documented out-of-scope evidence.

## 7. Run the critic and revise

Read `references/press-critic.md`. Build a hashed evidence bundle, save a version-2 `critic_round_<N>.json`, validate it with `scripts/critic_tool.py`, and record it with `manifest_tool.py state record-critic`. A later round must carry every previously open finding ID forward as resolved, accepted-risk, not-applicable, or still open.

Route findings:

- lexical -> revise the affected `OR` layer and rerun its evidence;
- structural -> `state reopen-scope`, rerun concept admission, save a new scope version, re-screen affected candidates, and re-register blocks;
- scope -> ask the user/protocol and stop;
- filter -> compare topic-only and filtered designs and diagnose losses;
- syntax -> repair and rerun PubMed translation/final QA;
- reporting -> correct the audit without pretending the strategy changed.

Save every material strategy revision under a new filename. Record the trigger, finding, evidence, change, expected effect, required re-probe, before/after counts, validation effect, and disposition. Use manifest supersession rather than silent overwrite.

Repeat objective evidence, testing, validation, and critic review until the latest critic artifact has `overall_status: pass` and no open must-fix or should-fix finding.

## 8. Final QA

After the critic passes:

1. Save the final recall-first topic-only strategy and any adopted filter/focused variant. For fragile topics, preserve both main and focused files; the focused strand cannot replace the main.
2. Deduplicate exact repeated terms without removing distinct variants.
3. Run `pubmed_tool.py search --query-file ... --retmax 0` and inspect PubMed translation warnings.
4. Fix unbalanced syntax and invalid field tags. Check spelling/hyphenation before removing zero-hit terms; remove and document genuine zero-hit terms by default, with free-text future-proofing kept only by explicit decision.
5. Run `hooks_tool.py final-qa` and any applicable filter check.
6. If the final topic-only count is below 500, run the low-count plausibility review. Diagnose; do not expand merely to cross the threshold.
7. Rerun the final selected strategy after cleanup so the delivered count matches the query.

Final QA cannot substitute for the critic: syntax hygiene does not review question translation, candidate-set integrity, MeSH breadth, or structural over-narrowing.

## 9. Audit and handoff

Read `references/audit-template.md` and `references/prisma-s-reporting.md`. Render the audit from structured JSON with `scripts/audit_markdown.py`.

The audit must include:

- the current retrieval-scope artifact and prior superseded versions;
- candidate-screening counts, decisions, evidence roles, and holdout independence;
- concept/MeSH/text-word evidence and saved record-content files reviewed;
- strategy variants, counts, samples, validation, and filter effects;
- concept-ablation recommendations and differential samples; for fragile topics, both strategy strands, known-item losses, unique records, workload estimates, and narrowing rationales;
- empirical fragility metrics, dimension scores, hard flags, and any reasoned human override; for no-seed builds, orthogonal pilot coverage, blinded screening, saturation history, and holdout freeze;
- every critic round and the revision-cycle ledger;
- final QA, caveats, and external peer-review attention points.

Append the audit and final artifacts to `run_manifest.json`. Run:

```text
python scripts/manifest_tool.py show --manifest run_manifest.json --validate --check-files --require-complete-loop
```

Do not finish until the combined gate passes. Report the audit and manifest paths. Label the delivered strategy as a draft pending human PRESS peer review.

## Stop criteria

Stop only when:

- all intake and scope gates are resolved;
- a versioned retrieval scope is locked;
- candidate screening is complete or explicitly not applicable;
- every essential block has required MeSH and count evidence or a reasoned waiver;
- held-out/seed/heuristic validation is correctly labelled and all in-scope misses are resolved;
- the latest critic round passes and all required re-probes are recorded;
- final QA and low-count/filter checks pass where applicable;
- the audit and manifest exist and the complete-loop gate passes;
- remaining limitations and the need for external human PRESS review are explicit.
