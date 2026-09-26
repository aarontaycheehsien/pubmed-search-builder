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
  python evals/generate.py <fixture.json> --effort medium --timeout 7200 --model gpt-5.5

A full build is an agentic run (minutes, real tokens). Run it in the background
if your shell caps command time. Re-scoring the harvested strategy afterward is
free (run_eval.py).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import manifest_tool  # noqa: E402
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


@contextlib.contextmanager
def agent_temp_root() -> Iterator[Path]:
    """Temporary root for the agent workspace that the harness can still read afterwards.

    ``tempfile.mkdtemp`` on Windows (Python 3.13+) gives the directory an owner-only ACL. The Codex
    sandbox runs commands as a separate sandbox user, so every file the agent creates is owned by
    that user and becomes unreadable to the harness: the completion gate cannot open the manifest
    and the artifacts cannot be copied out. A plain mkdir inherits the parent's ACL instead.
    """
    root = Path(tempfile.gettempdir()) / f"pubmed-skill-eval-{uuid.uuid4().hex[:12]}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


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
    # The critic reviewed the strategy's content at bundle time. A strategy revised in place
    # after the critic no longer is the pre-critic strategy, so it must match the bundle hash.
    reviewed_sha256 = critic_bundle_strategy_sha256(run_dir, artifact, critic)
    if reviewed_sha256 is not None and hashlib.sha256(strategy.read_bytes()).hexdigest() != reviewed_sha256:
        return None
    return strategy if strategy.read_text(encoding="utf-8").strip() else None


def critic_bundle_strategy_sha256(run_dir: Path, critic_path: Path, critic: dict) -> str | None:
    """Return the strategy hash frozen in the critic's evidence bundle, when one is recorded."""
    bundle_value = critic.get("evidence_bundle")
    if not bundle_value:
        return None
    bundle_path = resolve_within(critic_path.parent, str(bundle_value), search=False) or resolve_within(
        run_dir, str(bundle_value)
    )
    if bundle_path is None:
        return None
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    for item in bundle.get("artifacts") or [] if isinstance(bundle, dict) else []:
        if isinstance(item, dict) and item.get("role") == "strategy" and item.get("sha256"):
            return str(item["sha256"])
    return None


def final_strategy_binding_issue(run_dir: Path) -> str | None:
    """Return why ``final_strategy.txt`` is not the strategy the completion gate passed, or None.

    The gate binds the audit's final strategy to the inputs of the last final topic-only search.
    The harness scores ``final_strategy.txt``, which nothing in the gate ties to that search, so an
    agent that searched ``strategy_v3.txt`` and wrote ``final_strategy.txt`` separately could have
    a different strategy scored than the one that passed.
    """
    scored = run_dir / "final_strategy.txt"
    if not scored.is_file():
        return "final_strategy.txt was not written"
    try:
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "run_manifest.json is unreadable"
    entries = [entry for entry in manifest.get("entries") or [] if isinstance(entry, dict)]
    finals = sorted(
        (entry for entry in entries if manifest_tool.looks_like_final_topic_search(entry)),
        key=lambda entry: int(entry.get("seq") or 0),
    )
    if not finals:
        return "the manifest records no final topic-only search"
    searched: set[str] = set()
    for value in (finals[-1].get("input_sha256") or {}):
        path = resolve_within(run_dir, str(value), search=False)
        if path is not None and path.is_file() and path.suffix.casefold() not in {".json", ".csv"}:
            searched.add(path.read_text(encoding="utf-8-sig").strip())
    if not searched:
        return "the final topic-only search records no readable strategy input"
    if scored.read_text(encoding="utf-8-sig").strip() not in searched:
        return f"final_strategy.txt differs from the strategy input of the final search (seq {finals[-1].get('seq')})"
    return None


PMID_PATTERN = r"(?<!\d){pmid}(?!\d)"


