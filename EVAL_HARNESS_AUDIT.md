# Eval harness audit

Audit of `evals/` (score-only `run_eval.py`, suite `run_suite.py`, Phase 2 `generate.py`,
`drivers/codex.py`) before expensive benchmark runs. Scope: correctness only. No redesign, and no
fixture or gold-label changes. No fixture data errors were found, so none were edited.

## Method

- Read the scoring, aggregation, generation, and driver code paths end to end.
- Checked every bundled fixture: no duplicate gold PMIDs, no development PMIDs that are also
  evaluation gold, and no gold PMID in any `review_protocol` (the part the skill sees).
- Inspected a live packaged agent workspace: the prompt and every file except the transcript
  contain no gold PMID or fixture id.
- Ran `tests/test_eval_harness.py` and `tests/test_run_suite.py` (43 passed before changes), then the
  full suite.
- Ran full generated end-to-end evaluations (see below).
- Every fix has a regression test that fails against the pre-audit code and passes after.

## Bugs found and fixed

| # | Area | Defect | Consequence | Fix | Regression test |
|---|---|---|---|---|---|
| 1 | Gold leakage (`run_eval.score`) | PMIDs the fixture hands the skill (`development_pmids_given_to_skill`, `seed_pmids_given_to_skill`, `review_protocol.seeds.records`) counted as *never reviewed* unless the run's ledger also marked them reviewed. | "Never-reviewed" recall inflated by records the skill was given. `make_fixture.py --development-pmids` makes such fixtures by design. | Given PMIDs are always part of the seen set. | `test_pmids_given_to_the_skill_never_count_as_unseen` |
| 2 | Stale results (`generate.py`) | A reused `--run-dir` was merged into with `copytree(dirs_exist_ok=True)`. | A leftover `final_strategy.txt` / `scorecard.json` from an earlier run could be scored or reported as this run's result. | Refuse a non-empty run directory. | `test_a_reused_run_dir_is_refused_so_stale_artifacts_are_not_scored` |
| 3 | Critic before/after (`first_critic_strategy`) | The "before" strategy was whatever file sat at the critic's recorded path at scoring time. | A strategy revised in place after round 1 was scored as "before", so the ablation compared the final strategy with itself or with an intermediate version. | Require the file to match the strategy hash frozen in the critic's evidence bundle; otherwise the ablation is reported unavailable. | `test_first_critic_strategy_rejects_a_snapshot_revised_after_the_critic` |
| 4 | Critic before/after + gold leakage (`generate.py`) | Critic and candidate-ledger references were resolved against the copied run directory. The agent records absolute paths into the temporary workspace, which is deleted by then. | The ablation was silently "unavailable". The seen/mined sets fell back to a filename glob, which could pick a non-authoritative ledger (leaking reviewed gold into "never reviewed") or raise on two same-scope ledgers. | Resolve both against the live agent workspace before it is deleted, then rebase onto the run directory. | `test_ablation_survives_absolute_paths_into_the_deleted_agent_workspace`, `test_seen_pmids_come_from_the_manifest_ledger_even_when_its_path_is_absolute` |
| 5 | Critic before/after | `unseen_recall_delta` used `or 0` on each side. | When no gold went unreviewed (both sides undefined), the delta read `0.0` ("critic had no effect") instead of undefined. | Delta is `null` unless both sides are defined. | `test_ablation_delta_is_undefined_when_no_gold_went_unreviewed` |
| 6 | Incomplete runs accepted (`run_suite.resolve_strategy`) | `--generated-root` accepted any non-empty `final_strategy.txt`. `generate.py` keeps the artifacts of runs that fail Codex or the completion gate. | A failed or incomplete build could enter the table as a `generated` row. | Require a sibling `completion_gate.json` with `ok: true` and `returncode: 0`; otherwise the topic fails with a reason. | `test_a_generated_run_that_failed_the_completion_gate_is_not_scored` |
| 7 | Aggregation (`run_suite.summarize`, `compare`) | A topic where no gold PMID resolved in PubMed (recall undefined) was averaged in as 0% and counted in `<80%`. `compare` reported it as a regression or improvement. | One failed gold lookup could pull a source mean down and trigger a false regression. | Such topics are excluded from the means and listed as `undefined_recall_topics`, and they are not compared. | `test_undefined_recall_is_not_averaged_in_as_zero`, `test_undefined_recall_is_not_compared` |
| 8 | Incomplete runs (`drivers/codex.py`) | `subprocess.TimeoutExpired` escaped `run_skill`. **Hit in the first E2E run.** | `generate.py` crashed with a traceback, no artifacts were copied, and no failure record was written. | A timeout returns a failed result (`returncode 124`, `timed_out: true`). It is never retried; artifacts are kept and nothing is scored (exit 2). | `test_a_driver_timeout_is_a_failed_run_not_a_crash` |
| 9 | Incomplete runs (`generate.py`) | The agent workspace root came from `tempfile.TemporaryDirectory`. On Windows with Python 3.13+, that directory gets an owner-only ACL. The Codex sandbox runs commands as a separate sandbox user, so every file the agent creates is unreadable to the harness. **Hit in both earlier E2E attempts.** | The completion gate cannot read `run_manifest.json` and `copytree` raises, so no generated run can be scored or kept. The workspace cannot be cleaned up either. | Create the root with a plain `mkdir` under the system temp dir (inherits the parent ACL) and remove it afterwards. Verified live under the user's elevated Codex sandbox. | `test_agent_workspace_grants_the_harness_user_access` (Windows) |

