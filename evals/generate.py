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
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILL_DIR))

import run_eval  # noqa: E402
from drivers import codex  # noqa: E402
from pubmed_search_builder.core.workspace import resolve_within  # noqa: E402
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
    selected_path: Path | None = None
    manifest_paths = [run_dir / "run_manifest.json"]
    manifest_paths.extend(path for path in run_dir.rglob("run_manifest.json") if path != manifest_paths[0])
    for manifest_path in manifest_paths:
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        state = manifest.get("build_state") if isinstance(manifest, dict) else None
        screening = state.get("candidate_screening") if isinstance(state, dict) else None
        artifact = screening.get("artifact") if isinstance(screening, dict) else None
        if artifact:
            # Anchored to the run tree: an artifact reference that only resolves outside
            # this run belongs to another build and must not supply its evidence roles.
            selected_path = resolve_within(run_dir, str(artifact))
            if selected_path is not None:
                break
    candidates = [selected_path] if selected_path is not None else sorted(run_dir.rglob("candidate_ledger*.json"))
    parsed_candidates: list[tuple[int, Path, dict]] = []
    for path in candidates:
        if path is None:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("artifact_type") == "candidate-ledger-template" or data.get("ledger_status") == "template":
            continue
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            continue
        parsed_candidates.append((int(data.get("scope_version") or 0), path, data))
    if not parsed_candidates:
        return set(), set()
    if selected_path is None:
        highest = max(item[0] for item in parsed_candidates)
        current = [item for item in parsed_candidates if item[0] == highest]
        if len(current) != 1:
            raise ValueError("Multiple current candidate ledgers are present; record the authoritative ledger in run_manifest.json")
        _scope, _path, data = current[0]
    else:
        _scope, _path, data = parsed_candidates[0]
    records = data["records"]
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


