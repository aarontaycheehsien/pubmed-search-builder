#!/usr/bin/env python3
"""Run score-only evals across PubMed Search Builder fixtures.

This is a thin suite runner around ``evals/run_eval.py``. It caches completed
scorecards by fixture/strategy/block content hash so repeated aggregate checks
can be read from disk instead of re-querying NCBI. Generation runs remain in
``evals/generate.py``; this runner only scores already-written strategies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = HERE / ".cache" / "scorecards"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_eval


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_digest(path: Path | None) -> str:
    if path is None:
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def fixture_paths(topics: list[str]) -> list[Path]:
    if topics:
        return [run_eval.resolve_fixture(topic) for topic in topics]
    return sorted(path.resolve() for path in run_eval.DATASETS.glob("**/*.json") if "." not in path.stem)


def scoring_files(fixture_path: Path) -> tuple[Path | None, Path | None, str | None]:
    fixture = read_json(fixture_path)
    base = fixture_path.parent
    strategy_name = fixture.get("strategy_file")
    if not strategy_name:
        return None, None, "fixture has no baseline strategy_file"
    strategy_file = base / strategy_name
    if not strategy_file.exists():
        return None, None, f"strategy_file not found: {strategy_file}"
    blocks_file = base / fixture["blocks_file"] if fixture.get("blocks_file") else None
    if blocks_file is not None and not blocks_file.exists():
        return None, None, f"blocks_file not found: {blocks_file}"
    return strategy_file, blocks_file, None


def cache_key(fixture_path: Path, strategy_file: Path, blocks_file: Path | None, tool: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(fixture_path.resolve()).encode("utf-8"))
    digest.update(file_digest(fixture_path).encode("ascii"))
    digest.update(file_digest(strategy_file).encode("ascii"))
    digest.update(file_digest(blocks_file).encode("ascii"))
    digest.update(str(tool.resolve()).encode("utf-8"))
    return digest.hexdigest()[:24]


def score_or_cache(
    fixture_path: Path,
    tool: Path,
    cache_dir: Path,
    *,
    refresh: bool,
    cached_only: bool,
) -> dict:
    strategy_file, blocks_file, skip_reason = scoring_files(fixture_path)
    fixture = read_json(fixture_path)
    if skip_reason:
        return {
            "id": fixture.get("id") or fixture_path.stem,
            "suite": fixture.get("suite"),
            "fixture": str(fixture_path),
            "status": "skipped",
            "reason": skip_reason,
        }

    assert strategy_file is not None
    key = cache_key(fixture_path, strategy_file, blocks_file, tool)
    cache_path = cache_dir / f"{key}.json"
    if cache_path.exists() and not refresh:
        card = read_json(cache_path)
        card["cache"] = {"status": "hit", "path": str(cache_path)}
        return card
    if cached_only:
        return {
            "id": fixture.get("id") or fixture_path.stem,
            "suite": fixture.get("suite"),
            "fixture": str(fixture_path),
            "status": "skipped",
            "reason": "cache miss in cached-only mode",
            "cache": {"status": "miss", "path": str(cache_path)},
        }

    card = run_eval.score(fixture_path, tool)
    card["status"] = "scored"
    card["cache"] = {"status": "refresh" if refresh else "miss", "path": str(cache_path)}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def aggregate(cards: list[dict]) -> dict:
    scored = [card for card in cards if card.get("status", "scored") != "skipped"]
    recalls = [float(card["recall_reachable_percent"]) for card in scored if "recall_reachable_percent" in card]
    nnrs = [float(card["nnr_proxy"]) for card in scored if card.get("nnr_proxy") is not None]
    return {
        "fixture_count": len(cards),
        "scored_count": len(scored),
        "skipped_count": len(cards) - len(scored),
        "mean_recall_reachable_percent": round(statistics.mean(recalls), 2) if recalls else None,
        "sd_recall_reachable_percent": round(statistics.pstdev(recalls), 2) if len(recalls) > 1 else 0.0 if recalls else None,
        "mean_nnr_proxy": round(statistics.mean(nnrs), 2) if nnrs else None,
    }


def render(result: dict) -> str:
    summary = result["summary"]
    lines = [
        "PubMed Search Builder - eval suite",
        f"fixtures: {summary['fixture_count']}  scored: {summary['scored_count']}  skipped: {summary['skipped_count']}",
        f"mean recall (reachable): {summary['mean_recall_reachable_percent']}",
        f"sd recall (reachable): {summary['sd_recall_reachable_percent']}",
        f"mean NNR proxy: {summary['mean_nnr_proxy']}",
        "",
    ]
    for card in result["scorecards"]:
        if card.get("status") == "skipped":
            lines.append(f"- {card['id']}: skipped - {card['reason']}")
        else:
            cache = card.get("cache", {}).get("status", "none")
            lines.append(
                f"- {card['id']}: recall {card['recall_reachable_percent']}%, "
                f"hits {card['strategy_total_hits']}, cache {cache}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run score-only evals across fixtures with a local scorecard cache.")
    parser.add_argument("--topic", action="append", default=[], help="Fixture topic id/path to score. Repeatable. Default: all fixtures.")
    parser.add_argument("--pubmed-tool", default=str(run_eval.DEFAULT_TOOL), help="Path to pubmed_tool.py.")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="Scorecard cache directory.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached scorecards and rescore.")
    parser.add_argument("--cached-only", action="store_true", help="Do not run PubMed calls; report cache misses as skipped.")
    parser.add_argument("--output", help="Write aggregate JSON to this path.")
    parser.add_argument("--json", action="store_true", help="Print aggregate JSON instead of a text table.")
    args = parser.parse_args(argv)

    tool = Path(args.pubmed_tool).resolve()
    if not tool.exists():
        raise SystemExit(f"pubmed_tool.py not found: {tool}")
    cache_dir = Path(args.cache_dir)
    cards = [
        score_or_cache(path, tool, cache_dir, refresh=args.refresh, cached_only=args.cached_only)
        for path in fixture_paths(args.topic)
    ]
    result = {"summary": aggregate(cards), "scorecards": cards}

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result))
        if args.output:
            print(f"\naggregate JSON: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
