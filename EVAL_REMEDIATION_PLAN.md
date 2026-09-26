# Eval remediation plan

Follow-up to [EVAL_HARNESS_AUDIT.md](EVAL_HARNESS_AUDIT.md) (harness fixes committed in `92925cb`).
Goal: one `evals/generate.py` run passes the complete-loop gate and yields a scorecard with a live
critic ablation and a trustworthy never-reviewed recall. After that, benchmarks are worth running.

Evidence comes from the E2E attempt-3 run (CD011926), whose gate rejected the build, plus probes
run after the audit.

## Why the E2E build failed the gate

| Symptom in the gate / transcript | Root cause (verified) | Owner |
|---|---|---|
| No agreement check; no PRESS critic round | The nested isolated child (`isolated_runner.py` → `codex exec`) **hangs whenever it is launched from inside a Codex sandbox**. Launched from a normal shell, it answers in 9 s. Nested, it hangs with both the elevated and unelevated Windows sandbox. | skill script |
| Hung children outlive `--timeout 180`; the agent spent ~20 min polling PIDs | `run_isolated` uses `subprocess.run(timeout=…)`. On Windows it kills only `codex.cmd`, and `communicate()` then blocks on pipes held by the `node`/`codex.exe` grandchildren. The nested probe with `timeout=120` never returned. | skill script |
| Claude runner fallback failed | `401 OAuth access token has expired` in the Claude CLI. | user action |
| "MeSH sweeps stalled" | They never ran. `mesh_tool.py` rejected multi-word terms that PowerShell split (`unrecognized arguments: sepsis septicemia bloodstream infection`), and `--variants-file` exists but was not used. | skill guidance |
| `kind=mesh output is not a recognized mesh_tool artifact` (seq 8, 9) | The agent recorded `pubmed_tool.py term-diff` outputs as `--kind mesh`. The mismatch surfaces only at the final gate. | skill script |
| Hash drift on `final_strategy.txt`, `final_qa.json`, `audit_scaffold.json` | Files were edited after the entries that bound them. The gate catches it, but only at the end. | skill script/guidance |
| Audit render failed: `limits_filters_validated_filters_used requires an explicit decision` | The protocol already rejects all limits, but the audit scaffold does not prefill that decision from the locked protocol. | skill script |

## Phase 0: unblock the independent child (blocks everything else)

**Status.** Phase 0 is done: 0.1–0.4. For 0.3, the decision was to copy the ChatGPT login.

- **Diagnosis (0.2).** Inside a Codex sandbox, commands run as `codexsandboxonline`. That user's
  profile has no Codex login (`codex login status` → `Not logged in`), so a nested `codex exec`
  waits with no output. Setting `CODEX_HOME` to the host `.codex` finds the login, but the child
  then needs write access there and fails with `failed to initialize in-process app-server client:
  Access is denied`. Network access and reading `auth.json` both work. The host login is ChatGPT
  OAuth with no API key.
- **Preflight (0.4).** Run nested, it now fails in 0.2 s with this reason instead of hanging.
- **Fix (0.3).** Once the login was provisioned, a second blocker appeared: the sandbox user has no
  usable root-certificate store, so Codex's TLS failed (`workspace routing discovery failed`).
  When `codex login status` fails, the `codex-cli` runner now copies `auth.json` into a private,
  owner-only per-child home, exports the machine's roots to a CA bundle there, and deletes the
  copied credentials before the home.
- **Verified live, nested in the eval's sandbox configuration.** Preflight passes in 7.3 s and a
  critic-shaped call returns in 8 s. Failing and successful children leave no token copy behind.
- **Leftover.** One token copy from a pre-fix diagnostic run
  (`%TEMP%\pubmed-codex-home-28l3isfo`) is owned by an expired sandbox session and needs an
  administrator to delete it.
- **Not covered.** The `claude-code-cli` runner is not provisioned for the sandbox user, and the
  full E2E rerun belongs to Phase 3.

