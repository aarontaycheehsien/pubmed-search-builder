#!/usr/bin/env python3
"""Orthogonal no-seed pilot discovery with provenance-blinded screening and saturation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import candidate_ledger
import pubmed_tool


PILOT_TYPES = {
    "mesh-led",
    "exact-phrase-led",
    "operational-description-led",
    "prior-review-led",
    "citation-registry-led",
    "historical-terminology-led",
}


class NoSeedDiscoveryError(ValueError):
    pass


def read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NoSeedDiscoveryError(f"Could not read JSON {path}: {exc}") from exc


def write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def protocol_binding(path: str | None, scope_version: int) -> dict[str, Any] | None:
    if not path:
        return None
    protocol_path = Path(path)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("dsl_version") != 1:
        raise NoSeedDiscoveryError("Protocol file must use dsl_version 1")
    if data.get("scope_version") != scope_version:
        raise NoSeedDiscoveryError("Protocol scope_version does not match --scope-version")
    protocol_id = str(data.get("protocol_id") or "").strip()
    if not protocol_id:
        raise NoSeedDiscoveryError("Protocol file requires protocol_id")
    return {
        "protocol_id": protocol_id,
        "protocol_sha256": hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "dsl_version": 1,
        "protocol_path": str(protocol_path),
    }


def load_pilots(path: str) -> list[dict[str, Any]]:
    raw = read_json(path)
    if not isinstance(raw, list) or not raw:
        raise NoSeedDiscoveryError("Pilots file must be a non-empty JSON list")
    pilots: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise NoSeedDiscoveryError(f"Pilot {index} must be an object")
        pilot_type = str(item.get("type") or "").strip().casefold()
        if pilot_type not in PILOT_TYPES or pilot_type in seen_types:
            raise NoSeedDiscoveryError(f"Pilot {index} has an invalid or duplicate type: {pilot_type!r}")
        query = pubmed_tool.normalize_query(str(item.get("query") or ""))
        anchors = pubmed_tool.dedup_preserving_order([str(value) for value in item.get("anchor_pmids", [])])
        if not query and not anchors:
            raise NoSeedDiscoveryError(f"Pilot {pilot_type!r} requires query or anchor_pmids")
        if query:
            pubmed_tool.assert_plain_query(pilot_type, query)
        pubmed_tool.assert_numeric_pmids(anchors, source=f"{pilot_type} anchor_pmids")
        seen_types.add(pilot_type)
        pilots.append({**item, "type": pilot_type, "query": query, "anchor_pmids": anchors})
    missing = sorted(PILOT_TYPES - seen_types)
    if missing:
        raise NoSeedDiscoveryError("Pilots file is missing orthogonal types: " + ", ".join(missing))
    return pilots


def blind_id(scope_version: int, pmid: str) -> str:
    return "C" + hashlib.sha256(f"scope:{scope_version}:pmid:{pmid}".encode("utf-8")).hexdigest()[:12].upper()


def discover(
    client: pubmed_tool.NcbiClient,
    pilots: list[dict[str, Any]],
    *,
    scope_version: int,
    round_number: int,
    previous_state: dict[str, Any] | None,
    safety_cap_per_pilot: int,
    binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    seen_pmids = {str(value) for value in (previous_state or {}).get("seen_pmids", [])}
    provenance: dict[str, dict[str, Any]] = {}
    pilot_receipts = []
    cap_reached = False
    for pilot in pilots:
        pilot_type = str(pilot["type"])
        found: list[str] = list(pilot.get("anchor_pmids") or [])
        query = str(pilot.get("query") or "")
        query_count = None
        pilot_cap_reached = False
        if query:
            search = pubmed_tool.esearch(client, query, retmax=safety_cap_per_pilot, retstart=0, sort=None)
            query_count = int(search.get("count", 0) or 0)
            pilot_cap_reached = query_count > safety_cap_per_pilot
            found.extend(str(value) for value in search.get("pmids", []))
        anchors = pubmed_tool.dedup_preserving_order(found)
        if pilot_type == "citation-registry-led" and anchors and pilot.get("expand_links", True):
            related = pubmed_tool.related_pmids(
                client,
                anchors,
                links=list(pilot.get("links") or ["similar", "citedin", "refs"]),
                max_per_seed=max(1, int(pilot.get("max_per_seed") or 20)),
                max_total=safety_cap_per_pilot,
            )
            found.extend(
                str(item.get("pmid"))
                for item in related.get("candidate_pmids", [])
                if isinstance(item, dict) and item.get("pmid")
            )
            pilot_cap_reached = pilot_cap_reached or int(related.get("candidate_count_before_cap", 0) or 0) > safety_cap_per_pilot
        cap_reached = cap_reached or pilot_cap_reached
        found = pubmed_tool.dedup_preserving_order(found)
        pilot_receipts.append(
            {
                "type": pilot_type,
                "label": pilot.get("label") or pilot_type,
                "query_count": query_count,
                "candidate_count": len(found),
                "safety_cap_reached": pilot_cap_reached,
            }
        )
        for pmid in found:
            entry = provenance.setdefault(
                pmid,
                {"pmid": pmid, "candidate_id": blind_id(scope_version, pmid), "pilot_types": [], "pilot_labels": []},
            )
            if pilot_type not in entry["pilot_types"]:
                entry["pilot_types"].append(pilot_type)
            label = str(pilot.get("label") or pilot_type)
            if label not in entry["pilot_labels"]:
                entry["pilot_labels"].append(label)

    new_pmids = sorted(set(provenance) - seen_pmids, key=int)
    fetched = pubmed_tool.efetch(client, new_pmids) if new_pmids else {"records": []}
    by_pmid = {
        str(record.get("pmid")): record
        for record in fetched.get("records", [])
        if isinstance(record, dict) and record.get("pmid")
    }
    screening_records = []
    provenance_records = []
    for pmid in new_pmids:
        record = by_pmid.get(pmid, {"pmid": pmid})
        candidate_id = blind_id(scope_version, pmid)
        screening_records.append(
            {
                "candidate_id": candidate_id,
                "pmid": pmid,
                "title": record.get("title", ""),
                "abstract": record.get("abstract", ""),
                "year": record.get("year", ""),
                "mesh_headings": record.get("mesh_headings", []),
                "keywords": record.get("keywords", []),
                "decision": "",
                "title_abstract_reviewed": False,
                "eligibility_reason": "",
            }
        )
        provenance_records.append(provenance[pmid])
    screening = {
        "operation": "orthogonal-pilot-screening",
        "scope_version": scope_version,
        "round": round_number,
        "provenance_blinded": True,
        "pilot_types_excluded_from_screening_view": sorted(PILOT_TYPES),
        "records": screening_records,
        "note": "Screen titles/abstracts without consulting the separate provenance map.",
    }
    provenance_output = {
        "operation": "orthogonal-pilot-provenance",
        "scope_version": scope_version,
        "round": round_number,
        "pilot_types": sorted(PILOT_TYPES),
        "pilot_receipts": pilot_receipts,
        "records": provenance_records,
        "retrieval_safety_cap_per_pilot": safety_cap_per_pilot,
        "safety_cap_reached": cap_reached,
        "note": "The cap is an operational safety ceiling, never the discovery stopping rule.",
    }
    if binding:
        public_binding = {key: value for key, value in binding.items() if key != "protocol_path"}
        screening.update(public_binding)
        provenance_output.update(public_binding)
    return screening, provenance_output


def vocabulary_from_records(records: list[dict[str, Any]]) -> set[str]:
    vocabulary: set[str] = set()
    for record in records:
        if record.get("decision") != "include":
            continue
        terms = set(pubmed_tool.record_keyword_set(record)) | set(pubmed_tool.record_mesh_set(record))
        terms |= set(pubmed_tool.record_phrase_set(record)) | set(pubmed_tool.record_acronym_set(record))
        vocabulary.update(pubmed_tool.normalize_for_match(term) for term in terms if pubmed_tool.normalize_for_match(term))
    return vocabulary


def adjudicate(
    screening: dict[str, Any],
    provenance: dict[str, Any],
    *,
    previous_state: dict[str, Any] | None,
    scope_version: int,
    required_saturated_rounds: int,
    allocation_seed: str,
    binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if screening.get("operation") != "orthogonal-pilot-screening" or screening.get("provenance_blinded") is not True:
        raise NoSeedDiscoveryError("Screening artifact is not a provenance-blinded orthogonal-pilot file")
    if screening.get("scope_version") != scope_version or provenance.get("scope_version") != scope_version:
        raise NoSeedDiscoveryError("Screening/provenance scope_version mismatch")
    if binding:
        for key in ("protocol_id", "protocol_sha256"):
            if screening.get(key) != binding.get(key) or provenance.get(key) != binding.get(key):
                raise NoSeedDiscoveryError(f"Screening/provenance {key} does not match the supplied protocol")
    provenance_by_id = {
        str(item.get("candidate_id")): item
        for item in provenance.get("records", [])
        if isinstance(item, dict)
    }
    current_records = []
    for index, record in enumerate(screening.get("records", []), start=1):
        if not isinstance(record, dict):
            raise NoSeedDiscoveryError(f"Screening record {index} must be an object")
        candidate_id = str(record.get("candidate_id") or "")
        if candidate_id not in provenance_by_id:
            raise NoSeedDiscoveryError(f"Screening record {index} has no matching provenance entry")
        decision = str(record.get("decision") or "").strip().casefold()
        if decision not in candidate_ledger.DECISIONS:
            raise NoSeedDiscoveryError(f"Screening record {index} decision must be include, exclude, or uncertain")
        if record.get("title_abstract_reviewed") is not True:
            raise NoSeedDiscoveryError(f"Screening record {index} must record title_abstract_reviewed=true")
        reason = str(record.get("eligibility_reason") or "").strip()
        if not reason:
            raise NoSeedDiscoveryError(f"Screening record {index} requires eligibility_reason")
        prov = provenance_by_id[candidate_id]
        current_records.append(
            {
                **record,
                "provenance_detail": {"pilot_types": prov.get("pilot_types", []), "pilot_labels": prov.get("pilot_labels", [])},
            }
        )
    previous_records = [item for item in (previous_state or {}).get("adjudicated_records", []) if isinstance(item, dict)]
    combined_by_pmid = {str(item.get("pmid")): item for item in previous_records + current_records if item.get("pmid")}
    combined = list(combined_by_pmid.values())
    previous_included = {str(value) for value in (previous_state or {}).get("included_pmids", [])}
    included = {str(item.get("pmid")) for item in combined if item.get("decision") == "include"}
    previous_vocabulary = {str(value) for value in (previous_state or {}).get("vocabulary_terms", [])}
    vocabulary = vocabulary_from_records(combined)
    new_included = sorted(included - previous_included, key=int)
    new_vocabulary = sorted(vocabulary - previous_vocabulary)
    round_saturated = not new_included and not new_vocabulary
    consecutive = int((previous_state or {}).get("consecutive_saturated_rounds") or 0) + 1 if round_saturated else 0
    # Every round reruns all required pilot families. A clean rerun resolves an earlier cap after
    # the pilot was narrowed/completed, while a cap in the current round still blocks saturation.
    cap_reached_any = provenance.get("safety_cap_reached") is True
    saturation_reached = consecutive >= max(1, required_saturated_rounds) and not cap_reached_any
    state = {
        "operation": "orthogonal-pilot-adjudication",
        "ok": True,
        "scope_version": scope_version,
        "round": screening.get("round"),
        "provenance_blinded": True,
        "pilot_types": sorted(PILOT_TYPES),
        "seen_pmids": sorted(combined_by_pmid, key=int),
        "included_pmids": sorted(included, key=int),
        "adjudicated_records": combined,
        "vocabulary_terms": sorted(vocabulary),
        "new_included_pmids": new_included,
        "new_vocabulary_terms": new_vocabulary,
        "new_vocabulary_term_count": len(new_vocabulary),
        "round_saturated": round_saturated,
        "consecutive_saturated_rounds": consecutive,
        "required_saturated_rounds": max(1, required_saturated_rounds),
        "safety_cap_reached_any": cap_reached_any,
        "saturation_reached": saturation_reached,
        "stopping_rule": "Stop only after consecutive rounds add neither screened-in studies nor vocabulary; a reached safety cap blocks saturation.",
        "ledger_frozen": False,
    }
    if binding:
        state.update({key: value for key, value in binding.items() if key != "protocol_path"})
    ledger = None
    if saturation_reached and included:
        ledger_records = []
        for item in combined:
            decision = str(item.get("decision"))
            ledger_records.append(
                {
                    "pmid": str(item.get("pmid")),
                    "provenance": "pilot-anchor",
                    "decision": decision,
                    "title_abstract_reviewed": True,
                    "eligibility_reason": str(item.get("eligibility_reason")),
                    "use": "both" if decision == "include" else "heuristic" if decision == "uncertain" else "neither",
                    "provenance_detail": item.get("provenance_detail", {}),
                }
            )
        ledger = {"scope_version": scope_version, "records": ledger_records}
        if binding:
            ledger.update({
                "artifact_type": "candidate-ledger",
                "artifact_version": 1,
                "protocol_id": binding["protocol_id"],
                "dsl_version": 1,
                "generated_from": {"path": binding["protocol_path"], "sha256": binding["protocol_sha256"]},
                "ledger_status": "screened",
            })
        ledger, allocation = candidate_ledger.allocate_holdout(ledger, seed=allocation_seed)
        issues, summary = candidate_ledger.validate_ledger(ledger)
        if issues:
            raise NoSeedDiscoveryError("Allocated candidate ledger failed validation: " + "; ".join(issues))
        state["ledger_frozen"] = True
        state["holdout_allocation"] = allocation
        state["candidate_ledger_summary"] = summary
    elif saturation_reached:
        state["stop_reason"] = "vocabulary-and-relevant-study saturation reached with no included candidates"
    return state, ledger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orthogonal pilot discovery for no-seed PubMed builds.")
    sub = parser.add_subparsers(dest="command", required=True)
    discover_parser = sub.add_parser("discover")
    discover_parser.add_argument("--pilots-file", required=True)
    discover_parser.add_argument("--scope-version", type=int, required=True)
    discover_parser.add_argument("--protocol-file")
    discover_parser.add_argument("--round", type=int, required=True)
    discover_parser.add_argument("--previous-state")
    discover_parser.add_argument("--safety-cap-per-pilot", type=int, default=500)
    discover_parser.add_argument("--screening-output", required=True)
    discover_parser.add_argument("--provenance-output", required=True)
    adjudicate_parser = sub.add_parser("adjudicate")
    adjudicate_parser.add_argument("--screening-file", required=True)
    adjudicate_parser.add_argument("--provenance-file", required=True)
    adjudicate_parser.add_argument("--previous-state")
    adjudicate_parser.add_argument("--scope-version", type=int, required=True)
    adjudicate_parser.add_argument("--protocol-file")
    adjudicate_parser.add_argument("--required-saturated-rounds", type=int, default=2)
    adjudicate_parser.add_argument("--allocation-seed", default="no-seed-orthogonal-pilots")
    adjudicate_parser.add_argument("--state-output", required=True)
    adjudicate_parser.add_argument("--ledger-output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        binding = protocol_binding(args.protocol_file, args.scope_version)
        previous = read_json(args.previous_state) if args.previous_state else None
        if previous is not None and not isinstance(previous, dict):
            raise NoSeedDiscoveryError("Previous state must be a JSON object")
        if args.command == "discover":
            pilots = load_pilots(args.pilots_file)
            screening, provenance = discover(
                pubmed_tool.NcbiClient(),
                pilots,
                scope_version=args.scope_version,
                round_number=max(1, args.round),
                previous_state=previous,
                safety_cap_per_pilot=max(1, args.safety_cap_per_pilot),
                binding=binding,
            )
            write_json(args.screening_output, screening)
            write_json(args.provenance_output, provenance)
            receipt = {
                "operation": "orthogonal-pilot-discover",
                "ok": True,
                "screening_output": args.screening_output,
                "provenance_output": args.provenance_output,
                "candidate_count": len(screening["records"]),
                "provenance_blinded": True,
            }
        else:
            screening = read_json(args.screening_file)
            provenance = read_json(args.provenance_file)
            if not isinstance(screening, dict) or not isinstance(provenance, dict):
                raise NoSeedDiscoveryError("Screening and provenance files must contain JSON objects")
            state, ledger = adjudicate(
                screening,
                provenance,
                previous_state=previous,
                scope_version=args.scope_version,
                required_saturated_rounds=max(1, args.required_saturated_rounds),
                allocation_seed=args.allocation_seed,
                binding=binding,
            )
            if ledger is not None:
                write_json(args.ledger_output, ledger)
                state["ledger_output"] = args.ledger_output
            write_json(args.state_output, state)
            receipt = {
                "operation": "orthogonal-pilot-adjudicate",
                "ok": True,
                "state_output": args.state_output,
                "saturation_reached": state["saturation_reached"],
                "ledger_frozen": state["ledger_frozen"],
                "ledger_output": args.ledger_output if ledger is not None else None,
            }
    except (NoSeedDiscoveryError, pubmed_tool.PubMedError, candidate_ledger.CandidateLedgerError, OSError) as exc:
        receipt = {"operation": args.command, "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
