#!/usr/bin/env python3
"""Turn a user's known-relevant articles into seed PMIDs they can confirm.

Seed intake asks for PMIDs, but people usually have DOIs, PMC links, or a reference list. This
tool resolves each line of such a list against PubMed and reports what it found, so the user
confirms the seed set instead of retyping it.

Identifiers resolve exactly and are verified against the fetched record: the record's own DOI or
PMCID must equal the one supplied, because PubMed does not index PMCIDs as a field and falls back
to All Fields. A free-text citation never resolves on its own: it returns ranked title candidates
for the user to choose from, since a wrong seed would steer discovery and validation. Resolution
does not screen anything; seeds are still screened against the locked protocol like any other
candidate, and seed status stays the user's decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pubmed_tool  # noqa: E402

DOI_PATTERN = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
PMCID_PATTERN = re.compile(r"\b(PMC\d{4,10})\b", re.IGNORECASE)
PMID_PATTERN = re.compile(r"^(?:pmid\s*:?\s*)?(\d{1,9})$", re.IGNORECASE)
TITLE_STOPWORDS = frozenset(
    "a an and are as at be by for from in into is of on or the to with without via versus vs its their "
    "et al journal doi vol issue pp pages".split()
)
MAX_TITLE_WORDS = 10
MAX_CANDIDATES = 3
CANDIDATE_POOL = 20


class SeedResolutionError(ValueError):
    pass


def classify(line: str) -> tuple[str, str]:
    """Return (kind, value): pmid, doi, pmcid, or citation."""

    text = line.strip()
    pmid = PMID_PATTERN.match(text)
    if pmid:
        return "pmid", pmid.group(1)
    doi = DOI_PATTERN.search(text)
    if doi:
        return "doi", doi.group(1).rstrip(".,;)]")
    pmcid = PMCID_PATTERN.search(text)
    if pmcid:
        return "pmcid", pmcid.group(1).upper()
    return "citation", text


def title_segment(text: str) -> str:
    """The part of a citation most likely to be its title.

    A quoted title wins. Otherwise the citation is split at sentence breaks, and the segment with
    the most words is taken: in Vancouver and APA styles the author list, journal, and volume
    fragments are all shorter than the title.
    """

    quoted = re.search(r"[\"“]([^\"”]{12,})[\"”]", text)
    if quoted:
        return quoted.group(1)
    segments = [segment for segment in re.split(r"(?<=[.?!])\s+|\(\d{4}[a-z]?\)", text) if segment.strip()]
    return max(segments, key=lambda segment: len(re.findall(r"[A-Za-z]{3,}", segment)), default=text)


def title_words(text: str) -> list[str]:
    words = [
        word for word in re.findall(r"[A-Za-z0-9]+", title_segment(text))
        if len(word) >= 3 and word.casefold() not in TITLE_STOPWORDS
    ]
    return words[:MAX_TITLE_WORDS]


def token_set(text: str) -> set[str]:
    return {word.casefold() for word in re.findall(r"[A-Za-z0-9]+", str(text)) if len(word) >= 3}


def title_overlap(citation: str, title: str) -> float:
    """Share of the candidate title's words that appear in the citation text."""

    title_tokens = token_set(title)
    return round(len(title_tokens & token_set(citation)) / len(title_tokens), 3) if title_tokens else 0.0


IDENTITY_FIELDS = ("pmid", "doi", "pmcid")
CONTENT_FIELDS = ("title", "journal", "year")


def record_summary(record: dict[str, Any], *, identifiers_only: bool = False) -> dict[str, Any]:
    fields = IDENTITY_FIELDS if identifiers_only else IDENTITY_FIELDS + CONTENT_FIELDS
    return {key: record.get(key, "") for key in fields}


