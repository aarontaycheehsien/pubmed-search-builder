#!/usr/bin/env python3
"""Phase 2: drive the skill to generate a strategy, then score it.

One generation run for one fixture:
  1. Render the review question + protocol (gold PMIDs are NOT included, to
     avoid leakage) into a prompt that front-loads every gate ("approach A").
  2. Drive the deployed skill headlessly via drivers/codex.py.
  3. Harvest the strategy the skill saved (``final_strategy.txt`` in the run
     dir) and score it against the held-back gold set with the Phase 1 engine.

Usage:
  python evals/generate.py datasets/clef-tar-2018/CD011926.json
  python evals/generate.py <fixture.json> --effort medium --timeout 1800 --model gpt-5.5

A full build is an agentic run (minutes, real tokens). Run it in the background
if your shell caps command time. Re-scoring the harvested strategy afterward is
free (run_eval.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))

import run_eval  # noqa: E402
from drivers import codex  # noqa: E402

DEFAULT_TOOL = SKILL_DIR / "scripts" / "pubmed_tool.py"
DATASETS = HERE / "datasets"


def resolve_fixture(arg: str) -> Path:
    """Resolve a fixture argument to a path. Accepts a full/relative path OR a
    bare topic id (e.g. ``CD011431``), which is matched against
    ``datasets/**/<id>.json``."""
    p = Path(arg)
    if p.exists():
        return p.resolve()
    alt = (HERE / arg).resolve()
    if alt.exists():
        return alt
    stem = arg[:-5] if arg.endswith(".json") else arg
    matches = sorted(DATASETS.glob(f"**/{stem}.json"))
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        raise SystemExit(f"topic '{stem}' matches multiple fixtures:\n  " + "\n  ".join(str(m) for m in matches))
    available = sorted(f.stem for f in DATASETS.glob("**/*.json") if "." not in f.stem)
    raise SystemExit(f"fixture/topic not found: {arg}\navailable topics: {', '.join(available) or '(none)'}")


def build_prompt(fixture: dict, run_dir: Path) -> str:
    p = fixture.get("protocol", {})
    seeds = fixture.get("seed_pmids_given_to_skill") or []
    run_posix = run_dir.resolve().as_posix()
    seed_line = (
        f"Seed PMIDs: {', '.join(str(s) for s in seeds)}."
        if seeds
        else f"Seed PMIDs: {p.get('seeds', 'none — proceed under the no-seed workflow')}."
    )
    # The no-seed heuristic recall check is a user-decision gate the skill offers at the Validation
    # stage on a no-seed build. Pre-resolve it here (default: skip) so an unattended generation run
    # neither stalls asking nor spends extra time/tokens on it; the harness measures true recall
    # against the held-back gold set independently. Override per fixture via protocol.no_seed_recall.
    no_seed_recall = p.get(
        "no_seed_recall",
        "decline — do NOT run the optional heuristic recall estimation and do NOT ask; record it with "
        "`manifest_tool.py state resolve-recall-offer declined`",
    )
    lines = [
        "Follow the instructions in ./SKILL.md to build a high-sensitivity PubMed search",
        "strategy for an evidence synthesis, using the bundled scripts in ./scripts as it",
        "directs. Work fully autonomously and DO NOT ask me any questions: this message is",
        "the complete protocol and pre-resolves every decision gate in the skill (seed gate,",
        "framework, concept gate, optional blocks, methodological filter, limits, the no-seed",
        "recall check, and final cleanup). Wherever SKILL.md says it may ask the user, treat the",
        "protocol below as the user/protocol decision and proceed to completion.",
        "",
        "REVIEW QUESTION (plain language):",
        f"  {fixture['question']}",
        "",
        "PROTOCOL (resolves all gates — do not stop to ask):",
        f"  - {seed_line}",
        f"  - No-seed heuristic recall check (applies only on a no-seed build): {no_seed_recall}",
        f"  - Framework: {p.get('framework', 'choose the appropriate framework yourself')}",
        f"  - Essential concepts: {p.get('essential_concepts', 'identify the essential concepts yourself; prefer fewer AND blocks')}",
        f"  - Optional blocks: {p.get('optional_blocks', 'decline materially-optional secondary AND blocks')}",
        f"  - Methodological filter: {p.get('methodological_filter', 'none')}",
        f"  - Limits: {p.get('limits', 'none')}",
        f"  - Final cleanup: {p.get('final_cleanup', 'remove duplicates and zero-hit phrases automatically; keep all recall-bearing terms')}",
        "",
        "OUTPUT (required):",
        f"  - Save the FINAL topic-only PubMed strategy as UTF-8 to this exact path:",
        f"      {run_posix}/final_strategy.txt",
        "    Write ONLY the Boolean query text in that file (no commentary, no line numbers).",
        f"  - If you can, also save your concept blocks as a JSON list of objects with",
        f'      "label" and "query" keys to: {run_posix}/final_blocks.json',
        f"  - Write any audit Markdown and run_manifest.json into: {run_posix}",
        "",
        "When finished, reply with the final PubMed result count and confirm the path you",
        "saved final_strategy.txt to. You have everything you need; proceed now without asking.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 skill-generation eval (one run).")
    parser.add_argument("fixture", help="Fixture JSON path OR a bare topic id (e.g. CD011431).")
    parser.add_argument("--run-dir", help="Run directory (default: results/<id>/run-<UTC timestamp>).")
    parser.add_argument("--model", default=None, help="Model override (default: codex config).")
    parser.add_argument("--effort", default="medium", help="model_reasoning_effort (default: medium).")
    parser.add_argument("--timeout", type=int, default=1800, help="Driver timeout seconds (default: 1800).")
    parser.add_argument("--pubmed-tool", default=str(DEFAULT_TOOL))
    args = parser.parse_args(argv)

    fixture_path = resolve_fixture(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.run_dir) if args.run_dir else HERE / "results" / fixture["id"] / f"run-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(fixture, run_dir)
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"[generate] fixture={fixture['id']} run_dir={run_dir}")
    print(f"[generate] driving skill headlessly (effort={args.effort}, timeout={args.timeout}s)...")

    result = codex.run_skill(
        prompt,
        skill_dir=SKILL_DIR,
        run_dir=run_dir,
        model=args.model,
        reasoning_effort=args.effort,
        timeout=args.timeout,
    )
    if result.get("attempts", 1) > 1:
        print(f"[generate] relaunched after transient sandbox failure (attempts={result['attempts']})")
    print(f"[generate] codex exit={result['returncode']}  last_message:\n{result['last_message'][:600]}")
    if result["stderr"].strip():
        print(f"[generate] stderr (tail): {result['stderr'][-400:]}")

    strategy_file = run_dir / "final_strategy.txt"
    if not strategy_file.exists() or not strategy_file.read_text(encoding="utf-8").strip():
        print(
            "\n[generate] FAILED: the skill did not write a non-empty final_strategy.txt.\n"
            "This usually means it stalled at a gate (read last_message above) or saved\n"
            f"elsewhere. Inspect {run_dir} and {run_dir / 'events.jsonl'}."
        )
        return 2

    blocks_file = run_dir / "final_blocks.json"
    blocks_override = str(blocks_file) if blocks_file.exists() else None

    card = run_eval.score(
        fixture_path,
        Path(args.pubmed_tool),
        strategy_override=str(strategy_file),
        blocks_override=blocks_override,
    )
    card["generated"] = True
    card["model"] = args.model
    card["effort"] = args.effort
    card["run_dir"] = str(run_dir)
    (run_dir / "scorecard.json").write_text(json.dumps(card, indent=2), encoding="utf-8")

    print("\n" + run_eval.render(card))
    print(f"\nscorecard JSON: {run_dir / 'scorecard.json'}")
    print(f"generated strategy: {strategy_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