**0.1 Kill the whole child process tree on timeout** (`scripts/isolated_runner.py`)
- Replace `subprocess.run` with `Popen` plus `communicate(timeout=…)`.
  - Windows: start with `CREATE_NEW_PROCESS_GROUP` and kill with `taskkill /T /F /PID`, or a Job
    object.
  - POSIX: `start_new_session=True` and `os.killpg`.
- After the kill, drain the pipes with a short bounded wait. Raise `IsolatedRunnerError` with
  whatever stderr was captured.
- Test (`tests/test_isolated_runner.py`): a fake runner spawns a grandchild that sleeps while
  holding stdout. Assert that `run_isolated` returns within timeout + a grace period and that the
  grandchild is gone.

**0.2 Diagnose the nested hang** (needs 0.1 so the probe returns with stderr)
- Rerun the nested probe from the audit (`codex exec` → `python` → `isolated_runner` →
  `codex exec`) and capture the inner child's stderr and event stream.
- Hypotheses, in order to test:
  1. The sandbox user cannot read `~/.codex/auth.json` (try `CODEX_HOME` pointing at a readable
     copy).
  2. The grandchild has no network, because outer `network_access=true` may not propagate.
  3. `--ignore-user-config` drops settings the inner sandbox needs.
  4. The inner codex blocks on console/stdin.
- Repeat the probe with `--runner claude-code-cli` once the Claude CLI is re-authenticated.
- Record the finding in `references/` (runner troubleshooting).

**0.3 Fix according to 0.2.** If neither runner can work nested, choose between:
- **(a) Harness-brokered child.** The agent writes the frozen request bundle and stops. The harness,
  outside the sandbox, runs `isolated_runner` and places the validated response back, then resumes
  the agent. This needs a resume step in `generate.py` and a "pending isolated request" state in
  the manifest. It is a real design change; decide before building.
- **(b) Outer sandbox without an inner one.** Run the outer agent in a mode that permits nested
  CLIs. This weakens isolation, so the fixture/gold leak scan (2.3) would then be mandatory.

**0.4 Preflight at intake.** Add `isolated_runner.py preflight --runner auto --timeout 60`, which
runs a trivial schema-constrained call. SKILL.md should require it at Intake and record it in the
manifest. When it fails, stop within minutes with a clear gate issue instead of discovering the
problem 45 minutes in. `generate.py` can run the same preflight outside the sandbox before
launching.

## Phase 1: fail fast on agent recording errors (skill)

**Status.** Done: 1.1–1.4, each with a regression test that fails on the prior code.
- **1.1** `add` refuses `--kind mesh` for an output that isn't a `mesh_tool` artifact, and names
  `--kind sample` for `term-diff`.
- **1.2** The `add` receipt carries `binding_warnings`: the gate's own hash-binding findings, as soon
  as they arise.
- **1.3** `audit-scaffold` fills both required limits/filters notes from the locked protocol, or
  lists them as placeholders up front.
- **1.4** `mesh_tool` explains shell-split multi-word arguments. The PowerShell guidance warns
  against `Start-Process -ArgumentList` and points to `--variants-file`.

**1.1 Validate entry kinds at `manifest_tool.py add` time.** Reuse the gate's "recognized
mesh_tool artifact" check (`scripts/manifest_tool.py` ~L490) inside `cmd_add`, and refuse with a
hint (for example, `term-diff` output belongs under `--kind search` or `artifact`). Test: adding a
term-diff output as `--kind mesh` is rejected.

**1.2 Warn on hash drift when it happens.** When `add` records an entry, check whether any earlier
entry's bound inputs/outputs (for example `final_strategy.txt`) no longer match. Report them in
the command's JSON, and in `report`'s `next_actions`, so the agent re-runs the final
search/QA/audit chain immediately rather than at the gate.

**1.3 Prefill protocol-resolved audit decisions.** When the locked protocol rejects limits and
filters, the audit scaffold should fill `reporting_notes.limits_filters_validated_filters_used`
from the protocol, with provenance. Test in `tests/test_audit_scaffold.py`.

