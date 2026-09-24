#!/usr/bin/env python3
"""Re-run a finished PubMed strategy for a review update and check it still means the same thing.

A validated strategy does not stay validated on its own. PubMed changes underneath it: annual
MeSH revisions add, split, and retire descriptors, entry terms move, and Automatic Term Mapping
changes what untagged words expand to. Re-running the saved query text can therefore return a
different search from the one that was reviewed, with nothing in the count to show it.

`check` re-runs the frozen strategy live, compares PubMed's current translation with the one
saved at build time, optionally re-tests the validation records, and retrieves the records added
since the last search for screening. Drift is reported, never repaired: a changed translation
routes the strategy back through an existing-strategy review, because deciding whether the new
meaning is still the review's scope is a scope decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pubmed_tool  # noqa: E402
from pubmed_search_builder.infrastructure.cache import ResponseCache  # noqa: E402

DATE_FIELDS = {
    "crdt": "Create Date: when the record was created in PubMed, including older citations added late",
    "edat": "Entrez Date: when the record was added, but set to the publication date for citations added long after publication",
}
MAX_NEW_RECORDS = 9999  # ESearch cannot page beyond 10,000 records for one query.


class SearchUpdateError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SearchUpdateError(f"Could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SearchUpdateError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_day(value: str, label: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise SearchUpdateError(f"{label} must be a date in YYYY-MM-DD form") from exc


def sorted_notices(response: dict[str, Any]) -> dict[str, list[str]]:
    return {name: sorted(values) for name, values in sorted(pubmed_tool.esearch_notices(response).items())}


def translation_drift(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """What changed in PubMed's reading of the same query text."""

    before = pubmed_tool.normalize_query(str(baseline.get("query_translation") or ""))
    after = pubmed_tool.normalize_query(str(current.get("query_translation") or ""))
    old_pairs = set(pubmed_tool.translation_pairs(baseline.get("translations")))
    new_pairs = set(pubmed_tool.translation_pairs(current.get("translations")))
    old_notices = sorted_notices(baseline)
    new_notices = sorted_notices(current)
    appeared = {
        name: sorted(set(values) - set(old_notices.get(name, [])))
        for name, values in new_notices.items()
        if set(values) - set(old_notices.get(name, []))
    }
    cleared = {
        name: sorted(set(values) - set(new_notices.get(name, [])))
        for name, values in old_notices.items()
        if set(values) - set(new_notices.get(name, []))
    }
    old_codes = {item.get("code") for item in (baseline.get("query_translation_hook") or {}).get("issues", []) if isinstance(item, dict)}
    new_hook = [
        item for item in (current.get("query_translation_hook") or {}).get("issues", [])
        if isinstance(item, dict) and item.get("code") not in old_codes and item.get("severity") in {"warning", "error"}
    ]
    return {
        "translation_changed": before != after,
        "baseline_translation": before,
        "current_translation": after,
        "mappings_added": sorted(new_pairs - old_pairs),
        "mappings_removed": sorted(old_pairs - new_pairs),
        "notices_appeared": appeared,
        "notices_cleared": cleared,
        "new_translation_warnings": new_hook,
        "changed": before != after or bool(appeared) or bool(new_hook),
    }


def date_window_query(query: str, field: str, start: date, end: date) -> str:
    return f'({query}) AND ("{start:%Y/%m/%d}"[{field}] : "{end:%Y/%m/%d}"[{field}])'


