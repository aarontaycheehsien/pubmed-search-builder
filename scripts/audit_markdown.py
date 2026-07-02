#!/usr/bin/env python3
"""Render a compact-input PubMed audit JSON file to Markdown.

The default command output is intentionally small: the full audit is written to
disk and stdout receives only a short JSON receipt. Use --print-report only when
the Markdown itself is needed in the terminal.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_STATUS = "not performed"
PRESS_2015_ELEMENTS = [
    "1. Translation of the research question",
    "2. Boolean and proximity operators",
    "3. Subject headings",
    "4. Text-word search",
    "5. Spelling, syntax, line numbers",
    "6. Limits and filters",
]
PLACEHOLDER_RE = re.compile(
    r"\[[^\]\n]*(?:"
    r"name|scope|count|date|path|reason|decision|descriptor|query|source|"
    r"version|interface|adaptation|list|summary|concept|strategy|PMID|pmid|"
    r"record"
    r")[^\]\n]*\]"
)


class AuditMarkdownError(Exception):
    pass


def read_text_source(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8-sig")


def load_json(path: str) -> dict[str, Any]:
    try:
        data = json.loads(read_text_source(path))
    except json.JSONDecodeError as exc:
        raise AuditMarkdownError(f"Could not parse JSON input {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AuditMarkdownError("Audit input JSON must contain an object.")
    return data


def merge_overlay(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge an authored audit overlay into a scaffold.

    Dicts merge recursively so a small decisions file can fill scaffold placeholders without
    restating all mechanical fields. Lists and scalars replace the scaffold value.
    """
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge_overlay(existing, value)
        else:
            merged[key] = value
    return merged


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def compact_text(value: Any, default: str = DEFAULT_STATUS) -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        items = [compact_text(item, "") for item in value]
        items = [item for item in items if item]
        return "; ".join(items) if items else default
    if isinstance(value, dict):
        status = value.get("status")
        if status not in (None, "", [], {}):
            return compact_text(status, default)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value).strip()
    return text if text else default


def get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def first_value(data: dict[str, Any], paths: list[str], default: Any = None) -> Any:
    for path in paths:
        value = get_path(data, path, None)
        if value not in (None, "", [], {}):
            return value
    return default


def slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return text[:70] or "search"


def output_path_from_data(data: dict[str, Any], output: str | None) -> Path:
    if output:
        return Path(output)

    configured = first_value(
        data,
        [
            "reporting_notes.audit_markdown_file",
            "reporting_notes.audit_markdown_path",
            "audit_markdown_file",
            "audit_markdown_path",
        ],
    )
    if configured:
        return Path(str(configured))

    output_dir = Path(str(first_value(data, ["output_dir", "working_output_folder"], ".")))
    searched = compact_text(first_value(data, ["date_searched", "reporting_notes.date_searched"], date.today().isoformat()))
    topic = compact_text(first_value(data, ["topic", "review_question"], ""), "")
    if topic:
        return output_dir / f"audit_{slugify(topic)}_{searched}.md"
    return output_dir / f"audit_{searched}.md"


def resolve_existing_path(path: Path, if_exists: str) -> Path:
    if not path.exists() or if_exists == "overwrite":
        return path
    if if_exists == "fail":
        raise AuditMarkdownError(f"Output already exists: {path}")
    if if_exists != "suffix":
        raise AuditMarkdownError(f"Unsupported if_exists policy: {if_exists}")

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise AuditMarkdownError(f"Could not find available suffix for output path: {path}")