def resolve(client: pubmed_tool.NcbiClient, lines: list[str], *, identifiers_only: bool = False) -> dict[str, Any]:
    """Resolve seed lines. ``identifiers_only`` is the pre-scope-lock mode: it verifies DOIs,
    PMCIDs, and PMIDs but reports no titles or journals, and defers citations until after lock,
    so seed content cannot shape the scope."""

    items: list[dict[str, Any]] = []
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        kind, value = classify(text)
        item: dict[str, Any] = {"input": text, "kind": kind, "value": value}
        if kind == "pmid":
            item["search_pmids"] = [value]
        elif kind == "doi":
            item["search_pmids"] = [str(p) for p in pubmed_tool.esearch(client, f'"{value}"[doi]', 5, 0, None).get("pmids", [])]
        elif kind == "pmcid":
            item["search_pmids"] = [str(p) for p in pubmed_tool.esearch(client, value, 5, 0, None).get("pmids", [])]
        elif identifiers_only:
            item.update(status="deferred", reason="citations are resolved after scope lock, when titles may be shown")
            items.append(item)
            continue
        else:
            words = title_words(value)
            if len(words) < 3:
                item.update(status="not-found", reason="too few title words to search; supply the DOI or PMID")
                items.append(item)
                continue
            query = " AND ".join(f"{word}[ti]" for word in words)
            pmids = pubmed_tool.esearch(client, query, CANDIDATE_POOL, 0, None).get("pmids", [])
            if not pmids and len(words) > 6:
                query = " AND ".join(f"{word}[ti]" for word in words[:6])
                pmids = pubmed_tool.esearch(client, query, CANDIDATE_POOL, 0, None).get("pmids", [])
            item["title_query"] = query
            item["search_pmids"] = [str(p) for p in pmids]
        items.append(item)

    wanted = pubmed_tool.dedup_preserving_order([pmid for item in items for pmid in item.get("search_pmids", [])])
    records = {}
    if wanted:
        records = {str(r.get("pmid")): r for r in pubmed_tool.efetch(client, wanted).get("records", [])}

    for item in items:
        if "status" in item:
            continue
        found = [records[p] for p in item.pop("search_pmids", []) if p in records]
        kind, value = item["kind"], item["value"]
        if kind == "citation":
            ranked = sorted(found, key=lambda r: (-title_overlap(value, str(r.get("title"))), str(r.get("pmid"))))
            item["candidates"] = [
                {**record_summary(r), "title_overlap": title_overlap(value, str(r.get("title")))} for r in ranked[:MAX_CANDIDATES]
            ]
            if item["candidates"]:
                item["status"] = "needs-confirmation"
            else:
                item.update(status="not-found", reason="no PubMed title matches; supply the DOI or PMID")
            continue
        if kind == "doi":
            found = [r for r in found if str(r.get("doi") or "").casefold() == value.casefold()]
        elif kind == "pmcid":
            found = [r for r in found if str(r.get("pmcid") or "").upper() == value]
        if len(found) == 1:
            item.update(status="resolved", pmid=str(found[0].get("pmid")), record=record_summary(found[0], identifiers_only=identifiers_only))
        elif found:
            item.update(status="ambiguous", candidates=[record_summary(r, identifiers_only=identifiers_only) for r in found])
        else:
            item.update(status="not-found", reason=f"no PubMed record carries this {kind}")

    resolved = pubmed_tool.dedup_preserving_order([item["pmid"] for item in items if item.get("status") == "resolved"])
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "operation": "seed-resolution",
        "ok": True,
        "items": items,
        "status_counts": dict(sorted(counts.items())),
        "resolved_pmids": resolved,
        "needs_user_confirmation": [item["input"] for item in items if item["status"] in {"needs-confirmation", "ambiguous"}],
        "not_found": [item["input"] for item in items if item["status"] == "not-found"],
        "deferred": [item["input"] for item in items if item["status"] == "deferred"],
        "identifiers_only": identifiers_only,
        "note": (
            "Identifier matches are exact and verified against the record. Citation lines only return candidates: "
            "show them to the user and add a PMID only when the user confirms it. Seeds are still screened against "
            "the locked protocol, and seed status stays the user's decision."
        ),
        "request_info": client.metadata(),
    }


def render_table(result: dict[str, Any]) -> str:
    lines = ["| Input | Status | PMID | Title | Journal (year) |", "|---|---|---|---|---|"]
    for item in result["items"]:
        cell = lambda value: str(value).replace("|", "\\|")  # noqa: E731
        if item.get("record"):
            record = item["record"]
            title = cell(str(record.get("title", ""))[:90]) or "(not shown before scope lock)"
            source = f"{cell(record.get('journal', ''))} ({record.get('year', '')})" if record.get("journal") else ""
            lines.append(f"| {cell(item['input'][:60])} | {item['status']} | {record['pmid']} | {title} | {source} |")
        elif item.get("candidates"):
            for index, candidate in enumerate(item["candidates"]):
                label = cell(item["input"][:60]) if index == 0 else ""
                status = item["status"] if index == 0 else ""
                lines.append(f"| {label} | {status} | {candidate['pmid']}? | {cell(candidate['title'][:90])} | {cell(candidate['journal'])} ({candidate['year']}) |")
        else:
            lines.append(f"| {cell(item['input'][:60])} | {item['status']} | | {cell(item.get('reason', ''))} | |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-file", help="One DOI, PMID, PMCID, or citation per line ('-' for stdin).")
    source.add_argument("--item", action="append", help="One DOI, PMID, PMCID, or citation; repeatable.")
    parser.add_argument("--output", required=True, help="Resolution JSON.")
    parser.add_argument("--table", help="Optional Markdown table to show the user for confirmation.")
    parser.add_argument(
        "--identifiers-only",
        action="store_true",
        help="Pre-scope-lock mode: verify DOIs/PMCIDs/PMIDs without reporting titles; defer citations.",
    )
    args = parser.parse_args(argv)
    try:
        lines = args.item if args.item else pubmed_tool.read_text_source(args.input_file).splitlines()
        if not any(line.strip() and not line.strip().startswith("#") for line in lines):
            raise SeedResolutionError("No seed lines to resolve")
        client = pubmed_tool.NcbiClient()
        result = resolve(client, lines, identifiers_only=args.identifiers_only)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.table:
            Path(args.table).write_text(render_table(result), encoding="utf-8")
        receipt = {
            "operation": "seed-resolution",
            "ok": True,
            "output": args.output,
            "status_counts": result["status_counts"],
            "resolved_pmids": result["resolved_pmids"],
            "needs_user_confirmation": len(result["needs_user_confirmation"]),
        }
    except (SeedResolutionError, pubmed_tool.PubMedError, OSError) as exc:
        receipt = {"operation": "seed-resolution", "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