def check(
    client: pubmed_tool.NcbiClient,
    *,
    strategy_path: Path,
    baseline_path: Path,
    last_searched: str,
    until: str | None,
    date_field: str,
    validation_pmids: list[str],
    validation_source: str,
) -> dict[str, Any]:
    query = pubmed_tool.normalize_query(pubmed_tool.read_text_source(str(strategy_path)))
    if not query:
        raise SearchUpdateError("The strategy file is empty")
    baseline = read_json(baseline_path)
    if "query" not in baseline or "query_translation" not in baseline:
        raise SearchUpdateError("The baseline must be the build's saved `pubmed_tool.py search --output` artifact")
    if pubmed_tool.normalize_query(str(baseline.get("query") or "")) != query:
        raise SearchUpdateError(
            "The strategy differs from the baseline search; an update re-runs the same frozen strategy. "
            "Review a changed strategy as an existing-strategy review instead."
        )
    if date_field not in DATE_FIELDS:
        raise SearchUpdateError(f"--date-field must be one of: {', '.join(DATE_FIELDS)}")
    start = parse_day(last_searched, "--last-searched")
    end = parse_day(until, "--until") if until else datetime.now(timezone.utc).date()
    if start > end:
        raise SearchUpdateError("--last-searched is after the end of the update window")

    current = pubmed_tool.esearch(client, query, 0, 0, None)
    drift = translation_drift(baseline, current)

    # The window starts on the last search date itself: a one-day overlap is removed by
    # deduplication at screening, whereas a gap would silently lose records.
    window_query = date_window_query(query, date_field, start, end)
    window = pubmed_tool.esearch(client, window_query, 0, 0, None)
    new_count = int(window.get("count") or 0)
    if new_count > MAX_NEW_RECORDS:
        raise SearchUpdateError(
            f"{new_count} records fall in the update window, more than one ESearch request can return; "
            "split the window into shorter periods"
        )
    new_pmids = [str(pmid) for pmid in pubmed_tool.esearch(client, window_query, new_count, 0, None).get("pmids", [])] if new_count else []

    validation: dict[str, Any] = {"tested": False}
    if validation_pmids:
        retrieved = pubmed_tool.retrieve_against_pmids(client, query, validation_pmids)
        validation = {
            "tested": True,
            "source": validation_source,
            "pmid_count": len(validation_pmids),
            "retrieved": [pmid for pmid in validation_pmids if pmid in retrieved],
            "missed": [pmid for pmid in validation_pmids if pmid not in retrieved],
        }

    actions = []
    if drift["changed"]:
        actions.append(
            "PubMed now reads the strategy differently. Review the changed mappings and notices as an "
            "existing-strategy review before relying on the update; do not edit the strategy silently."
        )
    if validation.get("missed"):
        actions.append(
            "Validation records the strategy retrieved at handoff are now missed. Diagnose each (retraction, "
            "re-indexing, MeSH change) before relying on the update."
        )
    verdict = "review-required" if actions else "no-drift"
    baseline_count = int(baseline.get("count") or 0)
    current_count = int(current.get("count") or 0)
    return {
        "operation": "search-update",
        "ok": True,
        "checked_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "verdict": verdict,
        "required_actions": actions,
        "strategy_file": str(strategy_path),
        "baseline_search": str(baseline_path),
        "query": query,
        "count": current_count,
        "baseline_count": baseline_count,
        "count_change": current_count - baseline_count,
        "translation_drift": drift,
        "validation": validation,
        "update_window": {
            "date_field": date_field,
            "date_field_meaning": DATE_FIELDS[date_field],
            "from": start.isoformat(),
            "to": end.isoformat(),
            "query": window_query,
        },
        "new_records": {"count": new_count, "pmids": new_pmids},
        "prisma_s_update": (
            f"The PubMed search was updated on {end.isoformat()} by re-running the unchanged strategy, limited to "
            f"records with a {date_field.upper()} from {start.isoformat()} to {end.isoformat()} "
            f"({new_count} records retrieved for screening)."
        ),
        "note": "New records need screening against the locked protocol; this tool does not judge relevance.",
        "request_info": client.metadata(),
    }