def first_critic_strategy(run_dir: Path) -> Path | None:
    """Resolve the strategy snapshot reviewed in critic round 1 for before/after scoring.

    Every reference is resolved inside ``run_dir``. A bare filename must not fall back to
    the process working directory: a leftover ``critic_round_1.json`` from an unrelated
    build would otherwise be scored as this run's pre-critic strategy.
    """
    manifest = run_dir / "run_manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        rounds = data["build_state"]["critic_rounds"]
        artifact_value = str(rounds[0]["artifact"])
    except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    artifact = resolve_within(run_dir, artifact_value)
    if artifact is None:
        return None
    try:
        critic = json.loads(artifact.read_text(encoding="utf-8-sig"))
        strategy_value = str(critic["strategy_file"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    strategy = resolve_within(run_dir, strategy_value)
    if strategy is None or not strategy.is_file():
        return None
    return strategy if strategy.read_text(encoding="utf-8").strip() else None


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


def build_legacy_prompt(fixture: dict, run_dir: Path) -> str:
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
        f"    Initialise the manifest with `--workspace {run_posix}` and run the build from",
        "    there; the tools refuse to create build state in the skill directory itself.",
        "  - Run the manifest complete-loop gate and do not finish unless it passes.",
        "",
        "When finished, reply with the final PubMed result count and confirm the path you",
        "saved final_strategy.txt to. You have everything you need; proceed now without asking.",
    ]
    return "\n".join(lines)


def fixture_protocol(fixture: dict) -> tuple[dict | None, dict | None]:
    """Return ``(review_protocol, legacy_protocol)`` with a visible legacy warning."""
    review_protocol = fixture.get("review_protocol")
    if review_protocol is not None:
        if not isinstance(review_protocol, dict):
            raise ValueError("fixture review_protocol must be a JSON object")
        return copy.deepcopy(review_protocol), None
    legacy = fixture.get("protocol")
    if legacy is not None:
        if not isinstance(legacy, dict):
            raise ValueError("fixture protocol must be a JSON object")
        warnings.warn(
            "fixture field 'protocol' is deprecated; migrate it to the structured "
            "'review_protocol' DSL",
            FutureWarning,
            stacklevel=2,
        )
        return None, copy.deepcopy(legacy)
    raise ValueError("fixture requires review_protocol (or deprecated protocol)")


def build_prompt(fixture: dict, run_dir: Path) -> str:
    review_protocol, legacy = fixture_protocol(fixture)
    if review_protocol is None:
        legacy_fixture = dict(fixture)
        legacy_fixture["protocol"] = legacy or {}
        return build_legacy_prompt(legacy_fixture, run_dir)

    seeds = fixture.get("development_pmids_given_to_skill") or fixture.get("seed_pmids_given_to_skill") or []
    protocol_seed_records = review_protocol.setdefault("seeds", {}).setdefault("records", [])
    if seeds and not protocol_seed_records:
        protocol_seed_records.extend(
            {
                "pmid": str(seed),
                "role": "discovery-candidate",
                "rationale": "Development PMID supplied by the evaluation fixture.",
            }
            for seed in seeds
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    protocol_file = run_dir / "review_protocol.json"
    protocol_file.write_text(
        json.dumps(review_protocol, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    run_posix = run_dir.resolve().as_posix()
    protocol_posix = protocol_file.resolve().as_posix()
    compile_dir = (run_dir / "protocol_v1").resolve().as_posix()
    compile_receipt = (run_dir / "protocol_v1" / "protocol_compile_v1.json").resolve().as_posix()
    lines = [
        "Follow the instructions in ./SKILL.md to build a high-sensitivity PubMed search",
        "strategy for an evidence synthesis, using the bundled scripts in ./scripts.",
        "Work fully autonomously and DO NOT ask me questions: the locked structured",
        "review protocol is the complete decision source for this evaluation.",
        "",
        "REVIEW PROTOCOL DSL (authoritative):",
        f"  {protocol_posix}",
        "",
        "Before any candidate-record, MeSH, or PubMed work:",
        "  1. Validate the protocol in lock mode with scripts/protocol_tool.py.",
        f"  2. Compile it to {compile_dir}",
        f"     and save the compile receipt to {compile_receipt}",
        "  3. Use compiled files as derived workflow inputs; do not edit them to",
        "     change protocol scope.",
        "  4. Treat priorities.recall.policy as resolving the no-seed recall-check",
        "     gate and record that resolution in the manifest when applicable.",
        "",
        "OUTPUT (required):",
        "  - Save the FINAL topic-only PubMed strategy as UTF-8 to this exact path:",
        f"      {run_posix}/final_strategy.txt",
        "    Write ONLY the Boolean query text in that file (no commentary, no line numbers).",
        "  - If you can, also save concept blocks as a JSON list of objects with",
        f'      "label" and "query" keys to: {run_posix}/final_blocks.json',
        f"  - Write any audit Markdown and run_manifest.json into: {run_posix}",
        f"    Initialise the manifest with `--workspace {run_posix}` and run the build from",
        "    there; the tools refuse to create build state in the skill directory itself.",
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
    parser.add_argument(
        "--allow-zero-recall",
        action="store_true",
        help="Treat a scorecard that retrieved no gold PMIDs as a result rather than a harness fault.",
    )
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
            "before_unseen_recall": before_unseen.get("recall_percent"),
            "after_unseen_recall": after_unseen.get("recall_percent"),
            "unseen_recall_delta": round(float(after_unseen.get("recall_percent") or 0) - float(before_unseen.get("recall_percent") or 0), 4),
            "before_total_hits": before.get("strategy_total_hits"),
            "after_total_hits": card.get("strategy_total_hits"),
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

    if card["sanity"]["zero_recall"] and not args.allow_zero_recall:
        # The scorecard is still written -- it is this run's record and the fastest way to
        # diagnose the cause -- but the run does not report success on a number this shape.
        print(
            "\n[generate] SUSPECT: the generated strategy retrieved none of the gold set.\n"
            "Inspect the scored query in scorecard.json (strategy_query) before reporting\n"
            "this as a recall measurement. Re-run with --allow-zero-recall to accept it.",
            file=sys.stderr,
        )
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