def escape_table(value: Any) -> str:
    text = compact_text(value)
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    return "<br>".join(line.strip() for line in text.splitlines()) or DEFAULT_STATUS


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        rows = [[DEFAULT_STATUS for _ in headers]]
    lines = [
        "| " + " | ".join(escape_table(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        padded = list(row)[: len(headers)] + [""] * max(0, len(headers) - len(row))
        lines.append("| " + " | ".join(escape_table(item) for item in padded) + " |")
    return "\n".join(lines)


def bullet_lines(items: Any, *, default: str = DEFAULT_STATUS) -> list[str]:
    values = as_list(items)
    if not values:
        return [f"- {default}"]
    lines = []
    for item in values:
        if isinstance(item, dict):
            label = item.get("label") or item.get("name") or item.get("concept") or item.get("decision_point")
            detail = item.get("detail") or item.get("decision") or item.get("rationale") or item.get("status")
            if label:
                lines.append(f"- **{compact_text(label)}:** {compact_text(detail)}")
            else:
                lines.append(f"- {compact_text(item)}")
        else:
            lines.append(f"- {compact_text(item)}")
    return lines


def concept_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    concepts = first_value(data, ["search_structure.concepts", "concepts"], [])
    return [item for item in as_list(concepts) if isinstance(item, dict)]


def render_search_structure(data: dict[str, Any]) -> list[str]:
    search_structure = as_dict(data.get("search_structure"))
    concepts = concept_rows(data)
    lines = ["## Search structure", ""]
    framework = first_value(
        data,
        [
            "search_structure.framework",
            "framework",
            "framework_choice",
        ],
    )
    if framework not in (None, "", [], {}):
        lines.append(f"- **Framework:** {compact_text(framework)}")
    if concepts:
        for index, concept in enumerate(concepts, start=1):
            name = concept.get("name") or concept.get("concept") or f"Concept {index}"
            scope = concept.get("scope") or concept.get("description") or DEFAULT_STATUS
            coverage = concept.get("coverage") or concept.get("layers") or DEFAULT_STATUS
            lines.append(f"- **Concept {index}:** {compact_text(name)} - {compact_text(scope)}; {compact_text(coverage)}")
    else:
        lines.append("- **Concepts:** not performed")
    lines.extend(
        [
            f"- **Concept gate status:** {compact_text(search_structure.get('concept_gate_status'))}",
            f"- **AND-block admission summary:** {compact_text(search_structure.get('and_block_admission_summary'))}",
            f"- **Concepts kept inside existing `OR` blocks:** {compact_text(search_structure.get('concepts_inside_or_blocks'))}",
            f"- **Omitted or reserve concepts:** {compact_text(search_structure.get('omitted_or_reserve_concepts'))}",
            f"- **Methodological filters or limits:** {compact_text(search_structure.get('methodological_filters_or_limits'))}",
            "",
        ]
    )
    return lines


def render_stage_trace(data: dict[str, Any]) -> list[str]:
    trace_items = as_list(data.get("stage_trace"))
    if not trace_items:
        return []

    rows = []
    for item in trace_items:
        if not isinstance(item, dict):
            rows.append([item, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS])
            continue
        rows.append(
            [
                item.get("stage") or item.get("stage_name"),
                item.get("reference_files") or item.get("references") or item.get("reference_files_in_force"),
                item.get("action_taken") or item.get("doing_now") or item.get("action"),
                item.get("blocked_actions") or item.get("not_doing_yet"),
                item.get("decision_needed") or item.get("user_decision_needed"),
                item.get("user_protocol_decision") or item.get("user_or_protocol_decision") or item.get("protocol_decision"),
            ]
        )

    return [
        "## Stage Trace",
        "",
        markdown_table(
            [
                "Stage",
                "Reference files",
                "Action taken",
                "Blocked actions",
                "Decision needed",
                "User/protocol decision",
            ],
            rows,
        ),
        "",
    ]


def render_user_decisions(data: dict[str, Any]) -> list[str]:
    decisions = as_list(first_value(data, ["user_decisions", "optional_concept_decisions"], []))
    seed_pmids = first_value(data, ["seed_validation.seed_pmids_tested", "seed_pmids"], [])
    seed_status = first_value(data, ["seed_status", "seed_validation.seed_pmids_provided"], None)
    lines = ["## User decisions on optional concept blocks", ""]
    if decisions:
        for item in decisions:
            if isinstance(item, dict):
                label = item.get("concept") or item.get("label") or item.get("decision_point") or "Decision"
                offered = item.get("offered_because") or item.get("rationale") or DEFAULT_STATUS
                decision = item.get("decision") or item.get("user_decision") or item.get("status")
                handling = item.get("handling") or item.get("final_handling") or DEFAULT_STATUS
                lines.append(f"- **{compact_text(label)}:** offered because {compact_text(offered)} -> {compact_text(decision)}. {compact_text(handling)}")
            else:
                lines.append(f"- {compact_text(item)}")
    else:
        lines.append("- **Optional concept blocks:** not performed")
    lines.append(f"- **Seed PMIDs:** {compact_text(seed_status, 'not available')} -> {compact_text(seed_pmids, 'none supplied')}")
    lines.append(f"- **Study-design, date, language, age, species, or publication-type limits:** {compact_text(first_value(data, ['limit_decisions', 'filter_decisions']))}")
    lines.append("")
    return lines


def render_decision_ledger(data: dict[str, Any]) -> list[str]:
    rows = []
    for item in as_list(data.get("decision_ledger")):
        if not isinstance(item, dict):
            rows.append([item, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS])
            continue
        rows.append(
            [
                item.get("decision_point"),
                item.get("options_considered"),
                item.get("evidence_or_test_used"),
                item.get("decision_made"),
                item.get("rationale_or_recall_risk_note") or item.get("rationale"),
                item.get("reflected_in_strategy_or_report") or item.get("reflected_in"),
            ]
        )
    return [
        "## Decision ledger",
        "",
        markdown_table(
            [
                "Decision point",
                "Options considered",
                "Evidence or test used",
                "Decision made",
                "Rationale / recall-risk note",
                "Reflected in strategy/report",
            ],
            rows,
        ),
        "",
    ]


def truthy_audit_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "used", "supported"}


def collect_record_content_evidence(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    explicit_sources = as_list(data.get("record_content_evidence")) + as_list(data.get("record_content_decisions"))
    for item in explicit_sources:
        if isinstance(item, dict):
            rows.append(item)

    for item in as_list(data.get("decision_ledger")):
        if not isinstance(item, dict):
            continue
        has_record_fields = any(
            key in item
            for key in (
                "record_content_decision",
                "evidence_file_reviewed",
                "record_content_reviewed",
                "abstracts_reviewed",
                "receipt_only_stdout_used_as_decision_evidence",
                "decision_supported",
            )
        )
        if has_record_fields:
            rows.append(item)
    return rows


def record_content_evidence_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for index, item in enumerate(collect_record_content_evidence(data), start=1):
        if not truthy_audit_value(item.get("record_content_decision")):
            continue
        label = compact_text(item.get("decision_point") or item.get("label") or f"record-content decision {index}")
        evidence_file = item.get("evidence_file_reviewed") or item.get("evidence_files_reviewed")
        if evidence_file in (None, "", [], {}):
            issues.append(f"{label}: record-content decision lacks evidence_file_reviewed")
        if truthy_audit_value(item.get("receipt_only_stdout_used_as_decision_evidence")):
            issues.append(f"{label}: receipt-only stdout cannot be used as decision evidence")
    return issues


def render_record_content_evidence(data: dict[str, Any]) -> list[str]:
    rows = []
    for item in collect_record_content_evidence(data):
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                item.get("decision_point") or item.get("label") or item.get("decision") or DEFAULT_STATUS,
                item.get("evidence_file_reviewed") or item.get("evidence_files_reviewed"),
                item.get("record_content_reviewed"),
                item.get("abstracts_reviewed"),
                item.get("receipt_only_stdout_used_as_decision_evidence"),
                item.get("decision_supported"),
            ]
        )
    return [
        "## Record-content evidence reviewed",
        "",
        markdown_table(
            [
                "Decision",
                "Evidence file reviewed",
                "Record content reviewed",
                "Abstracts reviewed",
                "Receipt-only stdout used as decision evidence",
                "Decision supported",
            ],
            rows,
        ),
        "",
    ]


def render_final_strategy(data: dict[str, Any]) -> list[str]:
    strategy = compact_text(first_value(data, ["final_strategy", "strategy", "final_pubmed_strategy"]))
    date_searched = compact_text(first_value(data, ["date_searched", "reporting_notes.date_searched"], date.today().isoformat()))
    count = compact_text(first_value(data, ["result_count", "final_count", "pubmed_cli_checks.final_combined_topic_only_strategy"]))
    filter_count = compact_text(first_value(data, ["topic_plus_filter_count", "filter_count"], "not applicable"))
    focused_count = compact_text(first_value(data, ["focused_variant_count", "precision_variant_count"], "not performed"))
    chosen = compact_text(first_value(data, ["main_variant_chosen", "chosen_variant"], "sensitive/main by default"))
    return [
        "## Final PubMed strategy (draft)",
        "",
        "```text",
        strategy,
        "```",
        "",
        f"**Result count on {date_searched}:** {count} records.",
        "",
        f"- **Topic-plus-filter count:** {filter_count}",
        f"- **Focused/precision-supporting variant count:** {focused_count}",
        f"- **Main variant chosen:** {chosen}",
        "",
    ]


def mesh_review_lines(concept: dict[str, Any], index: int) -> list[str]:
    mesh = as_dict(concept.get("mesh_review") or concept.get("mesh") or concept.get("mesh_descriptors_considered"))
    name = concept.get("name") or concept.get("concept") or f"Concept {index}"
    lines = [f"**Concept {index} - {compact_text(name)}**"]
    fields = [
        ("Sweep inputs", "sweep_inputs"),
        ("Sweep outputs and candidate sources", "sweep_outputs_and_candidate_sources"),
        ("Details/tree inspected", "details_tree_inspected"),
        ("Candidates accepted", "candidates_accepted"),
        ("Candidates rejected with rationale", "candidates_rejected"),
        ("Candidates deferred or reserved", "candidates_deferred_or_reserved"),
        ("SCR or ATM mappings resolved", "scr_or_atm_mappings_resolved"),
        ("Entry terms harvested as `[tiab]`", "entry_terms_harvested_as_tiab"),
        ("Entry terms omitted", "entry_terms_omitted"),
        ("Counts tested", "counts_tested"),
    ]
    for label, key in fields:
        lines.append(f"- {label}: {compact_text(mesh.get(key))}")
    lines.append("")
    return lines


def fetched_seed_rows(records: Any) -> list[list[Any]]:
    rows = []
    for record in as_list(records):
        if not isinstance(record, dict):
            rows.append([record, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS])
            continue
        rows.append(
            [
                record.get("pmid"),
                record.get("title"),
                record.get("year"),
                record.get("publication_types"),
            ]
        )
    return rows


def render_pre_gate_seed_triage(data: dict[str, Any]) -> list[str]:
    triage = as_dict(first_value(data, ["pre_gate_seed_triage", "seed_triage"], {}))
    lines = ["### Pre-gate seed triage", ""]
    fields = [
        ("Requested seed entries", "requested_seed_entries"),
        ("Normalized unique numeric PMIDs", "normalized_unique_numeric_pmids"),
        ("Malformed entries excluded", "malformed_entries_excluded"),
        ("Evidence file reviewed", "evidence_file_reviewed"),
        ("Record content reviewed", "record_content_reviewed"),
        ("Abstracts reviewed", "abstracts_reviewed"),
        ("Receipt-only stdout used as decision evidence", "receipt_only_stdout_used_as_decision_evidence"),
        ("Decision supported", "decision_supported"),
        ("Missing/not-found PMIDs excluded", "missing_not_found_pmids_excluded"),
        ("Retracted seeds", "retracted_seeds"),
        ("Likely out-of-scope seeds", "likely_out_of_scope_seeds"),
        ("User/protocol decision when paused", "user_protocol_decision_when_paused"),
    ]
    none_when_empty = {"malformed_entries_excluded", "missing_not_found_pmids_excluded"}
    for label, key in fields:
        if key == "user_protocol_decision_when_paused":
            default = "not applicable"
        elif key in none_when_empty and key in triage:
            default = "none"
        else:
            default = DEFAULT_STATUS
        lines.append(f"- **{label}:** {compact_text(triage.get(key), default)}")
    lines.extend(["", "Fetched seed records:", ""])
    lines.append(markdown_table(["PMID", "Title", "Year", "Publication types"], fetched_seed_rows(triage.get("fetched_seed_records"))))
    lines.append("")
    return lines


def render_seed_set_expansion(data: dict[str, Any]) -> list[str]:
    expansion = as_dict(first_value(data, ["seed_set_expansion", "related_seed_expansion"], {}))
    labelling = expansion.get("labelling") or (
        "related-set evidence is recorded separately from user-confirmed seed evidence and is not treated as validated recall"
    )
    fields = [
        ("Expansion run", "expansion_run"),
        ("Link types used", "links_used"),
        ("Per-link candidate counts", "link_counts"),
        ("Max per seed", "max_per_seed"),
        ("Max total", "max_total"),
        ("Candidate count", "candidate_count"),
        ("Candidate count before cap", "candidate_count_before_cap"),
        ("High-overlap candidate PMIDs used for term discovery", "high_overlap_candidate_pmids"),
        ("How related-set evidence was used", "how_related_set_evidence_was_used"),
    ]
    lines = ["### Seed-set expansion (related)", ""]
    for label, key in fields:
        default = "not applicable - no usable seeds" if key == "expansion_run" else DEFAULT_STATUS
        lines.append(f"- **{label}:** {compact_text(expansion.get(key), default)}")
    lines.append(f"- **Labelling:** {compact_text(labelling)}")
    lines.append("")
    return lines


def render_relative_recall(data: dict[str, Any]) -> list[str]:
    recall = as_dict(first_value(data, ["relative_recall", "relative_recall_estimation"], {}))
    block_rows = []
    for item in as_list(recall.get("block_recall")):
        if isinstance(item, dict):
            block_rows.append(
                [
                    item.get("label"),
                    item.get("retrieved_count"),
                    item.get("recall_percent"),
                    item.get("bottleneck"),
                ]
            )
        else:
            block_rows.append([item, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS])

    miss_rows = []
    for item in as_list(recall.get("miss_diagnosis")):
        if isinstance(item, dict):
            miss_rows.append([item.get("pmid"), item.get("culprit_blocks"), item.get("and_interaction")])
        else:
            miss_rows.append([item, DEFAULT_STATUS, DEFAULT_STATUS])

    caveat = recall.get("caveat") or recall.get("note") or (
        "relative recall is recorded separately from known-item seed validation; a seed-expansion benchmark is a heuristic that can flatter recall"
    )
    lines = ["### Relative-recall estimation", ""]
    fields = [
        ("Relative-recall check run", "check_run"),
        ("Benchmark source", "benchmark_source"),
        ("Benchmark size", "benchmark_size"),
        ("Relative recall", "relative_recall_percent"),
        ("Retrieved count", "retrieved_count"),
        ("Missed count", "missed_count"),
        ("Retrieved PMIDs", "retrieved_pmids"),
        ("Missed PMIDs", "missed_pmids"),
        ("Bottleneck block", "bottleneck_block"),
    ]
    none_when_empty = {"retrieved_pmids", "missed_pmids"}
    for label, key in fields:
        default = "none" if key in none_when_empty and key in recall else DEFAULT_STATUS
        lines.append(f"- **{label}:** {compact_text(recall.get(key), default)}")
    lines.extend(["", "Per-block recall:", ""])
    lines.append(markdown_table(["Block", "Retrieved count", "Recall percent", "Bottleneck"], block_rows))
    lines.extend(["", "Misses and culprit blocks:", ""])
    lines.append(markdown_table(["PMID", "Culprit blocks", "AND interaction"], miss_rows))
    lines.extend(["", f"- **Caveat:** {compact_text(caveat)}", ""])
    return lines


def render_ncbi_work(data: dict[str, Any]) -> list[str]:
    lines = ["## NCBI CLI work performed", "", "### MeSH descriptors considered (per concept)", ""]
    concepts = concept_rows(data)
    if concepts:
        for index, concept in enumerate(concepts, start=1):
            lines.extend(mesh_review_lines(concept, index))
    else:
        lines.append("not performed")
        lines.append("")

    seed_pmids = first_value(data, ["seed_validation.seed_pmids_tested", "seed_pmids"], [])
    seed_mesh = first_value(data, ["mesh_derived_from_seed_records", "seed_mesh"], DEFAULT_STATUS)
    lines.extend(
        [
            "### MeSH derived from seed records",
            "",
            f"Seed PMIDs provided: **{'Yes' if as_list(seed_pmids) else 'No'}**.",
            "",
            f"- {compact_text(seed_mesh, 'True seed-derived MeSH was not available.')}",
            "",
        ]
    )
    lines.extend(render_pre_gate_seed_triage(data))
    lines.extend(render_seed_set_expansion(data))
    lines.extend(["### MeSH derived from PubMed query translations", ""])

    atm_rows = []
    for item in as_list(first_value(data, ["atm_translations", "pubmed_query_translations"], [])):
        if isinstance(item, dict):
            atm_rows.append([item.get("query"), item.get("translation"), item.get("added_explicitly")])
        else:
            atm_rows.append([item, DEFAULT_STATUS, DEFAULT_STATUS])
    lines.append(markdown_table(["Free-text query", "ATM/query translation observed", "Added explicitly?"], atm_rows))
    lines.extend(["", "### PubMed CLI checks", ""])

    check_rows = []
    checks = first_value(data, ["pubmed_cli_checks", "count_checks"], [])
    if isinstance(checks, dict):
        for label, value in checks.items():
            check_rows.append([label.replace("_", " "), value])
    else:
        for item in as_list(checks):
            if isinstance(item, dict):
                check_rows.append([item.get("label") or item.get("query_tested"), item.get("count")])
            else:
                check_rows.append([item, DEFAULT_STATUS])
    lines.append(markdown_table(["Block / query tested", "Result count"], check_rows))
    lines.append("")
    lines.extend(render_relative_recall(data))
    return lines


def render_tiab_expansion(data: dict[str, Any]) -> list[str]:
    expansion = as_dict(first_value(data, ["tiab_expansion", "title_abstract_expansion"], {}))
    fields = [
        ("Pre-MeSH brainstorm required", "pre_mesh_brainstorm_required"),
        ("Domain-framing question asked", "domain_framing_question_asked"),
        ("Brainstormed vocabulary families accepted", "brainstormed_vocabulary_families_accepted"),
        ("Brainstormed vocabulary families rejected", "brainstormed_vocabulary_families_rejected"),
        ("Brainstormed vocabulary families deferred/reserved", "brainstormed_vocabulary_families_deferred"),
        ("MeSH-entry-derived `[tiab]` variants added", "mesh_entry_derived_tiab_variants_added"),
        ("Seed-derived `[tiab]` variants added", "seed_derived_tiab_variants_added"),
        ("Sample-record-derived `[tiab]` variants added", "sample_record_derived_tiab_variants_added"),
        ("Acronyms and abbreviations added", "acronyms_and_abbreviations_added"),
        ("Acronyms and abbreviations tested but rejected", "acronyms_and_abbreviations_tested_but_rejected"),
        ("Singular/plural variants added", "singular_plural_variants_added"),
        ("Spelling variants added", "spelling_variants_added"),
        ("Hyphenation variants added", "hyphenation_variants_added"),
        ("Proximity candidates tested", "proximity_candidates_tested"),
        ("Proximity expressions added", "proximity_expressions_added"),
        ("Proximity expressions tested but rejected", "proximity_expressions_tested_but_rejected"),
        ("Proximity not applicable rationale", "proximity_not_applicable_rationale"),
        ("Wildcard stems added", "wildcard_stems_added"),
        ("Wildcard stems tested but rejected", "wildcard_stems_tested_but_rejected"),
        ("Zero-hit terms removed (documented)", "zero_hit_terms_removed"),
        ("Zero-hit terms kept after user choice", "zero_hit_terms_kept"),
    ]
    lines = ["## Title/abstract, proximity, and wildcard expansion log", ""]
    for label, key in fields:
        lines.append(f"- **{label}:** {compact_text(expansion.get(key))}")
    rows = []
    for item in as_list(expansion.get("morphology_review")):
        if isinstance(item, dict):
            rows.append(
                [
                    item.get("phrase_family"),
                    item.get("explicit_forms"),
                    item.get("wildcard_candidate"),
                    item.get("tested"),
                    item.get("decision"),
                    item.get("rationale"),
                ]
            )
        else:
            rows.append([item, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS, DEFAULT_STATUS])
    lines.extend(
        [
            "",
            "Morphology review for singular/plural `[tiab]` phrase families:",
            "",
            markdown_table(
                [
                    "Phrase family",
                    "Explicit forms",
                    "Phrase-anchored/concept-specific wildcard candidate",
                    "Tested?",
                    "Decision",
                    "Rationale",
                ],
                rows,
            ),
        ]
    )
    lines.append("")
    return lines


def render_rationale(data: dict[str, Any]) -> list[str]:
    rationale = as_dict(data.get("rationale"))
    fields = [
        ("MeSH choices", "mesh_choices"),
        ("Text-word choices", "text_word_choices"),
        ("Pre-MeSH vocabulary/domain choices", "pre_mesh_vocabulary_domain_choices"),
        ("Concept-gate and omitted-block choices", "concept_gate_and_omitted_block_choices"),
        ("Methodological filters or limits", "methodological_filters_or_limits"),
        ("Sensitivity vs precision", "sensitivity_vs_precision"),
        ("QA", "qa"),
    ]
    lines = ["## Rationale", ""]
    for label, key in fields:
        lines.append(f"- **{label}.** {compact_text(rationale.get(key))}")
    lines.append("")
    return lines


def render_press_coverage(data: dict[str, Any]) -> list[str]:
    raw = first_value(data, ["press_2015_element_coverage", "press_coverage"], None)
    by_index: dict[int, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not isinstance(value, dict):
                value = {"coverage": value}
            digits = re.findall(r"\d+", str(key))
            if digits:
                idx = int(digits[0]) - 1
                if 0 <= idx < len(PRESS_2015_ELEMENTS):
                    by_index[idx] = value
    elif isinstance(raw, list):
        for index, value in enumerate(raw):
            if isinstance(value, dict):
                digits = re.findall(r"\d+", str(value.get("element", "")))
                idx = int(digits[0]) - 1 if digits else index
            else:
                idx = index
                value = {"coverage": value}
            if 0 <= idx < len(PRESS_2015_ELEMENTS):
                by_index[idx] = value

    rows = []
    for index, element in enumerate(PRESS_2015_ELEMENTS):
        item = by_index.get(index, {})
        coverage = item.get("coverage") or item.get("status")
        notes = item.get("notes") or item.get("supporting_section") or item.get("note")
        rows.append([element, compact_text(coverage), compact_text(notes)])

    return [
        "## PRESS 2015 element coverage",
        "",
        "Map the audit's QA checks to the six PRESS 2015 elements "
        "([McGowan et al. 2016](https://doi.org/10.1016/j.jclinepi.2016.01.021)). "
        "For each element, state `addressed`, `not applicable`, or `not performed` "
        "and link to the supporting section in this audit.",
        "",
        markdown_table(["PRESS 2015 element", "Coverage", "Notes / supporting section"], rows),
        "",
        "Peer review by an information specialist is still required before the strategy is run "
        "as a final search; this self-mapping is a coverage record, not a substitute for external "
        "PRESS peer review.",
        "",
    ]


def render_seed_validation(data: dict[str, Any]) -> list[str]:
    seed = as_dict(data.get("seed_validation"))
    pmids = as_list(seed.get("seed_pmids_tested") or data.get("seed_pmids"))
    lines = [
        "## Seed PMID validation",
        "",
        f"Seed PMIDs provided: **{'Yes' if pmids else 'No'}**.",
        "",
    ]
    if pmids:
        lines.extend(
            [
                f"- Seed PMIDs tested: {compact_text(pmids)}",
                f"- Retrieved: {compact_text(seed.get('retrieved'))}",
                f"- Missed: {compact_text(seed.get('missed'), 'none')}",
                f"- Reason for misses: {compact_text(seed.get('reason_for_misses'), 'none')}",
                f"- Revisions made after seed testing: {compact_text(seed.get('revisions_made_after_seed_testing'))}",
                f"- Seeds judged out of scope, if any: {compact_text(seed.get('seeds_judged_out_of_scope'), 'none')}",
            ]
        )
    else:
        lines.extend(
            [
                "- Validation was limited to MeSH checks, PubMed block testing, sample inspection, final QA, and filter checks where relevant.",
                "- True seed-derived MeSH and known-item recall were not available.",
            ]
        )
    lines.append("")
    return lines


def render_peer_review(data: dict[str, Any]) -> list[str]:
    points = as_list(data.get("peer_review_attention_points"))
    lines = [
        "## Peer review status",
        "",
        "**This is a draft strategy. Per PRESS (McGowan et al., 2016), it should be peer reviewed by a second information specialist before being run as the final search.**",
        "",
        "Peer-review attention points:",
    ]
    if points:
        for index, point in enumerate(points, start=1):
            lines.append(f"{index}. {compact_text(point)}")
    else:
        lines.append("1. not performed")
    lines.append("")
    return lines


def render_reporting_notes(data: dict[str, Any], output_path: Path | None = None) -> list[str]:
    notes = as_dict(data.get("reporting_notes"))
    output_text = str(output_path) if output_path else compact_text(notes.get("audit_markdown_file") or notes.get("audit_markdown_path"))
    fields = [
        ("Database", notes.get("database") or "PubMed"),
        ("Date searched", notes.get("date_searched") or data.get("date_searched") or date.today().isoformat()),
        ("Limits, filters, validated filters used", notes.get("limits_filters_validated_filters_used")),
        ("Restrictions and justifications", notes.get("restrictions_and_justifications")),
        ("Audit Markdown file", output_text),
        ("Audit workbook", notes.get("audit_workbook") or "not exported"),
        ("Run manifest", notes.get("run_manifest") or notes.get("run_manifest_path")),
        ("Remaining caveats", notes.get("remaining_caveats")),
        ("Other databases", notes.get("other_databases") or "Database-specific strategies for other sources were not requested / not built / built separately."),
    ]
    lines = ["## Reporting notes", ""]
    for label, value in fields:
        lines.append(f"- **{label}:** {compact_text(value)}")
    lines.append("")
    lines.append("For PRISMA-S 2021 reporting items applicable to this skill, see `references/prisma-s-reporting.md`.")
    lines.append("")
    return lines


def concept_block_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = first_value(data, ["concept_blocks", "blocks"], [])
    return [item for item in as_list(blocks) if isinstance(item, dict) and (item.get("query") or item.get("label"))]


def hash_combination(combination: Any, n_blocks: int) -> str:
    """Render a combination such as '1 AND 2' as '#1 AND #2'. Default: all blocks AND-ed."""
    text = compact_text(combination, "")
    if not text or text == DEFAULT_STATUS:
        return " AND ".join(f"#{i}" for i in range(1, n_blocks + 1))
    return re.sub(r"#?\b(\d+)\b", lambda m: f"#{m.group(1)}", text)


def build_line_set(data: dict[str, Any]) -> tuple[list[list[str]], list[str]]:
    """Return (table_rows, consistency_issues) for the numbered PubMed line set.

    Rows are 4-column [Line, Concept, Search query, Results]. The consistency guard flags a
    block whose query text does not appear in final_strategy - a sign the delivered strategy
    drifted from the blocks the line set is built from.
    """
    blocks = concept_block_rows(data)
    if not blocks:
        return [], []
    rows: list[list[str]] = []
    for index, block in enumerate(blocks, start=1):
        rows.append([
            f"#{index}",
            compact_text(block.get("label"), f"Concept {index}"),
            compact_text(block.get("query")),
            compact_text(block.get("count")),
        ])
    n = len(blocks)
    final_count = compact_text(first_value(data, ["result_count", "final_count", "topic_only_count"]))
    rows.append([f"#{n + 1}", "Topic (combined)", hash_combination(data.get("combination"), n), final_count])
    filt = as_dict(data.get("methodological_filter"))
    if filt.get("query"):
        rows.append([f"#{n + 2}", "Methodological filter", compact_text(filt.get("query")), compact_text(filt.get("count"))])
        rows.append([
            f"#{n + 3}",
            "Topic + filter",
            f"#{n + 1} AND #{n + 2}",
            compact_text(first_value(data, ["topic_plus_filter_count", "filter_count"])),
        ])

    issues: list[str] = []
    final_strategy = compact_text(first_value(data, ["final_strategy", "strategy", "final_pubmed_strategy"]), "")
    if final_strategy and final_strategy != DEFAULT_STATUS:
        norm_final = re.sub(r"\s+", " ", final_strategy).lower()
        for index, block in enumerate(blocks, start=1):
            query = compact_text(block.get("query"), "")
            if query and query != DEFAULT_STATUS and re.sub(r"\s+", " ", query).lower() not in norm_final:
                issues.append(f"block #{index} query is not present in the final strategy (possible line-set drift)")
    return rows, issues


def render_line_set(data: dict[str, Any]) -> list[str]:
    rows, issues = build_line_set(data)
    if not rows:
        return []
    date_searched = compact_text(
        first_value(data, ["date_searched", "reporting_notes.date_searched"], date.today().isoformat())
    )
    lines = [
        "## Search strategy (numbered line set)",
        "",
        f"PubMed, searched {date_searched}. Line numbers (`#n`) reference earlier lines, as in the PubMed Advanced Search history.",
        "",
        markdown_table(["Line", "Concept", "Search query", "Results"], rows),
        "",
    ]
    if issues:
        lines.append("**Line-set consistency warnings:**")
        lines.extend(f"- {issue}" for issue in issues)
        lines.append("")
    return lines


def render_prisma_s_appendix(data: dict[str, Any]) -> list[str]:
    notes = as_dict(data.get("reporting_notes"))
    filt = as_dict(data.get("methodological_filter"))
    date_searched = compact_text(
        first_value(data, ["date_searched", "reporting_notes.date_searched"], date.today().isoformat())
    )
    final_strategy = compact_text(first_value(data, ["final_strategy", "strategy", "final_pubmed_strategy"]))
    if filt.get("query") or filt.get("source"):
        filter_text = (
            f"{compact_text(filt.get('source'), 'validated filter')} "
            f"({compact_text(filt.get('version'), 'version not stated')}), PubMed interface; "
            f"adapted: {compact_text(filt.get('adapted'), 'no')}."
        )
    else:
        filter_text = "No methodological search filter was applied."
    multi_db = compact_text(
        notes.get("multi_database") or notes.get("other_databases"),
        "Out of scope for this strategy; the protocol should specify additional databases, each needing a translated strategy.",
    )
    limits = compact_text(
        notes.get("restrictions_and_justifications") or notes.get("limits"),
        "No limits or restrictions were applied.",
    )
    prior_work = compact_text(notes.get("prior_work"), "not applicable")
    updates = compact_text(notes.get("updates"), "No updates planned.")
    peer = compact_text(
        first_value(data, ["peer_review_status", "reporting_notes.peer_review"]),
        "Not yet peer reviewed; per PRESS (McGowan et al., 2016) it should be peer reviewed by a second information specialist before being run.",
    )
    return [
        "## PRISMA-S appendix (PubMed)",
        "",
        "Paste-ready reporting block; items follow PRISMA-S 2021 (Rethlefsen et al., 2021). See `references/prisma-s-reporting.md`.",
        "",
        "- **Database (Item 1):** PubMed (NLM interface, https://pubmed.ncbi.nlm.nih.gov/).",
        f"- **Multi-database searching (Item 2):** {multi_db}",
        "- **Full search strategy (Item 8):** the numbered line set above; final combined strategy:",
        "",
        "```text",
        final_strategy,
        "```",
        "",
        f"- **Limits and restrictions (Item 9):** {limits}",
        f"- **Search filters (Item 10):** {filter_text}",
        f"- **Prior work (Item 11):** {prior_work}",
        f"- **Updates (Item 12):** {updates}",
        f"- **Date of final search (Item 13):** {date_searched}",
        f"- **Peer review (Item 14):** {peer}",
        "- **Total records and deduplication (Items 15-16):** to be reported by the review team after the search is run.",
        "",
    ]


def render_appendix_document(data: dict[str, Any]) -> str:
    """Standalone paste-ready artifact: just the line set + PRISMA-S appendix."""
    title = compact_text(first_value(data, ["title", "topic", "review_question"], "PubMed search"))
    lines = [f"# {title} - search strategy appendix", ""]
    lines.extend(render_line_set(data))
    lines.extend(render_prisma_s_appendix(data))
    return "\n".join(lines).rstrip() + "\n"


def render_audit_markdown(data: dict[str, Any], output_path: Path | None = None) -> str:
    title = compact_text(first_value(data, ["title", "topic", "review_question"], "PubMed search audit"))
    lines = [f"# {title}", ""]
    lines.extend(render_search_structure(data))
    lines.extend(render_stage_trace(data))
    lines.extend(render_user_decisions(data))
    lines.extend(render_decision_ledger(data))
    lines.extend(render_record_content_evidence(data))
    lines.extend(render_final_strategy(data))
    lines.extend(render_line_set(data))
    lines.extend(render_ncbi_work(data))
    lines.extend(render_tiab_expansion(data))
    lines.extend(render_rationale(data))
    lines.extend(render_press_coverage(data))
    lines.extend(render_seed_validation(data))
    lines.extend(render_peer_review(data))
    lines.extend(render_reporting_notes(data, output_path))
    lines.extend(render_prisma_s_appendix(data))
    return "\n".join(lines).rstrip() + "\n"


def remove_fenced_blocks(markdown: str) -> str:
    lines = []
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines)


def unresolved_placeholders(markdown: str) -> list[str]:
    visible = remove_fenced_blocks(markdown)
    found = []
    for match in PLACEHOLDER_RE.finditer(visible):
        value = match.group(0)
        lower = value.lower()
        if lower in {"[tiab]", "[mesh]", "[mh]", "[pt]", "[sb]", "[ti]", "[ad]"}:
            continue
        if value not in found:
            found.append(value)
    return found


def write_audit_markdown(
    *,
    data: dict[str, Any],
    output: str | None,
    if_exists: str,
    allow_placeholders: bool,
) -> dict[str, Any]:
    initial_path = output_path_from_data(data, output)
    path = resolve_existing_path(initial_path, if_exists)
    record_issues = record_content_evidence_issues(data)
    if record_issues:
        preview = "; ".join(record_issues[:5])
        raise AuditMarkdownError(f"Record-content evidence validation failed: {preview}")
    markdown = render_audit_markdown(data, path)
    placeholders = unresolved_placeholders(markdown)
    if placeholders and not allow_placeholders:
        preview = ", ".join(placeholders[:5])
        raise AuditMarkdownError(f"Unresolved audit placeholders found: {preview}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return {
        "ok": True,
        "operation": "audit-markdown",
        "output_path": str(path),
        "bytes": path.stat().st_size,
        "placeholder_count": len(placeholders),
        "section_count": markdown.count("\n## "),
    }


def write_json(data: dict[str, Any]) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    json.dump(data, sys.stdout, indent=2, ensure_ascii="utf" not in encoding)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render PubMed audit JSON to a Markdown audit report.")
    parser.add_argument("audit_json", help="Structured audit JSON file. Use '-' for stdin.")
    parser.add_argument("--output", help="Markdown output path. Defaults to JSON reporting_notes or audit_<date>.md.")
    parser.add_argument(
        "--if-exists",
        choices=["fail", "suffix", "overwrite"],
        default="fail",
        help="How to handle an existing output path. Default: fail.",
    )
    parser.add_argument(
        "--overlay-json",
        help="Optional small authored JSON object to deep-merge into the audit scaffold before rendering.",
    )
    parser.add_argument("--allow-placeholders", action="store_true", help="Allow unresolved placeholder-like text.")
    parser.add_argument("--print-report", action="store_true", help="Print the full Markdown report instead of the compact JSON receipt.")
    parser.add_argument(
        "--emit-appendix",
        help="Also write a standalone paste-ready appendix (numbered line set + PRISMA-S block) to this path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data = load_json(args.audit_json)
        if args.overlay_json:
            data = merge_overlay(data, load_json(args.overlay_json))
        summary = write_audit_markdown(
            data=data,
            output=args.output,
            if_exists=args.if_exists,
            allow_placeholders=args.allow_placeholders,
        )
        if args.emit_appendix:
            appendix_markdown = render_appendix_document(data)
            appendix_placeholders = unresolved_placeholders(appendix_markdown)
            if appendix_placeholders and not args.allow_placeholders:
                raise AuditMarkdownError(
                    f"Unresolved appendix placeholders found: {', '.join(appendix_placeholders[:5])}"
                )
            appendix_path = resolve_existing_path(Path(args.emit_appendix), args.if_exists)
            appendix_path.parent.mkdir(parents=True, exist_ok=True)
            appendix_path.write_text(appendix_markdown, encoding="utf-8")
            summary["appendix_path"] = str(appendix_path)
        if args.print_report:
            sys.stdout.write(Path(summary["output_path"]).read_text(encoding="utf-8"))
        else:
            write_json(summary)
        return 0
    except AuditMarkdownError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
