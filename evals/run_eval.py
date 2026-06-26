#!/usr/bin/env python3
"""Score-only eval runner (Phase 1).

Scores an *already-written* PubMed strategy against a single gold-standard
fixture and prints a recall scorecard. It does NOT run the skill / an LLM; it
wraps the bundled ``scripts/pubmed_tool.py`` commands that already exist:

  * ``search``  - resolve which gold PMIDs exist in PubMed (reachability) and
                  get the strategy's total hit count (for an NNR proxy).
  * ``recall``  - relative recall + per-block bottleneck diagnosis against the
                  gold relevant set.

All recall math lives in ``pubmed_tool.py`` and is reused verbatim via
subprocess + ``--output`` JSON, so nothing is re-implemented here.

Usage:
    python evals/run_eval.py datasets/clef-tar-2018/CD011926.json
    python evals/run_eval.py <fixture.json> --output results/CD011926.json --json

A fixture is a JSON object:
    {
      "id": "CD011926",
      "question": "....",
      "strategy_file": "CD011926.strategy.txt",   # relative to the fixture dir
      "blocks_file":   "CD011926.blocks.json",     # optional
      "gold_relevant_pmids": [9350892, ...]
    }
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TOOL = HERE.parent / "scripts" / "pubmed_tool.py"
DATASETS = HERE / "datasets"
UID_CHUNK = 100  # PMIDs per reachability ESearch


def resolve_fixture(arg: str) -> Path:
    """Resolve a fixture argument to a path. Accepts a full/relative path OR a
    bare topic id (e.g. ``CD011926``) matched against ``datasets/**/<id>.json``."""
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


def _run_tool(tool: Path, args: list[str]) -> dict:
    """Run a pubmed_tool.py subcommand and return parsed JSON stdout."""
    cmd = [sys.executable, str(tool), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(
            f"pubmed_tool.py failed ({' '.join(args[:2])}): exit {proc.returncode}\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise SystemExit(f"Could not parse pubmed_tool.py output as JSON: {exc}\n{proc.stdout[:500]}")


def _write_temp(text: str) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    fh.write(text)
    fh.close()
    return fh.name


def resolve_in_pubmed(tool: Path, gold: list[str]) -> set[str]:
    """Return the subset of gold PMIDs that actually exist in PubMed."""
    found: set[str] = set()
    for i in range(0, len(gold), UID_CHUNK):
        chunk = gold[i : i + UID_CHUNK]
        query = " OR ".join(f"{pmid}[uid]" for pmid in chunk)
        path = _write_temp(query)
        data = _run_tool(tool, ["search", "--query-file", path, "--retmax", str(len(chunk))])
        found.update(str(p) for p in (data.get("pmids") or []))
    return found


def strategy_total_count(tool: Path, strategy_file: Path) -> int:
    data = _run_tool(tool, ["search", "--query-file", str(strategy_file), "--retmax", "0"])
    return int(data.get("count") or 0)


def run_recall(tool: Path, strategy_file: Path, gold: list[str], blocks_file: Path | None) -> dict:
    out = _write_temp("")  # reuse temp path machinery for the --output file
    args = [
        "recall",
        "--query-file", str(strategy_file),
        "--benchmark-pmids", *gold,
        "--output", out,
    ]
    if blocks_file is not None:
        args += ["--blocks-file", str(blocks_file)]
    _run_tool(tool, args)
    return json.loads(Path(out).read_text(encoding="utf-8"))


def score(
    fixture_path: Path,
    tool: Path,
    *,
    strategy_override: str | Path | None = None,
    blocks_override: str | Path | None = None,
) -> dict:
    """Score a strategy against the fixture's gold set.

    By default scores the fixture's own ``strategy_file`` (Phase 1). Pass
    ``strategy_override`` to score a different strategy (e.g. one the skill
    generated in Phase 2); ``blocks_override`` supplies matching concept blocks
    for per-block diagnosis, else per-block diagnosis is skipped for the
    overridden strategy.
    """
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    base = fixture_path.parent
    gold = [str(p) for p in fixture["gold_relevant_pmids"]]
    if strategy_override is not None:
        strategy_file = Path(strategy_override)
        blocks_file = Path(blocks_override) if blocks_override else None
    elif not fixture.get("strategy_file"):
        raise SystemExit(
            f"fixture {fixture.get('id')} has no baseline 'strategy_file'. "
            "Score-only mode needs a strategy; use evals/generate.py to have the skill build one."
        )
    else:
        strategy_file = base / fixture["strategy_file"]
        if blocks_override:
            blocks_file = Path(blocks_override)
        elif fixture.get("blocks_file"):
            blocks_file = base / fixture["blocks_file"]
        else:
            blocks_file = None
    if not strategy_file.exists():
        raise SystemExit(f"strategy_file not found: {strategy_file}")

    in_pubmed = resolve_in_pubmed(tool, gold)
    unreachable = [p for p in gold if p not in in_pubmed]

    recall_data = run_recall(tool, strategy_file, gold, blocks_file)
    retrieved = [str(p) for p in (recall_data.get("retrieved_pmids") or [])]
    missed_all = [str(p) for p in (recall_data.get("missed_pmids") or [])]
    missed_reachable = [p for p in missed_all if p in in_pubmed]

    reachable_n = len(in_pubmed)
    retrieved_n = len(retrieved)  # retrieved is always a subset of in_pubmed
    recall_reachable = round(retrieved_n / reachable_n * 100, 1) if reachable_n else 0.0

    total_hits = strategy_total_count(tool, strategy_file)
    nnr_proxy = round(total_hits / retrieved_n) if retrieved_n else None

    # Per-block recall recomputed over the *reachable* denominator.
    blocks_out = []
    for row in recall_data.get("block_recall") or []:
        bc = int(row.get("retrieved_count") or 0)
        blocks_out.append(
            {
                "label": row.get("label"),
                "retrieved_count": bc,
                "recall_reachable_percent": round(bc / reachable_n * 100, 1) if reachable_n else 0.0,
            }
        )
    if blocks_out:
        worst = min(b["retrieved_count"] for b in blocks_out)
        for b in blocks_out:
            b["bottleneck"] = b["retrieved_count"] == worst

    and_interaction = [
        m["pmid"] for m in (recall_data.get("miss_diagnosis") or [])
        if isinstance(m, dict) and m.get("and_interaction") and str(m.get("pmid")) in in_pubmed
    ]

    return {
        "id": fixture.get("id"),
        "suite": fixture.get("suite"),
        "question": fixture.get("question"),
        "gold_total": len(gold),
        "gold_in_pubmed": reachable_n,
        "gold_unreachable": unreachable,
        "retrieved": retrieved_n,
        "recall_reachable_percent": recall_reachable,
        "missed_in_pubmed": missed_reachable,
        "strategy_total_hits": total_hits,
        "nnr_proxy": nnr_proxy,
        "block_recall": blocks_out,
        "and_interaction_misses": and_interaction,
        "fixture": str(fixture_path),
        "strategy_file": str(strategy_file),
    }


def render(card: dict) -> str:
    lines = []
    lines.append("PubMed Search Builder - score-only eval")
    lines.append(f"topic: {card['id']}  ({card['suite']})")
    lines.append(f'"{card["question"]}"')
    lines.append("")
    unreachable = card["gold_unreachable"]
    lines.append(f"gold relevant PMIDs ........ {card['gold_total']}")
    note = f"   ({len(unreachable)} not in PubMed - unreachable, excluded)" if unreachable else ""
    lines.append(f"  in PubMed ................ {card['gold_in_pubmed']}{note}")
    lines.append(f"  retrieved by strategy .... {card['retrieved']}")
    lines.append(
        f"recall (of reachable) ...... {card['recall_reachable_percent']}%"
        f"   ({card['retrieved']}/{card['gold_in_pubmed']})"
    )
    missed = card["missed_in_pubmed"]
    if missed:
        shown = ", ".join(missed[:10]) + (" ..." if len(missed) > 10 else "")
        lines.append(f"missed (in PubMed) ......... {len(missed)}   [{shown}]")
    lines.append("")
    lines.append(f"strategy total hits ........ {card['strategy_total_hits']:,}")
    lines.append(
        f"NNR proxy .................. ~{card['nnr_proxy']}   "
        "(total / gold-retrieved; not true precision)"
    )
    if card["block_recall"]:
        lines.append("")
        lines.append("per-block recall (of reachable):")
        for b in card["block_recall"]:
            flag = "   <- bottleneck" if b.get("bottleneck") else ""
            lines.append(
                f"  {b['label']:<44} {b['recall_reachable_percent']:>5}%"
                f"  ({b['retrieved_count']}/{card['gold_in_pubmed']}){flag}"
            )
    if card["and_interaction_misses"]:
        lines.append("")
        lines.append(
            "AND-interaction misses (retrieved by every block alone but lost by the "
            f"full strategy - check NOT/filters/proximity): {len(card['and_interaction_misses'])}"
        )
    if unreachable:
        lines.append("")
        lines.append(f"unreachable gold PMIDs: {', '.join(unreachable)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score-only PubMed strategy eval (Phase 1).")
    parser.add_argument("fixture", help="Fixture JSON path OR a bare topic id (e.g. CD011926).")
    parser.add_argument("--pubmed-tool", default=str(DEFAULT_TOOL), help="Path to pubmed_tool.py.")
    parser.add_argument("--output", help="Write the scorecard JSON to this path.")
    parser.add_argument("--json", action="store_true", help="Print the scorecard JSON to stdout instead of the table.")
    parser.add_argument("--strategy-file", help="Score this strategy instead of the fixture's baseline strategy_file.")
    parser.add_argument("--blocks-file", help="Concept blocks JSON for per-block diagnosis (use with --strategy-file).")
    args = parser.parse_args(argv)

    fixture_path = resolve_fixture(args.fixture)
    tool = Path(args.pubmed_tool).resolve()
    if not tool.exists():
        raise SystemExit(f"pubmed_tool.py not found: {tool}")

    card = score(
        fixture_path,
        tool,
        strategy_override=args.strategy_file,
        blocks_override=args.blocks_file,
    )

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(card, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(card, indent=2))
    else:
        print(render(card))
        if args.output:
            print(f"\nscorecard JSON: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
