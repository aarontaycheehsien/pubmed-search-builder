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
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILL_DIR))

import run_eval  # noqa: E402
from drivers import codex  # noqa: E402
from tools import package_skill  # noqa: E402

DEFAULT_TOOL = SKILL_DIR / "scripts" / "pubmed_tool.py"
DATASETS = HERE / "datasets"


def isolated_run_workspace(source: Path, root: Path) -> tuple[Path, Path]:
    """Package only runtime skill files and return (skill_dir, opaque_run_dir).

    Evaluation fixtures, repository metadata, tests, prior results, and gold PMIDs are deliberately
    absent from the agent-readable workspace. The opaque run id also prevents source-review or
    fixture identifiers from leaking through the required output path.
    """
    skill_dir = root / package_skill.SKILL_NAME
    package_skill.package_skill(source, skill_dir)
    run_dir = skill_dir / ".eval-output" / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    return skill_dir, run_dir


def completion_gate(skill_dir: Path, run_dir: Path) -> tuple[bool, dict]:
    """Run the packaged skill's full completion gate before any generated query is scored."""
    manifest = run_dir / "run_manifest.json"
    if not manifest.is_file():
        return False, {"ok": False, "issues": ["run_manifest.json was not produced"]}
    cmd = [
        sys.executable,
        str(skill_dir / "scripts" / "manifest_tool.py"),
        "show",
        "--manifest",
        str(manifest),
        "--validate",
        "--check-files",
        "--require-complete-loop",
    ]
    proc = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, encoding="utf-8")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "issues": ["completion gate did not emit valid JSON"],
            "stdout": proc.stdout[-1000:],
            "stderr": proc.stderr[-1000:],
        }
    payload["returncode"] = proc.returncode
    (run_dir / "completion_gate.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return proc.returncode == 0 and payload.get("ok") is True, payload


def candidate_evidence_pmids(run_dir: Path) -> tuple[set[str], set[str]]:
    """Return (reviewed, mined) PMIDs from the generated candidate ledger, if present."""
    candidates = sorted(run_dir.rglob("candidate_ledger*.json"))
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            continue
        reviewed: set[str] = set()
        mined: set[str] = set()
        for item in records:
            if not isinstance(item, dict):
                continue
            pmid = str(item.get("pmid") or "").strip()
            if not pmid:
                continue
            if item.get("title_abstract_reviewed") is True:
                reviewed.add(pmid)
            if item.get("decision") == "include" and item.get("use") in {"discovery", "both"}:
                mined.add(pmid)
        return reviewed, mined
    return set(), set()


def first_critic_strategy(run_dir: Path) -> Path | None:
    """Resolve the strategy snapshot reviewed in critic round 1 for before/after scoring."""
    manifest = run_dir / "run_manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        rounds = data["build_state"]["critic_rounds"]
        artifact_value = str(rounds[0]["artifact"])
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    artifact = Path(artifact_value)
    if not artifact.is_file():
        candidates = list(run_dir.rglob(artifact.name))
        artifact = candidates[0] if candidates else artifact
    try:
        critic = json.loads(artifact.read_text(encoding="utf-8-sig"))
        strategy_value = str(critic["strategy_file"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    strategy = Path(strategy_value)
    if not strategy.is_file():
        candidates = list(run_dir.rglob(strategy.name))
        strategy = candidates[0] if candidates else strategy
    return strategy if strategy.is_file() and strategy.read_text(encoding="utf-8").strip() else None


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
    seeds = fixture.get("development_pmids_given_to_skill") or fixture.get("seed_pmids_given_to_skill") or []
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
        "  - Run the manifest complete-loop gate and do not finish unless it passes.",
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
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pubmed-skill-eval-") as temp_root:
        isolated_skill, agent_run_dir = isolated_run_workspace(SKILL_DIR, Path(temp_root))
        prompt = build_prompt(fixture, agent_run_dir)
        (agent_run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"[generate] fixture={fixture['id']} run_dir={run_dir}")
        print(f"[generate] driving isolated skill (effort={args.effort}, timeout={args.timeout}s)...")

        result = codex.run_skill(
            prompt,
            skill_dir=isolated_skill,
            run_dir=agent_run_dir,
            model=args.model,
            reasoning_effort=args.effort,
            timeout=args.timeout,
        )
        if result.get("attempts", 1) > 1:
            print(f"[generate] relaunched after transient sandbox failure (attempts={result['attempts']})")
        print(f"[generate] codex exit={result['returncode']}  last_message:\n{result['last_message'][:600]}")
        if result["stderr"].strip():
            print(f"[generate] stderr (tail): {result['stderr'][-400:]}")

        gate_ok = False
        gate_payload: dict = {"ok": False, "issues": ["Codex process failed"]}
        if result["returncode"] == 0:
            gate_ok, gate_payload = completion_gate(isolated_skill, agent_run_dir)
        shutil.copytree(agent_run_dir, run_dir, dirs_exist_ok=True)

    if result["returncode"] != 0:
        print("\n[generate] FAILED: Codex returned a non-zero exit code; generated files are not scored.")
        return 2
    if not gate_ok:
        print("\n[generate] FAILED: generated artifacts did not pass the complete-loop gate.")
        for issue in gate_payload.get("issues", [])[:20]:
            print(f"  - {issue}")
        return 3

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
    reviewed_pmids, mined_pmids = candidate_evidence_pmids(run_dir)

    card = run_eval.score(
        fixture_path,
        Path(args.pubmed_tool),
        strategy_override=str(strategy_file),
        blocks_override=blocks_override,
        seen_pmids=reviewed_pmids,
        mined_pmids=mined_pmids,
    )
    card["generated"] = True
    card["model"] = args.model
    card["effort"] = args.effort
    card["run_dir"] = str(run_dir)
    card["completion_gate"] = gate_payload
    pre_critic = first_critic_strategy(run_dir)
    if pre_critic and pre_critic.resolve() != strategy_file.resolve():
        before = run_eval.score(
            fixture_path,
            Path(args.pubmed_tool),
            strategy_override=str(pre_critic),
            seen_pmids=reviewed_pmids,
            mined_pmids=mined_pmids,
        )
        before_unseen = before.get("unseen_evaluation", {})
        after_unseen = card.get("unseen_evaluation", {})
        card["critic_ablation"] = {
            "available": True,
            "before_strategy": str(pre_critic),
            "after_strategy": str(strategy_file),
            "before_unseen_recall": before_unseen.get("recall"),
            "after_unseen_recall": after_unseen.get("recall"),
            "unseen_recall_delta": round(float(after_unseen.get("recall") or 0) - float(before_unseen.get("recall") or 0), 4),
            "before_total_hits": before.get("strategy", {}).get("total_hits"),
            "after_total_hits": card.get("strategy", {}).get("total_hits"),
        }
    else:
        card["critic_ablation"] = {
            "available": False,
            "reason": "critic round 1 strategy snapshot was missing or identical to the final strategy",
        }
    (run_dir / "scorecard.json").write_text(json.dumps(card, indent=2), encoding="utf-8")

    print("\n" + run_eval.render(card))
    print(f"\nscorecard JSON: {run_dir / 'scorecard.json'}")
    print(f"generated strategy: {strategy_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
