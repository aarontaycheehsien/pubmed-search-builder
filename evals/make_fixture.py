#!/usr/bin/env python3
"""Create an eval fixture from any source of "known relevant" records.

The eval harness is source-agnostic: a fixture is just a question + a gold set
of relevant PMIDs + a protocol. CLEF TAR is one source; this helper builds a
fixture from any of:

  * PMIDs you already have (a published review's included studies, a curated set)
  * DOIs (resolved to PMIDs via PubMed [AID])
  * a "defining query" (its PubMed results become the gold set)

It resolves the gold set to a deduplicated PMID list, reports DOIs/PMIDs that do
not resolve or are not in PubMed, and writes ``datasets/<suite>/<id>.json`` with
a default protocol you can then tighten.

Examples:
  python evals/make_fixture.py --id MYREVIEW --question "..." \
      --gold-pmids 12345678 23456789 34567890

  python evals/make_fixture.py --id SR2024 --question-file q.txt \
      --gold-dois-file included_dois.txt --suite my-reviews

  python evals/make_fixture.py --id PRIORSEARCH --question "..." \
      --gold-query-file prior_search.txt --gold-retmax 500

Then build a strategy for it and score:
  python evals/generate.py MYREVIEW
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))

import run_eval  # noqa: E402  (reuses _run_tool / resolve_in_pubmed)

DEFAULT_TOOL = SKILL_DIR / "scripts" / "pubmed_tool.py"
DATASETS = HERE / "datasets"

DEFAULT_PROTOCOL = {
    "seeds": "none — proceed under the no-seed workflow",
    "framework": "choose the appropriate framework yourself (PICO / PECO / PIRD / PCC / SPIDER) for this question",
    "essential_concepts": "identify the essential concepts yourself; prefer fewer AND blocks per the skill's anti-pattern guidance",
    "optional_blocks": "decline materially-optional secondary AND blocks (outcomes, comparators, reference standards) unless central to scope",
    "methodological_filter": "none",
    "limits": "none (no date, language, species, or age limits)",
    "final_cleanup": "remove exact duplicate terms and genuinely zero-hit phrases (after ruling out typos); keep all recall-bearing terms; apply automatically without asking.",
    "no_seed_recall": "decline — do NOT run the optional heuristic recall estimation and do NOT ask; record it with `manifest_tool.py state resolve-recall-offer declined`",
}


def _read_tokens(path: Path) -> list[str]:
    """Read whitespace/comma/newline-separated tokens from a file."""
    raw = path.read_text(encoding="utf-8-sig")
    return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]


def _search_pmids(tool: Path, query: str, retmax: int) -> list[str]:
    fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    fh.write(query)
    fh.close()
    data = run_eval._run_tool(tool, ["search", "--query-file", fh.name, "--retmax", str(retmax)])
    return [str(p) for p in (data.get("pmids") or [])]


def resolve_dois(tool: Path, dois: list[str]) -> tuple[list[str], list[str]]:
    """Resolve each DOI to a PMID via PubMed [AID]. Returns (pmids, unresolved_dois)."""
    pmids: list[str] = []
    unresolved: list[str] = []
    for doi in dois:
        found = _search_pmids(tool, f'"{doi}"[AID]', 2)
        if found:
            pmids.append(found[0])
        else:
            unresolved.append(doi)
    return pmids, unresolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an eval fixture from any relevant-record source.")
    parser.add_argument("--id", required=True, help="Topic id (no dots), e.g. MYREVIEW.")
    q = parser.add_mutually_exclusive_group(required=True)
    q.add_argument("--question", help="Plain-language review question.")
    q.add_argument("--question-file", help="UTF-8 file containing the review question.")
    parser.add_argument("--suite", default="custom", help="Dataset subfolder / suite label (default: custom).")
    gold = parser.add_mutually_exclusive_group(required=True)
    gold.add_argument("--gold-pmids", nargs="+", help="Gold relevant PMIDs.")
    gold.add_argument("--gold-pmids-file", help="File of gold PMIDs (whitespace/comma/newline separated).")
    gold.add_argument("--gold-dois-file", help="File of gold DOIs (resolved to PMIDs via PubMed [AID]).")
    gold.add_argument("--gold-query-file", help="UTF-8 file with a query whose PubMed results define the gold set.")
    parser.add_argument("--gold-retmax", type=int, default=1000, help="Cap for --gold-query-file results (default: 1000).")
    parser.add_argument("--protocol-json", help="JSON file with a protocol object (else a default template is written).")
    parser.add_argument("--source", help="Free-text provenance note for the fixture.")
    parser.add_argument("--pubmed-tool", default=str(DEFAULT_TOOL))
    parser.add_argument("--force", action="store_true", help="Overwrite an existing fixture.")
    args = parser.parse_args(argv)

    if "." in args.id:
        raise SystemExit("topic id must not contain a dot (it would collide with auxiliary files).")
    tool = Path(args.pubmed_tool).resolve()
    if not tool.exists():
        raise SystemExit(f"pubmed_tool.py not found: {tool}")

    question = args.question or Path(args.question_file).read_text(encoding="utf-8").strip()

    unresolved_dois: list[str] = []
    gold_source = ""
    if args.gold_pmids:
        pmids = [str(p) for p in args.gold_pmids]
        gold_source = "PMIDs (CLI)"
    elif args.gold_pmids_file:
        pmids = _read_tokens(Path(args.gold_pmids_file))
        gold_source = f"PMIDs file ({args.gold_pmids_file})"
    elif args.gold_dois_file:
        dois = _read_tokens(Path(args.gold_dois_file))
        pmids, unresolved_dois = resolve_dois(tool, dois)
        gold_source = f"DOIs file ({args.gold_dois_file}); {len(pmids)}/{len(dois)} resolved via [AID]"
    else:  # gold_query_file
        query = Path(args.gold_query_file).read_text(encoding="utf-8")
        pmids = _search_pmids(tool, query, args.gold_retmax)
        gold_source = f"defining query ({args.gold_query_file}), retmax {args.gold_retmax}"

    pmids = run_eval.dedup_preserving_order(pmids) if hasattr(run_eval, "dedup_preserving_order") else list(dict.fromkeys(pmids))
    if not pmids:
        raise SystemExit("no gold PMIDs resolved — check the source input.")

    in_pubmed = run_eval.resolve_in_pubmed(tool, pmids)
    not_in_pubmed = [p for p in pmids if p not in in_pubmed]

    protocol = json.loads(Path(args.protocol_json).read_text(encoding="utf-8")) if args.protocol_json else dict(DEFAULT_PROTOCOL)

    fixture = {
        "id": args.id,
        "suite": args.suite,
        "question": question,
        "gold_relevant_pmids": [int(p) for p in pmids],
        "source": args.source or f"custom fixture; gold from {gold_source}",
        "gold_source": gold_source,
        "protocol": protocol,
        "seed_pmids_given_to_skill": [],
        "notes": "Created with make_fixture.py. No baseline strategy: use evals/generate.py (Phase 2). "
                 "Harness reports reachable vs. unreachable gold separately.",
    }
    if not args.protocol_json:
        fixture["protocol_note"] = "Auto-generated default protocol — review and tighten for this topic before running generate.py."
    if unresolved_dois:
        fixture["unresolved_dois"] = unresolved_dois

    out_dir = DATASETS / args.suite
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.id}.json"
    if out_path.exists() and not args.force:
        raise SystemExit(f"fixture already exists: {out_path} (use --force to overwrite)")
    out_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")

    print(f"[make_fixture] wrote {out_path}")
    print(f"[make_fixture] gold PMIDs: {len(pmids)}  in PubMed: {len(in_pubmed)}  not in PubMed: {len(not_in_pubmed)}")
    if not_in_pubmed:
        print(f"[make_fixture]   not in PubMed (excluded from recall denominator at score time): {', '.join(not_in_pubmed)}")
    if unresolved_dois:
        print(f"[make_fixture]   unresolved DOIs ({len(unresolved_dois)}): {', '.join(unresolved_dois[:10])}{' ...' if len(unresolved_dois) > 10 else ''}")
    if not args.protocol_json:
        print("[make_fixture] default protocol written - review/tighten it, then: "
              f"python evals/generate.py {args.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