def leakage_scan(events_path: Path, fixture: dict, fixture_path: Path) -> dict:
    """Scan the agent transcript for evidence that it reached the answer key.

    Two signals: a command or file edit that names the repository, fixture files, or qrels; and a
    gold PMID the agent used before any tool output showed it (PMIDs the fixture gives the skill
    are exempt). Output is anything a command printed, so a PMID the agent discovered in PubMed
    results is not a finding.
    """
    gold_field = "evaluation_gold_pmids" if fixture.get("evaluation_gold_pmids") else "gold_relevant_pmids"
    gold = {str(pmid) for pmid in fixture.get(gold_field) or []} - run_eval.given_to_skill_pmids(fixture)
    patterns = {pmid: re.compile(PMID_PATTERN.format(pmid=pmid)) for pmid in gold}
    forbidden = {
        str(SKILL_DIR).casefold(),
        SKILL_DIR.as_posix().casefold(),
        "evals/datasets",
        "evals\\datasets",
        "qrel",
        fixture_path.name.casefold(),
    }
    if len(str(fixture.get("id") or "")) >= 4:
        forbidden.add(str(fixture["id"]).casefold())
    repository_references: list[str] = []
    undiscovered_gold: list[dict] = []
    shown: set[str] = set()
    actions = 0
    try:
        lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"clean": False, "error": f"transcript unreadable: {events_path}"}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if item.get("type") == "command_execution":
            action = str(item.get("command") or "")
            output = str(item.get("aggregated_output") or "")
        elif item.get("type") == "file_change":
            action, output = json.dumps(item.get("changes") or item), ""
        else:
            continue
        actions += 1
        lowered = action.casefold()
        for marker in sorted(forbidden):
            if marker and marker in lowered:
                repository_references.append(f"{marker}: {action[:200]}")
        for pmid, pattern in patterns.items():
            if pmid not in shown and pattern.search(action):
                undiscovered_gold.append({"pmid": pmid, "action": action[:200]})
                shown.add(pmid)
        shown.update(pmid for pmid, pattern in patterns.items() if pattern.search(output))
    return {
        "clean": not repository_references and not undiscovered_gold,
        "actions_scanned": actions,
        "repository_references": repository_references,
        "gold_used_before_discovery": undiscovered_gold,
    }


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
    # A CD011926 build took ~50 min, and over 60 min on another attempt; 1800 s cut builds off mid-discovery.
    parser.add_argument("--timeout", type=int, default=7200, help="Driver timeout seconds (default: 7200).")
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
    if run_dir.exists() and any(run_dir.iterdir()):
        # Artifacts are merged into run_dir, so a leftover final_strategy.txt or scorecard.json
        # from an earlier run would be scored or reported as this run's result.
        raise SystemExit(f"run directory is not empty; refusing to mix runs: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    with agent_temp_root() as temp_root:
        isolated_skill, agent_run_dir = isolated_run_workspace(SKILL_DIR, temp_root)
        prompt = build_prompt(fixture, agent_run_dir)
        (agent_run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        print(f"[generate] fixture={fixture['id']} run_dir={run_dir}")
        print(f"[generate] driving isolated skill (effort={args.effort}, timeout={args.timeout}s)...")

        started = time.monotonic()
        result = codex.run_skill(
            prompt,
            skill_dir=isolated_skill,
            run_dir=agent_run_dir,
            model=args.model,
            reasoning_effort=args.effort,
            timeout=args.timeout,
        )
        elapsed_seconds = round(time.monotonic() - started)
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
        # Resolve evidence against the live agent workspace: the manifest's absolute paths point
        # into it, and it is deleted when this block exits.
        reviewed_pmids: set[str] = set()
        mined_pmids: set[str] = set()
        pre_critic: Path | None = None
        binding_issue: str | None = None
        if gate_ok:
            binding_issue = final_strategy_binding_issue(agent_run_dir)
            reviewed_pmids, mined_pmids = candidate_evidence_pmids(agent_run_dir)
            live_pre_critic = first_critic_strategy(agent_run_dir)
            if live_pre_critic is not None:
                pre_critic = run_dir / live_pre_critic.relative_to(agent_run_dir.resolve())

    if result["returncode"] != 0:
        reason = f"timed out after {args.timeout}s" if result.get("timed_out") else "returned a non-zero exit code"
        print(f"\n[generate] FAILED: Codex {reason}; generated files are not scored.")
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
    if binding_issue:
        print(f"\n[generate] FAILED: the scored file is not the gated strategy: {binding_issue}.")
        return 3

    blocks_file = run_dir / "final_blocks.json"
    blocks_override = str(blocks_file) if blocks_file.exists() else None

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
    card["elapsed_seconds"] = elapsed_seconds
    card["run_dir"] = str(run_dir)
    card["completion_gate"] = gate_payload
    card["leakage_scan"] = leakage_scan(run_dir / "events.jsonl", fixture, fixture_path)
    if pre_critic and pre_critic.resolve() != strategy_file.resolve():
        before = run_eval.score(
            fixture_path,
            Path(args.pubmed_tool),
            strategy_override=str(pre_critic),
            seen_pmids=reviewed_pmids,
            mined_pmids=mined_pmids,
        )
        before_recall = before.get("unseen_evaluation", {}).get("recall_percent")
        after_recall = card.get("unseen_evaluation", {}).get("recall_percent")
        card["critic_ablation"] = {
            "available": True,
            "before_strategy": str(pre_critic),
            "after_strategy": str(strategy_file),
            "before_unseen_recall": before_recall,
            "after_unseen_recall": after_recall,
            # Undefined when every gold record was reviewed: a 0.0 delta would read as "no effect".
            "unseen_recall_delta": (
                round(float(after_recall) - float(before_recall), 4)
                if before_recall is not None and after_recall is not None
                else None
            ),
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

    if not card["leakage_scan"].get("clean"):
        print(
            "\n[generate] LEAKAGE: the transcript shows the agent reaching the answer key; this run is\n"
            "not a measurement. See leakage_scan in scorecard.json.",
            file=sys.stderr,
        )
        return 5
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
