#!/usr/bin/env python3
"""Validate and compile the review protocol and searchable-scope DSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


DSL_VERSION = 1
ARTIFACT_VERSION = 1
ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
PROTOCOL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SEED_ROLES = {"discovery-candidate", "holdout-candidate", "both-candidate", "heuristic"}
CONCEPT_ROLES = {"essential", "optional"}
FRAGILITY = {"stable", "fragile", "very_fragile"}
DECISION_TYPES = {"filter", "limit"}
DECISION_STATUSES = {"selected", "rejected"}

ROOT_KEYS = {
    "dsl_version", "protocol_id", "scope_version", "version_change", "review",
    "eligibility", "searchable_scope", "screening_only", "filters_and_limits",
    "date_boundaries", "seeds", "priorities", "focused_variants",
}


class ProtocolError(ValueError):
    """Raised for invalid protocols, compilation drift, and verification failures."""


def canonical_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 representation used for protocol identity."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolError(f"JSON file {path} must contain an object")
    return value


def _unknown(obj: dict[str, Any], allowed: set[str], path: str, issues: list[str]) -> None:
    for key in sorted(obj):
        if key not in allowed and not key.startswith("x-"):
            issues.append(f"{path}.{key} is not permitted (extensions must use x-*)")


def _object(value: Any, path: str, allowed: set[str], required: set[str], issues: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(f"{path} must be an object")
        return {}
    _unknown(value, allowed, path, issues)
    for key in sorted(required - value.keys()):
        issues.append(f"{path}.{key} is required")
    return value


def _array(value: Any, path: str, issues: list[str]) -> list[Any]:
    if not isinstance(value, list):
        issues.append(f"{path} must be an array")
        return []
    return value


def _text(value: Any, path: str, issues: list[str], *, lock: bool = False) -> str:
    if not isinstance(value, str):
        issues.append(f"{path} must be a string")
        return ""
    if lock and not value.strip():
        issues.append(f"{path} must not be empty in lock mode")
    return value.strip()


def _id(value: Any, path: str, issues: list[str], *, lock: bool) -> str:
    text = _text(value, path, issues, lock=lock)
    if text and not ID_RE.fullmatch(text):
        issues.append(f"{path} must use lowercase letters, digits, underscores, or hyphens and start with a letter")
    return text


def _ids(items: list[Any], path: str, issues: list[str], *, lock: bool) -> list[str]:
    values = [_id(value, f"{path}[{index}]", issues, lock=lock) for index, value in enumerate(items)]
    seen: set[str] = set()
    for value in values:
        if value and value in seen:
            issues.append(f"{path} contains duplicate ID {value!r}")
        seen.add(value)
    return values


def _iso_date(value: Any, path: str, issues: list[str]) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        issues.append(f"{path} must be an ISO date or null")
        return None
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        issues.append(f"{path} must be an ISO date in YYYY-MM-DD form")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(f"{path} must be an ISO date in YYYY-MM-DD form")
        return None


def _named_records(
    value: Any,
    path: str,
    allowed: set[str],
    required: set[str],
    issues: list[str],
    *,
    lock: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, raw in enumerate(_array(value, path, issues)):
        item_path = f"{path}[{index}]"
        item = _object(raw, item_path, allowed, required, issues)
        if not item:
            continue
        ids.append(_id(item.get("id"), f"{item_path}.id", issues, lock=lock))
        records.append(item)
    _ids(ids, f"{path} IDs", issues, lock=lock)
    return records, ids


def validate_protocol(data: dict[str, Any], mode: str = "lock") -> list[str]:
    """Return deterministic structural and semantic validation issues."""
    if mode not in {"draft", "lock"}:
        raise ProtocolError("validation mode must be draft or lock")
    lock = mode == "lock"
    issues: list[str] = []
    if not isinstance(data, dict):
        return ["protocol must be an object"]
    _unknown(data, ROOT_KEYS, "$", issues)
    for key in sorted(ROOT_KEYS - data.keys()):
        issues.append(f"$.{key} is required")

    if data.get("dsl_version") != DSL_VERSION:
        issues.append(f"$.dsl_version must be {DSL_VERSION}")
    protocol_id = _text(data.get("protocol_id"), "$.protocol_id", issues, lock=lock)
    if protocol_id and not PROTOCOL_ID_RE.fullmatch(protocol_id):
        issues.append("$.protocol_id has an invalid identifier")
    scope_version = data.get("scope_version")
    if not isinstance(scope_version, int) or isinstance(scope_version, bool) or scope_version < 1:
        issues.append("$.scope_version must be a positive integer")

    change = _object(data.get("version_change"), "$.version_change",
                     {"previous_scope_version", "reason", "decision_source"},
                     {"previous_scope_version", "reason", "decision_source"}, issues)
    previous = change.get("previous_scope_version")
    if previous is not None and (not isinstance(previous, int) or isinstance(previous, bool) or previous < 1):
        issues.append("$.version_change.previous_scope_version must be a positive integer or null")
    _text(change.get("reason"), "$.version_change.reason", issues, lock=lock)
    _text(change.get("decision_source"), "$.version_change.decision_source", issues, lock=lock)
    if isinstance(scope_version, int) and scope_version >= 1:
        expected = None if scope_version == 1 else scope_version - 1
        if previous != expected:
            issues.append(f"$.version_change.previous_scope_version must be {expected!r} for scope version {scope_version}")

    review = _object(data.get("review"), "$.review", {"question", "framework"}, {"question", "framework"}, issues)
    _text(review.get("question"), "$.review.question", issues, lock=lock)
    framework = _object(review.get("framework"), "$.review.framework", {"name", "rationale", "slots"},
                        {"name", "rationale", "slots"}, issues)
    _text(framework.get("name"), "$.review.framework.name", issues, lock=lock)
    _text(framework.get("rationale"), "$.review.framework.rationale", issues, lock=lock)
    slots, slot_ids = _named_records(framework.get("slots"), "$.review.framework.slots",
                                     {"id", "label", "description"}, {"id", "label", "description"}, issues, lock=lock)
    for index, slot in enumerate(slots):
        _text(slot.get("label"), f"$.review.framework.slots[{index}].label", issues, lock=lock)
        _text(slot.get("description"), f"$.review.framework.slots[{index}].description", issues, lock=lock)
    if lock and not slots:
        issues.append("$.review.framework.slots must contain at least one slot in lock mode")

    eligibility = _object(data.get("eligibility"), "$.eligibility", {"inclusion", "exclusion"},
                          {"inclusion", "exclusion"}, issues)
    criteria: list[dict[str, Any]] = []
    criterion_ids: list[str] = []
    for kind in ("inclusion", "exclusion"):
        rows, row_ids = _named_records(eligibility.get(kind), f"$.eligibility.{kind}",
                                       {"id", "label", "description"}, {"id", "label", "description"}, issues, lock=lock)
        criteria.extend(rows)
        criterion_ids.extend(row_ids)
        for index, row in enumerate(rows):
            _text(row.get("label"), f"$.eligibility.{kind}[{index}].label", issues, lock=lock)
            _text(row.get("description"), f"$.eligibility.{kind}[{index}].description", issues, lock=lock)
    _ids(criterion_ids, "$.eligibility criterion IDs", issues, lock=lock)
    if lock and not criteria:
        issues.append("$.eligibility must define at least one criterion in lock mode")

    searchable = _object(data.get("searchable_scope"), "$.searchable_scope", {"concepts"}, {"concepts"}, issues)
    concepts, concept_ids = _named_records(
        searchable.get("concepts"), "$.searchable_scope.concepts",
        {"id", "label", "role", "eligibility_refs", "framework_slots", "definition", "rationale", "provisional_fragility", "term_families"},
        {"id", "label", "role", "eligibility_refs", "framework_slots", "definition", "rationale", "provisional_fragility"}, issues, lock=lock)
    concept_roles: dict[str, str] = {}
    for index, concept in enumerate(concepts):
        base = f"$.searchable_scope.concepts[{index}]"
        cid = str(concept.get("id") or "")
        role = concept.get("role")
        if role not in CONCEPT_ROLES:
            issues.append(f"{base}.role must be essential or optional")
        if cid:
            concept_roles[cid] = str(role or "")
        _text(concept.get("label"), f"{base}.label", issues, lock=lock)
        _text(concept.get("definition"), f"{base}.definition", issues, lock=lock)
        _text(concept.get("rationale"), f"{base}.rationale", issues, lock=lock)
        if concept.get("provisional_fragility") not in FRAGILITY:
            issues.append(f"{base}.provisional_fragility must be stable, fragile, or very_fragile")
        eligibility_refs = _ids(_array(concept.get("eligibility_refs"), f"{base}.eligibility_refs", issues),
                                f"{base}.eligibility_refs", issues, lock=lock)
        framework_refs = _ids(_array(concept.get("framework_slots"), f"{base}.framework_slots", issues),
                              f"{base}.framework_slots", issues, lock=lock)
        for ref in eligibility_refs:
            if ref and ref not in criterion_ids:
                issues.append(f"{base}.eligibility_refs references unknown criterion {ref!r}")
        for ref in framework_refs:
            if ref and ref not in slot_ids:
                issues.append(f"{base}.framework_slots references unknown slot {ref!r}")
        if lock and not framework_refs:
            issues.append(f"{base}.framework_slots must not be empty in lock mode")
        if "term_families" in concept:
            for term_index, term in enumerate(_array(concept.get("term_families"), f"{base}.term_families", issues)):
                _text(term, f"{base}.term_families[{term_index}]", issues, lock=lock)
    if lock and not any(role == "essential" for role in concept_roles.values()):
        issues.append("$.searchable_scope.concepts must contain at least one essential concept in lock mode")

    screening = _object(data.get("screening_only"), "$.screening_only", {"properties"}, {"properties"}, issues)
    screening_rows, screening_ids = _named_records(
        screening.get("properties"), "$.screening_only.properties",
        {"id", "label", "eligibility_refs", "instructions", "recall_rationale"},
        {"id", "label", "eligibility_refs", "instructions", "recall_rationale"}, issues, lock=lock)
    for index, row in enumerate(screening_rows):
        base = f"$.screening_only.properties[{index}]"
        _text(row.get("label"), f"{base}.label", issues, lock=lock)
        _text(row.get("instructions"), f"{base}.instructions", issues, lock=lock)
        _text(row.get("recall_rationale"), f"{base}.recall_rationale", issues, lock=lock)
        for ref in _ids(_array(row.get("eligibility_refs"), f"{base}.eligibility_refs", issues),
                        f"{base}.eligibility_refs", issues, lock=lock):
            if ref and ref not in criterion_ids:
                issues.append(f"{base}.eligibility_refs references unknown criterion {ref!r}")

    filters = _object(data.get("filters_and_limits"), "$.filters_and_limits", {"decisions"}, {"decisions"}, issues)
    decisions, decision_ids = _named_records(
        filters.get("decisions"), "$.filters_and_limits.decisions",
        {"id", "type", "label", "status", "value", "validated_source", "rationale"},
        {"id", "type", "label", "status", "value", "validated_source", "rationale"}, issues, lock=lock)
    for index, decision in enumerate(decisions):
        base = f"$.filters_and_limits.decisions[{index}]"
        if decision.get("type") not in DECISION_TYPES:
            issues.append(f"{base}.type must be filter or limit")
        if decision.get("status") not in DECISION_STATUSES:
            issues.append(f"{base}.status must be selected or rejected")
        _text(decision.get("label"), f"{base}.label", issues, lock=lock)
        _text(decision.get("rationale"), f"{base}.rationale", issues, lock=lock)
        source = decision.get("validated_source")
        if source is not None and not isinstance(source, str):
            issues.append(f"{base}.validated_source must be a string or null")
        if lock and decision.get("type") == "filter" and decision.get("status") == "selected" and not str(source or "").strip():
            issues.append(f"{base}.validated_source is required for a selected filter")
        selected_value = decision.get("value")
        if lock and decision.get("status") == "selected" and (
            selected_value is None or (isinstance(selected_value, str) and not selected_value.strip())
        ):
            issues.append(f"{base}.value is required for a selected decision")

    dates = _object(data.get("date_boundaries"), "$.date_boundaries", {"eligibility", "search", "rationale"},
                    {"eligibility", "search", "rationale"}, issues)
    date_values: dict[str, tuple[date | None, date | None]] = {}
    raw_ranges: dict[str, dict[str, Any]] = {}
    for kind in ("eligibility", "search"):
        date_range = _object(dates.get(kind), f"$.date_boundaries.{kind}", {"start", "end"}, {"start", "end"}, issues)
        raw_ranges[kind] = date_range
        start = _iso_date(date_range.get("start"), f"$.date_boundaries.{kind}.start", issues)
        end = _iso_date(date_range.get("end"), f"$.date_boundaries.{kind}.end", issues)
        date_values[kind] = (start, end)
        if start and end and start > end:
            issues.append(f"$.date_boundaries.{kind} start must not be after end")
    date_rationale = _text(dates.get("rationale"), "$.date_boundaries.rationale", issues, lock=False)
    if lock and raw_ranges.get("search") != raw_ranges.get("eligibility") and not date_rationale:
        issues.append("$.date_boundaries.rationale is required when search and eligibility dates differ")

    seeds = _object(data.get("seeds"), "$.seeds", {"records"}, {"records"}, issues)
    seen_pmids: set[str] = set()
    for index, raw in enumerate(_array(seeds.get("records"), "$.seeds.records", issues)):
        base = f"$.seeds.records[{index}]"
        seed = _object(raw, base, {"pmid", "role", "rationale"}, {"pmid", "role", "rationale"}, issues)
        if not seed:
            continue
        pmid = _text(seed.get("pmid"), f"{base}.pmid", issues, lock=lock)
        if pmid and not re.fullmatch(r"[1-9][0-9]*", pmid):
            issues.append(f"{base}.pmid must contain digits and not start with zero")
        if pmid in seen_pmids:
            issues.append(f"{base}.pmid duplicates PMID {pmid}")
        seen_pmids.add(pmid)
        if seed.get("role") not in SEED_ROLES:
            issues.append(f"{base}.role is invalid")
        _text(seed.get("rationale"), f"{base}.rationale", issues, lock=lock)

    priorities = _object(data.get("priorities"), "$.priorities", {"recall", "workload"}, {"recall", "workload"}, issues)
    recall = _object(priorities.get("recall"), "$.priorities.recall", {"policy", "minimum_heldout_recall"},
                     {"policy", "minimum_heldout_recall"}, issues)
    _text(recall.get("policy"), "$.priorities.recall.policy", issues, lock=lock)
    threshold = recall.get("minimum_heldout_recall")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 <= threshold <= 1:
        issues.append("$.priorities.recall.minimum_heldout_recall must be between 0 and 1")
    workload = _object(priorities.get("workload"), "$.priorities.workload", {"policy", "selection_rule"},
                       {"policy", "selection_rule"}, issues)
    _text(workload.get("policy"), "$.priorities.workload.policy", issues, lock=lock)
    _text(workload.get("selection_rule"), "$.priorities.workload.selection_rule", issues, lock=lock)

    variants, variant_ids = _named_records(
        data.get("focused_variants"), "$.focused_variants",
        {"id", "label", "optional_concept_ids", "filter_limit_ids", "excluded_concept_ids", "rationale"},
        {"id", "label", "optional_concept_ids", "filter_limit_ids", "excluded_concept_ids", "rationale"}, issues, lock=lock)
    for index, variant in enumerate(variants):
        base = f"$.focused_variants[{index}]"
        _text(variant.get("label"), f"{base}.label", issues, lock=lock)
        _text(variant.get("rationale"), f"{base}.rationale", issues, lock=lock)
        optionals = _ids(_array(variant.get("optional_concept_ids"), f"{base}.optional_concept_ids", issues),
                         f"{base}.optional_concept_ids", issues, lock=lock)
        decision_refs = _ids(_array(variant.get("filter_limit_ids"), f"{base}.filter_limit_ids", issues),
                             f"{base}.filter_limit_ids", issues, lock=lock)
        excluded = _ids(_array(variant.get("excluded_concept_ids"), f"{base}.excluded_concept_ids", issues),
                        f"{base}.excluded_concept_ids", issues, lock=lock)
        if lock and not optionals and not decision_refs:
            issues.append(f"{base} must add at least one optional concept, filter, or limit")
        for ref in optionals:
            if concept_roles.get(ref) != "optional":
                issues.append(f"{base}.optional_concept_ids must reference optional concept {ref!r}")
        for ref in decision_refs:
            if ref not in decision_ids:
                issues.append(f"{base}.filter_limit_ids references unknown decision {ref!r}")
        for ref in excluded:
            if ref not in concept_roles:
                issues.append(f"{base}.excluded_concept_ids references unknown concept {ref!r}")
            elif concept_roles[ref] == "essential":
                issues.append(f"{base} may not exclude essential concept {ref!r}")

    migration = data.get("x-migration")
    if lock and isinstance(migration, dict) and migration.get("unresolved"):
        issues.append("$.x-migration.unresolved must be resolved before lock")
    return sorted(set(issues))


def require_valid(data: dict[str, Any], mode: str = "lock") -> None:
    issues = validate_protocol(data, mode)
    if issues:
        raise ProtocolError("Protocol validation failed:\n- " + "\n- ".join(issues))


def new_protocol() -> dict[str, Any]:
    """Return a structurally complete draft with explicit decisions to fill."""
    return {
        "dsl_version": DSL_VERSION,
        "protocol_id": "review-protocol",
        "scope_version": 1,
        "version_change": {"previous_scope_version": None, "reason": "", "decision_source": ""},
        "review": {"question": "", "framework": {"name": "", "rationale": "", "slots": []}},
        "eligibility": {"inclusion": [], "exclusion": []},
        "searchable_scope": {"concepts": []},
        "screening_only": {"properties": []},
        "filters_and_limits": {"decisions": []},
        "date_boundaries": {
            "eligibility": {"start": None, "end": None},
            "search": {"start": None, "end": None},
            "rationale": "",
        },
        "seeds": {"records": []},
        "priorities": {
            "recall": {"policy": "", "minimum_heldout_recall": 1.0},
            "workload": {"policy": "", "selection_rule": ""},
        },
        "focused_variants": [],
    }


def _envelope(protocol: dict[str, Any], source: Path, artifact_type: str) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "artifact_version": ARTIFACT_VERSION,
        "protocol_id": protocol["protocol_id"],
        "scope_version": protocol["scope_version"],
        "dsl_version": protocol["dsl_version"],
        "generated_from": {"path": source.name, "sha256": canonical_sha256(protocol)},
    }


def build_artifacts(protocol: dict[str, Any], source: Path) -> dict[str, dict[str, Any]]:
    """Build all deterministic derivative artifacts, keyed by output filename."""
    version = protocol["scope_version"]
    concepts = protocol["searchable_scope"]["concepts"]
    seeds = protocol["seeds"]["records"]
    decisions = protocol["filters_and_limits"]["decisions"]

    concept_ledger = {
        **_envelope(protocol, source, "concept-ledger"),
        "ledger_status": "scope-baseline",
        "concepts": concepts,
        "screening_only_properties": protocol["screening_only"]["properties"],
        "evidence_overlay_required": True,
    }
    candidate_template = {
        **_envelope(protocol, source, "candidate-ledger-template"),
        "ledger_status": "template",
        "records": [
            {
                "pmid": item["pmid"],
                "provenance": "user-seed",
                "requested_role": item["role"],
                "decision": "pending",
                "title_abstract_reviewed": False,
                "eligibility_reason": "",
                "rationale": item["rationale"],
            }
            for item in seeds
        ],
    }
    block_registry = {
        **_envelope(protocol, source, "block-registry"),
        "registry_status": "scope-baseline",
        "blocks": [
            {
                "block_id": item["id"],
                "label": item["label"],
                "role": item["role"],
                "concept_id": item["id"],
                "definition": item["definition"],
                "rationale": item["rationale"],
                "provisional_fragility": item["provisional_fragility"],
                "term_families": item.get("term_families", []),
            }
            for item in concepts
        ],
        "realization_required": True,
    }
    critic_packet = {
        **_envelope(protocol, source, "critic-packet"),
        "required_domains": [
            "review-question", "scope-version-change", "eligibility-vs-searchable-scope", "concept-structure",
            "screening-only-properties", "filters-and-limits", "date-boundaries",
            "seed-roles", "recall-and-workload", "focused-variants",
        ],
        "protocol_summary": {
            "version_change": protocol["version_change"],
            "review": protocol["review"],
            "eligibility": protocol["eligibility"],
            "searchable_scope": protocol["searchable_scope"],
            "screening_only": protocol["screening_only"],
            "filters_and_limits": protocol["filters_and_limits"],
            "date_boundaries": protocol["date_boundaries"],
            "seeds": protocol["seeds"],
            "priorities": protocol["priorities"],
            "focused_variants": protocol["focused_variants"],
        },
    }
    conditional_sections: list[dict[str, Any]] = []
    if seeds:
        conditional_sections.append({"id": "seed-accounting", "title": "Seed accounting", "required": True, "source_refs": ["seeds"]})
    if any(value is not None for ranges in (protocol["date_boundaries"]["eligibility"], protocol["date_boundaries"]["search"]) for value in ranges.values()):
        conditional_sections.append({"id": "date-boundaries", "title": "Date boundaries", "required": True, "source_refs": ["date_boundaries"]})
    if decisions:
        conditional_sections.append({"id": "filters-and-limits", "title": "Filters and limits", "required": True, "source_refs": ["filters_and_limits"]})
    if protocol["focused_variants"]:
        conditional_sections.append({"id": "focused-variants", "title": "Focused variants", "required": True, "source_refs": ["focused_variants"]})
    audit_outline = {
        **_envelope(protocol, source, "audit-outline"),
        "sections": [
            {"id": "review-question", "title": "Review question and framework", "required": True, "source_refs": ["review"]},
            {"id": "eligibility", "title": "Eligibility criteria", "required": True, "source_refs": ["eligibility"]},
            {"id": "searchable-scope", "title": "Searchable scope and concept ledger", "required": True, "source_refs": ["searchable_scope"]},
            {"id": "screening-only", "title": "Screening-only properties", "required": True, "source_refs": ["screening_only"]},
            {"id": "validation", "title": "Validation and recall", "required": True, "source_refs": ["priorities.recall"]},
            {"id": "workload", "title": "Screening workload", "required": True, "source_refs": ["priorities.workload"]},
            {"id": "critic-review", "title": "PRESS-informed internal review", "required": True, "source_refs": ["review", "searchable_scope"]},
            *[
                {
                    "id": f"concept-{concept['id']}",
                    "title": f"Concept: {concept['label']}",
                    "required": True,
                    "source_refs": [f"searchable_scope.concepts.{concept['id']}"],
                }
                for concept in concepts
            ],
            *[
                {
                    "id": f"focused-variant-{variant['id']}",
                    "title": f"Focused variant: {variant['label']}",
                    "required": True,
                    "source_refs": [f"focused_variants.{variant['id']}"],
                }
                for variant in protocol["focused_variants"]
            ],
            *conditional_sections,
        ],
    }
    return {
        f"concept_ledger_v{version}.json": concept_ledger,
        f"candidate_ledger_template_v{version}.json": candidate_template,
        f"block_registry_v{version}.json": block_registry,
        f"critic_packet_v{version}.json": critic_packet,
        f"audit_outline_v{version}.json": audit_outline,
    }


def _atomic_write_many(files: dict[Path, bytes]) -> None:
    for path, content in files.items():
        if path.exists() and path.read_bytes() != content:
            raise ProtocolError(f"Refusing to overwrite immutable artifact with different content: {path}")
    pending: list[tuple[Path, Path]] = []
    try:
        for path, content in files.items():
            if path.exists():
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
            temp_path = Path(raw_temp)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            pending.append((temp_path, path))
        for temp_path, path in pending:
            os.replace(temp_path, path)
    finally:
        for temp_path, _ in pending:
            if temp_path.exists():
                temp_path.unlink()


def compile_protocol(protocol_path: Path, output_dir: Path, receipt_path: Path) -> dict[str, Any]:
    protocol = load_json(protocol_path)
    require_valid(protocol, "lock")
    artifacts = build_artifacts(protocol, protocol_path)
    artifact_bytes = {name: pretty_bytes(value) for name, value in artifacts.items()}
    receipt_parent = receipt_path.parent.resolve()
    receipt_artifacts = []
    for name in sorted(artifacts):
        path = (output_dir / name).resolve()
        receipt_artifacts.append({
            "artifact_type": artifacts[name]["artifact_type"],
            "path": Path(os.path.relpath(path, receipt_parent)).as_posix(),
            "sha256": hashlib.sha256(artifact_bytes[name]).hexdigest(),
        })
    receipt = {
        "operation": "protocol-compile",
        "ok": True,
        "protocol_sha256": canonical_sha256(protocol),
        "protocol_id": protocol["protocol_id"],
        "scope_version": protocol["scope_version"],
        "dsl_version": protocol["dsl_version"],
        "artifacts": receipt_artifacts,
    }
    files = {(output_dir / name): content for name, content in artifact_bytes.items()}
    if receipt_path.resolve() in {path.resolve() for path in files}:
        raise ProtocolError("Compile receipt path must not replace a generated derivative artifact")
    files[receipt_path] = pretty_bytes(receipt)
    _atomic_write_many(files)
    return receipt


def verify_protocol(protocol_path: Path, receipt_path: Path) -> dict[str, Any]:
    protocol = load_json(protocol_path)
    require_valid(protocol, "lock")
    receipt = load_json(receipt_path)
    issues: list[str] = []
    if receipt.get("operation") != "protocol-compile" or receipt.get("ok") is not True:
        issues.append("receipt is not a successful protocol-compile receipt")
    expected = {
        "protocol_sha256": canonical_sha256(protocol),
        "protocol_id": protocol["protocol_id"],
        "scope_version": protocol["scope_version"],
        "dsl_version": protocol["dsl_version"],
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            issues.append(f"receipt {key} does not match the protocol")
    rows = receipt.get("artifacts")
    if not isinstance(rows, list) or len(rows) != 5:
        issues.append("receipt artifacts must contain the five generated derivatives")
        rows = []
    seen_types: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"receipt artifact {index} must be an object")
            continue
        artifact_type = str(row.get("artifact_type") or "")
        if artifact_type in seen_types:
            issues.append(f"receipt repeats artifact type {artifact_type!r}")
        seen_types.add(artifact_type)
        path_value = row.get("path")
        if not isinstance(path_value, str) or not path_value:
            issues.append(f"receipt artifact {index} path is invalid")
            continue
        path = (receipt_path.parent / path_value).resolve()
        if not path.is_file():
            issues.append(f"generated artifact is missing: {path_value}")
            continue
        actual_hash = file_sha256(path)
        if actual_hash != row.get("sha256"):
            issues.append(f"generated artifact hash mismatch: {path_value}")
            continue
        try:
            artifact = load_json(path)
        except ProtocolError as exc:
            issues.append(str(exc))
            continue
        envelope = {
            "artifact_type": artifact_type,
            "artifact_version": ARTIFACT_VERSION,
            "protocol_id": protocol["protocol_id"],
            "scope_version": protocol["scope_version"],
            "dsl_version": protocol["dsl_version"],
            "generated_from": {"path": protocol_path.name, "sha256": expected["protocol_sha256"]},
        }
        for key, value in envelope.items():
            if artifact.get(key) != value:
                issues.append(f"generated artifact {path_value} has mismatched {key}")
    required_types = {"concept-ledger", "candidate-ledger-template", "block-registry", "critic-packet", "audit-outline"}
    if seen_types != required_types:
        issues.append("receipt artifact types are incomplete or unexpected")
    if issues:
        raise ProtocolError("Protocol verification failed:\n- " + "\n- ".join(sorted(set(issues))))
    return {
        "operation": "protocol-verify",
        "ok": True,
        "protocol_id": protocol["protocol_id"],
        "scope_version": protocol["scope_version"],
        "protocol_sha256": expected["protocol_sha256"],
        "artifact_count": len(rows),
    }


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:64].rstrip("-") or "migrated-review"


def _entity_id(text: str, fallback: str) -> str:
    value = _slug(text).replace("-", "_")
    if not value or not value[0].isalpha():
        value = f"{fallback}_{value}".rstrip("_")
    return value[:64].rstrip("_")


def migrate_scope(legacy: dict[str, Any], source: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map known legacy retrieval-scope fields without inventing missing decisions."""
    unresolved: list[str] = []
    question = str(legacy.get("review_question") or "").strip()
    framework_name = str(legacy.get("framework") or legacy.get("question_type") or "").strip()
    framework_rationale = str(legacy.get("framework_rationale") or "").strip()
    if not question:
        unresolved.append("review.question")
    if not framework_name:
        unresolved.append("review.framework.name")
    if not framework_rationale:
        unresolved.append("review.framework.rationale")

    raw_blocks = legacy.get("essential_blocks") if isinstance(legacy.get("essential_blocks"), list) else []
    concepts = []
    used_concept_ids: set[str] = set()
    for index, block in enumerate(raw_blocks, start=1):
        label = str(block).strip()
        base_id = _entity_id(label, f"concept_{index}")
        cid = base_id
        suffix = 2
        while cid in used_concept_ids:
            cid = f"{base_id[:58]}_{suffix}"
            suffix += 1
        used_concept_ids.add(cid)
        terms = (legacy.get("within_block_term_families") or {}).get(block, []) if isinstance(legacy.get("within_block_term_families"), dict) else []
        concepts.append({
            "id": cid, "label": label, "role": "essential", "eligibility_refs": [],
            "framework_slots": ["review_focus"], "definition": "", "rationale": "",
            "provisional_fragility": "fragile", "term_families": terms if isinstance(terms, list) else [],
        })
        unresolved.extend([f"searchable_scope.concepts[{index - 1}].definition", f"searchable_scope.concepts[{index - 1}].rationale"])
    if not concepts:
        unresolved.append("searchable_scope.concepts")

    screening_rows = []
    for index, raw in enumerate(legacy.get("screening_only") if isinstance(legacy.get("screening_only"), list) else [], start=1):
        if isinstance(raw, dict):
            label = str(raw.get("concept") or f"Screening property {index}")
            reason = str(raw.get("reason") or "")
        else:
            label, reason = str(raw), ""
        screening_rows.append({
            "id": f"screening_{index}", "label": label, "eligibility_refs": [],
            "instructions": "Assess during screening.", "recall_rationale": reason,
        })
        if not reason:
            unresolved.append(f"screening_only.properties[{index - 1}].recall_rationale")

    scope_version = legacy.get("scope_version") if isinstance(legacy.get("scope_version"), int) and not isinstance(legacy.get("scope_version"), bool) else 1
    filter_note = str(legacy.get("filters") or "").strip()
    if not filter_note:
        unresolved.append("filters_and_limits.decisions")
    protocol = {
        "dsl_version": DSL_VERSION,
        "protocol_id": _slug(question),
        "scope_version": scope_version,
        "version_change": {
            "previous_scope_version": None if scope_version == 1 else scope_version - 1,
            "reason": str(legacy.get("scope_change_reason") or ("Initial migrated protocol" if scope_version == 1 else "")).strip(),
            "decision_source": f"Migrated from {source.name}",
        },
        "review": {
            "question": question,
            "framework": {
                "name": framework_name, "rationale": framework_rationale,
                "slots": [{"id": "review_focus", "label": "Review focus", "description": framework_name or "Resolve framework slot"}],
            },
        },
        "eligibility": {"inclusion": [], "exclusion": []},
        "searchable_scope": {"concepts": concepts},
        "screening_only": {"properties": screening_rows},
        "filters_and_limits": {
            "decisions": ([{
                "id": "legacy_filters", "type": "limit", "label": "Legacy filter statement",
                "status": "rejected", "value": None, "validated_source": None, "rationale": filter_note,
            }] if filter_note else [])
        },
        "date_boundaries": {"eligibility": {"start": None, "end": None}, "search": {"start": None, "end": None}, "rationale": ""},
        "seeds": {"records": []},
        "priorities": {
            "recall": {"policy": "Recall-first main strategy", "minimum_heldout_recall": 1.0},
            "workload": {"policy": "Use workload only after recall qualification", "selection_rule": "Choose the lowest burden among recall-qualified strategies"},
        },
        "focused_variants": [],
        "x-migration": {"source": source.name, "unresolved": sorted(set(unresolved))},
    }
    unresolved.extend(["eligibility", "date_boundaries", "seeds", "focused_variants"])
    protocol["x-migration"]["unresolved"] = sorted(set(unresolved))
    report = {
        "operation": "protocol-migrate-scope",
        "ok": True,
        "source": str(source),
        "scope_version": scope_version,
        "protocol_id": protocol["protocol_id"],
        "unresolved": protocol["x-migration"]["unresolved"],
        "lock_ready": False,
    }
    return protocol, report


