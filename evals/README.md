# Evals

Measure whether a PubMed strategy actually achieves high **recall** against a
gold-standard relevant set. This is the recall benchmark for the skill.

## No command line: the GUI

Don't want to use a terminal? Double-click **`eval_gui.bat`** (opens with no
console window) or run `python evals/gui.py`. The window exposes every option:

- **Run Eval** tab — pick a topic, choose *Generate with skill (Phase 2)* or
  *Score baseline (Phase 1)*, set reasoning effort / timeout / model, and Run.
  Output streams live into the log; long builds run on a background thread so
  the window stays responsive. *Open results folder* opens the run artifacts.
  In **Score mode** a *Baseline strategy* panel lets you paste a strategy, load
  one from a file, or load the topic's current baseline; add an optional concept-
  blocks JSON for per-block diagnosis. Tick *Save as this topic's baseline* to
  persist it to the fixture (writes `<id>.strategy.txt` and sets `strategy_file`),
  so a topic without a baseline becomes scorable going forward. Leave the box
  empty to score the fixture's existing baseline.
- **Create Fixture** tab — enter a topic id + question, pick a gold source
  (PMIDs, DOIs file, PMIDs file, or a defining query), and create a fixture from
  any source (see "Bring your own topic" below). The new topic appears in the
  Run Eval dropdown automatically.

For a richer, dedicated fixture builder, double-click **`make_fixture_gui.bat`**
(or run `python evals/make_fixture_gui.py`). It adds editable **protocol** fields
(the gate-resolving instructions the skill follows in Phase 2, pre-filled with
sensible defaults) and a *Preview JSON* button to see the exact fixture before
writing. Tuning the protocol per topic is what gives good Phase 2 results, so
this is the recommended way to add a new topic.

Both GUIs just shell out to the same scripts below, so anything they do is
reproducible from the command line and vice versa.

## Phase 1: score-only (this directory)

Score-only mode takes an **already-written** strategy and scores it. It does
**not** run the skill / an LLM, so it is near-zero cost: ~3 cheap NCBI calls per
fixture and no tokens. All recall math is reused from
`../scripts/pubmed_tool.py` (`search` + `recall`) — `run_eval.py` only
orchestrates and formats.

### Run it

Both runners accept a fixture path **or a bare topic id** (matched against
`datasets/**/<id>.json`):

```bash
python evals/run_eval.py CD011926                       # by topic id
python evals/run_eval.py evals/datasets/clef-tar-2018/CD011926.json   # by path
python evals/run_eval.py CD011926 --output evals/results/CD011926.json
python evals/run_eval.py CD011926 --json               # machine-readable
python evals/run_suite.py --cached-only                 # aggregate cached scorecards only
```

Requires the same NCBI env as the rest of the skill (`.env`; check with
`python scripts/pubmed_tool.py doctor`).

Score-only mode needs a strategy to score, so it only works on fixtures that
carry a baseline `strategy_file` (currently `CD011926`). Fixtures without one
(`CD011431`, `CD010657`) are for Phase 2, where the skill builds the strategy.

### Benchmark topics (CLEF TAR 2018 Task 2)

| topic | gold | baseline strategy | review |
|---|---|---|---|
| `CD011926` | 29 | yes | molecular assays for neonatal sepsis diagnosis |
| `CD011431` | 26 | no (Phase 2) | rapid diagnostic tests for non-falciparum / P. vivax malaria |
| `CD010657` | 35 | no (Phase 2) | DMSA scan or ultrasound for vesicoureteral reflux in children |

### What it reports

- **recall (of reachable)** — share of gold PMIDs the strategy retrieves,
  measured over the gold PMIDs that actually exist in PubMed. Gold PMIDs not in
  PubMed (e.g. Embase-only records from the source review's multi-database
  search) are reported separately as *unreachable* and excluded from the
  denominator, so the search is not penalised for records it cannot reach.
- **NNR proxy** — strategy total hits ÷ gold retrieved. A workload proxy, **not
  true precision** (true precision needs a fully screened retrieved set).
- **per-block recall** — when `blocks_file` is given, which concept block leaks
  recall (the **bottleneck**), recomputed over the reachable denominator.
- **AND-interaction misses** — gold records retrieved by every block alone but
  lost by the full strategy (points at `NOT`, filters, or proximity, not a weak
  block).

### Caveat: one run is a smoke test

Scoring a fixed strategy is deterministic, so score-only mode is stable. But a
single fixture is a sanity check that the pipeline works and recall is in a sane
range — it is **not** a benchmark of the skill. Don't tune the skill off one
number.

## Fixtures

One JSON object per topic, with the strategy and (optional) concept blocks as
sibling files (kept as plain UTF-8 so they dodge the PowerShell quoting traps
documented in `references/mesh-and-pubmed-tools.md`):

```
datasets/<suite>/<id>.json            # metadata + gold answer key
datasets/<suite>/<id>.strategy.txt    # the strategy being scored
datasets/<suite>/<id>.blocks.json     # optional: [{label, query}, ...] for bottleneck diagnosis
```

Fixture schema:

```json
{
  "id": "CD011926",
  "suite": "clef-tar-2018",
  "question": "plain-language review question",
  "strategy_file": "CD011926.strategy.txt",
  "blocks_file": "CD011926.blocks.json",
  "gold_relevant_pmids": [9350892, 10878046, "..."],
  "source": "where the gold set came from"
}
```

