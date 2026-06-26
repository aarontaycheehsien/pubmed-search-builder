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
            f"- **Concepts kept inside existing `OR` blocks:** {compact_text(search_structure.get('concepts_inside_or_blocks'))}",
            f"- **Omitted or reserve concepts:** {compact_text(search_structure.get('omitted_or_reserve_concepts'))}",
            f"- **Methodological filters or limits:** {compact_text(search_structure.get('methodological_filters_or_limits'))}",
            "",
        ]
    )
    return lines


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
            "### MeSH derived from PubMed query translations",
            "",
        ]
    )

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
        ("Proximity expressions added", "proximity_expressions_added"),
        ("Proximity expressions tested but rejected", "proximity_expressions_tested_but_rejected"),
        ("Wildcard stems added", "wildcard_stems_added"),
        ("Wildcard stems tested but rejected", "wildcard_stems_tested_but_rejected"),
    ]
    lines = ["## Title/abstract, proximity, and wildcard expansion log", ""]
    for label, key in fields:
        lines.append(f"- **{label}:** {compact_text(expansion.get(key))}")
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
                f"- Missed: {compact_text(seed.get('missed'))}",
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


def render_audit_markdown(data: dict[str, Any], output_path: Path | None = None) -> str:
    title = compact_text(first_value(data, ["title", "topic", "review_question"], "PubMed search audit"))
    lines = [f"# {title}", ""]
    lines.extend(render_search_structure(data))
    lines.extend(render_user_decisions(data))
    lines.extend(render_decision_ledger(data))
    lines.extend(render_final_strategy(data))
    lines.extend(render_ncbi_work(data))
    lines.extend(render_tiab_expansion(data))
    lines.extend(render_rationale(data))
    lines.extend(render_seed_validation(data))
    lines.extend(render_peer_review(data))
    lines.extend(render_reporting_notes(data, output_path))
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
        default="suffix",
        help="How to handle an existing output path. Default: suffix.",
    )
    parser.add_argument("--allow-placeholders", action="store_true", help="Allow unresolved placeholder-like text.")
    parser.add_argument("--print-report", action="store_true", help="Print the full Markdown report instead of the compact JSON receipt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data = load_json(args.audit_json)
        summary = write_audit_markdown(
            data=data,
            output=args.output,
            if_exists=args.if_exists,
            allow_placeholders=args.allow_placeholders,
        )
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