def write_new(path: Path, value: Any) -> None:
    content = pretty_bytes(value)
    if path.exists():
        raise ProtocolError(f"Refusing to overwrite existing file: {path}")
    _atomic_write_many({path: content})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    new = subparsers.add_parser("new", help="Write a structurally complete draft protocol")
    new.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate", help="Validate a draft or lock-ready protocol")
    validate.add_argument("protocol", type=Path)
    validate.add_argument("--mode", choices=("draft", "lock"), default="lock")
    compile_cmd = subparsers.add_parser("compile", help="Compile immutable protocol derivatives")
    compile_cmd.add_argument("protocol", type=Path)
    compile_cmd.add_argument("--output-dir", type=Path, required=True)
    compile_cmd.add_argument("--receipt", type=Path, required=True)
    verify = subparsers.add_parser("verify", help="Verify the protocol and all compiled derivatives")
    verify.add_argument("protocol", type=Path)
    verify.add_argument("--receipt", type=Path, required=True)
    migrate = subparsers.add_parser("migrate-scope", help="Map a legacy retrieval-scope JSON file")
    migrate.add_argument("scope", type=Path)
    migrate.add_argument("--output", type=Path, required=True)
    migrate.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            draft = new_protocol()
            require_valid(draft, "draft")
            write_new(args.output, draft)
            result = {"operation": "protocol-new", "ok": True, "output": str(args.output)}
        elif args.command == "validate":
            protocol = load_json(args.protocol)
            require_valid(protocol, args.mode)
            result = {
                "operation": "protocol-validate", "ok": True, "mode": args.mode,
                "protocol_id": protocol.get("protocol_id"), "scope_version": protocol.get("scope_version"),
                "protocol_sha256": canonical_sha256(protocol),
            }
        elif args.command == "compile":
            result = compile_protocol(args.protocol, args.output_dir, args.receipt)
        elif args.command == "verify":
            result = verify_protocol(args.protocol, args.receipt)
        else:
            legacy = load_json(args.scope)
            protocol, report = migrate_scope(legacy, args.scope)
            require_valid(protocol, "draft")
            _atomic_write_many({args.output: pretty_bytes(protocol), args.report: pretty_bytes(report)})
            result = report
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ProtocolError as exc:
        print(json.dumps({"operation": f"protocol-{args.command}", "ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