`strategy_file`/`blocks_file` paths are resolved relative to the fixture file.

### Bring your own topic (any source, not just CLEF)

The harness is **source-agnostic** — a fixture is only a question + a gold set of
relevant PMIDs + a protocol. The gold set can come from a published review's
included studies, your own curated set, a list of DOIs, or a defining query.
`make_fixture.py` builds the fixture and resolves the gold set for you:

```bash
# from PMIDs you already have
python evals/make_fixture.py --id MYREVIEW --question "..." \
    --gold-pmids 12345678 23456789 34567890

# from a published review's DOIs (resolved to PMIDs via PubMed [AID])
python evals/make_fixture.py --id SR2024 --question-file q.txt \
    --gold-dois-file included_dois.txt --suite my-reviews

# from a defining query (its PubMed results become the gold set)
python evals/make_fixture.py --id PRIORSEARCH --question "..." \
    --gold-query-file prior_search.txt --gold-retmax 500
```

It writes `datasets/<suite>/<id>.json` with a **default protocol** — review and
tighten the `protocol` block for your topic, then run `python evals/generate.py
<id>`. It reports DOIs that don't resolve and gold PMIDs not in PubMed (the
latter are excluded from the recall denominator at score time). Custom fixtures
work with the same topic-id selection as the CLEF ones; only the `datasets/`
subfolder differs.

### Adding a fixture from CLEF TAR

The bundled fixture (`CD011926`) comes from the
[CLEF TAR 2018 Task 2](https://github.com/CLEF-TAR/tar/tree/master/2018-TAR/Task2/Testing)
dataset. Each topic ships a title and the finally-included studies; the gold set
is the **content-level** qrels (`qrel_content_task2`, relevance `1`):

```bash
# gold relevant PMIDs for a topic
curl -s ".../qrels/qrel_content_task2" | awk '$1=="<TOPIC>" && $4==1 {print $3}'
```

Pick a topic with ~15-45 included studies so recall is a meaningful fraction.
The published CLEF queries are Ovid syntax, so author a PubMed strategy for the
fixture (as done for `CD011926`) rather than pasting the Ovid query — translation
is a separate concern.

## Phase 2 (in progress)

Drive the **skill itself** to generate the strategy under test, then score it
with the Phase 1 engine. Approach: front-load a `protocol` in the prompt that
pre-resolves every gate (the skill's own "protocol already decides it" bypass),
so the agent runs unattended ("approach A" — scores search *construction*, not
interactive elicitation). The gold PMIDs are held back from the prompt to
prevent leakage.

### Headless driver (`drivers/codex.py`) — spike confirmed

`codex exec` runs the deployed skill non-interactively. Verified recipe
(codex-cli 0.130.0-alpha.5, gpt-5.5):

```bash
codex exec -C <skill_dir> -s workspace-write \
  -c approval_policy=never \
  -c sandbox_workspace_write.network_access=true \
  -c model_reasoning_effort=<effort> \
  --skip-git-repo-check --color never \
  -o <last_message_file> --json -        # prompt piped via stdin
```

Spike findings:
- **Prompt must go through stdin** (`-` arg). As a plain argument, `codex exec`
  blocks reading stdin for EOF in a non-interactive shell.
- **`sandbox_workspace_write.network_access=true` is required** — the default
  workspace-write sandbox blocks outbound sockets (WinError 10013), breaking
  every NCBI call. With it enabled, `pubmed_tool.py doctor` returns
  `checks.ok=true` from inside the sandbox.
- `approval_policy=never` keeps it unattended; `--skip-git-repo-check` because
  the skill dir is not a git repo; `-o` captures the final message; `--json`
  saves a JSONL transcript.

### Generate (`generate.py`) — built

Drives the skill to build a strategy, then scores it. Accepts a topic id or a
fixture path:

```bash
python evals/generate.py CD011926               # one full build + score
python evals/generate.py CD011431 --effort medium --timeout 1800
```

A full build is an agentic run (minutes, real tokens). Per run it writes
`results/<id>/run-<UTC>/` containing the prompt, JSONL transcript, the skill's
artifacts (strategy, blocks, audit, manifest), and `scorecard.json`. The gold
PMIDs are **not** in the prompt (no leakage). If your shell caps command time,
launch it in the background.

### Suite runner and cache

`run_suite.py` runs score-only fixtures in aggregate and stores completed
scorecards under `evals/.cache/scorecards/`, keyed by fixture, strategy, blocks,
and tool content. Use `--cached-only` for deterministic offline summaries that
never call NCBI; omit it to score cache misses with `run_eval.py`.

```bash
python evals/run_suite.py --topic CD011926
python evals/run_suite.py --cached-only --json
python evals/run_suite.py --refresh --output evals/results/suite.json
```

### Still to build

- `run_suite.py --runs N` variance summaries and saved regression diffs.
- A lower-level NCBI response cache for `run_eval.py` fetches, separate from
  scorecard caching.
- Retry logic around the driver (transient `windows sandbox: ... runner
  pipe-in` timeouts have been observed at the tail of a build).

Everything above feeds the strategy file into Phase 1's `score()` unchanged.
