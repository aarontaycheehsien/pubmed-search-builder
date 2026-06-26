#!/usr/bin/env python3
"""Hook-style QA helpers for the pubmed-search-builder skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ISSUE_LEVELS = ("error", "warning", "info")


def read_file(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8-sig")


def read_text_source(
    *,
    text: str | None,
    file_path: str | None,
    use_stdin: bool,
    parser: argparse.ArgumentParser,
    label: str,
) -> str:
    source_count = sum([text is not None, file_path is not None, use_stdin])
    if source_count != 1:
        parser.error(f"Provide exactly one {label} source.")
    if use_stdin:
        value = sys.stdin.read()
    elif file_path is not None:
        value = read_file(file_path)
    else:
        value = text or ""
    if not value.strip():
        parser.error(f"{label} text is empty.")
    return value


def add_issue(issues: list[dict[str, str]], severity: str, code: str, message: str, evidence: str = "") -> None:
    issue = {"severity": severity, "code": code, "message": message}
    if evidence:
        issue["evidence"] = evidence
    issues.append(issue)


def severity_counts(issues: list[dict[str, str]]) -> dict[str, int]:
    return {level: sum(1 for issue in issues if issue["severity"] == level) for level in ISSUE_LEVELS}


def snippets(pattern: str, text: str, *, flags: int = re.IGNORECASE, limit: int = 10) -> list[str]:
    found = []
    for match in re.finditer(pattern, text, flags):
        value = match.group(0)
        if value not in found:
            found.append(value)
        if len(found) >= limit:
            break
    return found


def compact_evidence(value: str, limit: int = 220) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def strip_outer_parentheses(text: str) -> str:
    value = text.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        in_quote = False
        balanced_outer = True
        for index, char in enumerate(value):
            if char == '"':
                in_quote = not in_quote
            if in_quote:
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    balanced_outer = False
                    break
        if not balanced_outer or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def split_top_level_and(text: str) -> list[str]:
    parts = []
    start = 0
    depth = 0
    in_quote = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            in_quote = not in_quote
            index += 1
            continue
        if not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(depth - 1, 0)
            elif depth == 0 and text[index : index + 3].upper() == "AND":
                before = text[index - 1] if index > 0 else " "
                after = text[index + 3] if index + 3 < len(text) else " "
                if not before.isalnum() and not after.isalnum():
                    part = text[start:index].strip()
                    if part:
                        parts.append(strip_outer_parentheses(part))
                    start = index + 3
                    index += 3
                    continue
        index += 1
    tail = text[start:].strip()
    if tail:
        parts.append(strip_outer_parentheses(tail))
    return parts


def split_top_level_or(text: str) -> list[str]:
    parts = []
    start = 0
    depth = 0
    in_quote = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            in_quote = not in_quote
            index += 1
            continue
        if not in_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(depth - 1, 0)
            elif depth == 0 and text[index : index + 2].upper() == "OR":
                before = text[index - 1] if index > 0 else " "
                after = text[index + 2] if index + 2 < len(text) else " "
                if not before.isalnum() and not after.isalnum():
                    part = text[start:index].strip()
                    if part:
                        parts.append(part)
                    start = index + 2
                    index += 2
                    continue
        index += 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def extract_leaf_atoms(text: str) -> list[str]:
    """Collect leaf OR-terms across arbitrary AND/OR nesting (quote/paren aware)."""
    text = strip_outer_parentheses(text.strip())
    if not text:
        return []
    and_parts = split_top_level_and(text)
    if len(and_parts) > 1:
        atoms: list[str] = []
        for part in and_parts:
            atoms.extend(extract_leaf_atoms(part))
        return atoms
    or_parts = split_top_level_or(text)
    if len(or_parts) > 1:
        atoms = []
        for part in or_parts:
            atoms.extend(extract_leaf_atoms(part))
        return atoms
    return [text]


def duplicate_term_issues(text: str) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for atom in extract_leaf_atoms(text):
        normalized = " ".join(atom.split()).lower()
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
        display.setdefault(normalized, " ".join(atom.split()))
    issues: list[dict[str, str]] = []
    for normalized, count in counts.items():
        if count > 1:
            add_issue(
                issues,
                "warning",
                "duplicate_term",
                "An exact term appears more than once; remove the duplicate copies. This is recall-neutral cleanup and reduces 'not found in PubMed' noise from repeated zero-hit terms.",
                f"{display[normalized]} ({count}x)",
            )
    return issues


def has_mesh_layer(text: str) -> bool:
    return bool(re.search(r"\[(?:mesh|mesh terms|mh|mesh:noexp)\]", text, re.IGNORECASE))


def has_tiab_layer(text: str) -> bool:
    return bool(re.search(r"\[(?:tiab|title/abstract)\]", text, re.IGNORECASE))


def likely_filter_or_limit_block(text: str) -> bool:
    lower = text.lower()
    if re.search(r"\[(?:pt|publication type|sb|lang|la|dp|date - publication|publication date|edat|crdt)\]", lower):
        return True
    return bool(
        re.search(
            r"\b(?:humans?|animals?|adult|child|adolescent|aged|infant)\s*\[(?:mesh|mesh terms|mh)\]",
            lower,
        )
    )


def add_layer_balance_issues(issues: list[dict[str, str]], text: str) -> None:
    blocks = split_top_level_and(text)
    concept_blocks = [block for block in blocks if not likely_filter_or_limit_block(block)]

    if len(concept_blocks) <= 1:
        has_mesh = has_mesh_layer(text)
        has_tiab = has_tiab_layer(text)
        if has_mesh and not has_tiab:
            add_issue(issues, "warning", "mesh_without_tiab", "A high-sensitivity concept should usually pair MeSH with title/abstract terms.")
        if has_tiab and not has_mesh:
            add_issue(issues, "info", "tiab_without_mesh", "Check whether an appropriate MeSH descriptor exists for each essential concept.")
        return

    for index, block in enumerate(concept_blocks, start=1):
        has_mesh = has_mesh_layer(block)
        has_tiab = has_tiab_layer(block)
        if has_mesh and not has_tiab:
            add_issue(
                issues,
                "warning",
                "concept_block_mesh_without_tiab",
                f"Concept block {index} has MeSH but no title/abstract layer.",
                compact_evidence(block),
            )
        if has_tiab and not has_mesh:
            add_issue(
                issues,
                "info",
                "concept_block_tiab_without_mesh",
                f"Concept block {index} has title/abstract terms but no MeSH layer.",
                compact_evidence(block),
            )


def detect_methodological_intents(text: str) -> list[str]:
    patterns = {
        "randomized-trial": r"\b(randomi[sz]ed|random allocation|clinical trial|controlled trial|rct)\b",
        "systematic-review": r"\b(systematic review|meta-analysis|metaanalysis|evidence synthesis|scoping review)\b",
        "qualitative": r"\b(qualitative|interview|focus group|ethnograph|grounded theory|thematic analysis)\b",
        "diagnostic": r"\b(diagnostic accuracy|sensitivity and specificity|specificity|receiver operating|roc curve|diagnos[ei]s)\b",
        "prognostic": r"\b(prognos|prediction model|predictive model|risk model|survival|mortality risk)\b",
        "observational": r"\b(cohort|case-control|cross-sectional|observational|registry|case series)\b",
        "economic": r"\b(cost-effectiveness|cost utility|economic evaluation|quality-adjusted|qaly)\b",
    }
    detected = []
    for label, pattern in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            detected.append(label)
    return detected


def detect_filter_fragments(text: str) -> list[str]:
    patterns = [
        r"\b(randomized controlled trial|controlled clinical trial|clinical trial|meta-analysis|systematic review)\[pt\]",
        r"\b(review|case reports|observational study|clinical trial)\[pt\]",
        r"\bclinical queries\b",
        r"\bcochrane hsss\b",
        r"\bmcMaster\b",
        r"\bISSG\b",
    ]
    found = []
    for pattern in patterns:
        found.extend(snippets(pattern, text))
    return found[:20]


def final_qa(strategy: str, *, zero_hit_terms: list[str] | None = None) -> dict[str, object]:
    issues: list[dict[str, str]] = []
    text = strategy.strip()
    lower = text.lower()

    if text.count("(") != text.count(")"):
        add_issue(issues, "error", "unbalanced_parentheses", "The strategy has an unequal number of opening and closing parentheses.")
    if text.count('"') % 2:
        add_issue(issues, "error", "unbalanced_quotes", "The strategy has an odd number of quotation marks.")

    major_topic = snippets(r"\[(?:majr|mesh major topic)\]", text)
    for value in major_topic:
        add_issue(issues, "warning", "major_topic_tag", "Major-topic tags reduce recall and need explicit justification.", value)

    not_ops = snippets(r"\bNOT\b", text, flags=0)
    for value in not_ops:
        add_issue(issues, "warning", "not_operator", "NOT can remove relevant records and needs explicit justification.", value)

    limit_patterns = {
        "language_limit": r"\b[a-z]+\[lang\]|\[la\]",
        "date_limit": r"\[(?:dp|date - publication|publication date|edat|crdt)\]",
        "species_limit": r"\b(?:humans?|animals?)\s*\[(?:mesh|mesh terms|mh)\]",
        "age_limit": r"\b(?:adult|child|adolescent|aged|infant)\s*\[(?:mesh|mesh terms|mh)\]",
        "publication_type_filter": r"\[(?:pt|publication type)\]",
        "full_text_filter": r"\b(?:free full text|full text)\[sb\]",
    }
    for code, pattern in limit_patterns.items():
        for value in snippets(pattern, lower):
            add_issue(issues, "warning", code, "Limits and filters can reduce recall; document the protocol justification and retrieval impact.", value)

    for value in snippets(r"\b[a-z][a-z0-9-]{0,3}\*", text):
        add_issue(issues, "warning", "short_wildcard", "Short wildcard stems can exceed PubMed's expansion cap or add heavy noise; test or replace them.", value)

    for value in snippets(r'"[^"]*\*[^"]*"\[(?:ti|tiab|ad):~\d+\]', text):
        add_issue(issues, "error", "proximity_with_truncation", "PubMed does not allow truncation inside proximity expressions.", value)

    issues.extend(duplicate_term_issues(text))

    for term in zero_hit_terms or []:
        value = term.strip()
        if value:
            add_issue(
                issues,
                "warning",
                "zero_hit_cleanup_candidate",
                "This term was reported as not found in PubMed; remove and document it by default unless intentionally retained for future reruns.",
                value,
            )

    add_layer_balance_issues(issues, text)

    intents = detect_methodological_intents(text)
    filters = detect_filter_fragments(text)
    if intents or filters:
        add_issue(
            issues,
            "warning",
            "methodological_filter_review_needed",
            "Run hooks_tool.py filter-check. If a methodological filter is used, document source and count impact; if the language is topical, use --filter-decision none with a reason.",
            ", ".join(intents or filters),
        )

    followups = [
        "Resolve all errors before final output.",
        "Document justification for all recall-reducing warnings that remain.",
        "Include unresolved limitations in the final strategy notes.",
    ]
    if any(issue["code"] == "duplicate_term" for issue in issues):
        followups.append(
            "Remove the terms flagged as duplicate_term; this is recall-neutral cleanup, not a recall-reducing warning to justify."
        )
    if any(issue["code"] == "zero_hit_cleanup_candidate" for issue in issues):
        followups.append(
            "Remove and document zero_hit_cleanup_candidate terms by default after checking spelling, hyphenation, and spacing."
        )

    return {
        "hook": "pre_final_strategy_qa",
        "ok": not any(issue["severity"] == "error" for issue in issues),
        "issue_counts": severity_counts(issues),
        "issues": issues,
        "required_followups": followups,
    }


def filter_check(
    text: str,
    *,
    filter_decision: str,
    no_filter_reason: str | None,
    filter_source: str | None,
    topic_only_count: int | None,
    topic_plus_filter_count: int | None,
    seed_impact: str | None,
    seed_pmids: list[str] | None,
) -> dict[str, object]:
    issues: list[dict[str, str]] = []
    intents = detect_methodological_intents(text)
    filters = detect_filter_fragments(text)
    review_needed = bool(intents or filters)
    no_filter_used = filter_decision == "none"
    validated_filter_review_needed = review_needed and (not no_filter_used or bool(filters))

    if no_filter_used and filters:
        add_issue(
            issues,
            "warning",
            "filter_fragments_conflict_with_none",
            "The text appears to contain methodological filter fragments, but filter decision is 'none'; verify that no filter was actually applied.",
            ", ".join(filters),
        )
    if no_filter_used and review_needed and not no_filter_reason:
        add_issue(
            issues,
            "warning",
            "missing_no_filter_reason",
            "State why no methodological filter was applied even though diagnostic, prognostic, or other evidence-type language was detected.",
        )
    if review_needed and not no_filter_used and not filter_source:
        add_issue(
            issues,
            "warning",
            "missing_validated_filter_source",
            "State the validated filter or hedge source, version, interface, and any adaptation.",
        )
    if review_needed and not no_filter_used and topic_only_count is None:
        add_issue(issues, "warning", "missing_topic_only_count", "Test and report the topic-only PubMed count before adding the filter.")
    if review_needed and not no_filter_used and topic_plus_filter_count is None:
        add_issue(issues, "warning", "missing_topic_plus_filter_count", "Test and report the topic-plus-filter PubMed count.")
    if review_needed and not no_filter_used and seed_pmids and not seed_impact:
        add_issue(issues, "warning", "missing_seed_filter_impact", "Check whether the methodological filter loses any supplied seed PMIDs.")

    required_actions = []
    if review_needed and no_filter_used:
        required_actions = [
            "Document that the detected evidence-type language is part of the topical concept rather than a methodological search filter.",
            "Report that no methodological filter or hedge was applied and give the reason.",
        ]
    elif review_needed:
        required_actions = [
            "Read references/validated-methodological-filters-and-hedges.md before finalizing the filter.",
            "Prefer a validated PubMed/interface-appropriate filter over ad hoc construction.",
            "Use pubmed_tool.py batch to compare topic-only and topic-plus-filter counts.",
            "If seed PMIDs exist, validate topic-only and topic-plus-filter retrieval separately.",
            "Cite filter source, version, interface, adaptation, and recall risk in final output.",
        ]

    return {
        "hook": "methodological_filter_check",
        "requires_methodological_filter_review": review_needed,
        "requires_validated_filter_review": validated_filter_review_needed,
        "filter_decision": filter_decision,
        "no_filter_reason": no_filter_reason or "",
        "detected_intents": intents,
        "detected_filter_fragments": filters,
        "filter_source": filter_source or "",
        "topic_only_count": topic_only_count,
        "topic_plus_filter_count": topic_plus_filter_count,
        "seed_pmids": seed_pmids or [],
        "seed_impact": seed_impact or "",
        "ok": not any(issue["severity"] == "error" for issue in issues),
        "issue_counts": severity_counts(issues),
        "issues": issues,
        "required_actions": required_actions,
    }


def write_json(data: dict[str, object]) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    json.dump(data, sys.stdout, indent=2, ensure_ascii="utf" not in encoding)
    sys.stdout.write("\n")


def add_text_args(parser: argparse.ArgumentParser, prefix: str, help_label: str) -> None:
    parser.add_argument(f"--{prefix}", help=help_label)
    parser.add_argument(f"--{prefix}-file", help=f"Read {help_label} from a UTF-8 file. Use '-' for stdin.")
    parser.add_argument(f"--{prefix}-stdin", action="store_true", help=f"Read {help_label} from stdin.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hook-style QA helpers for PubMed search strategies.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    qa_parser = subparsers.add_parser("final-qa", help="Run pre-final strategy QA checks.")
    add_text_args(qa_parser, "strategy", "strategy text")
    qa_parser.add_argument(
        "--zero-hit-terms",
        nargs="*",
        default=[],
        help="Terms reported by PubMed as not found; emitted as zero_hit_cleanup_candidate issues.",
    )

    filter_parser = subparsers.add_parser("filter-check", help="Check methodological filter requirements.")
    add_text_args(filter_parser, "text", "protocol/request/strategy text")
    filter_parser.add_argument(
        "--filter-decision",
        choices=["undecided", "used", "none"],
        default="undecided",
        help="Whether a methodological filter/hedge was used, intentionally not used, or not yet decided.",
    )
    filter_parser.add_argument("--no-filter-reason", help="Reason no methodological filter was applied when evidence-type language is topical.")
    filter_parser.add_argument("--filter-source")
    filter_parser.add_argument("--topic-only-count", type=int)
    filter_parser.add_argument("--topic-plus-filter-count", type=int)
    filter_parser.add_argument("--seed-impact", help="Summary of seed PMID impact after adding the filter.")
    filter_parser.add_argument("--seed-pmids", nargs="*", default=[])

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "final-qa":
        strategy = read_text_source(
            text=args.strategy,
            file_path=args.strategy_file,
            use_stdin=args.strategy_stdin,
            parser=parser,
            label="strategy",
        )
        write_json(final_qa(strategy, zero_hit_terms=args.zero_hit_terms))
    elif args.command == "filter-check":
        text = read_text_source(
            text=args.text,
            file_path=args.text_file,
            use_stdin=args.text_stdin,
            parser=parser,
            label="filter-check",
        )
        write_json(
            filter_check(
                text,
                filter_decision=args.filter_decision,
                no_filter_reason=args.no_filter_reason,
                filter_source=args.filter_source,
                topic_only_count=args.topic_only_count,
                topic_plus_filter_count=args.topic_plus_filter_count,
                seed_impact=args.seed_impact,
                seed_pmids=args.seed_pmids,
            )
        )
    else:
        parser.error(f"Unknown command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
