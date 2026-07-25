#!/usr/bin/env python3
"""Score every fixture and aggregate the result into one comparable table.

A single fixture score is a smoke test. What defends a claim about recall -- and what turns a
change to the skill from "sounds better" into a regression diff -- is the same set of topics
scored the same way before and after.

Each topic's strategy comes from one of three sources, and every row records which:

``baseline``   the strategy the fixture ships, hand-authored for that topic.
``naive``      compiled deterministically from the fixture's own protocol (see naive_baseline.py).
               A floor, not the skill: no MeSH, no expansion, no critic loop.
``generated``  what the skill built in a Phase 2 run. The only source that measures the skill.

Mixing them in one table is deliberate, but reading a floor score as the skill's recall would be
a serious misreading, so the source is printed on every row and the summary refuses to average
across sources.

Usage:
    python evals/run_suite.py                          # score every fixture
    python evals/run_suite.py --topic CD011926 --topic Muthu_2022
    python evals/run_suite.py --runs 3                 # variance across repeats
    python evals/run_suite.py --markdown evals/RESULTS.md
    python evals/run_suite.py --fail-on-regression     # non-zero exit if recall dropped
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import naive_baseline  # noqa: E402
import run_eval  # noqa: E402

DEFAULT_TOOL = HERE.parent / "scripts" / "pubmed_tool.py"
DEFAULT_SUITE_OUTPUT = HERE / "results" / "suite.json"
DERIVED_DIR = HERE / "results" / "derived"
SOURCES = ("auto", "baseline", "naive", "generated")
# A recall drop beyond this is treated as a regression rather than PubMed drift.
REGRESSION_TOLERANCE = 0.5


def discover_fixtures() -> list[Path]:
    found: list[Path] = []
    for path in sorted(run_eval.DATASETS.glob("**/*.json")):
        if path.name.endswith(".blocks.json") or path.name.endswith(".strategy.txt"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id"):
            found.append(path)
    return found


def resolve_strategy(fixture_path: Path, fixture: dict, source: str, generated_root: Path | None):
    """Return ``(source, strategy_path, blocks_path)`` for one fixture."""
    topic = str(fixture.get("id"))
    if source in {"auto", "generated"} and generated_root is not None:
        candidate = generated_root / topic / "final_strategy.txt"
        if candidate.is_file() and candidate.read_text(encoding="utf-8").strip():
            blocks = generated_root / topic / "final_blocks.json"
            return "generated", candidate, (blocks if blocks.is_file() else None)
        if source == "generated":
            raise FileNotFoundError(f"no generated strategy for {topic} under {generated_root}")
    if source in {"auto", "baseline"} and fixture.get("strategy_file"):
        strategy = fixture_path.parent / fixture["strategy_file"]
        blocks = fixture_path.parent / fixture["blocks_file"] if fixture.get("blocks_file") else None
        return "baseline", strategy, blocks
    if source == "baseline":
        raise FileNotFoundError(f"fixture {topic} has no baseline strategy_file")
    compiled = naive_baseline.compile_from_fixture(fixture)
    strategy, blocks = naive_baseline.write_strategy(compiled, DERIVED_DIR, topic)
    return "naive", strategy, blocks


def score_topic(fixture_path: Path, tool: Path, source: str, generated_root: Path | None, runs: int, use_cache: bool) -> dict:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    topic = str(fixture.get("id"))
    row: dict = {"id": topic, "suite": fixture.get("suite"), "question": fixture.get("question")}
    try:
        resolved_source, strategy, blocks = resolve_strategy(fixture_path, fixture, source, generated_root)
    except (FileNotFoundError, naive_baseline.NaiveBaselineError) as exc:
        row.update({"ok": False, "error": str(exc), "strategy_source": None})
        return row

    recalls: list[float] = []
    card: dict = {}
    for _ in range(max(1, runs)):
        card = run_eval.score(
            fixture_path,
            tool,
            strategy_override=str(strategy),
            blocks_override=str(blocks) if blocks else None,
            use_cache=use_cache,
        )
        recalls.append(float(card.get("recall_reachable_percent") or 0.0))

    bottleneck = next(
        (item["label"] for item in card.get("block_recall") or [] if item.get("bottleneck")), None
    )
    row.update(
        {
            "ok": True,
            "strategy_source": resolved_source,
            "strategy_sha256": card.get("strategy_sha256"),
            "gold_total": card.get("gold_total"),
            "gold_in_pubmed": card.get("gold_in_pubmed"),
            "retrieved": card.get("retrieved"),
            "recall_reachable_percent": card.get("recall_reachable_percent"),
            "recall_mean": round(statistics.fmean(recalls), 2),
            "recall_sd": round(statistics.stdev(recalls), 3) if len(recalls) > 1 else 0.0,
            "runs": len(recalls),
            "strategy_total_hits": card.get("strategy_total_hits"),
            "nnr_proxy": card.get("nnr_proxy"),
            "bottleneck_block": bottleneck,
            "and_interaction_misses": len(card.get("and_interaction_misses") or []),
            "missed_in_pubmed": len(card.get("missed_in_pubmed") or []),
            "zero_recall": bool((card.get("sanity") or {}).get("zero_recall")),
        }
    )
    return row


def summarize(rows: list[dict]) -> dict:
    scored = [row for row in rows if row.get("ok")]
    by_source: dict[str, dict] = {}
    for source in sorted({str(row["strategy_source"]) for row in scored}):
        subset = [row for row in scored if row["strategy_source"] == source]
        recalls = [float(row["recall_reachable_percent"] or 0.0) for row in subset]
        by_source[source] = {
            "topics": len(subset),
            "gold_in_pubmed": sum(int(row.get("gold_in_pubmed") or 0) for row in subset),
            "retrieved": sum(int(row.get("retrieved") or 0) for row in subset),
            "mean_recall_percent": round(statistics.fmean(recalls), 2) if recalls else None,
            "median_recall_percent": round(statistics.median(recalls), 2) if recalls else None,
            "min_recall_percent": round(min(recalls), 2) if recalls else None,
            "max_recall_percent": round(max(recalls), 2) if recalls else None,
            "topics_below_80": sum(1 for value in recalls if value < 80.0),
            "zero_recall_topics": [row["id"] for row in subset if row.get("zero_recall")],
        }
    return {
        "topics_total": len(rows),
        "topics_scored": len(scored),
        "topics_failed": [row["id"] for row in rows if not row.get("ok")],
        # Never averaged across sources: a naive floor and a generated strategy are not the
        # same measurement and a combined mean would mean nothing.
        "by_strategy_source": by_source,
    }


def compare(current: dict, previous: dict | None) -> dict:
    if not previous:
        return {"available": False, "reason": "no previous suite scorecard to compare against"}
    before = {row["id"]: row for row in previous.get("topics", []) if row.get("ok")}
    deltas: list[dict] = []
    regressions: list[dict] = []
    for row in current.get("topics", []):
        if not row.get("ok") or row["id"] not in before:
            continue
        prior = before[row["id"]]
        if prior.get("strategy_source") != row.get("strategy_source"):
            continue  # comparing a floor against a generated strategy is not a regression signal
        change = round(float(row["recall_reachable_percent"] or 0) - float(prior["recall_reachable_percent"] or 0), 2)
        entry = {
            "id": row["id"],
            "strategy_source": row["strategy_source"],
            "before": prior["recall_reachable_percent"],
            "after": row["recall_reachable_percent"],
            "delta": change,
            "strategy_changed": prior.get("strategy_sha256") != row.get("strategy_sha256"),
        }
        deltas.append(entry)
        if change < -REGRESSION_TOLERANCE:
            regressions.append(entry)
    return {
        "available": True,
        "compared_topics": len(deltas),
        "regressions": regressions,
        "improvements": [item for item in deltas if item["delta"] > REGRESSION_TOLERANCE],
        "deltas": deltas,
    }


def render_markdown(scorecard: dict) -> str:
    lines = [
        "# Eval suite results",
        "",
        f"Generated {scorecard['generated_utc']} against {scorecard['summary']['topics_scored']} "
        f"of {scorecard['summary']['topics_total']} fixtures.",
        "",
        "`recall` is measured over gold PMIDs that exist in PubMed; records the source review found "
        "only in other databases are excluded from the denominator. `NNR` is total hits ÷ gold "
        "retrieved — a workload proxy, not precision.",
        "",
        "**Read the `source` column before the recall column.**",
        "",
        "| source | meaning |",
        "|---|---|",
        "| `generated` | the skill built this strategy — the only rows that measure the skill |",
        "| `baseline` | strategy hand-authored for the fixture |",
        "| `naive` | compiled from the fixture's protocol term families: no MeSH, no expansion, no critic loop. A floor. |",
        "",
        "| topic | suite | source | gold (in PubMed) | retrieved | recall | hits | NNR | bottleneck block |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in scorecard["topics"]:
        if not row.get("ok"):
            lines.append(f"| {row['id']} | {row.get('suite') or ''} | — | — | — | **failed** | — | — | {row.get('error', '')[:60]} |")
            continue
        sd = f" ±{row['recall_sd']}" if row.get("runs", 1) > 1 else ""
        lines.append(
            f"| {row['id']} | {row.get('suite') or ''} | `{row['strategy_source']}` | "
            f"{row['gold_in_pubmed']} | {row['retrieved']} | {row['recall_reachable_percent']}%{sd} | "
            f"{row['strategy_total_hits']:,} | {row['nnr_proxy'] or '—'} | {row.get('bottleneck_block') or '—'} |"
        )
    lines.append("")
    lines.append("## By strategy source")
    lines.append("")
    lines.append("| source | topics | gold in PubMed | retrieved | mean recall | median | min | max | topics <80% |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for source, stats in scorecard["summary"]["by_strategy_source"].items():
        lines.append(
            f"| `{source}` | {stats['topics']} | {stats['gold_in_pubmed']} | {stats['retrieved']} | "
            f"{stats['mean_recall_percent']}% | {stats['median_recall_percent']}% | "
            f"{stats['min_recall_percent']}% | {stats['max_recall_percent']}% | {stats['topics_below_80']} |"
        )
    regression = scorecard.get("regression") or {}
    if regression.get("available"):
        lines.extend(["", "## Change since the previous run", ""])
        if regression["regressions"]:
            lines.append("| topic | before | after | delta |")
            lines.append("|---|---:|---:|---:|")
            for item in regression["regressions"]:
                lines.append(f"| {item['id']} | {item['before']}% | {item['after']}% | **{item['delta']}** |")
        else:
            lines.append(f"No regression across {regression['compared_topics']} comparable topics.")
    return "\n".join(lines) + "\n"


def render_text(scorecard: dict) -> str:
    lines = ["PubMed Search Builder — eval suite", ""]
    for row in scorecard["topics"]:
        if not row.get("ok"):
            lines.append(f"  {row['id'][:44]:46s} FAILED  {row.get('error','')[:50]}")
            continue
        sd = f" ±{row['recall_sd']:.1f}" if row.get("runs", 1) > 1 else ""
        lines.append(
            f"  {row['id'][:44]:46s} {row['strategy_source']:>10s}  "
            f"{row['recall_reachable_percent']:>5}%{sd}  ({row['retrieved']}/{row['gold_in_pubmed']})  "
            f"hits={row['strategy_total_hits']:,}"
        )
    lines.append("")
    for source, stats in scorecard["summary"]["by_strategy_source"].items():
        lines.append(
            f"  {source:>10s}: {stats['topics']} topics, mean {stats['mean_recall_percent']}%, "
            f"median {stats['median_recall_percent']}%, min {stats['min_recall_percent']}%, "
            f"{stats['topics_below_80']} below 80%"
        )
    regression = scorecard.get("regression") or {}
    if regression.get("available"):
        lines.append("")
        if regression["regressions"]:
            lines.append(f"  REGRESSIONS ({len(regression['regressions'])}):")
            for item in regression["regressions"]:
                lines.append(f"    {item['id']}: {item['before']}% -> {item['after']}% ({item['delta']})")
        else:
            lines.append(f"  no regression across {regression['compared_topics']} comparable topics")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score every eval fixture and aggregate the results.")
    parser.add_argument("--topic", action="append", help="Restrict to this topic id (repeatable).")
    parser.add_argument("--source", choices=SOURCES, default="auto", help="Strategy source (default: auto).")
    parser.add_argument("--generated-root", help="Directory of <topic>/final_strategy.txt from Phase 2 runs.")
    parser.add_argument("--runs", type=int, default=1, help="Score each topic N times for variance.")
    parser.add_argument("--pubmed-tool", default=str(DEFAULT_TOOL))
    parser.add_argument("--output", default=str(DEFAULT_SUITE_OUTPUT), help="Suite scorecard JSON path.")
    parser.add_argument("--markdown", help="Also render a Markdown table to this path.")
    parser.add_argument("--baseline", help="Previous suite scorecard for the delta (default: --output if it exists).")
    parser.add_argument("--fail-on-regression", action="store_true", help="Exit non-zero when recall dropped.")
    parser.add_argument("--no-cache", action="store_true", help="Take every NCBI request live.")
    parser.add_argument("--json", action="store_true", help="Print the scorecard JSON instead of the table.")
    args = parser.parse_args(argv)

    tool = Path(args.pubmed_tool).resolve()
    if not tool.is_file():
        raise SystemExit(f"pubmed_tool.py not found: {tool}")
    fixtures = discover_fixtures()
    if args.topic:
        wanted = {value.casefold() for value in args.topic}
        fixtures = [
            path for path in fixtures
            if str(json.loads(path.read_text(encoding="utf-8-sig")).get("id", "")).casefold() in wanted
        ]
        if not fixtures:
            raise SystemExit(f"no fixture matched: {', '.join(args.topic)}")
    generated_root = Path(args.generated_root).resolve() if args.generated_root else None

    output = Path(args.output)
    previous = None
    baseline_path = Path(args.baseline) if args.baseline else output
    if baseline_path.is_file():
        try:
            previous = json.loads(baseline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

    rows: list[dict] = []
    for index, path in enumerate(fixtures, start=1):
        topic = json.loads(path.read_text(encoding="utf-8-sig")).get("id")
        print(f"[{index}/{len(fixtures)}] {topic}", file=sys.stderr)
        try:
            rows.append(score_topic(path, tool, args.source, generated_root, args.runs, not args.no_cache))
        except SystemExit as exc:
            rows.append({"id": topic, "ok": False, "error": str(exc), "strategy_source": None})
        except Exception:  # noqa: BLE001 - one broken fixture must not lose the whole suite
            rows.append({"id": topic, "ok": False, "error": traceback.format_exc(limit=1).strip(), "strategy_source": None})

    scorecard = {
        "operation": "eval-suite",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs_per_topic": max(1, args.runs),
        "requested_source": args.source,
        "topics": rows,
        "summary": summarize(rows),
    }
    scorecard["regression"] = compare(scorecard, previous)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(scorecard), encoding="utf-8")

    print(json.dumps(scorecard, indent=2, ensure_ascii=False) if args.json else render_text(scorecard))
    print(f"\nsuite scorecard: {output}", file=sys.stderr)

    if args.fail_on_regression and scorecard["regression"].get("regressions"):
        return 4
    return 0 if scorecard["summary"]["topics_scored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
