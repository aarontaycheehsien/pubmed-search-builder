#!/usr/bin/env python3
"""Normalize MeSH backend/fidelity evidence for CLI outputs, manifests, and audits.

This module is deliberately offline and dependency-free.  It reads only the stable provenance
fields emitted by ``mesh_tool.py`` so the manifest and audit can disclose reduced-fidelity
E-utilities evidence without re-running a network request or trusting hand-written notes.
"""

from __future__ import annotations

from typing import Any


MESH_EVIDENCE_SCHEMA_VERSION = 1
MESH_OPERATIONS = frozenset({"lookup", "terms", "details", "tree", "sweep"})
KNOWN_FIDELITIES = frozenset({"full", "reduced"})


def _text(value: object) -> str:
    return str(value or "").strip()


def _marker(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    backend = _text(value.get("backend"))
    fidelity = _text(value.get("fidelity"))
    method = _text(value.get("method"))
    if not backend or not fidelity or not method:
        return None
    marker = {"backend": backend, "fidelity": fidelity, "method": method}
    fallback_reason = _text(value.get("fallback_reason"))
    if fallback_reason:
        marker["fallback_reason"] = fallback_reason
    return marker


def _marker_values(value: object) -> list[dict[str, str]]:
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    markers = []
    for item in values:
        marker = _marker(item)
        if marker and marker not in markers:
            markers.append(marker)
    return markers


def _sorted_markers(markers: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        markers,
        key=lambda marker: (
            marker["backend"],
            marker["fidelity"],
            marker["method"],
            marker.get("fallback_reason", ""),
        ),
    )


def _record_markers(record: object, fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(record, dict):
        return list(fallback)
    markers = _marker_values(record.get("provenance"))
    return markers or list(fallback)


def _record_rows(payload: dict[str, object]) -> list[object]:
    operation = _text(payload.get("operation"))
    if operation == "sweep":
        candidates = payload.get("candidates")
        return candidates if isinstance(candidates, list) else []
    results = payload.get("results")
    if isinstance(results, list):
        return results
    if operation in {"details", "tree"}:
        return [payload]
    return []


def _all_markers(payload: dict[str, object]) -> list[dict[str, str]]:
    values = []
    values.extend(_marker_values(payload.get("provenance")))
    values.extend(_marker_values(payload.get("backend_provenance")))
    values.extend(_marker_values(payload.get("term_mapping_provenance")))
    for row in _record_rows(payload):
        if isinstance(row, dict):
            values.extend(_marker_values(row.get("provenance")))
    raw_searches = payload.get("raw_searches")
    if isinstance(raw_searches, list):
        for row in raw_searches:
            if isinstance(row, dict):
                values.extend(_marker_values(row.get("provenance")))
                for result in row.get("results", []) if isinstance(row.get("results"), list) else []:
                    if isinstance(result, dict):
                        values.extend(_marker_values(result.get("provenance")))
    unique: list[dict[str, str]] = []
    for marker in values:
        if marker not in unique:
            unique.append(marker)
    return _sorted_markers(unique)


def _classify(markers: list[dict[str, str]]) -> str:
    fidelities = {marker["fidelity"] for marker in markers}
    if not markers or not fidelities.issubset(KNOWN_FIDELITIES):
        return "unclassified"
    if fidelities == {"full"}:
        return "full_only"
    if fidelities == {"reduced"}:
        return "reduced_only"
    return "mixed"


def _overall_fidelity(markers: list[dict[str, str]]) -> str:
    fidelities = {marker["fidelity"] for marker in markers}
    if not markers or not fidelities.issubset(KNOWN_FIDELITIES):
        return "unknown"
    if fidelities == {"full"}:
        return "full"
    if fidelities == {"reduced"}:
        return "reduced"
    return "mixed"


def _unique_strings(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def is_mesh_artifact(payload: object) -> bool:
    return isinstance(payload, dict) and _text(payload.get("operation")) in MESH_OPERATIONS


def build_mesh_evidence(payload: dict[str, object]) -> dict[str, object]:
    """Return the canonical, deterministic summary for one mesh_tool JSON payload."""
    operation = _text(payload.get("operation"))
    if operation not in MESH_OPERATIONS:
        raise ValueError(f"Not a mesh_tool artifact: operation={operation!r}")
    markers = _all_markers(payload)
    top_level_markers = _marker_values(payload.get("provenance"))
    rows = _record_rows(payload)
    counts = {"total": 0, "full_only": 0, "reduced_only": 0, "mixed": 0, "unclassified": 0}
    for row in rows:
        counts["total"] += 1
        counts[_classify(_record_markers(row, top_level_markers))] += 1

    status = _text(payload.get("status")) or "complete"
    reduced = any(marker["fidelity"] == "reduced" for marker in markers)
    methods = _unique_strings([marker["method"] for marker in markers])
    limitations: list[str] = []
    review_required: list[str] = []
    if operation == "sweep" and status != "complete":
        statement = "This MeSH sweep is partial and cannot be treated as complete MeSH/entry-term recall evidence."
        limitations.append(statement)
        review_required.append(statement)
    if reduced:
        statement = (
            "Some candidates use reduced-fidelity E-utilities metadata. Confirm preferred headings, entry terms, "
            "qualifiers, and tree context against MeSH RDF before accepting or rejecting them."
        )
        limitations.append(statement)
        review_required.append(statement)
    if "eutils_tree_esearch_esummary" in methods:
        statement = (
            "E-utilities tree context omits RDF-only annotations, history/public MeSH notes, and "
            "Supplementary Concept Record mapping."
        )
        limitations.append(statement)
        review_required.append(statement)
    tree_search = payload.get("tree_search")
    if isinstance(tree_search, dict) and tree_search.get("truncated") is True:
        statement = "The E-utilities tree-number search was truncated; rerun with a higher bound before finalizing explosion decisions."
        limitations.append(statement)
        review_required.append(statement)

    return {
        "schema_version": MESH_EVIDENCE_SCHEMA_VERSION,
        "operation": operation,
        "status": status,
        "overall_fidelity": _overall_fidelity(markers),
        "backends_used": _unique_strings([marker["backend"] for marker in markers]),
        "methods": methods,
        "fallback_reasons": _unique_strings([marker.get("fallback_reason", "") for marker in markers]),
        "provenance_markers": markers,
        "records": counts,
        "reduced_fidelity_present": reduced,
        "limitations": limitations,
        "review_required": review_required,
    }


def mesh_evidence_issues(payload: dict[str, object]) -> list[str]:
    """Validate a stored mesh_evidence block against the artifact it describes."""
    if not is_mesh_artifact(payload):
        return []
    stored = payload.get("mesh_evidence")
    if stored is None:
        return []  # Legacy Phase 1-3 artifact: derive conservatively at read time.
    if not isinstance(stored, dict):
        return ["mesh_evidence must be an object"]
    expected = build_mesh_evidence(payload)
    if stored != expected:
        return ["mesh_evidence does not match the artifact provenance fields"]
    return []


def complete_sweep_evidence(summary: object) -> bool:
    return isinstance(summary, dict) and summary.get("operation") == "sweep" and summary.get("status") == "complete"