Changed test expectation: `test_auto_prefers_a_generated_strategy` now writes a passing
`completion_gate.json` next to the generated strategy (fix 6).

## Checked and found correct

- **Denominators:** recall is over gold that resolves in PubMed; unreachable gold is excluded and
  reported. Duplicate gold PMIDs cannot inflate it (both reachability and `recall` de-duplicate).
  Per-block recall uses the same reachable denominator. The NNR proxy is total hits ÷ gold retrieved.
- **Scored strategy identity:** each scorecard embeds `strategy_query` and `strategy_sha256`.
  Suite rows never average across strategy sources, and regressions compare only same-source rows.
- **Caching:** NCBI cache keys include the full query parameters, so a changed strategy cannot reuse
  another's counts. The cache is per topic, and query results expire after 24 h. `--no-cache` forces
  live data.
- **Zero recall:** flagged in `sanity`, not persisted by `run_eval.py` without `--allow-zero-recall`,
  and `generate.py` exits 4. The suite keeps zero-recall rows in its means (deliberately
  conservative) and lists them.
- **Isolation:** the packaged runtime excludes `evals/`, `tests/`, fixtures, and prior results, and
  the run directory name is opaque.

## Not fixed (not demonstrated in this audit; worth knowing)

- **Scored file vs gated strategy.** The gate checks `final_strategy.txt` only when that file is
  the recorded input to the final search. In the E2E run it was, and the gate caught a
  post-search edit (`input artifact hash no longer matches: final_strategy.txt`). If an agent
  searches a different file (for example `strategy_v3.txt`) and writes `final_strategy.txt`
  separately, nothing checks that they have the same content. Suggested fix: compare
  `final_strategy.txt` with the text of the last final-topic-search input before scoring.
- **Transient-failure relaunch reuses the dirty workspace.** A relaunched attempt starts with the
  partial artifacts of the failed one.
- **Filesystem isolation depends on the Codex sandbox.** The transcript shows the agent can
  traverse outside the skill directory (`..\..\..\..\..\scripts`). Gold is safe only because the
  repository path is never disclosed.
- **`--runs N` is not variance.** With the cache on, repeats return identical responses.

## Environment notes

- The user's `~/.codex/config.toml` sets `[windows] sandbox = "elevated"` (Codex CLI 0.157.1; the
  driver was verified on 0.130). That combination exposed fix 9. With the fix in place the harness
  works under that config, and no Codex configuration was changed.
- Workspaces left by the two pre-fix attempts under `%TEMP%\pubmed-skill-eval-*` carry
  sandbox-only ACLs. The harness user cannot delete them without taking ownership (administrator).
- `scripts/isolated_runner.py` (the skill's independent-critic launcher) also uses `mkdtemp`. It
  runs inside the agent's sandbox as the sandbox user, so the same mismatch does not arise there. It
  is noted here but was not changed.

## End-to-end runs (CD011926, Codex, effort medium)

Run output was kept in the session scratchpad, not the repository.

| Attempt | Harness | Outcome |
|---|---|---|
| 1 | pre-fix | Codex hit the 3600 s timeout while still in candidate discovery. `TimeoutExpired` escaped, then cleanup failed on sandbox-owned files (`PermissionError`). No artifacts, no failure record (fixes 8, 9). |
| 2 | fixes 1–8 | Stopped early: files the agent created were still unreadable, which pointed to the owner-only temp root (fix 9). A `windows.sandbox=unelevated` override did not help. |
| 3 | all fixes, user's normal Codex config, 3 h timeout | Codex exited 0 after ~50 min. All artifacts were readable and copied. The completion gate ran and **rejected** the build (exit 3, nothing scored): no agreement check, no PRESS critic round (the skill's nested independent critic runner stalled and Claude Code auth failed), validation not bound to the final strategy, and the post-search edit of `final_strategy.txt` noted above. The incomplete run was correctly not accepted. |

Leakage checks on attempt 3:

- 160 agent commands scanned; none referenced the repository, `evals/`, fixtures, or qrels.
- The 4 gold PMIDs the agent typed had all first appeared in its own PubMed results.
- The manifest contains absolute references into the (deleted) temporary workspace, which is the
  premise of fix 4.

Scoring stage exercised on the attempt-3 strategy with the fixed code. This is **not a valid
measurement**, because the gate failed.

- Recall 96.6% (28/29 reachable) at 2,239 hits.
- The agent's own candidate screening had reviewed **27 of the 29** gold records, so
  never-reviewed recall is 1/2.
- The headline recall of a generated build can be almost entirely on records the build saw. Read
  `unseen_evaluation` first.

No critic round was recorded, so the before/after ablation could not be exercised live. It is
covered by fixes 3–5 and their tests.

**Before benchmarking:** the harness itself is now sound on this machine. The limiting factor is the
skill's nested independent-critic launch inside the Codex sandbox. Until that works, generated builds
will fail the gate. Budget more than 60 min per topic (`--timeout`); CD011926 took about 50 min on this attempt and over 60 min on the first.
