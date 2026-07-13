#!/usr/bin/env python3
"""Optional trial-registry sentinel for detecting PubMed search leaks.

Registry records remain separate from PubMed discovery and term mining. After
eligibility screening and publication linkage, eligible PubMed-indexed PMIDs form
an external relative-recall benchmark; unpublished trials are audited separately.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
PMID_RE = re.compile(r"(?<!\d)([1-9]\d{4,9})(?!\d)")
DECISIONS = {"include", "exclude", "uncertain", "pending"}
ACTIVE_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING"}


class RegistryError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Could not read JSON {path}: {exc}") from exc


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protocol_binding(path: str | None, scope_version: int) -> dict[str, Any]:
    if not path:
        return {"scope_version": scope_version, "information_source_mode": "unspecified"}
    protocol = read_json(path)
    if not isinstance(protocol, dict) or protocol.get("scope_version") != scope_version:
        raise RegistryError("Protocol scope_version does not match --scope-version")
    mode = protocol.get("information_source_mode", "pubmed-only")
    external = protocol.get("external_validation") or {}
    if mode != "pubmed-plus-external-validation" or external.get("status") != "enabled":
        raise RegistryError("Protocol does not enable pubmed-plus-external-validation mode")
    return {
        "scope_version": scope_version,
        "protocol_id": protocol.get("protocol_id"),
        "protocol_sha256": canonical_sha256(protocol),
        "information_source_mode": mode,
        "external_validation": external,
    }


def http_json(url: str, *, timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "pubmed-search-builder/registry-sentinel"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegistryError(f"Registry/API request failed for {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"Registry/API response was not an object: {url}")
    return value


def dig(value: Any, *path: str, default: Any = None) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def all_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(all_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(all_strings(item))
    return found


def ctgov_reference_links(study: dict[str, Any]) -> list[dict[str, Any]]:
    """Build linked-publication seeds from ClinicalTrials.gov references, by type.

    ClinicalTrials.gov ``referencesModule`` mixes reference types: ``RESULT`` and
    ``DERIVED`` references are publications *of* the trial, while ``BACKGROUND``
    references are literature the trial merely *cites*. Only result/derived
    references are trial reports (high confidence, eligible for the relative-recall
    denominator). Background citations - and any untyped reference - are surfaced as
    ``uncertain`` links for human review and stay out of the denominator, so a cited
    background paper the strategy legitimately does not retrieve cannot masquerade as
    a missed trial report and block handoff.
    """
    references = dig(study, "protocolSection", "referencesModule", "references", default=[]) or []
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, bool]] = set()
    for reference in references:
        if not isinstance(reference, dict):
            continue
        ref_type = str(reference.get("type") or "").strip().upper()
        is_result = ref_type in {"RESULT", "DERIVED"}
        for pmid in PMID_RE.findall(str(reference.get("pmid") or "")):
            key = (pmid, is_result)
            if key in seen:
                continue
            seen.add(key)
            links.append({
                "pmid": pmid,
                "citation": str(reference.get("citation") or ""),
                "link_method": "registry-result-reference" if is_result else "registry-background-citation",
                "confidence": "high" if is_result else "uncertain",
                "reference_type": ref_type or "UNSPECIFIED",
                "pubmed_reachability": "indexed",
            })
    return links


def normalize_ctgov(study: dict[str, Any]) -> dict[str, Any]:
    protocol = study.get("protocolSection") or {}
    ident = protocol.get("identificationModule") or {}
    status_module = protocol.get("statusModule") or {}
    nct = str(ident.get("nctId") or "").strip()
    secondary = []
    for item in ident.get("secondaryIdInfos") or []:
        if isinstance(item, dict) and item.get("id"):
            secondary.append(str(item["id"]).strip())
    interventions = []
    for item in dig(protocol, "armsInterventionsModule", "interventions", default=[]) or []:
        if isinstance(item, dict) and item.get("name"):
            interventions.append(str(item["name"]).strip())
    return {
        "registry_sources": ["clinicaltrials.gov"],
        "registry_ids": sorted(set([nct, *secondary]) - {""}),
        "primary_registry_id": nct,
        "title": ident.get("briefTitle") or ident.get("officialTitle") or "",
        "conditions": dig(protocol, "conditionsModule", "conditions", default=[]) or [],
        "interventions": interventions,
        "recruitment_status": status_module.get("overallStatus") or "UNKNOWN",
        "has_registry_results": bool(study.get("hasResults")),
        "eligibility_decision": "pending",
        "eligibility_reason": "",
        "linked_publications": ctgov_reference_links(study),
        "raw_record": study,
    }


def clinicaltrials_search(
    query: str,
    *,
    page_size: int = 100,
    api_base: str = CTGOV_API,
    fetcher: Callable[[str], dict[str, Any]] = http_json,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    token = ""
    records: list[dict[str, Any]] = []
    raw_pages: list[dict[str, Any]] = []
    while True:
        params = {"query.term": query, "pageSize": str(page_size), "format": "json", "countTotal": "true"}
        if token:
            params["pageToken"] = token
        page = fetcher(api_base + "?" + urllib.parse.urlencode(params))
        raw_pages.append(page)
        studies = page.get("studies") or []
        if not isinstance(studies, list):
            raise RegistryError("ClinicalTrials.gov response field 'studies' was not a list")
        records.extend(normalize_ctgov(item) for item in studies if isinstance(item, dict))
        next_token = page.get("nextPageToken")
        if not next_token:
            break
        if str(next_token) == token:
            raise RegistryError("ClinicalTrials.gov repeated a page token; pagination stopped")
        token = str(next_token)
    return records, raw_pages


def pick(row: dict[str, Any], names: list[str]) -> str:
    lowered = {str(k).strip().lower(): str(v).strip() for k, v in row.items() if v is not None}
    for name in names:
        if lowered.get(name.lower()):
            return lowered[name.lower()]
    return ""


def normalize_ictrp_row(row: dict[str, Any]) -> dict[str, Any]:
    trial_id = pick(row, ["trial_id", "trialid", "trial id", "primary registry and trial identifying number", "registration number"])
    secondary = pick(row, ["secondary ids", "secondary_id", "secondary identifying numbers"])
    ids = [trial_id, *re.split(r"[;,|]", secondary)]
    ids = sorted({item.strip() for item in ids if item.strip()})
    return {
        "registry_sources": ["who-ictrp"],
        "registry_ids": ids,
        "primary_registry_id": trial_id,
        "title": pick(row, ["public title", "scientific title", "title"]),
        "conditions": [pick(row, ["health condition(s) or problem(s) studied", "condition", "conditions"])],
        "interventions": [pick(row, ["intervention(s)", "intervention", "interventions"])],
        "recruitment_status": pick(row, ["recruitment status", "status"]) or "UNKNOWN",
        "has_registry_results": pick(row, ["results available", "has results"]).lower() in {"yes", "true", "1"},
        "eligibility_decision": "pending",
        "eligibility_reason": "",
        "linked_publications": [],
        "raw_record": row,
    }


def import_ictrp(path: str) -> list[dict[str, Any]]:
    source = Path(path)
    if source.suffix.lower() == ".xml":
        root = ET.parse(source).getroot()
        rows = []
        candidates = list(root) if list(root) else [root]
        for record in candidates:
            row = {child.tag.split("}")[-1]: (child.text or "").strip() for child in record.iter() if child is not record}
            rows.append(row)
    else:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    return [normalize_ictrp_row(row) for row in rows if isinstance(row, dict)]


def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda r: (str(r.get("primary_registry_id") or ""), str(r.get("title") or ""))):
        ids = set(str(x) for x in record.get("registry_ids", []) if str(x))
        matches = [group for group in groups if ids & set(group.get("registry_ids", []))]
        if not matches:
            fresh = json.loads(json.dumps(record))
            fresh["source_records"] = [
                {"source": source, "raw_record": fresh.get("raw_record")}
                for source in fresh.get("registry_sources", [])
            ]
            groups.append(fresh)
            continue
        target = matches[0]
        for extra in matches[1:]:
            for key in ("registry_ids", "registry_sources", "linked_publications"):
                target[key] = target.get(key, []) + extra.get(key, [])
            groups.remove(extra)
        for key in ("registry_ids", "registry_sources", "linked_publications"):
            target[key] = target.get(key, []) + record.get(key, [])
        target.setdefault("source_records", []).extend(
            {"source": source, "raw_record": record.get("raw_record")}
            for source in record.get("registry_sources", [])
        )
        target["registry_ids"] = sorted(set(target["registry_ids"]))
        target["registry_sources"] = sorted(set(target["registry_sources"]))
        pubs = {json.dumps(pub, sort_keys=True): pub for pub in target["linked_publications"]}
        target["linked_publications"] = [pubs[key] for key in sorted(pubs)]
    for index, record in enumerate(groups, 1):
        record["trial_id"] = f"TRIAL-{index:05d}"
    return groups


def publication_class(record: dict[str, Any]) -> str:
    publications = record.get("linked_publications") or []
    if any(pub.get("pmid") for pub in publications if isinstance(pub, dict)):
        return "pubmed-indexed"
    if publications:
        return "published-non-pubmed"
    if record.get("has_registry_results"):
        return "registry-results-only"
    status = str(record.get("recruitment_status") or "").upper().replace(" ", "_")
    if status in ACTIVE_STATUSES:
        return "ongoing"
    if status == "COMPLETED":
        return "completed-no-results"
    if status in {"TERMINATED", "WITHDRAWN", "SUSPENDED"}:
        return "terminated"
    return "unknown"


def apply_links(records: list[dict[str, Any]], links: list[dict[str, Any]]) -> None:
    by_id = {rid: record for record in records for rid in record.get("registry_ids", [])}
    for link in links:
        rid = str(link.get("registry_id") or link.get("trial_id") or "")
        record = by_id.get(rid) or next((r for r in records if r.get("trial_id") == rid), None)
        if record is None:
            raise RegistryError(f"Publication link references unknown trial/registry ID {rid!r}")
        record.setdefault("linked_publications", []).append({
            "pmid": str(link.get("pmid") or ""),
            "citation": str(link.get("citation") or ""),
            "link_method": str(link.get("link_method") or "manual"),
            "confidence": str(link.get("confidence") or "uncertain"),
            "pubmed_reachability": str(link.get("pubmed_reachability") or ("indexed" if link.get("pmid") else "not-indexed")),
        })


def evaluate(records: list[dict[str, Any]], retrieved_pmids: set[str]) -> dict[str, Any]:
    denominator: set[str] = set()
    for record in records:
        decision = record.get("eligibility_decision", "pending")
        if decision not in DECISIONS or decision == "pending":
            raise RegistryError(f"Invalid eligibility decision {decision!r}")
        if not str(record.get("eligibility_reason") or "").strip():
            raise RegistryError(f"Eligibility reason is missing for trial {record.get('trial_id')!r}")
        record["publication_status"] = publication_class(record)
        record["final_strategy_retrieved"] = None
        if decision != "include":
            continue
        trial_hits = []
        for publication in record.get("linked_publications") or []:
            pmid = str(publication.get("pmid") or "")
            confidence = str(publication.get("confidence") or "").casefold()
            if pmid and confidence in {"high", "confirmed"}:
                denominator.add(pmid)
                hit = pmid in retrieved_pmids
                publication["final_strategy_retrieved"] = hit
                trial_hits.append(hit)
        if trial_hits:
            record["final_strategy_retrieved"] = all(trial_hits)
    hits = sorted(denominator & retrieved_pmids, key=int)
    misses = sorted(denominator - retrieved_pmids, key=int)
    eligible = [r for r in records if r.get("eligibility_decision") == "include"]
    return {
        "eligible_trials": len(eligible),
        "eligible_linked_pubmed_pmids": len(denominator),
        "retrieved_pmids": hits,
        "missed_pmids": misses,
        "relative_recall_percent": None if not denominator else round(100 * len(hits) / len(denominator), 2),
        "unresolved_pubmed_misses": misses,
        "ambiguous_link_count": sum(
            1
            for record in eligible
            for publication in (record.get("linked_publications") or [])
            if publication.get("pmid") and str(publication.get("confidence") or "").casefold() not in {"high", "confirmed"}
        ),
        "interpretation": (
            "No eligible registry trials were found; this provides no reassurance."
            if not eligible else
            "Eligible linked PubMed publications missed by the strategy require investigation. Non-PubMed, "
            "unpublished, registry-only, and ongoing trials are coverage findings, not PubMed query failures."
        ),
    }


def load_retrieved_pmids(path: str) -> set[str]:
    value = read_json(path)
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = value.get("retrieved_pmids") or value.get("pmids") or []
    else:
        raise RegistryError("Retrieved-PMIDs file must be a JSON list or object")
    return {str(item) for item in items if re.fullmatch(r"[1-9]\d*", str(item))}


def selftest() -> dict[str, Any]:
    pages = [
        {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT1", "briefTitle": "A"}, "statusModule": {"overallStatus": "COMPLETED"}}}], "nextPageToken": "next"},
        {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT2", "briefTitle": "B"}, "statusModule": {"overallStatus": "RECRUITING"}}}]},
    ]
    calls: list[str] = []
    def fake(url: str) -> dict[str, Any]:
        calls.append(url)
        return pages[len(calls) - 1]
    records, raw = clinicaltrials_search("condition AND psychotherapy", page_size=1, fetcher=fake)
    assert len(records) == 2 and len(raw) == 2 and "pageToken=next" in calls[1]
    records[0]["registry_ids"].append("SHARED")
    records[1]["registry_ids"].append("SHARED")
    merged = merge_records(records)
    assert len(merged) == 1 and set(merged[0]["registry_sources"]) == {"clinicaltrials.gov"}
    merged[0]["eligibility_decision"] = "include"
    merged[0]["eligibility_reason"] = "Eligible intervention trial"
    merged[0]["linked_publications"] = [{"pmid": "12345", "citation": "", "link_method": "test", "confidence": "high", "pubmed_reachability": "indexed"}]
    result = evaluate(merged, {"12345"})
    assert result["relative_recall_percent"] == 100.0 and not result["missed_pmids"]
    merged[0]["linked_publications"].append({"pmid": "67890", "citation": "", "link_method": "test", "confidence": "high", "pubmed_reachability": "indexed"})
    missed = evaluate(merged, {"12345"})
    assert missed["relative_recall_percent"] == 50.0 and missed["unresolved_pubmed_misses"] == ["67890"]
    non_pubmed = json.loads(json.dumps(merged[0]))
    non_pubmed["linked_publications"] = [{"pmid": "", "citation": "Journal report", "link_method": "manual", "confidence": "high", "pubmed_reachability": "not-indexed"}]
    assert publication_class(non_pubmed) == "published-non-pubmed"
    empty = evaluate([{**non_pubmed, "eligibility_decision": "exclude"}], set())
    assert empty["eligible_trials"] == 0 and "no reassurance" in empty["interpretation"].lower()
    try:
        clinicaltrials_search("x", fetcher=lambda _url: (_ for _ in ()).throw(RegistryError("mock failure")))
        raise AssertionError("expected mocked API failure")
    except RegistryError:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "ictrp.csv"
        csv_path.write_text("TrialID,Public title,Recruitment Status\nACTRN1,Trial C,Completed\n", encoding="utf-8")
        assert import_ictrp(str(csv_path))[0]["primary_registry_id"] == "ACTRN1"
        xml_path = Path(tmp) / "ictrp.xml"
        xml_path.write_text("<records><record><trial_id>ISRCTN1</trial_id><title>Trial D</title></record></records>", encoding="utf-8")
        assert import_ictrp(str(xml_path))[0]["primary_registry_id"] == "ISRCTN1"
        protocol_path = Path(tmp) / "protocol.json"
        protocol_path.write_text(json.dumps({"scope_version": 1, "protocol_id": "test", "information_source_mode": "pubmed-only"}), encoding="utf-8")
        try:
            protocol_binding(str(protocol_path), 1)
            raise AssertionError("pubmed-only protocol must reject registry execution")
        except RegistryError:
            pass
    return {"ok": True, "tests": 11}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ct = sub.add_parser("clinicaltrials-search")
    ct.add_argument("--query", required=True)
    ct.add_argument("--page-size", type=int, default=100)
    ct.add_argument("--api-base", default=CTGOV_API)
    ct.add_argument("--scope-version", type=int, required=True)
    ct.add_argument("--protocol-file", required=True)
    ct.add_argument("--output", required=True)
    ictrp = sub.add_parser("ictrp-import")
    ictrp.add_argument("--input", required=True)
    ictrp.add_argument("--scope-version", type=int, required=True)
    ictrp.add_argument("--protocol-file", required=True)
    ictrp.add_argument("--output", required=True)
    source_status = sub.add_parser("source-status")
    source_status.add_argument("--source", required=True)
    source_status.add_argument("--status", required=True, choices=["declined", "unavailable", "not-applicable"])
    source_status.add_argument("--reason", required=True)
    source_status.add_argument("--scope-version", type=int, required=True)
    source_status.add_argument("--protocol-file", required=True)
    source_status.add_argument("--output", required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--inputs", nargs="+", required=True)
    merge.add_argument("--scope-version", type=int, required=True)
    merge.add_argument("--protocol-file", required=True)
    merge.add_argument("--output", required=True)
    screen = sub.add_parser("screen")
    screen.add_argument("--ledger", required=True, help="Manually adjudicated registry ledger JSON")
    screen.add_argument("--scope-version", type=int, required=True)
    screen.add_argument("--protocol-file", required=True)
    screen.add_argument("--allow-uncertain", action="store_true")
    screen.add_argument("--output", required=True)
    link = sub.add_parser("link-pubmed")
    link.add_argument("--ledger", required=True)
    link.add_argument("--links-file", help="JSON list or {'links': [...]} of manually verified links")
    link.add_argument("--scope-version", type=int, required=True)
    link.add_argument("--protocol-file", required=True)
    link.add_argument("--output", required=True)
    ev = sub.add_parser("evaluate-pubmed")
    ev.add_argument("--ledger", required=True)
    ev.add_argument("--retrieved-pmids-file", required=True, help="PMIDs retrieved by the final PubMed strategy")
    ev.add_argument("--scope-version", type=int, required=True)
    ev.add_argument("--protocol-file", required=True)
    ev.add_argument("--output", required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    try:
        if args.command == "selftest":
            print(json.dumps(selftest(), indent=2))
            return 0
        binding = protocol_binding(args.protocol_file, args.scope_version)
        now = utc_now()
        if args.command == "clinicaltrials-search":
            records, pages = clinicaltrials_search(args.query, page_size=max(1, min(args.page_size, 1000)), api_base=args.api_base)
            parsed_base = urllib.parse.urlsplit(args.api_base)
            version_url = urllib.parse.urlunsplit((parsed_base.scheme, parsed_base.netloc, "/api/v2/version", "", ""))
            try:
                version = http_json(version_url)
            except RegistryError as exc:
                version = {"unavailable": str(exc)}
            artifact = {"operation": "registry-search", "source": "clinicaltrials.gov", "status": "complete", "interface": "ClinicalTrials.gov API v2", "api_base": args.api_base, "query": args.query, "run_utc": now, "data_as_of_utc": version.get("dataTimestamp"), "api_version": version, "record_count": len(records), "records": records, "raw_pages": pages, **binding}
        elif args.command == "ictrp-import":
            records = import_ictrp(args.input)
            artifact = {"operation": "registry-import", "source": "who-ictrp", "status": "complete", "interface": "user-supplied export", "input_file": str(Path(args.input).resolve()), "run_utc": now, "record_count": len(records), "records": records, **binding}
        elif args.command == "source-status":
            artifact = {"operation": "registry-source-status", "source": args.source, "status": args.status, "reason": args.reason, "run_utc": now, "records": [], **binding}
        elif args.command == "merge":
            inputs = [read_json(path) for path in args.inputs]
            for value in inputs:
                if value.get("scope_version") != args.scope_version:
                    raise RegistryError("Input registry artifact scope_version mismatch")
            records = merge_records([record for value in inputs for record in value.get("records", [])])
            artifact = {"operation": "registry-merge", "run_utc": now, "input_artifacts": args.inputs, "record_count": len(records), "records": records, **binding}
        elif args.command == "screen":
            source = read_json(args.ledger)
            if source.get("operation") != "registry-merge":
                raise RegistryError("screen requires a registry-merge ledger")
            records = source.get("records") or []
            bad = [r.get("trial_id") for r in records if r.get("eligibility_decision") not in DECISIONS - {"pending"}]
            uncertain = [r.get("trial_id") for r in records if r.get("eligibility_decision") == "uncertain"]
            missing_reason = [r.get("trial_id") for r in records if not str(r.get("eligibility_reason") or "").strip()]
            if bad or missing_reason or (uncertain and not args.allow_uncertain):
                raise RegistryError(f"Registry screening incomplete: invalid/pending={bad}, missing reasons={missing_reason}, uncertain={uncertain}")
            artifact = {"operation": "registry-screen", "run_utc": now, "screening_complete": True, "records": records, **binding}
        elif args.command == "link-pubmed":
            source = read_json(args.ledger)
            if source.get("operation") != "registry-screen" or source.get("screening_complete") is not True:
                raise RegistryError("link-pubmed requires a completed registry-screen artifact")
            records = source.get("records") or []
            if args.links_file:
                links_value = read_json(args.links_file)
                links = links_value if isinstance(links_value, list) else links_value.get("links", [])
                apply_links(records, links)
            for record in records:
                record["publication_status"] = publication_class(record)
            artifact = {"operation": "registry-publication-link", "run_utc": now, "records": records, **binding}
        else:
            source = read_json(args.ledger)
            if source.get("operation") != "registry-publication-link":
                raise RegistryError("evaluate-pubmed requires a registry-publication-link artifact")
            records = source.get("records") or []
            summary = evaluate(records, load_retrieved_pmids(args.retrieved_pmids_file))
            artifact = {"operation": "external-pubmed-benchmark", "run_utc": now, "retrieved_pmids_input": {"path": str(Path(args.retrieved_pmids_file).resolve()), "sha256": file_sha256(args.retrieved_pmids_file)}, "records": records, "summary": summary, "handoff_blocked": bool(summary["unresolved_pubmed_misses"]), **binding}
        write_json(args.output, artifact)
        print(json.dumps({"ok": True, "operation": artifact["operation"], "output": args.output, "record_count": len(artifact.get("records", []))}, indent=2))
        return 0
    except RegistryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