def render_report(result: dict[str, Any]) -> str:
    drift = result["translation_drift"]
    window = result["update_window"]
    validation = result["validation"]
    lines = [
        f"# PubMed search update ({window['to']})",
        "",
        f"- **Verdict:** {result['verdict']}",
        f"- **Update window:** {window['from']} to {window['to']} by `{window['date_field']}` ({window['date_field_meaning']})",
        f"- **New records for screening:** {result['new_records']['count']}",
        f"- **Whole-strategy count:** {result['count']} (at build: {result['baseline_count']}; change {result['count_change']:+d})",
        f"- **Translation changed since the build:** {'yes' if drift['translation_changed'] else 'no'}",
    ]
    if validation.get("tested"):
        lines.append(
            f"- **Validation records:** {len(validation['retrieved'])} of {validation['pmid_count']} retrieved"
            + (f"; missed: {', '.join(validation['missed'])}" if validation["missed"] else "")
        )
    if drift["mappings_added"] or drift["mappings_removed"]:
        lines += ["", "## Term-mapping changes", ""]
        lines += [f"- Added: `{item}`" for item in drift["mappings_added"]]
        lines += [f"- Removed: `{item}`" for item in drift["mappings_removed"]]
    if drift["notices_appeared"] or drift["new_translation_warnings"]:
        lines += ["", "## New PubMed notices", ""]
        lines += [f"- `{name}`: {', '.join(values)}" for name, values in drift["notices_appeared"].items()]
        lines += [f"- `{item.get('code')}`: {item.get('evidence', item.get('message', ''))}" for item in drift["new_translation_warnings"]]
    if result["required_actions"]:
        lines += ["", "## Required before relying on this update", ""]
        lines += [f"- {action}" for action in result["required_actions"]]
    lines += ["", "## PRISMA-S update statement", "", result["prisma_s_update"], ""]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("check", help="Re-run a frozen strategy, check translation drift, and fetch new records.")
    run.add_argument("--strategy-file", required=True, help="The frozen final strategy that was searched at handoff.")
    run.add_argument("--baseline-search", required=True, help="The build's saved final `pubmed_tool.py search --output` JSON.")
    run.add_argument("--last-searched", required=True, help="Date of the last search (YYYY-MM-DD), from the audit's PRISMA-S dates.")
    run.add_argument("--until", help="End of the update window (YYYY-MM-DD); default today (UTC).")
    run.add_argument("--date-field", default="crdt", choices=sorted(DATE_FIELDS))
    validation = run.add_mutually_exclusive_group()
    validation.add_argument("--candidate-ledger", help="Re-test the build's development-validation records.")
    validation.add_argument("--validation-pmids", nargs="+", help="Re-test these PMIDs.")
    run.add_argument("--output", required=True, help="Update result JSON.")
    run.add_argument("--report", help="Optional Markdown report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Always live: a cached response would describe PubMed as it was, which is what is being checked.
    client = pubmed_tool.NcbiClient(cache=ResponseCache.disabled("search updates are always retrieved live"))
    try:
        pmids: list[str] = []
        source = ""
        if args.candidate_ledger:
            pmids, _meta = pubmed_tool.candidate_ledger_pmids(args.candidate_ledger, "validation")
            source = f"candidate-ledger:{args.candidate_ledger}"
        elif args.validation_pmids:
            pmids = pubmed_tool.dedup_preserving_order([str(value).strip() for value in args.validation_pmids])
            pubmed_tool.assert_numeric_pmids(pmids, source="--validation-pmids")
            source = "explicit-pmids"
        result = check(
            client,
            strategy_path=Path(args.strategy_file),
            baseline_path=Path(args.baseline_search),
            last_searched=args.last_searched,
            until=args.until,
            date_field=args.date_field,
            validation_pmids=pmids,
            validation_source=source,
        )
        write_json(Path(args.output), result)
        if args.report:
            report = Path(args.report)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(render_report(result), encoding="utf-8")
        receipt = {
            "operation": "search-update",
            "ok": True,
            "output": args.output,
            "report": args.report,
            "verdict": result["verdict"],
            "count": result["count"],
            "new_record_count": result["new_records"]["count"],
            "translation_changed": result["translation_drift"]["translation_changed"],
        }
    except (SearchUpdateError, pubmed_tool.PubMedError, OSError) as exc:
        receipt = {"operation": "search-update", "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