**1.4 MeSH argument guidance.**
- `references/mesh-and-pubmed-tools.md` and SKILL.md: pass multi-word variants through
  `--variants-file`.
- Do not background tool runs with PID files; use `--max-seconds`.
- In `mesh_tool.py`, on `unrecognized arguments`, append a hint pointing to `--variants-file`.

Doc edits must be co-edited with `tests/test_concept_analysis_docs.py`, which pins wording across
the docs.

## Phase 2: harness known gaps (evals)

**2.1 Bind the scored file to the gated strategy** (`evals/generate.py`). After the gate passes,
require `final_strategy.txt` (stripped) to equal the text of the last final-topic-search input,
using the same logic as the gate in `manifest_tool.py` ~L2720. On a mismatch, exit 3 with the
reason. Test with a fake run whose searched file differs from `final_strategy.txt`.

**2.2 Clean relaunch** (`evals/drivers/codex.py`). Snapshot the pre-launch file list (prompt,
protocol). Before a transient-failure relaunch, delete everything else, or give each attempt a
fresh agent run dir. Test: the attempt-1 artifacts are absent in attempt 2.

**2.3 Automated leakage scan** (`evals/generate.py`). Scan `events.jsonl` for:
- commands referencing the repository path, `evals/`, `datasets/`, the fixture id, or qrels;
- gold PMIDs typed in a command before they appeared in any tool output.

Record the result as `leakage_scan` in the scorecard, and fail (exit 5) on a hit. This automates
the manual check from the audit.

**2.4 Never-reviewed recall in the suite** (`evals/run_suite.py`). For `generated` rows, load
seen/mined PMIDs from the run's ledger (`generate.candidate_evidence_pmids`) and pass them to
`score`. Add `unseen_gold`/`unseen_recall` columns to the table and to RESULTS.md. The attempt-3
run shows why this matters: 27 of 29 gold records were reviewed, so the headline recall was mostly
on seen records.

**2.5 Suite ↔ generate layout.** `generate.py` writes `results/<id>/run-<UTC>/`, while
`--generated-root` expects `<root>/<id>/final_strategy.txt`. Let `resolve_strategy` pick the
latest run dir under `<root>/<id>/run-*` whose `completion_gate.json` passed, and record which run
was used in the row.

**2.6 `--runs N`.** Scoring a fixed strategy is deterministic, so `--runs N` measures nothing
beyond PubMed drift. Either reject `--runs > 1` without `--no-cache`, or remove it and document that
generation variance needs N `generate.py` runs (one per `--run-dir`).

**2.7 Timeout default.** Raise the `generate.py --timeout` default from 1800 s to 7200 s. CD011926
took about 50 min, and more than 60 min on another attempt. Record `elapsed_seconds` in the
scorecard.

## Phase 3: acceptance

1. Unit tests for every item above, the full suite green, and each new test failing on the
   pre-change code.
2. One `generate.py CD011926` run: gate passes, scorecard written, `critic_ablation.available` is
   true, `leakage_scan` is clean, `unseen_evaluation` is reported.
3. `run_suite.py --generated-root evals/results` picks that run and shows never-reviewed recall.
4. Update EVAL_HARNESS_AUDIT.md "Not fixed" and `evals/README.md` ("Still to build").

## Needs you (not code)

- Re-authenticate the Claude CLI (`claude` → `/login`); its token expired and it is the fallback
  runner.
- Decide 0.3 (a) vs (b) if 0.2 shows neither runner can work nested.
- Delete the locked leftovers `%TEMP%\pubmed-skill-eval-13n76dnj` and `-prjg4nci` from an
  administrator shell (`takeown /r` + `icacls /grant`), or leave them.
- Suggested order: 0.1 → 0.2 → 0.4 → 1.x → 2.1/2.3/2.4 → 0.3 as decided → Phase 3. Items 2.2, 2.5,
  2.6, and 2.7 are small and can go in any batch.
