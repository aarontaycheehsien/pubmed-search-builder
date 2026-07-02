#!/usr/bin/env python3
"""Small PubMed E-utilities helper for the pubmed-search-builder skill."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_EMAIL = ""
DEFAULT_TOOL = "codex-search-strategy-check"
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_RETRIES = 3
REQUEST_BACKOFF_SECONDS = 1.0
TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
INLINE_QUERY_WARNING_LENGTH = 1400
HUGE_RETMAX_WARNING = 1000
QUERY_TRANSLATION_MAX_ISSUES = 5
QUERY_TRANSLATION_EVIDENCE_LIMIT = 240
ATM_EXPANSION_RATIO_WARNING = 4.0
RELATED_MAX_PER_SEED = 20
RELATED_MAX_TOTAL = 200
RELATED_LINKNAMES = {
    "similar": "pubmed_pubmed",
    "citedin": "pubmed_pubmed_citedin",
    "refs": "pubmed_pubmed_refs",
}
ENV_FILE_CACHE: dict[str, str] | None = None
API_KEY_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?P<name>NCBI_API_KEY|api[_-]?key)\s*=\s*(?P<value>[^\s&),;]+)",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9-]{1,9}s?\b")
STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "with",
    "would",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}

VARIANT_METADATA_FIELDS = (
    "role",
    "hypothesis",
    "changes_from_baseline",
    "recall_risk",
    "workload_rationale",
    "decision_status",
    "decision_reason",
)
SEED_VALIDATION_WARNING = "Seed PMID retrieval is known-item validation, not true search sensitivity."
RECALL_UID_CHUNK = 100
BENCHMARK_QUERY_CAP = 500
RELATIVE_RECALL_NOTE = (
    "Relative recall is the share of a benchmark relevant set the strategy retrieves; it is "
    "relative to that benchmark, not absolute search sensitivity. Against a seed-expansion "
    "benchmark (e.g. a related-articles/citation set) it is a heuristic that can flatter recall, "
    "because the benchmark is strategy-adjacent. Against an independent, hand-screened gold "
    "standard (e.g. the included studies of a prior review) it is a legitimate relative-recall "
    "estimate but still not absolute sensitivity, since no negatives are screened. A benchmark "
    "PMID that is not in PubMed is indistinguishable from a genuine miss. Do not use a recall "
    "number to silently narrow a recall-first strategy."
)
TERM_DIFF_NOTE = (
    "Controlled-vocabulary vs free-text differential (Bramer et al. 2018, doi:10.5195/jmla.2018.283), "
    "a term-discovery aid, not validated recall. Read mesh_only records (indexed under the MeSH "
    "layer but missed by the [tiab] layer) to harvest free-text phrasings/synonyms to ADD to the "
    "[tiab] layer; read tiab_only records (caught by free text but not the MeSH layer) for missing "
    "MeSH descriptors and indexing gaps/recent unindexed records. Inspect the saved records before "
    "deciding (No reviewed JSON, no decision). Classify harvested terms by concept role like any "
    "other candidate; never auto-add. Recall-only: use this to ADD coverage, never to remove terms."
)
NO_LABELLED_SAMPLE_NOTE = "not estimable; no labelled sample supplied"
ZERO_RELEVANT_SAMPLE_NOTE = "undefined/infinite; zero relevant labelled records"
TRUE_RELEVANCE_VALUES = {"1", "true", "yes", "y", "relevant", "include", "included"}
FALSE_RELEVANCE_VALUES = {"0", "false", "no", "n", "irrelevant", "exclude", "excluded", "not relevant"}
SAMPLE_METADATA_KEYS = {"sample_description", "description", "method", "sampling_method", "note", "notes"}

DEFAULT_TERM_RANK_MAX_TERMS = 40
TERM_RANK_RELEVANT_QUERY_CAP = 200
PUBMED_TOTAL_ESTIMATE = 38_000_000
TERM_RANK_NOISE_BACKGROUND = 100_000
TERM_RANK_NOISE_COVERAGE = 0.5
TERM_RANK_FIELDS = ("tiab", "mesh")
TERM_RANK_CAVEAT = (
    "Term-rank scores are descriptive term-discovery aids derived from a relevant/seed record set, "
    "not validated search recall. coverage = relevant_df / relevant_record_count. "
    "lift = coverage / (background_count / pubmed_total_estimate) and uses an approximate corpus "
    "size, so lift is meaningful only for relative ranking, not as an absolute statistic. "
    "Treat high-coverage, high-lift terms as strong [tiab]/[Mesh] candidates and verify in PubMed. "
    "Structured-abstract section labels (e.g. OBJECTIVES, RESULTS), statistical fragments "
    "(e.g. 'p 0', '95 ci'), and non-topical MeSH (check tags such as Humans/Female and common "
    "geographic descriptors such as Queensland) are excluded from candidates before scoring."
)

# Term-rank noise classes dropped from candidates before scoring (see term_rank_noise_reason).
# Stored as normalize_for_match()-normalized forms (lowercase, alnum tokens, single spaces).
STRUCTURED_ABSTRACT_HEADINGS = {
    "background", "objective", "objectives", "aim", "aims", "goal", "goals", "purpose",
    "introduction", "importance", "rationale", "context",
    "method", "methods", "methodology", "materials and methods", "patients and methods",
    "design", "study design", "setting", "settings",
    "participant", "participants", "subjects",
    "intervention", "interventions", "exposure", "exposures",
    "measurement", "measurements", "main outcome measures", "main outcome measure",
    "outcome", "outcomes", "outcome measures", "main results",
    "result", "results", "finding", "findings",
    "conclusion", "conclusions", "conclusions and relevance", "interpretation", "discussion",
    "data sources", "study selection", "data extraction", "data synthesis", "data collection",
    "eligibility criteria", "selection criteria", "search strategy",
    "limitation", "limitations",
    "trial registration", "clinical trial registration", "registration",
    "funding", "keywords",
}

NON_TOPICAL_TERMS = {
    # MeSH check tags (complete).
    "humans", "animals", "male", "female", "pregnancy",
    "infant", "infant newborn", "child", "child preschool", "adolescent",
    "adult", "young adult", "middle aged", "aged", "aged 80 and over",
    # Common geographic descriptors (partial; rare place names may still slip through).
    "africa", "asia", "europe", "north america", "south america", "australia",
    "antarctica", "oceania", "americas", "latin america", "caribbean region",
    "mediterranean region", "scandinavian and nordic countries",
    "united states", "united states of america", "usa", "united kingdom", "great britain",
    "canada", "new zealand", "china", "india", "japan", "south korea", "republic of korea",
    "germany", "france", "italy", "spain", "netherlands", "sweden", "norway", "denmark",
    "finland", "switzerland", "belgium", "austria", "ireland", "portugal", "greece", "poland",
    "russia", "brazil", "mexico", "argentina", "chile", "colombia", "south africa", "nigeria",
    "kenya", "ethiopia", "ghana", "egypt", "israel", "saudi arabia", "iran", "iraq", "turkey",
    "pakistan", "bangladesh", "sri lanka", "nepal", "indonesia", "malaysia", "philippines",
    "thailand", "vietnam", "singapore", "taiwan", "hong kong",
    "queensland", "new south wales", "victoria", "western australia", "south australia",
    "tasmania", "northern territory", "england", "scotland", "wales", "northern ireland",
    "california", "texas", "florida", "new york", "ontario", "quebec", "british columbia",
}

# >=3-letter statistical markers that must not count as a "content" token in the fragment check.
STAT_WORDS = {"iqr", "sem", "aor"}

# Section-label words that are never topical, so a tiab phrase beginning or ending with one is a
# structured-abstract artifact (e.g. "results copd", "objectives to assess"). Deliberately a
# conservative subset of STRUCTURED_ABSTRACT_HEADINGS: words that double as topical modifiers
# (intervention, exposure, outcome, design, setting, participants, subjects, context) are excluded
# so phrases like "early intervention" survive.
BOUNDARY_NOISE_TOKENS = {
    "background", "objective", "objectives", "aim", "aims", "goal", "goals", "purpose",
    "introduction", "importance", "rationale",
    "method", "methods", "methodology",
    "result", "results", "finding", "findings",
    "conclusion", "conclusions", "interpretation", "discussion",
    "limitation", "limitations", "registration", "funding", "keywords",
}


class PubMedError(Exception):
    pass


def retry_delay(attempt: int) -> float:
    # exponential backoff with light jitter to avoid synchronized retries during sweeps
    base = REQUEST_BACKOFF_SECONDS * (2 ** attempt)
    return base + random.uniform(0, REQUEST_BACKOFF_SECONDS)


def transient_http_error(exc: urllib.error.HTTPError) -> bool:
    return exc.code in TRANSIENT_HTTP_STATUS


def parse_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def env_file_values() -> dict[str, str]:
    global ENV_FILE_CACHE
    if ENV_FILE_CACHE is not None:
        return ENV_FILE_CACHE

    values: dict[str, str] = {}
    seen: set[Path] = set()
    candidates = [
        Path(__file__).resolve().parents[1] / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        values.update(parse_env_file(candidate))

    ENV_FILE_CACHE = values
    return values


def read_env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    value = env_file_values().get(name)
    if value:
        return value
    if os.name != "nt":
        return default
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value) if value else default
    except OSError:
        return default


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def normalize_query(query: str) -> str:
    return " ".join(query.split())


def read_text_source(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def resolve_query(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    query = getattr(args, "query", None)
    query_file = getattr(args, "query_file", None)
    query_stdin = getattr(args, "query_stdin", False)

    source_count = sum(
        [
            query is not None,
            query_file is not None,
            bool(query_stdin),
        ]
    )
    if source_count != 1:
        parser.error("Provide exactly one query source: query, --query-file, or --query-stdin.")

    if query_stdin:
        text = sys.stdin.read()
    elif query_file is not None:
        text = read_text_source(query_file)
    elif query == "-":
        text = sys.stdin.read()
    else:
        text = str(query)

    resolved = normalize_query(text)
    if not resolved:
        parser.error("Query is empty.")
    return resolved


def resolve_named_query(inline: str | None, file_arg: str | None, label: str, parser: argparse.ArgumentParser) -> str:
    """Resolve a named query from an inline string or a file (UTF-8, '-' for stdin); exactly one required."""
    if inline is not None and file_arg is not None:
        parser.error(f"Use only one of --{label}-query or --{label}-query-file.")
    if file_arg is not None:
        text = read_text_source(file_arg)
    elif inline is not None:
        text = sys.stdin.read() if inline == "-" else inline
    else:
        parser.error(f"Provide --{label}-query or --{label}-query-file.")
    resolved = normalize_query(text)
    if not resolved:
        parser.error(f"The {label} query is empty.")
    return resolved


def parse_batch_queries(raw: str) -> list[dict[str, str]]:
    stripped = raw.strip()
    if not stripped:
        raise PubMedError("Batch query input is empty.")

    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise PubMedError(f"Could not parse batch JSON: {exc}") from exc
        if isinstance(data, dict):
            items = []
            for label, query in data.items():
                assert_plain_query(str(label), query)
                items.append({"label": str(label), "query": str(query)})
        elif isinstance(data, list):
            items = []
            for index, item in enumerate(data, start=1):
                if isinstance(item, str):
                    assert_plain_query(f"query_{index}", item)
                    items.append({"label": f"query_{index}", "query": item})
                elif isinstance(item, dict):
                    label = item.get("label") or item.get("name") or f"query_{index}"
                    query = item.get("query")
                    assert_plain_query(str(label), query)
                    items.append({"label": str(label), "query": str(query)})
                else:
                    raise PubMedError(f"Batch item {index} must be a string or object.")
        else:
            raise PubMedError("Batch JSON must be an object or array.")
    else:
        items = []
        for index, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                label, query = line.split("\t", 1)
                items.append({"label": label.strip() or f"query_{index}", "query": query})
            else:
                items.append({"label": f"query_{index}", "query": line})

    normalized = []
    for index, item in enumerate(items, start=1):
        query = normalize_query(item["query"])
        if not query:
            raise PubMedError(f"Batch item {index} has an empty query.")
        normalized.append({"label": item["label"], "query": query})
    return normalized


def query_source(args: argparse.Namespace) -> str:
    if getattr(args, "query_file", None) is not None:
        return "file"
    if getattr(args, "query_stdin", False) or getattr(args, "query", None) == "-":
        return "stdin"
    if getattr(args, "query", None) is not None:
        return "argument"
    return "none"


def add_hook_issue(issues: list[dict[str, str]], severity: str, code: str, message: str) -> None:
    issues.append({"severity": severity, "code": code, "message": message})


def compact_evidence(value: object, limit: int = QUERY_TRANSLATION_EVIDENCE_LIMIT) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def add_translation_issue(
    issues: list[dict[str, str]],
    severity: str,
    code: str,
    message: str,
    evidence: object = "",
) -> None:
    if len(issues) >= QUERY_TRANSLATION_MAX_ISSUES:
        return
    issue = {"severity": severity, "code": code, "message": message}
    if evidence:
        issue["evidence"] = compact_evidence(evidence)
    issues.append(issue)


def normalize_warning_items(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, dict):
        items = []
        for key, nested in value.items():
            for item in normalize_warning_items(nested):
                items.append(f"{key}: {item}")
        return items
    text = str(value).strip()
    return [text] if text else []


def warning_code(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"pubmed_warning_{normalized or 'message'}"


def translation_pairs(translations: object) -> list[str]:
    if not isinstance(translations, list):
        return []
    pairs = []
    for item in translations:
        if not isinstance(item, dict):
            continue
        source = item.get("from") or item.get("From") or ""
        target = item.get("to") or item.get("To") or ""
        if source or target:
            pairs.append(f"{source} -> {target}")
    return pairs


def translation_sources(translations: object) -> list[str]:
    if not isinstance(translations, list):
        return []
    sources = []
    for item in translations:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or item.get("From") or "").strip()
        if source:
            sources.append(source)
    return sources


def field_tags(text: str) -> list[str]:
    return re.findall(r"\[[^\]]+\]", text)


def untagged_terms(text: str) -> list[str]:
    without_tagged_phrases = re.sub(r'"[^"]+"\s*\[[^\]]+\]', " ", text)
    without_tagged_terms = re.sub(r"\b[\w*.-]+\b\s*\[[^\]]+\]", " ", without_tagged_phrases)
    without_tags = re.sub(r"\[[^\]]+\]", " ", without_tagged_terms)
    tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9-]{1,}\b", without_tags)
    ignored = {"AND", "OR", "NOT"}
    return [token for token in tokens if token.upper() not in ignored]


def query_translation_drift_hook(
    query: str,
    query_translation: str,
    translations: object,
    warnings: object,
    errors: object = None,
) -> dict[str, object]:
    issues: list[dict[str, str]] = []

    if isinstance(warnings, dict):
        for key, value in warnings.items():
            for item in normalize_warning_items(value):
                add_translation_issue(
                    issues,
                    "warning",
                    warning_code(key),
                    "PubMed reported a query translation warning; review the translated query before relying on the count.",
                    f"{key}: {item}",
                )
    else:
        for item in normalize_warning_items(warnings):
            add_translation_issue(
                issues,
                "warning",
                "pubmed_warning_message",
                "PubMed reported a query translation warning; review the translated query before relying on the count.",
                item,
            )

    if isinstance(errors, dict):
        phrase_items = normalize_warning_items(errors.get("phrasesnotfound"))
        field_items = normalize_warning_items(errors.get("fieldsnotfound"))
    elif errors:
        phrase_items = normalize_warning_items(errors)
        field_items = []
    else:
        phrase_items = []
        field_items = []

    not_found = list(dict.fromkeys(phrase_items))
    if not_found:
        evidence = ", ".join(not_found)
        if len(phrase_items) > len(not_found):
            evidence += f" ({len(phrase_items)} total occurrences)"
        add_translation_issue(
            issues,
            "warning",
            "phrases_not_found",
            "PubMed found no records for these terms (zero hits). The default is to remove and document them (removal is recall-neutral since they match no records); offer to keep any as an intentional zero-hit term. First check spelling, hyphenation, and spacing variants, because a not-found term may be a typo for a real term rather than genuinely absent.",
            evidence,
        )

    fields_not_found = list(dict.fromkeys(field_items))
    if fields_not_found:
        add_translation_issue(
            issues,
            "warning",
            "fields_not_found",
            "PubMed did not recognize these field tags, so part of the query may be silently mis-scoped; fix the field tag.",
            ", ".join(fields_not_found),
        )

    tags = field_tags(query)
    atm_sources = translation_sources(translations)
    untagged = atm_sources if tags else atm_sources or untagged_terms(query)
    has_translation = bool(query_translation.strip())
    lower_translation = query_translation.lower()

    if untagged and translation_pairs(translations):
        add_translation_issue(
            issues,
            "info",
            "automatic_term_mapping_used",
            "Untagged query text triggered PubMed Automatic Term Mapping.",
            "; ".join(translation_pairs(translations)[:3]),
        )

    if untagged and "[all fields]" in lower_translation:
        add_translation_issue(
            issues,
            "warning",
            "all_fields_mapping",
            "PubMed mapped untagged text to All Fields; confirm this broad fallback is intentional.",
            query_translation,
        )

    if untagged and ("[mesh terms]" in lower_translation or "[mesh]" in lower_translation):
        add_translation_issue(
            issues,
            "info",
            "mesh_mapping_from_atm",
            "PubMed mapped untagged text to MeSH; confirm the mapped concept matches the intended meaning.",
            query_translation,
        )

    acronym_terms = []
    for term in untagged:
        acronym_terms.extend(re.findall(r"\b[A-Z0-9]{2,6}\b", term))
    if acronym_terms and has_translation:
        add_translation_issue(
            issues,
            "warning",
            "untagged_acronym_mapping",
            "Short uppercase or acronym-like terms were untagged; PubMed may map them ambiguously.",
            ", ".join(acronym_terms),
        )

    normalized_query_length = max(len(" ".join(query.split())), 1)
    normalized_translation_length = len(" ".join(query_translation.split()))
    if untagged and normalized_translation_length > max(200, int(normalized_query_length * ATM_EXPANSION_RATIO_WARNING)):
        add_translation_issue(
            issues,
            "warning",
            "large_translation_expansion",
            "PubMed expanded the query translation substantially; review for unintended broadening.",
            query_translation,
        )

    if tags and untagged and translation_pairs(translations):
        add_translation_issue(
            issues,
            "warning",
            "mixed_tagged_and_untagged_query",
            "The query mixes field-tagged and untagged text, so only part of it may be controlled by explicit field tags.",
            ", ".join(untagged[:8]),
        )

    if tags and not untagged and has_translation and "[all fields]" in lower_translation and "[all fields]" not in query.lower():
        add_translation_issue(
            issues,
            "warning",
            "fielded_query_all_fields_fallback",
            "A mostly field-tagged query translated to All Fields; confirm PubMed did not broaden the intended field scope.",
            query_translation,
        )

    return {
        "name": "query_translation_drift",
        "ok": True,
        "review_recommended": bool(issues),
        "issues": issues,
    }


def query_inputs(
    *,
    query: str | None = None,
    queries: list[dict[str, object]] | None = None,
) -> list[tuple[str, str]]:
    values = []
    if query:
        values.append(("query", query))
    for index, item in enumerate(queries or [], start=1):
        label = str(item.get("label") or f"batch query {index}")
        item_query = str(item.get("query") or "")
        if item_query:
            values.append((label, item_query))
    return values


def text_contains_api_key_value(client: "NcbiClient", text: str) -> bool:
    return bool(client.api_key and client.api_key in text)


def text_contains_api_key_assignment(text: str) -> bool:
    return bool(API_KEY_ASSIGNMENT_PATTERN.search(text))


def pre_command_hook(
    client: "NcbiClient",
    args: argparse.Namespace,
    *,
    query: str | None = None,
    queries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    issues: list[dict[str, str]] = []
    argv = sys.argv[1:]

    if client.api_key and any(client.api_key in item for item in argv):
        add_hook_issue(
            issues,
            "error",
            "api_key_on_command_line",
            "The NCBI API key appears in the command line. Use the NCBI_API_KEY environment variable instead.",
        )

    if any("api_key=" in item.lower() or item.upper().startswith("NCBI_API_KEY=") for item in argv):
        add_hook_issue(
            issues,
            "error",
            "api_key_argument",
            "Do not pass API keys as command arguments or query parameters.",
        )

    for label, value in query_inputs(query=query, queries=queries):
        if text_contains_api_key_value(client, value):
            add_hook_issue(
                issues,
                "error",
                "api_key_in_query_text",
                "The NCBI API key appears in query text. Use the NCBI_API_KEY environment variable instead.",
            )
            break

    for label, value in query_inputs(query=query, queries=queries):
        if text_contains_api_key_assignment(value):
            add_hook_issue(
                issues,
                "error",
                "api_key_assignment_in_query_text",
                "Query text contains an API-key assignment. Do not put API keys in queries, query files, or stdin.",
            )
            break

    if query and len(query) > INLINE_QUERY_WARNING_LENGTH and query_source(args) == "argument":
        add_hook_issue(
            issues,
            "warning",
            "long_inline_query",
            "Long PubMed strategies should use --query-file or --query-stdin to avoid shell quoting errors.",
        )

    for item in queries or []:
        if len(item.get("query", "")) > INLINE_QUERY_WARNING_LENGTH:
            add_hook_issue(
                issues,
                "warning",
                "long_batch_query",
                f"Batch query '{item.get('label', '')}' is long; keep batch files as UTF-8 text/JSON rather than shell arguments.",
            )

    retmax = getattr(args, "retmax", None)
    if isinstance(retmax, int):
        if retmax > HUGE_RETMAX_WARNING:
            add_hook_issue(
                issues,
                "warning",
                "large_retmax",
                f"retmax={retmax} is large. Use --retmax 0 for count-only block testing or sample only a small inspection set.",
            )
        elif args.command == "batch" and retmax > 0:
            add_hook_issue(
                issues,
                "info",
                "count_only_preferred",
                "Use --retmax 0 for batch count comparisons unless returned PMID samples are needed.",
            )

    return {
        "name": "pre_pubmed_command",
        "ok": not any(issue["severity"] == "error" for issue in issues),
        "issues": issues,
    }


def attach_hook(data: dict[str, object], hook: dict[str, object]) -> dict[str, object]:
    data["pre_command_hook"] = hook
    return data


class NcbiClient:
    def __init__(self) -> None:
        self.email = read_env("NCBI_EMAIL", DEFAULT_EMAIL)
        self.tool = read_env("NCBI_TOOL", DEFAULT_TOOL)
        self.api_key = read_env("NCBI_API_KEY", "")
        self.rate_limit_per_second = 10 if self.api_key else 3
        self.min_interval = 1.0 / self.rate_limit_per_second
        self._last_request = 0.0
        self.retries_performed = 0  # transient NCBI retries this run, surfaced in metadata()

    def common_params(self) -> dict[str, str]:
        params = {
            "tool": self.tool,
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def request(self, endpoint: str, params: dict[str, str], *, method: str = "GET") -> bytes:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

        url = f"{BASE_URL}/{endpoint}"
        merged = self.common_params()
        merged.update(params)
        encoded = urllib.parse.urlencode(merged).encode("utf-8")

        if method == "POST":
            req = urllib.request.Request(url, data=encoded, method="POST")
        else:
            req = urllib.request.Request(f"{url}?{encoded.decode('utf-8')}", method="GET")

        user_agent = f"{self.tool}/1.0"
        if self.email:
            user_agent = f"{user_agent} ({self.email})"
        req.add_header("User-Agent", user_agent)

        for attempt in range(REQUEST_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    data = response.read()
                self._last_request = time.monotonic()
                return data
            except urllib.error.HTTPError as exc:
                if not transient_http_error(exc) or attempt == REQUEST_RETRIES:
                    body = exc.read().decode("utf-8", errors="replace")[:2000]
                    raise PubMedError(
                        f"NCBI HTTP {exc.code} after {attempt + 1} attempt(s): {body}"
                    ) from exc
            except urllib.error.URLError as exc:
                if attempt == REQUEST_RETRIES:
                    raise PubMedError(
                        f"NCBI request failed after {attempt + 1} attempt(s): {exc.reason}"
                    ) from exc
            except TimeoutError as exc:
                if attempt == REQUEST_RETRIES:
                    raise PubMedError(
                        f"NCBI request timed out after {attempt + 1} attempt(s): {exc}"
                    ) from exc
            except OSError as exc:
                if attempt == REQUEST_RETRIES:
                    raise PubMedError(
                        f"NCBI request failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
            # Reaching here means a transient error was caught and another attempt follows.
            self.retries_performed += 1
            time.sleep(retry_delay(attempt))

        raise PubMedError("NCBI request failed: retries exhausted.")

    def metadata(self) -> dict[str, object]:
        return {
            "tool": self.tool,
            "email_configured": bool(self.email),
            "api_key_used": bool(self.api_key),
            "rate_limit_per_second": self.rate_limit_per_second,
            "retries_performed": self.retries_performed,
        }


def esearch(client: NcbiClient, query: str, retmax: int, retstart: int, sort: str | None) -> dict[str, object]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": str(retmax),
        "retstart": str(retstart),
    }
    if sort:
        params["sort"] = sort

    raw = client.request("esearch.fcgi", params, method="POST" if len(query) > 1400 else "GET")
    data = json.loads(raw.decode("utf-8"))
    result = data.get("esearchresult", {})
    query_translation = result.get("querytranslation", "")
    translations = result.get("translationset", [])
    warnings = result.get("warninglist", {})
    errors = result.get("errorlist", {})
    return {
        "query": query,
        "count": int(result.get("count", 0)),
        "retmax": int(result.get("retmax", retmax)),
        "retstart": int(result.get("retstart", retstart)),
        "pmids": result.get("idlist", []),
        "query_translation": query_translation,
        "translations": translations,
        "warnings": warnings,
        "errors": errors,
        "query_translation_hook": query_translation_drift_hook(query, query_translation, translations, warnings, errors),
        "request_info": client.metadata(),
    }


def parse_article(article: ET.Element) -> dict[str, object]:
    citation = article.find("MedlineCitation")
    pubmed_data = article.find("PubmedData")
    article_node = citation.find("Article") if citation is not None else None

    pmid = element_text(citation.find("PMID") if citation is not None else None)
    title = element_text(article_node.find("ArticleTitle") if article_node is not None else None)

    abstract_parts = []
    if article_node is not None:
        for abstract_text in article_node.findall("./Abstract/AbstractText"):
            label = abstract_text.attrib.get("Label") or abstract_text.attrib.get("NlmCategory")
            text = element_text(abstract_text)
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)

    journal_node = article_node.find("Journal") if article_node is not None else None
    journal = element_text(journal_node.find("Title") if journal_node is not None else None)
    journal_iso = element_text(journal_node.find("ISOAbbreviation") if journal_node is not None else None)
    pubdate = journal_node.find("./JournalIssue/PubDate") if journal_node is not None else None
    year = element_text(pubdate.find("Year") if pubdate is not None else None)
    if not year and pubdate is not None:
        year = element_text(pubdate.find("MedlineDate"))

    doi = ""
    if article_node is not None:
        for node in article_node.findall("ELocationID"):
            if node.attrib.get("EIdType") == "doi":
                doi = element_text(node)
                break
    if not doi and pubmed_data is not None:
        for node in pubmed_data.findall("./ArticleIdList/ArticleId"):
            if node.attrib.get("IdType") == "doi":
                doi = element_text(node)
                break

    publication_types = []
    if article_node is not None:
        publication_types = [
            element_text(node)
            for node in article_node.findall("./PublicationTypeList/PublicationType")
            if element_text(node)
        ]

    mesh_headings = []
    if citation is not None:
        for heading in citation.findall("./MeshHeadingList/MeshHeading"):
            descriptor = heading.find("DescriptorName")
            qualifiers = []
            for qualifier in heading.findall("QualifierName"):
                qualifiers.append(
                    {
                        "ui": qualifier.attrib.get("UI", ""),
                        "major_topic": qualifier.attrib.get("MajorTopicYN", ""),
                        "name": element_text(qualifier),
                    }
                )
            if descriptor is not None:
                mesh_headings.append(
                    {
                        "ui": descriptor.attrib.get("UI", ""),
                        "major_topic": descriptor.attrib.get("MajorTopicYN", ""),
                        "name": element_text(descriptor),
                        "qualifiers": qualifiers,
                    }
                )

    keywords = []
    if citation is not None:
        keywords = [
            element_text(node)
            for node in citation.findall("./KeywordList/Keyword")
            if element_text(node)
        ]

    return {
        "pmid": pmid,
        "title": title,
        "abstract": "\n".join(abstract_parts),
        "journal": journal,
        "journal_iso": journal_iso,
        "year": year,
        "doi": doi,
        "publication_types": publication_types,
        "mesh_headings": mesh_headings,
        "keywords": keywords,
    }


def normalize_for_match(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def in_strategy(term: str, strategy_text: str) -> bool:
    if not strategy_text:
        return False
    raw = term.lower()
    normalized = normalize_for_match(term)
    strategy_lower = strategy_text.lower()
    strategy_normalized = normalize_for_match(strategy_text)
    return raw in strategy_lower or bool(normalized and normalized in strategy_normalized)


def record_search_text(record: dict[str, object]) -> str:
    keywords = record.get("keywords", [])
    keyword_text = " ".join(str(item) for item in keywords if item)
    return " ".join(
        [
            str(record.get("title", "")),
            str(record.get("abstract", "")),
            keyword_text,
        ]
    )


def text_tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]


def useful_ngram(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if not any(any(ch.isalpha() for ch in token) for token in tokens):
        return False
    if tokens[0] in STOPWORDS or tokens[-1] in STOPWORDS:
        return False
    non_stop = [token for token in tokens if token not in STOPWORDS]
    return len(non_stop) >= min(2, len(tokens))


def phrase_counter(records: list[dict[str, object]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        tokens = text_tokens(record_search_text(record))
        for size in (2, 3):
            for index in range(0, max(0, len(tokens) - size + 1)):
                gram_tokens = tokens[index : index + size]
                if useful_ngram(gram_tokens):
                    counts[" ".join(gram_tokens)] += 1
    return counts


def acronym_counter(records: list[dict[str, object]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        for match in ACRONYM_PATTERN.finditer(record_search_text(record)):
            value = match.group(0).strip("-")
            if len(value) > 1 and not value.isdigit():
                counts[value] += 1
    return counts


def counted_rows(
    counts: Counter[str],
    *,
    max_items: int,
    min_count: int = 1,
    strategy_text: str = "",
) -> list[dict[str, object]]:
    rows = []
    for term, count in counts.most_common():
        if count < min_count:
            continue
        rows.append(
            {
                "term": term,
                "count": count,
                "in_strategy": in_strategy(term, strategy_text) if strategy_text else False,
            }
        )
        if len(rows) >= max_items:
            break
    return rows


def mine_seed_pmids(
    client: NcbiClient,
    pmids: list[str],
    *,
    strategy_text: str = "",
    max_phrases: int = 80,
    max_acronyms: int = 60,
    min_phrase_count: int = 1,
) -> dict[str, object]:
    fetch_result = efetch(client, pmids)
    records = list(fetch_result.get("records", []))
    found_pmids = [str(record.get("pmid", "")) for record in records if record.get("pmid")]
    found_set = set(found_pmids)

    mesh_counts: Counter[str] = Counter()
    mesh_major_counts: Counter[str] = Counter()
    mesh_uis: defaultdict[str, set[str]] = defaultdict(set)
    keyword_counts: Counter[str] = Counter()
    pub_type_counts: Counter[str] = Counter()

    for record in records:
        for heading in record.get("mesh_headings", []):
            if not isinstance(heading, dict):
                continue
            name = str(heading.get("name", ""))
            if not name:
                continue
            mesh_counts[name] += 1
            ui = str(heading.get("ui", ""))
            if ui:
                mesh_uis[name].add(ui)
            if str(heading.get("major_topic", "")).upper() == "Y":
                mesh_major_counts[name] += 1
        for keyword in record.get("keywords", []):
            if keyword:
                keyword_counts[str(keyword)] += 1
        for pub_type in record.get("publication_types", []):
            if pub_type:
                pub_type_counts[str(pub_type)] += 1

    phrase_rows = counted_rows(
        phrase_counter(records),
        max_items=max_phrases,
        min_count=min_phrase_count,
        strategy_text=strategy_text,
    )
    acronym_rows = counted_rows(
        acronym_counter(records),
        max_items=max_acronyms,
        min_count=1,
        strategy_text=strategy_text,
    )
    keyword_rows = counted_rows(keyword_counts, max_items=80, min_count=1, strategy_text=strategy_text)

    mesh_rows = []
    for term, count in mesh_counts.most_common():
        mesh_rows.append(
            {
                "term": term,
                "count": count,
                "major_count": mesh_major_counts.get(term, 0),
                "uis": sorted(mesh_uis.get(term, set())),
                "in_strategy": in_strategy(term, strategy_text) if strategy_text else False,
            }
        )

    candidate_terms: dict[str, dict[str, object]] = {}
    for source, rows in (
        ("phrase", phrase_rows),
        ("keyword", keyword_rows),
        ("acronym", acronym_rows),
        ("mesh", mesh_rows),
    ):
        for row in rows:
            term = str(row.get("term", ""))
            if not term:
                continue
            key = normalize_for_match(term)
            if key not in candidate_terms:
                candidate_terms[key] = {
                    "term": term,
                    "sources": [],
                    "count": 0,
                    "in_strategy": in_strategy(term, strategy_text) if strategy_text else False,
                }
            candidate_terms[key]["sources"].append(source)
            candidate_terms[key]["count"] = max(int(candidate_terms[key]["count"]), int(row.get("count", 0)))

    candidates = sorted(
        candidate_terms.values(),
        key=lambda item: (-int(item.get("count", 0)), str(item.get("term", "")).lower()),
    )

    return {
        "operation": "mine",
        "requested_pmids": [str(pmid) for pmid in pmids],
        "found_pmids": found_pmids,
        "missing_pmids": [str(pmid) for pmid in pmids if str(pmid) not in found_set],
        "record_count": len(records),
        "records": [
            {
                "pmid": record.get("pmid", ""),
                "title": record.get("title", ""),
                "abstract": record.get("abstract", ""),
                "journal": record.get("journal", ""),
                "year": record.get("year", ""),
                "doi": record.get("doi", ""),
                "publication_types": record.get("publication_types", []),
                "mesh_headings": [
                    heading.get("name", "")
                    for heading in record.get("mesh_headings", [])
                    if isinstance(heading, dict) and heading.get("name")
                ],
                "keywords": record.get("keywords", []),
            }
            for record in records
        ],
        "mesh_heading_counts": mesh_rows,
        "keyword_counts": keyword_rows,
        "publication_type_counts": counted_rows(pub_type_counts, max_items=80, min_count=1),
        "phrase_counts": phrase_rows,
        "acronym_counts": acronym_rows,
        "candidate_tiab_terms": candidates[: max(max_phrases, max_acronyms)],
        "strategy_provided": bool(strategy_text),
        "request_info": client.metadata(),
    }


def efetch(client: NcbiClient, pmids: list[str]) -> dict[str, object]:
    if not pmids:
        raise PubMedError("No PMIDs supplied.")

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    raw = client.request("efetch.fcgi", params, method="POST" if len(pmids) > 50 else "GET")
    root = ET.fromstring(raw)
    records = [parse_article(article) for article in root.findall("./PubmedArticle")]
    requested_pmids = [str(pmid) for pmid in pmids]
    found_pmids = [str(record.get("pmid", "")) for record in records if record.get("pmid")]
    found_set = set(found_pmids)
    return {
        "operation": "fetch",
        "requested_pmids": requested_pmids,
        "found_pmids": found_pmids,
        "missing_pmids": [pmid for pmid in requested_pmids if pmid not in found_set],
        "records": records,
        "request_info": client.metadata(),
    }


def elink_neighbors(client: NcbiClient, seed_pmid: str, linkname: str) -> list[dict[str, object]]:
    """Return PubMed neighbors for one seed via eLink as [{"pmid", "score"}] rows."""
    params = {
        "dbfrom": "pubmed",
        "db": "pubmed",
        "id": str(seed_pmid),
        "linkname": linkname,
        "retmode": "json",
    }
    # Similarity scores are only returned for the "similar articles" set.
    if linkname == "pubmed_pubmed":
        params["cmd"] = "neighbor_score"
    raw = client.request("elink.fcgi", params, method="GET")
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    neighbors: list[dict[str, object]] = []
    for linkset in payload.get("linksets", []) or []:
        for linksetdb in linkset.get("linksetdbs", []) or []:
            if linksetdb.get("linkname") != linkname:
                continue
            for link in linksetdb.get("links", []) or []:
                if isinstance(link, dict):
                    pmid = str(link.get("id", "")).strip()
                    score_value = link.get("score")
                    score = int(score_value) if str(score_value).isdigit() else None
                else:
                    pmid = str(link).strip()
                    score = None
                if pmid:
                    neighbors.append({"pmid": pmid, "score": score})
    return neighbors


def related_pmids(
    client: NcbiClient,
    pmids: list[str],
    *,
    links: list[str],
    max_per_seed: int,
    max_total: int,
) -> dict[str, object]:
    seeds = [str(pmid) for pmid in pmids]
    seed_set = set(seeds)
    # candidate pmid -> aggregated provenance
    candidates: dict[str, dict[str, object]] = {}
    link_counts: dict[str, int] = {name: 0 for name in links}

    for linkname in links:
        eutils_linkname = RELATED_LINKNAMES[linkname]
        for seed in seeds:
            neighbors = elink_neighbors(client, seed, eutils_linkname)
            kept = 0
            for neighbor in neighbors:
                pmid = str(neighbor.get("pmid", ""))
                if not pmid or pmid in seed_set:
                    continue
                if kept >= max_per_seed:
                    break
                kept += 1
                link_counts[linkname] += 1
                entry = candidates.get(pmid)
                if entry is None:
                    entry = {
                        "pmid": pmid,
                        "via": [],
                        "seed_sources": [],
                        "similarity_score": None,
                        "seed_overlap_count": 0,
                    }
                    candidates[pmid] = entry
                if linkname not in entry["via"]:
                    entry["via"].append(linkname)
                if seed not in entry["seed_sources"]:
                    entry["seed_sources"].append(seed)
                    entry["seed_overlap_count"] = len(entry["seed_sources"])
                score = neighbor.get("score")
                if score is not None:
                    current = entry["similarity_score"]
                    if current is None or int(score) > int(current):
                        entry["similarity_score"] = int(score)

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -int(item.get("seed_overlap_count", 0)),
            -(int(item["similarity_score"]) if item.get("similarity_score") is not None else -1),
            str(item.get("pmid", "")),
        ),
    )
    capped = ranked[:max_total]

    return {
        "operation": "related",
        "seed_pmids": seeds,
        "links_used": links,
        "max_per_seed": max_per_seed,
        "max_total": max_total,
        "link_counts": link_counts,
        "candidate_count": len(capped),
        "candidate_count_before_cap": len(ranked),
        "candidate_pmids": capped,
        "note": SEED_VALIDATION_WARNING,
        "request_info": client.metadata(),
    }


def sample(client: NcbiClient, query: str, retmax: int, sort: str | None) -> dict[str, object]:
    search_result = esearch(client, query, retmax=retmax, retstart=0, sort=sort)
    pmids = list(search_result.get("pmids", []))
    fetch_result = efetch(client, pmids) if pmids else {"requested_pmids": [], "records": []}
    return {
        "operation": "sample",
        "search": search_result,
        "records": fetch_result.get("records", []),
        "request_info": client.metadata(),
    }


def term_diff(client: NcbiClient, mesh_query: str, tiab_query: str, retmax: int, sort: str | None) -> dict[str, object]:
    """Controlled-vocabulary vs free-text differential for one concept block (Bramer optimization).

    Computes `(MeSH) NOT (tiab)` and `(tiab) NOT (MeSH)` with counts and a fetched sample of each, so
    the searcher can read the differential records to discover missed [tiab] terms and missing MeSH.
    Inputs are the two halves of the SAME concept block."""
    mesh_not_tiab = f"({mesh_query}) NOT ({tiab_query})"
    tiab_not_mesh = f"({tiab_query}) NOT ({mesh_query})"
    mesh_search = esearch(client, mesh_query, retmax=0, retstart=0, sort=None)
    tiab_search = esearch(client, tiab_query, retmax=0, retstart=0, sort=None)
    mesh_only_search = esearch(client, mesh_not_tiab, retmax=retmax, retstart=0, sort=sort)
    tiab_only_search = esearch(client, tiab_not_mesh, retmax=retmax, retstart=0, sort=sort)
    mesh_only_pmids = list(mesh_only_search.get("pmids", []))
    tiab_only_pmids = list(tiab_only_search.get("pmids", []))
    mesh_only_fetch = efetch(client, mesh_only_pmids) if mesh_only_pmids else {"records": []}
    tiab_only_fetch = efetch(client, tiab_only_pmids) if tiab_only_pmids else {"records": []}
    mesh_count = int(mesh_search.get("count", 0) or 0)
    tiab_count = int(tiab_search.get("count", 0) or 0)
    mesh_only_count = int(mesh_only_search.get("count", 0) or 0)
    tiab_only_count = int(tiab_only_search.get("count", 0) or 0)
    return {
        "operation": "term-diff",
        "queries": {
            "mesh": mesh_query,
            "tiab": tiab_query,
            "mesh_not_tiab": mesh_not_tiab,
            "tiab_not_mesh": tiab_not_mesh,
        },
        "counts": {
            "mesh": mesh_count,
            "tiab": tiab_count,
            "overlap": mesh_count - mesh_only_count,
            "combined": mesh_count + tiab_only_count,
            "mesh_only": mesh_only_count,
            "tiab_only": tiab_only_count,
        },
        "mesh_only_sample": {
            "count": mesh_only_count,
            "pmids": mesh_only_pmids,
            "records": mesh_only_fetch.get("records", []),
        },
        "tiab_only_sample": {
            "count": tiab_only_count,
            "pmids": tiab_only_pmids,
            "records": tiab_only_fetch.get("records", []),
        },
        "query_translation_hooks": {
            "mesh_not_tiab": mesh_only_search.get("query_translation_hook", {}),
            "tiab_not_mesh": tiab_only_search.get("query_translation_hook", {}),
        },
        "note": TERM_DIFF_NOTE,
        "request_info": client.metadata(),
    }


def validate(client: NcbiClient, query: str, pmids: list[str]) -> dict[str, object]:
    seed_block = " OR ".join(f"{pmid}[uid]" for pmid in pmids)
    validation_query = f"({query}) AND ({seed_block})"
    search_result = esearch(client, validation_query, retmax=max(len(pmids), 20), retstart=0, sort=None)
    retrieved = set(search_result.get("pmids", []))
    provided = [str(pmid) for pmid in pmids]
    return {
        "query": query,
        "validation_query": validation_query,
        "provided_pmids": provided,
        "retrieved_pmids": [pmid for pmid in provided if pmid in retrieved],
        "missed_pmids": [pmid for pmid in provided if pmid not in retrieved],
        "search_count": search_result.get("count", 0),
        "query_translation": search_result.get("query_translation", ""),
        "warnings": search_result.get("warnings", {}),
        "query_translation_hook": search_result.get("query_translation_hook", {}),
        "request_info": client.metadata(),
    }


def retrieve_against_pmids(client: NcbiClient, query: str, pmids: list[str]) -> set[str]:
    """Return the subset of pmids retrieved by query, chunking the uid block for large sets."""
    retrieved: set[str] = set()
    for start in range(0, len(pmids), RECALL_UID_CHUNK):
        chunk = pmids[start : start + RECALL_UID_CHUNK]
        if not chunk:
            continue
        uid_block = " OR ".join(f"{pmid}[uid]" for pmid in chunk)
        combined = f"({query}) AND ({uid_block})"
        search_result = esearch(client, combined, retmax=len(chunk), retstart=0, sort=None)
        retrieved.update(str(pmid) for pmid in search_result.get("pmids", []))
    return retrieved


def load_benchmark_or_blocks_json(path: str) -> object:
    """Load JSON that may be an object (related/mine output) or a bare list."""
    try:
        return json.loads(read_text_source(path))
    except json.JSONDecodeError as exc:
        raise PubMedError(f"Could not parse JSON file {path}: {exc}") from exc


POWERSHELL_OBJECT_SIGNATURES = (
    "@{",
    "LastWriteTime",
    "LastAccessTime",
    "CreationTime",
    "DirectoryName",
    "PSChildName",
    "PSParentPath",
    "PSProvider",
    "VersionInfo",
    "System.IO.",
)


def assert_plain_query(label: str, query: object) -> None:
    """Reject a query value that is a serialized object/file-metadata blob instead of a plain PubMed
    query string (the usual cause is PowerShell ConvertTo-Json of a file/object). Shared by the
    recall block validator and the variants/batch query parsers."""
    if isinstance(query, (dict, list)):
        raise PubMedError(
            f"Query {label!r} is a non-string {type(query).__name__}; a query must be plain PubMed query "
            "text. An object was serialized into the query field - in PowerShell, Get-Item/Get-ChildItem "
            'piped to ConvertTo-Json does this. Write each entry as {"label": "...", "query": "<query text>"}.'
        )
    text = "" if query is None else str(query)
    if not text.strip():
        raise PubMedError(
            f"Query {label!r} is missing or empty. Each entry needs a non-empty PubMed query string; if the "
            "file was built in PowerShell, make sure an object was not serialized in place of the query text."
        )
    signature = next((sig for sig in POWERSHELL_OBJECT_SIGNATURES if sig in text), None)
    if signature is not None:
        raise PubMedError(
            f"Query {label!r} looks like serialized object/file metadata, not a PubMed query "
            f"(found {signature!r} in {compact_evidence(text)!r}). This usually means PowerShell serialized "
            "a file or object into the query field. Write the query as plain text."
        )


def validate_recall_blocks(raw: object) -> None:
    """Fail fast on a malformed --blocks-file (e.g. a PowerShell-serialized object in a query field)
    before any network call, with a clear message naming the offending block."""
    if isinstance(raw, list):
        for index, item in enumerate(raw, start=1):
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("name") or f"block {index}")
                assert_plain_query(label, item.get("query"))
            elif isinstance(item, str):
                assert_plain_query(f"block {index}", item)
            else:
                raise PubMedError(f"Block {index} must be an object or query string, got {type(item).__name__}.")
    elif isinstance(raw, dict):
        for index, (label, value) in enumerate(raw.items(), start=1):
            if isinstance(value, dict) and "query" in value:
                assert_plain_query(str(label), value.get("query"))
            else:
                assert_plain_query(str(label), value)
    else:
        raise PubMedError(
            "--blocks-file must contain a JSON list of {label, query} blocks or a {label: query} map, "
            f"got {type(raw).__name__}."
        )


def extract_benchmark_pmids(data: object, *, min_seed_overlap: int) -> list[str]:
    """Pull a PMID list from a benchmark JSON payload (related/mine output or a bare list)."""
    pmids: list[str] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if isinstance(data.get("candidate_pmids"), list):
            items = data["candidate_pmids"]
        elif isinstance(data.get("found_pmids"), list):
            items = data["found_pmids"]
        elif isinstance(data.get("requested_pmids"), list):
            items = data["requested_pmids"]
        else:
            items = []
    else:
        items = []
    for item in items:
        if isinstance(item, dict):
            if int(item.get("seed_overlap_count", 0) or 0) < min_seed_overlap:
                continue
            pmid = str(item.get("pmid", "")).strip()
        else:
            pmid = str(item).strip()
        if pmid:
            pmids.append(pmid)
    return pmids


def assert_numeric_pmids(pmids: list[str], *, source: str) -> None:
    """Fail fast when a PMID source yielded non-numeric values, the usual cause being a
    PowerShell-serialized object/metadata serialized instead of a PMID list."""
    bad = [pmid for pmid in pmids if not str(pmid).strip().isdigit()]
    if bad:
        preview = compact_evidence(", ".join(str(pmid) for pmid in bad[:5]))
        raise PubMedError(
            f"{source} produced non-numeric values where PMIDs were expected (e.g. {preview!r}). This often "
            "means an object or metadata was serialized instead of a PMID list (a PowerShell ConvertTo-Json "
            "pitfall). Provide a JSON list of numeric PMIDs, or a related/mine output."
        )


def dedup_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def filter_pmids(
    pmids: list[str], *, only: list[str] | None = None, exclude: list[str] | None = None
) -> tuple[list[str], list[str]]:
    """Apply an optional accepted-whitelist (``only``) and exclusion (``exclude``) filter to a
    resolved relevant-set PMID list. Returns ``(kept, removed)`` with order preserved, so a seed
    excluded at pre-gate triage never reaches term ranking even when reused from a mine JSON."""
    kept = dedup_preserving_order([str(pmid) for pmid in pmids])
    only_set = {str(pmid) for pmid in (only or [])}
    exclude_set = {str(pmid) for pmid in (exclude or [])}
    removed: list[str] = []
    if only_set:
        removed += [pmid for pmid in kept if pmid not in only_set]
        kept = [pmid for pmid in kept if pmid in only_set]
    if exclude_set:
        removed += [pmid for pmid in kept if pmid in exclude_set]
        kept = [pmid for pmid in kept if pmid not in exclude_set]
    return kept, dedup_preserving_order(removed)


def relative_recall(
    client: NcbiClient,
    query: str,
    benchmark_pmids: list[str],
    *,
    benchmark_source: str,
    blocks: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    benchmark = dedup_preserving_order([str(pmid) for pmid in benchmark_pmids])
    if not benchmark:
        raise PubMedError("No benchmark PMIDs resolved for relative-recall estimation.")

    full_retrieved = retrieve_against_pmids(client, query, benchmark)
    retrieved_pmids = [pmid for pmid in benchmark if pmid in full_retrieved]
    missed_pmids = [pmid for pmid in benchmark if pmid not in full_retrieved]
    benchmark_size = len(benchmark)

    result: dict[str, object] = {
        "operation": "recall",
        "query": query,
        "benchmark_source": benchmark_source,
        "benchmark_size": benchmark_size,
        "retrieved_count": len(retrieved_pmids),
        "missed_count": len(missed_pmids),
        "relative_recall_percent": round((len(retrieved_pmids) / benchmark_size) * 100, 2),
        "retrieved_pmids": retrieved_pmids,
        "missed_pmids": missed_pmids,
        "note": RELATIVE_RECALL_NOTE,
        "request_info": client.metadata(),
    }

    if blocks:
        block_retrieved: dict[str, set[str]] = {}
        block_recall = []
        for block in blocks:
            label = str(block.get("label", ""))
            block_query = str(block.get("query", ""))
            retrieved = retrieve_against_pmids(client, block_query, benchmark)
            block_retrieved[label] = retrieved
            block_recall.append(
                {
                    "label": label,
                    "query": block_query,
                    "retrieved_count": len(retrieved),
                    "recall_percent": round((len(retrieved) / benchmark_size) * 100, 2),
                    "bottleneck": False,
                }
            )
        if block_recall:
            min_recall = min(row["recall_percent"] for row in block_recall)
            for row in block_recall:
                row["bottleneck"] = row["recall_percent"] == min_recall

        miss_diagnosis = []
        for pmid in missed_pmids:
            culprit_blocks = [label for label, retrieved in block_retrieved.items() if pmid not in retrieved]
            miss_diagnosis.append(
                {
                    "pmid": pmid,
                    "culprit_blocks": culprit_blocks,
                    "and_interaction": len(culprit_blocks) == 0,
                }
            )
        result["block_recall"] = block_recall
        result["miss_diagnosis"] = miss_diagnosis
        result["block_diagnosis_note"] = (
            "culprit_blocks lists concept blocks that individually fail to retrieve a missed PMID. "
            "and_interaction marks a miss retrieved by every block alone but lost by the full strategy "
            "(check NOT operators, filters, or proximity rather than a weak block)."
        )

    return result


def batch_search(client: NcbiClient, queries: list[dict[str, object]], retmax: int, sort: str | None) -> dict[str, object]:
    results = []
    for item in queries:
        query = str(item["query"])
        search_result = esearch(client, query, retmax=retmax, retstart=0, sort=sort)
        results.append(
            {
                "label": str(item["label"]),
                "query": query,
                "count": search_result.get("count", 0),
                "retmax": search_result.get("retmax", retmax),
                "pmids": search_result.get("pmids", []),
                "query_translation": search_result.get("query_translation", ""),
                "warnings": search_result.get("warnings", {}),
                "query_translation_hook": search_result.get("query_translation_hook", {}),
            }
        )
    return {
        "query_count": len(results),
        "results": results,
        "request_info": client.metadata(),
    }


def normalize_variant_item(item: object, index: int, *, label_override: str | None = None) -> dict[str, object]:
    if isinstance(item, str):
        label = label_override or f"query_{index}"
        query = item
        source: dict[str, object] = {}
    elif isinstance(item, dict):
        label = label_override or item.get("label") or item.get("name") or f"query_{index}"
        query = item.get("query")
        source = item
    else:
        raise PubMedError(f"Variant item {index} must be a string or object.")

    assert_plain_query(str(label), query)  # reject object/metadata/empty queries (PowerShell pitfall)
    normalized_query = normalize_query(str(query))
    if not normalized_query:
        raise PubMedError(f"Variant item {index} has an empty query.")
    result: dict[str, object] = {"label": str(label), "query": normalized_query}
    for field in VARIANT_METADATA_FIELDS:
        if field in source and source[field] is not None:
            result[field] = source[field]
    return result


def parse_variant_items(data: object) -> list[dict[str, object]]:
    if isinstance(data, list):
        return [normalize_variant_item(item, index) for index, item in enumerate(data, start=1)]
    if isinstance(data, dict):
        items = []
        for index, (label, value) in enumerate(data.items(), start=1):
            if isinstance(value, dict):
                items.append(normalize_variant_item(value, index, label_override=str(label)))
            else:
                items.append(normalize_variant_item(str(value), index, label_override=str(label)))
        return items
    raise PubMedError("Variant JSON must be an object or array.")


def parse_variant_queries(raw: str) -> tuple[list[dict[str, object]], str | None]:
    stripped = raw.strip()
    if not stripped:
        raise PubMedError("Variant input is empty.")
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise PubMedError(f"Could not parse variants JSON: {exc}") from exc
        if isinstance(data, dict) and "variants" in data:
            variants = data.get("variants")
            if not isinstance(variants, list):
                raise PubMedError("Variant JSON field 'variants' must be an array.")
            queries = parse_variant_items(variants)
            baseline = data.get("baseline_label") or data.get("baseline") or data.get("main")
            return queries, str(baseline) if baseline else None
        return parse_variant_items(data), None
    return parse_batch_queries(raw), None


def parse_relevance_value(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    text = str(value).strip().lower()
    if not text or text in {"unknown", "unclear", "maybe", "na", "n/a"}:
        return None
    if text in TRUE_RELEVANCE_VALUES:
        return True
    if text in FALSE_RELEVANCE_VALUES:
        return False
    raise PubMedError(f"Unrecognized relevance label: {value!r}")


def labelled_sample_summary(sample: object, label: str) -> dict[str, object]:
    sample_description = ""
    entries: list[tuple[str, object]] = []

    if isinstance(sample, dict):
        sample_description = str(
            sample.get("sample_description")
            or sample.get("description")
            or sample.get("sampling_method")
            or sample.get("method")
            or ""
        )
        labelled_data = sample.get("labels")
        if labelled_data is None:
            labelled_data = sample.get("pmids")
        if labelled_data is None:
            labelled_data = sample.get("records")
        if labelled_data is None:
            labelled_data = {key: value for key, value in sample.items() if key not in SAMPLE_METADATA_KEYS}

        if isinstance(labelled_data, dict):
            entries.extend((str(pmid), value) for pmid, value in labelled_data.items())
        elif isinstance(labelled_data, list):
            for index, item in enumerate(labelled_data, start=1):
                if not isinstance(item, dict):
                    raise PubMedError(f"Labelled sample item {index} for {label!r} must be an object.")
                pmid = item.get("pmid") or item.get("uid") or item.get("id")
                if pmid is None:
                    raise PubMedError(f"Labelled sample item {index} for {label!r} is missing a PMID.")
                if "relevant" in item:
                    relevance = item.get("relevant")
                elif "label" in item:
                    relevance = item.get("label")
                else:
                    relevance = item.get("included")
                entries.append((str(pmid), relevance))
        else:
            raise PubMedError(f"Labelled sample for {label!r} must contain a labels object or list.")
    elif isinstance(sample, list):
        for index, item in enumerate(sample, start=1):
            if not isinstance(item, dict):
                raise PubMedError(f"Labelled sample item {index} for {label!r} must be an object.")
            pmid = item.get("pmid") or item.get("uid") or item.get("id")
            if pmid is None:
                raise PubMedError(f"Labelled sample item {index} for {label!r} is missing a PMID.")
            if "relevant" in item:
                relevance = item.get("relevant")
            elif "label" in item:
                relevance = item.get("label")
            else:
                relevance = item.get("included")
            entries.append((str(pmid), relevance))
    else:
        raise PubMedError(f"Labelled sample for {label!r} must be an object or array.")

    labelled_pmids = []
    relevant = 0
    for pmid, raw_value in entries:
        relevance = parse_relevance_value(raw_value)
        if relevance is None:
            continue
        labelled_pmids.append(pmid)
        if relevance:
            relevant += 1

    size = len(labelled_pmids)
    precision = round(relevant / size, 4) if size else None
    nnr = round(size / relevant, 2) if relevant else None
    if not size:
        note = NO_LABELLED_SAMPLE_NOTE
    elif relevant == 0:
        note = ZERO_RELEVANT_SAMPLE_NOTE
    else:
        note = "estimated from labelled pilot sample"

    return {
        "labelled_sample_size": size,
        "relevant_labelled_records": relevant,
        "estimated_precision": precision,
        "estimated_nnr": nnr,
        "estimated_nnr_note": note,
        "labelled_sample_pmids": labelled_pmids,
        "labelled_sample_description": sample_description,
    }


def parse_labelled_samples(raw: str) -> dict[str, dict[str, object]]:
    stripped = raw.strip()
    if not stripped:
        raise PubMedError("Labelled sample input is empty.")
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise PubMedError(f"Could not parse labelled samples JSON: {exc}") from exc
    if isinstance(data, dict) and "samples" in data:
        data = data.get("samples")
    if not isinstance(data, dict):
        raise PubMedError("Labelled samples JSON must be an object keyed by variant label.")
    return {str(label): labelled_sample_summary(sample, str(label)) for label, sample in data.items()}


def default_labelled_sample_summary() -> dict[str, object]:
    return {
        "labelled_sample_size": 0,
        "relevant_labelled_records": 0,
        "estimated_precision": None,
        "estimated_nnr": None,
        "estimated_nnr_note": NO_LABELLED_SAMPLE_NOTE,
        "labelled_sample_pmids": [],
        "labelled_sample_description": "",
    }


def seed_recall_percent(retrieved_pmids: list[str], seed_pmids: list[str]) -> float | None:
    if not seed_pmids:
        return None
    return round((len(retrieved_pmids) / len(seed_pmids)) * 100, 2)


def compare_variants(
    client: NcbiClient,
    queries: list[dict[str, object]],
    *,
    retmax: int,
    sort: str | None,
    baseline_label: str | None,
    seed_pmids: list[str] | None = None,
    labelled_samples: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    if not queries:
        raise PubMedError("No variants supplied.")
    batch_result = batch_search(client, queries, retmax=retmax, sort=sort)
    results = list(batch_result.get("results", []))
    baseline = None
    if baseline_label:
        for item in results:
            if item.get("label") == baseline_label:
                baseline = item
                break
        if baseline is None:
            raise PubMedError(f"Baseline variant not found: {baseline_label}")
    if baseline is None:
        baseline = results[0]
    baseline_count = int(baseline.get("count", 0) or 0)
    baseline_pmids = set(str(pmid) for pmid in baseline.get("pmids", []))
    seed_pmids = [str(pmid) for pmid in (seed_pmids or [])]
    labelled_samples = labelled_samples or {}

    compared = []
    for item, source_query in zip(results, queries):
        count = int(item.get("count", 0) or 0)
        pmids = set(str(pmid) for pmid in item.get("pmids", []))
        entry = dict(item)
        for field in VARIANT_METADATA_FIELDS:
            if field in source_query:
                entry[field] = source_query[field]
        entry["count_delta_from_baseline"] = count - baseline_count
        entry["percent_of_baseline"] = round((count / baseline_count) * 100, 2) if baseline_count else None
        if retmax > 0:
            entry["sample_overlap_with_baseline"] = sorted(pmids & baseline_pmids)
            entry["sample_lost_from_baseline"] = sorted(baseline_pmids - pmids)
            entry["sample_gained_vs_baseline"] = sorted(pmids - baseline_pmids)
        if seed_pmids:
            seed_result = validate(client, str(entry.get("query", "")), seed_pmids)
            retrieved_seed_pmids = list(seed_result.get("retrieved_pmids", []))
            missed_seed_pmids = list(seed_result.get("missed_pmids", []))
            entry["seed_pmids_tested"] = seed_pmids
            entry["seed_pmids_retrieved"] = retrieved_seed_pmids
            entry["seed_pmids_missed"] = missed_seed_pmids
            entry["seed_recall_percent"] = seed_recall_percent(retrieved_seed_pmids, seed_pmids)
            entry["seed_validation_warning"] = SEED_VALIDATION_WARNING
            entry["seed_validation_search_count"] = seed_result.get("search_count", 0)
        sample_summary = labelled_samples.get(str(entry.get("label", "")), default_labelled_sample_summary())
        entry.update(sample_summary)
        compared.append(entry)

    return {
        "operation": "variants",
        "design_ledger": True,
        "variant_count": len(compared),
        "baseline_label": baseline.get("label", ""),
        "retmax": retmax,
        "sort": sort or "",
        "results": compared,
        "pmid_comparison_note": "PMID overlap is based only on returned samples when retmax > 0; counts are complete PubMed counts.",
        "seed_validation_note": SEED_VALIDATION_WARNING if seed_pmids else "",
        "nnr_note": "NNR is estimated only from relevance-labelled pilot samples; counts alone are workload proxies, not precision.",
        "request_info": client.metadata(),
    }


def record_phrase_set(record: dict[str, object]) -> set[str]:
    tokens = text_tokens(record_search_text(record))
    grams: set[str] = set()
    for size in (2, 3):
        for index in range(0, max(0, len(tokens) - size + 1)):
            gram_tokens = tokens[index : index + size]
            if useful_ngram(gram_tokens):
                grams.add(" ".join(gram_tokens))
    return grams


def record_acronym_set(record: dict[str, object]) -> set[str]:
    found: set[str] = set()
    for match in ACRONYM_PATTERN.finditer(record_search_text(record)):
        value = match.group(0).strip("-")
        if len(value) > 1 and not value.isdigit():
            found.add(value)
    return found


def record_mesh_set(record: dict[str, object]) -> set[str]:
    names: set[str] = set()
    for heading in record.get("mesh_headings", []):
        if isinstance(heading, dict):
            name = str(heading.get("name", ""))
        else:
            name = str(heading)
        if name:
            names.add(name)
    return names


def record_keyword_set(record: dict[str, object]) -> set[str]:
    return {str(keyword).strip() for keyword in record.get("keywords", []) if str(keyword).strip()}


def background_query_for(term: str, field: str) -> str:
    cleaned = " ".join(str(term).split()).strip('"')
    if field == "mesh":
        return f'"{cleaned}"[Mesh]'
    if " " in cleaned:
        return f'"{cleaned}"[tiab]'
    return f"{cleaned}[tiab]"


def _content_token(token: str) -> bool:
    """A token carries topical content if it has >=3 alphabetic characters and is not a known
    statistical marker. Operates on whitespace-split tokens of the display term, so hyphenated
    symbols like ``IL-6``/``PD-L1`` stay one token and are not mistaken for statistical fragments."""
    return sum(1 for ch in token if ch.isalpha()) >= 3 and token.lower() not in STAT_WORDS


def term_rank_noise_reason(term: str, field: str) -> str | None:
    """Classify a term-rank candidate as a noise class to drop, or return None to keep it.

    Drops structured-abstract section labels (OBJECTIVES, RESULTS, ...), MeSH check tags and common
    geographic descriptors (Humans, Female, Queensland, ...), and statistical fragments (``p 0``,
    ``95 ci``, ...). The statistical rule applies only to multi-token ``tiab`` candidates, so single
    tokens such as ``p53``, ``IL-6``, ``PD-L1`` are never dropped as statistical.
    """
    cleaned = " ".join(str(term).split())
    normalized = normalize_for_match(cleaned)
    if not normalized:
        return "empty"
    if normalized in NON_TOPICAL_TERMS:
        return "non_topical"
    if normalized in STRUCTURED_ABSTRACT_HEADINGS:
        return "boilerplate"
    if field == "tiab":
        tokens = cleaned.split()
        if len(tokens) >= 2:
            if not any(_content_token(token) for token in tokens):
                return "statistical"
            words = normalized.split()
            if words and (words[0] in BOUNDARY_NOISE_TOKENS or words[-1] in BOUNDARY_NOISE_TOKENS):
                return "boilerplate"
    return None


def term_rank_candidates(
    records: list[dict[str, object]],
    fields: list[str],
    strategy_text: str,
) -> tuple[list[dict[str, object]], int]:
    total = len(records)
    document_frequency: defaultdict[tuple[str, str], int] = defaultdict(int)
    display: dict[tuple[str, str], str] = {}
    sources: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    want_tiab = "tiab" in fields
    want_mesh = "mesh" in fields

    for record in records:
        per_record: list[tuple[str, str, str]] = []
        if want_tiab:
            per_record.extend((term, "tiab", "phrase") for term in record_phrase_set(record))
            per_record.extend((term, "tiab", "acronym") for term in record_acronym_set(record))
            per_record.extend((term, "tiab", "keyword") for term in record_keyword_set(record))
        if want_mesh:
            per_record.extend((term, "mesh", "mesh") for term in record_mesh_set(record))

        counted_keys: set[tuple[str, str]] = set()
        for term, field, source in per_record:
            cleaned = " ".join(str(term).split())
            if term_rank_noise_reason(cleaned, field):
                continue
            normalized = normalize_for_match(cleaned)
            if not normalized:
                continue
            key = (field, normalized)
            sources[key].add(source)
            display.setdefault(key, cleaned)
            if key not in counted_keys:
                counted_keys.add(key)
                document_frequency[key] += 1

    rows: list[dict[str, object]] = []
    for key, count in document_frequency.items():
        field, _normalized = key
        term = display[key]
        rows.append(
            {
                "term": term,
                "field": field,
                "relevant_df": count,
                "coverage": round(count / total, 4) if total else 0.0,
                "sources": sorted(sources[key]),
                "in_strategy": in_strategy(term, strategy_text) if strategy_text else False,
            }
        )
    return rows, total


def term_rank(
    client: NcbiClient,
    records: list[dict[str, object]],
    *,
    fields: list[str],
    max_terms: int,
    strategy_text: str,
    pubmed_total: int,
) -> dict[str, object]:
    rows, total = term_rank_candidates(records, fields, strategy_text)
    rows.sort(
        key=lambda row: (
            -int(row["relevant_df"]),
            0 if row["field"] == "mesh" else 1,
            str(row["term"]).lower(),
        )
    )
    scored = rows[:max_terms]
    pubmed_total = max(int(pubmed_total), 1)

    for row in scored:
        background_query = background_query_for(str(row["term"]), str(row["field"]))
        search_result = esearch(client, background_query, retmax=0, retstart=0, sort=None)
        background_count = int(search_result.get("count", 0) or 0)
        coverage = float(row["coverage"])
        row["background_query"] = background_query
        row["background_count"] = background_count
        row["suggested_layer"] = background_query
        if background_count <= 0:
            row["lift"] = None
            row["background_zero"] = True
            row["noise_risk"] = False
        else:
            row["lift"] = round(coverage / (background_count / pubmed_total), 2)
            row["noise_risk"] = bool(
                background_count >= TERM_RANK_NOISE_BACKGROUND and coverage < TERM_RANK_NOISE_COVERAGE
            )

    scored.sort(
        key=lambda row: (
            -float(row["coverage"]),
            -(row.get("lift") or 0.0),
            -int(row["relevant_df"]),
            str(row["term"]).lower(),
        )
    )

    return {
        "operation": "term-rank",
        "relevant_record_count": total,
        "fields": fields,
        "max_terms": max_terms,
        "pubmed_total_estimate": pubmed_total,
        "candidates_considered": len(rows),
        "candidates_scored": len(scored),
        "candidates_unscored": max(0, len(rows) - len(scored)),
        "method_note": TERM_RANK_CAVEAT,
        "ranked_terms": scored,
        "request_info": client.metadata(),
    }


def load_json_file(path: str) -> dict[str, object]:
    try:
        data = json.loads(read_text_source(path))
    except json.JSONDecodeError as exc:
        raise PubMedError(f"Could not parse JSON file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PubMedError(f"JSON file must contain an object: {path}")
    return data


def sheet_name(value: str, fallback: str) -> str:
    text = re.sub(r"[\x00-\x1f]", " ", str(value))
    cleaned = re.sub(r"[\[\]:*?/\\]", " ", text)
    cleaned = " ".join(cleaned.split()).strip("'") or fallback
    return cleaned[:31]


def unique_sheet_names(sheets: list[tuple[str, list[list[object]]]]) -> list[tuple[str, list[list[object]]]]:
    used: set[str] = set()
    result = []
    for index, (name, rows) in enumerate(sheets, start=1):
        base = sheet_name(name, f"Sheet{index}")
        candidate = base
        counter = 2
        while candidate.lower() in used:
            suffix = f" {counter}"
            candidate = f"{base[:31 - len(suffix)]}{suffix}"
            counter += 1
        used.add(candidate.lower())
        result.append((candidate, rows or [[name, "No data"]]))
    return result


def excel_col(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xml_attr(value: object) -> str:
    return xml_escape(clean_xml_text(value), {'"': "&quot;"})


def clean_xml_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    if len(text) > 32000:
        text = f"{text[:31980]}... [truncated]"
    return text


def cell_xml(row_index: int, col_index: int, value: object, *, header: bool = False) -> str:
    ref = f"{excel_col(col_index)}{row_index}"
    style = ' s="1"' if header else ""
    if value is None or value == "":
        return f'<c r="{ref}"{style}/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{style}><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'
    text = xml_escape(clean_xml_text(value))
    space = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
    return f'<c r="{ref}" t="inlineStr"{style}><is><t{space}>{text}</t></is></c>'


def worksheet_xml(rows: list[list[object]]) -> str:
    max_cols = max((len(row) for row in rows), default=1)
    max_rows = max(len(rows), 1)
    dimension = f"A1:{excel_col(max_cols)}{max_rows}"
    widths = []
    for col_index in range(max_cols):
        max_len = 8
        for row in rows:
            if col_index < len(row):
                max_len = max(max_len, min(60, len(clean_xml_text(row[col_index])) + 2))
        widths.append(f'<col min="{col_index + 1}" max="{col_index + 1}" width="{max_len}" customWidth="1"/>')
    row_xml = []
    for row_index, row in enumerate(rows or [[]], start=1):
        cells = "".join(cell_xml(row_index, col_index, value, header=row_index == 1) for col_index, value in enumerate(row, start=1))
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    auto_filter = f'<autoFilter ref="{dimension}"/>' if rows and len(rows) > 1 and max_cols > 1 else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft"/></sheetView></sheetViews>'
        f'<cols>{"".join(widths)}</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        f"{auto_filter}"
        "</worksheet>"
    )


def workbook_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def write_xlsx(path: Path, sheets: list[tuple[str, list[list[object]]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_sheets = unique_sheet_names(sheets)
    content_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index, _ in enumerate(safe_sheets, start=1)
    )
    workbook_sheets = "".join(
        f'<sheet name="{xml_attr(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _) in enumerate(safe_sheets, start=1)
    )
    workbook_rels = "".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index, _ in enumerate(safe_sheets, start=1)
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            f"{content_overrides}</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{workbook_sheets}</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{workbook_rels}<Relationship Id="rId{len(safe_sheets) + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/styles.xml", workbook_styles_xml())
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            "<dc:title>PubMed search audit workbook</dc:title>"
            "<dc:creator>pubmed-search-builder</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            "</cp:coreProperties>",
        )
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            "<Application>pubmed-search-builder</Application></Properties>",
        )
        for index, (_, rows) in enumerate(safe_sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet_xml(rows))


def list_text(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(list_text(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if value is None else str(value)


def query_warning_codes(item: dict[str, object]) -> str:
    hook = item.get("query_translation_hook", {})
    warnings = []
    if isinstance(hook, dict):
        warnings = [issue.get("code", "") for issue in hook.get("issues", []) if isinstance(issue, dict)]
    return "; ".join(str(warning) for warning in warnings if warning)


def has_design_metadata(results: list[object]) -> bool:
    ledger_fields = set(VARIANT_METADATA_FIELDS) | {
        "seed_pmids_tested",
        "labelled_sample_size",
        "estimated_precision",
        "estimated_nnr",
    }
    for item in results:
        if not isinstance(item, dict):
            continue
        if any(field in item and item.get(field) not in ("", None, [], 0) for field in ledger_fields):
            return True
    return False


def build_audit_workbook(
    *,
    output_path: str,
    mine_data: dict[str, object] | None,
    variants_data: dict[str, object] | None,
    mine_source: str,
    variants_source: str,
    term_rank_data: dict[str, object] | None = None,
    term_rank_source: str = "",
) -> dict[str, object]:
    sheets: list[tuple[str, list[list[object]]]] = []
    summary = [
        ["Field", "Value"],
        ["Generated UTC", datetime.now(timezone.utc).replace(microsecond=0).isoformat()],
        ["Mine JSON", mine_source or "not supplied"],
        ["Variants JSON", variants_source or "not supplied"],
        ["Term-rank JSON", term_rank_source or "not supplied"],
        ["Seed records", mine_data.get("record_count", "") if mine_data else ""],
        ["Requested PMIDs", list_text(mine_data.get("requested_pmids", [])) if mine_data else ""],
        ["Found PMIDs", list_text(mine_data.get("found_pmids", [])) if mine_data else ""],
        ["Missing PMIDs", list_text(mine_data.get("missing_pmids", [])) if mine_data else ""],
        ["Variant count", variants_data.get("variant_count", "") if variants_data else ""],
        ["Baseline variant", variants_data.get("baseline_label", "") if variants_data else ""],
        ["Term-rank record count", term_rank_data.get("relevant_record_count", "") if term_rank_data else ""],
        ["Term-rank scored terms", term_rank_data.get("candidates_scored", "") if term_rank_data else ""],
    ]
    sheets.append(("Summary", summary))

    if variants_data:
        results = list(variants_data.get("results", []))
        include_extra_variant_columns = has_design_metadata(results)
        variant_header = ["Label", "Count", "Delta from baseline", "Percent of baseline", "Retmax", "Warnings"]
        if include_extra_variant_columns:
            variant_header.extend(["Role", "Decision status", "Seed recall %", "Estimated precision", "Estimated NNR"])
        variant_header.append("Query")
        variant_rows = [variant_header]
        ledger_rows = [
            [
                "Label",
                "Role",
                "Decision status",
                "Count",
                "Delta from baseline",
                "Percent of baseline",
                "Seed PMIDs retrieved",
                "Seed PMIDs missed",
                "Seed recall %",
                "Labelled sample size",
                "Relevant labelled records",
                "Estimated precision",
                "Estimated NNR",
                "Estimated NNR note",
                "Warnings",
                "Hypothesis",
                "Changes from baseline",
                "Recall risk",
                "Workload rationale",
                "Decision reason",
                "Query",
            ]
        ]
        for item in results:
            if not isinstance(item, dict):
                continue
            variant_row = [
                item.get("label", ""),
                item.get("count", ""),
                item.get("count_delta_from_baseline", ""),
                item.get("percent_of_baseline", ""),
                item.get("retmax", ""),
                query_warning_codes(item),
            ]
            if include_extra_variant_columns:
                variant_row.extend(
                    [
                        item.get("role", ""),
                        item.get("decision_status", ""),
                        item.get("seed_recall_percent", ""),
                        item.get("estimated_precision", ""),
                        item.get("estimated_nnr", ""),
                    ]
                )
            variant_row.append(item.get("query", ""))
            variant_rows.append(variant_row)
            ledger_rows.append(
                [
                    item.get("label", ""),
                    item.get("role", ""),
                    item.get("decision_status", ""),
                    item.get("count", ""),
                    item.get("count_delta_from_baseline", ""),
                    item.get("percent_of_baseline", ""),
                    list_text(item.get("seed_pmids_retrieved", [])),
                    list_text(item.get("seed_pmids_missed", [])),
                    item.get("seed_recall_percent", ""),
                    item.get("labelled_sample_size", ""),
                    item.get("relevant_labelled_records", ""),
                    item.get("estimated_precision", ""),
                    item.get("estimated_nnr", ""),
                    item.get("estimated_nnr_note", ""),
                    query_warning_codes(item),
                    item.get("hypothesis", ""),
                    list_text(item.get("changes_from_baseline", "")),
                    item.get("recall_risk", ""),
                    item.get("workload_rationale", ""),
                    item.get("decision_reason", ""),
                    item.get("query", ""),
                ]
            )
        sheets.append(("Variants", variant_rows))
        sheets.append(("Design Ledger", ledger_rows))

    if mine_data:
        record_rows = [["PMID", "Year", "Title", "Journal", "DOI", "Publication types", "Keywords"]]
        for record in mine_data.get("records", []):
            if isinstance(record, dict):
                record_rows.append(
                    [
                        record.get("pmid", ""),
                        record.get("year", ""),
                        record.get("title", ""),
                        record.get("journal", ""),
                        record.get("doi", ""),
                        list_text(record.get("publication_types", [])),
                        list_text(record.get("keywords", [])),
                    ]
                )
        sheets.append(("Seed Records", record_rows))

        mesh_rows = [["Term", "Count", "Major count", "UIs", "In strategy"]]
        for item in mine_data.get("mesh_heading_counts", []):
            if isinstance(item, dict):
                mesh_rows.append([item.get("term", ""), item.get("count", ""), item.get("major_count", ""), list_text(item.get("uis", [])), item.get("in_strategy", "")])
        sheets.append(("MeSH Terms", mesh_rows))

        for sheet_title, key in (("Keywords", "keyword_counts"), ("Phrases", "phrase_counts"), ("Acronyms", "acronym_counts")):
            rows = [["Term", "Count", "In strategy"]]
            for item in mine_data.get(key, []):
                if isinstance(item, dict):
                    rows.append([item.get("term", ""), item.get("count", ""), item.get("in_strategy", "")])
            sheets.append((sheet_title, rows))

        candidate_rows = [["Term", "Sources", "Count", "In strategy"]]
        for item in mine_data.get("candidate_tiab_terms", []):
            if isinstance(item, dict):
                candidate_rows.append([item.get("term", ""), list_text(item.get("sources", [])), item.get("count", ""), item.get("in_strategy", "")])
        sheets.append(("TIAB Candidates", candidate_rows))

    if term_rank_data:
        term_rank_rows = [
            ["Term", "Field", "Relevant df", "Coverage", "Background count", "Lift", "Noise risk", "In strategy", "Sources", "Suggested layer"]
        ]
        for item in term_rank_data.get("ranked_terms", []):
            if isinstance(item, dict):
                term_rank_rows.append(
                    [
                        item.get("term", ""),
                        item.get("field", ""),
                        item.get("relevant_df", ""),
                        item.get("coverage", ""),
                        item.get("background_count", ""),
                        item.get("lift", ""),
                        item.get("noise_risk", ""),
                        item.get("in_strategy", ""),
                        list_text(item.get("sources", [])),
                        item.get("suggested_layer", ""),
                    ]
                )
        sheets.append(("Term Ranking", term_rank_rows))

    output = Path(output_path)
    write_xlsx(output, sheets)
    return {
        "operation": "audit-workbook",
        "output": str(output),
        "sheet_count": len(sheets),
        "sheets": [name for name, _ in sheets],
    }


AUDIT_SCAFFOLD_RECORD_KINDS = ("fetch", "mine", "sample")
AUDIT_SCAFFOLD_NOTE = (
    "Mechanical fields were filled from saved tool outputs; judgment fields are bracketed "
    "placeholders that audit_markdown.py refuses to render until you author them. Counts come "
    "from --output file content, not the manifest's hand-typed --count. Fill all placeholders, "
    "complete the remaining audit-template.md sections, then render with audit_markdown.py."
)


def audit_placeholder(text: str) -> str:
    """A bracketed placeholder. Callers include an audit_markdown PLACEHOLDER_RE trigger word
    (decision/reason/count/date/summary/concept/strategy/record/pmid/source/name) so the renderer
    refuses to emit the audit until the agent replaces it."""
    return f"[{text}]"


def scaffold_resolve_output(path: Path, if_exists: str) -> Path:
    # Mirrors audit_markdown.py/manifest_tool.py so a re-run never clobbers an authored audit.
    if not path.exists() or if_exists == "overwrite":
        return path
    if if_exists == "fail":
        raise PubMedError(f"Audit scaffold output already exists: {path}")
    if if_exists != "suffix":
        raise PubMedError(f"Unsupported --if-exists policy: {if_exists}")
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise PubMedError(f"Could not find an available suffix for: {path}")


def _scaffold_count_from_output(output_path: object) -> int | None:
    """Read a tool-produced count from a saved --output file; None if unreadable/absent."""
    if not isinstance(output_path, str) or not output_path:
        return None
    try:
        data = load_json_file(output_path)
    except Exception:
        return None
    count = data.get("count") if isinstance(data, dict) else None
    return count if isinstance(count, int) else None


def _scaffold_record_summary(record: object) -> dict[str, object] | None:
    if not isinstance(record, dict):
        return None
    pmid = str(record.get("pmid") or "").strip()
    if not pmid:
        return None
    return {
        "pmid": pmid,
        "title": record.get("title") or "",
        "year": record.get("year") or "",
        "publication_types": record.get("publication_types") or [],
        "abstract_present": bool(str(record.get("abstract") or "").strip()),
    }


def _scaffold_seed_triage(
    seed_fetch_data: dict[str, object] | None,
    seed_mine_data: dict[str, object] | None,
    sources: dict[str, str],
) -> dict[str, object] | None:
    source_key = "seed_fetch" if seed_fetch_data else "seed_mine"
    data = seed_fetch_data or seed_mine_data
    if not data:
        return None
    requested = [str(pmid) for pmid in (data.get("requested_pmids") or [])]
    found = [str(pmid) for pmid in (data.get("found_pmids") or [])]
    missing = [str(pmid) for pmid in (data.get("missing_pmids") or [])]
    records = [
        row
        for row in (_scaffold_record_summary(record) for record in (data.get("records") or []))
        if row is not None
    ]
    return {
        "requested_seed_entries": requested,
        "normalized_unique_numeric_pmids": dedup_preserving_order(requested),
        "malformed_entries_excluded": "not available from saved fetch/mine JSON",
        "fetched_seed_records": records,
        "evidence_file_reviewed": sources.get(source_key, ""),
        "record_content_reviewed": audit_placeholder("record content reviewed: yes/no"),
        "abstracts_reviewed": audit_placeholder("abstracts reviewed: yes/no/not available"),
        "receipt_only_stdout_used_as_decision_evidence": "no",
        "decision_supported": audit_placeholder("decision supported: yes/no"),
        "missing_not_found_pmids_excluded": missing,
        "retracted_seeds": audit_placeholder("retracted seed decision after record review, or none"),
        "likely_out_of_scope_seeds": audit_placeholder("out-of-scope seed decision after record review, or none"),
        "user_protocol_decision_when_paused": audit_placeholder("user/protocol decision for seed triage if paused, or not applicable"),
        "found_pmids": found,
    }


def _scaffold_related_candidate_labels(candidates: object) -> list[str]:
    rows = [item for item in (candidates or []) if isinstance(item, dict)]
    high_overlap = [item for item in rows if int(item.get("seed_overlap_count") or 0) > 1]
    labels: list[str] = []
    for item in high_overlap[:20]:
        pmid = str(item.get("pmid") or "").strip()
        if not pmid:
            continue
        overlap = item.get("seed_overlap_count")
        via = list_text(item.get("via") or [])
        labels.append(f"{pmid} (seed_overlap_count={overlap}; via={via})")
    return labels


def _scaffold_seed_set_expansion(related_data: dict[str, object] | None) -> dict[str, object] | None:
    if not related_data:
        return None
    return {
        "expansion_run": "Yes",
        "links_used": related_data.get("links_used") or [],
        "link_counts": related_data.get("link_counts") or {},
        "max_per_seed": related_data.get("max_per_seed"),
        "max_total": related_data.get("max_total"),
        "candidate_count": related_data.get("candidate_count"),
        "candidate_count_before_cap": related_data.get("candidate_count_before_cap"),
        "high_overlap_candidate_pmids": _scaffold_related_candidate_labels(related_data.get("candidate_pmids")),
        "how_related_set_evidence_was_used": audit_placeholder("related-set use decision: fed to term-rank / recall heuristic / not used"),
        "labelling": (
            "related-set evidence is recorded separately from user-confirmed seed evidence and is not treated as validated recall"
        ),
    }


def _scaffold_bottleneck_block(block_recall: object) -> str:
    for item in block_recall or []:
        if isinstance(item, dict) and item.get("bottleneck"):
            return str(item.get("label") or "")
    return ""


def _scaffold_relative_recall(
    recall_data: dict[str, object] | None,
    seed_status: str = "unknown",
    recall_offer: str = "",
) -> dict[str, object] | None:
    """Build the relative-recall audit block.

    On a no-seed build the benchmark is a pilot-expansion heuristic; label it as such and reflect the
    recorded recall-offer outcome (done / declined / not-applicable) so a declined offer reads as a
    deliberate choice rather than `not performed`. See `references/no-seed-recall-estimation.md`."""
    no_seed = seed_status == "no"
    if recall_data:
        source = recall_data.get("benchmark_source")
        if no_seed:
            label = "no-seed pilot-expansion heuristic"
            source = f"{source} ({label})" if source and label not in str(source) else (source or label)
        return {
            "check_run": "Yes (no-seed heuristic)" if no_seed else "Yes",
            "benchmark_source": source,
            "benchmark_size": recall_data.get("benchmark_size"),
            "relative_recall_percent": recall_data.get("relative_recall_percent"),
            "retrieved_count": recall_data.get("retrieved_count"),
            "missed_count": recall_data.get("missed_count"),
            "retrieved_pmids": recall_data.get("retrieved_pmids") or [],
            "missed_pmids": recall_data.get("missed_pmids") or [],
            "block_recall": recall_data.get("block_recall") or [],
            "bottleneck_block": _scaffold_bottleneck_block(recall_data.get("block_recall")),
            "miss_diagnosis": recall_data.get("miss_diagnosis") or [],
            "caveat": recall_data.get("note") or RELATIVE_RECALL_NOTE,
        }
    # No recall JSON. On a no-seed build, still record a resolved offer as a deliberate outcome.
    if no_seed and recall_offer == "declined":
        return {"check_run": "Offered; declined by user", "caveat": RELATIVE_RECALL_NOTE}
    if no_seed and recall_offer == "not-applicable":
        return {"check_run": "Not applicable (no-seed build)", "caveat": RELATIVE_RECALL_NOTE}
    return None


def _scaffold_concept_blocks(blocks_raw: object, cli_checks: dict[str, object]) -> list[dict[str, object]]:
    """Normalize a --blocks-file into concept_blocks [{label, query, count}].

    Counts come from the block's own `count` if present, else from a labelled manifest search entry
    (the pubmed_cli_checks map) matched by label. Counts are best-effort: an unmatched block simply
    has no count, which the renderer shows as 'not performed'.
    """
    normalized: list[tuple[str, str, object]] = []
    if isinstance(blocks_raw, list):
        for index, item in enumerate(blocks_raw, start=1):
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("name") or f"Concept {index}")
                query, count = item.get("query"), item.get("count")
            else:
                label, query, count = f"Concept {index}", item, None
            if query:
                normalized.append((label, str(query), count))
    elif isinstance(blocks_raw, dict):
        for index, (label, value) in enumerate(blocks_raw.items(), start=1):
            if isinstance(value, dict):
                query, count = value.get("query"), value.get("count")
            else:
                query, count = value, None
            if query:
                normalized.append((str(label), str(query), count))

    blocks: list[dict[str, object]] = []
    for label, query, count in normalized:
        if count is None and isinstance(cli_checks, dict):
            matched = cli_checks.get(label)
            count = matched if isinstance(matched, int) else None
        block: dict[str, object] = {"label": label, "query": query}
        if count is not None:
            block["count"] = count
        blocks.append(block)
    return blocks


def build_audit_scaffold(
    *,
    topic_slug: str,
    manifest_data: dict[str, object] | None,
    date_searched: str | None,
    final_search_data: dict[str, object] | None,
    strategy_text: str | None,
    validate_data: dict[str, object] | None,
    variants_data: dict[str, object] | None,
    seed_fetch_data: dict[str, object] | None,
    seed_mine_data: dict[str, object] | None,
    related_data: dict[str, object] | None,
    recall_data: dict[str, object] | None,
    seed_status: str,
    audit_workbook: str | None,
    sources: dict[str, str],
    blocks_data: object | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build a partial audit JSON (audit_markdown.py contract) from saved tool outputs.

    Mechanical fields are filled from file content; judgment fields are trigger-word placeholders;
    the scaffold cites that record-content evidence files exist but never attests the agent
    reviewed them ("No reviewed JSON, no decision").
    """
    entries = [e for e in (manifest_data or {}).get("entries", []) if isinstance(e, dict)]
    filled: list[str] = []
    placeholders: list[str] = []
    audit: dict[str, object] = {}

    slug = topic_slug or str((manifest_data or {}).get("topic_slug") or "")
    if slug:
        audit["title"] = f"PubMed high-sensitivity search audit: {slug}"
        audit["topic"] = slug
        filled.append("title/topic")
    else:
        audit["title"] = audit_placeholder("name this search topic or review question")
        placeholders.append("title")

    if date_searched:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_searched):
            raise PubMedError("--date-searched must use YYYY-MM-DD.")
        audit["date_searched"] = date_searched
        filled.append("date_searched (override)")
    else:
        # date_searched: search-time from the manifest, never the scaffold-run time.
        search_dates = sorted(
            str(e.get("timestamp_utc", ""))[:10]
            for e in entries
            if e.get("kind") == "search" and str(e.get("timestamp_utc", ""))
        )
        if search_dates:
            audit["date_searched"] = search_dates[-1]
            filled.append("date_searched")
        elif manifest_data and manifest_data.get("updated_utc"):
            audit["date_searched"] = str(manifest_data["updated_utc"])[:10]
            filled.append("date_searched")
        else:
            audit["date_searched"] = audit_placeholder("date searched")
            placeholders.append("date_searched")

    # result_count + final_strategy: only from explicit final inputs; never guessed.
    if final_search_data and isinstance(final_search_data.get("count"), int):
        audit["result_count"] = final_search_data["count"]
        filled.append("result_count")
    else:
        audit["result_count"] = audit_placeholder("final result count")
        placeholders.append("result_count")
    if strategy_text and strategy_text.strip():
        audit["final_strategy"] = strategy_text.strip()
        filled.append("final_strategy")
    else:
        audit["final_strategy"] = audit_placeholder("final PubMed strategy text")
        placeholders.append("final_strategy")

    # pubmed_cli_checks: labeled manifest search/batch entries; counts from --output file content.
    cli_checks: dict[str, object] = {}
    for entry in entries:
        kind = entry.get("kind")
        label = str(entry.get("label") or "").strip()
        out = entry.get("output_path")
        if kind == "search" and label:
            count = _scaffold_count_from_output(out)
            cli_checks[label] = count if count is not None else entry.get("count")
        elif kind == "batch" and isinstance(out, str) and out:
            try:
                batch = load_json_file(out)
            except Exception:
                batch = None
            for row in (batch.get("results", []) if isinstance(batch, dict) else []):
                if isinstance(row, dict) and row.get("label"):
                    cli_checks[str(row["label"])] = row.get("count")
    if final_search_data and isinstance(final_search_data.get("count"), int):
        cli_checks.setdefault("Final combined topic-only strategy", final_search_data["count"])
    if cli_checks:
        audit["pubmed_cli_checks"] = cli_checks
        filled.append("pubmed_cli_checks")

    # concept_blocks: numbered line set + PRISMA-S appendix input (audit_markdown.py). Counts are
    # matched from labelled manifest search entries; the combination defaults to all blocks AND-ed
    # (override in an overlay for non-trivial logic). The agent still authors filter/limit details.
    if blocks_data is not None:
        concept_blocks = _scaffold_concept_blocks(blocks_data, cli_checks)
        if concept_blocks:
            audit["concept_blocks"] = concept_blocks
            audit["combination"] = " AND ".join(str(i) for i in range(1, len(concept_blocks) + 1))
            filled.append("concept_blocks")

    # Aggregate zero-hit / not-found phrases across saved search/batch outputs (the final search is
    # post-hygiene and usually clean, so scan them all). Removed-vs-kept stays the agent's decision.
    zero_hit: list[str] = []
    for entry in entries:
        if entry.get("kind") not in ("search", "batch"):
            continue
        out = entry.get("output_path")
        if not (isinstance(out, str) and out):
            continue
        try:
            doc = load_json_file(out)
        except Exception:
            continue
        nodes = [doc, *(r for r in doc.get("results", []) if isinstance(r, dict))] if isinstance(doc, dict) else []
        for node in nodes:
            phrases, _ = _not_found_phrases(node)
            zero_hit.extend(phrases)
    zero_hit = list(dict.fromkeys(p for p in zero_hit if p))[:COMPACT_NOT_FOUND_CAP]

    # ATM translation from the final search (sanitize brackets so field tags can't self-block).
    if final_search_data and final_search_data.get("query_translation"):
        translation = str(final_search_data["query_translation"]).replace("[", "(").replace("]", ")")
        audit["atm_translations"] = [
            {"query": "final topic-only strategy", "translation": translation, "added_explicitly": audit_placeholder("confirm: yes/no")}
        ]
        filled.append("atm_translations")

    # Seed validation from the validate output, or an explicit/placeholdered seed status.
    if validate_data:
        provided = validate_data.get("provided_pmids") or []
        missed = validate_data.get("missed_pmids") or []
        seed_block: dict[str, object] = {
            "seed_pmids_tested": provided,
            "retrieved": validate_data.get("retrieved_pmids") or [],
            "missed": missed,
            "seeds_judged_out_of_scope": "none",
            "revisions_made_after_seed_testing": audit_placeholder("revisions after seed testing, or none"),
        }
        if missed:
            seed_block["reason_for_misses"] = audit_placeholder("reason for each missed seed")
            placeholders.append("seed_validation.reason_for_misses")
        else:
            seed_block["reason_for_misses"] = "none"
        audit["seed_validation"] = seed_block
        filled.append("seed_validation")
    elif seed_status == "no":
        pass  # renderer shows "Seed PMIDs provided: No" with the no-seed limits.
    else:
        audit["seed_pmids"] = [audit_placeholder("state seed PMIDs tested, or 'no seeds supplied'")]
        placeholders.append("seed_validation.seed_pmids")

    # Variant choice (mechanical, from decision_status/role).
    if variants_data:
        results = [r for r in variants_data.get("results", []) if isinstance(r, dict)]
        selected = [r for r in results if str(r.get("decision_status", "")).lower() == "selected"]
        if selected:
            audit["main_variant_chosen"] = f"{selected[0].get('label', '')} ({selected[0].get('count', '')} records)"
            filled.append("main_variant_chosen")
        focused = [r for r in results if str(r.get("role", "")).lower() in ("focused", "precision")]
        if focused:
            audit["focused_variant_count"] = "; ".join(f"{r.get('label', '')}={r.get('count', '')}" for r in focused)
            filled.append("focused_variant_count")

    seed_triage = _scaffold_seed_triage(seed_fetch_data, seed_mine_data, sources)
    if seed_triage:
        audit["pre_gate_seed_triage"] = seed_triage
        filled.append("pre_gate_seed_triage")
        placeholders.append("pre_gate_seed_triage (record review/scope decisions)")

    seed_expansion = _scaffold_seed_set_expansion(related_data)
    if seed_expansion:
        audit["seed_set_expansion"] = seed_expansion
        filled.append("seed_set_expansion")
        placeholders.append("seed_set_expansion.how_related_set_evidence_was_used")

    manifest_state = (manifest_data or {}).get("build_state")
    recall_offer = ""
    if isinstance(manifest_state, dict):
        recall_offer = str(manifest_state.get("recall_offer") or "")
    relative_recall = _scaffold_relative_recall(recall_data, seed_status=seed_status, recall_offer=recall_offer)
    if relative_recall:
        audit["relative_recall"] = relative_recall
        filled.append("relative_recall")

    # Record-content evidence: cite that the saved files exist; never attest review.
    rc_rows = []
    for entry in entries:
        kind = str(entry.get("kind") or "")
        out = entry.get("output_path")
        if kind in AUDIT_SCAFFOLD_RECORD_KINDS and isinstance(out, str) and out:
            rc_rows.append(
                {
                    "decision_point": audit_placeholder(f"decision this {kind} JSON supports"),
                    "evidence_file_reviewed": out,
                    "record_content_reviewed": audit_placeholder("record content reviewed: yes/no"),
                    "abstracts_reviewed": audit_placeholder("abstracts reviewed: yes/no/not available"),
                    "receipt_only_stdout_used_as_decision_evidence": "no",
                    "decision_supported": audit_placeholder("decision supported: yes/no"),
                }
            )
    if rc_rows:
        audit["record_content_evidence"] = rc_rows
        filled.append("record_content_evidence (paths only)")
        placeholders.append("record_content_evidence (review/supported)")

    # Forced judgment placeholders: the agent must author these (render blocked until then).
    audit["search_structure"] = {
        "framework": audit_placeholder("framework, question type, and reason"),
        "concept_gate_status": "completed",
        "and_block_admission_summary": audit_placeholder("AND-block admission summary"),
        "methodological_filters_or_limits": audit_placeholder("none, or filter source/version/interface/adaptation"),
    }
    audit["decision_ledger"] = [
        {
            "decision_point": audit_placeholder("author the decision ledger: each decision point"),
            "options_considered": audit_placeholder("options considered"),
            "evidence_or_test_used": audit_placeholder("evidence or test used"),
            "decision_made": audit_placeholder("decision made"),
            "rationale_or_recall_risk_note": audit_placeholder("rationale and recall-risk reason"),
            "reflected_in_strategy_or_report": audit_placeholder("where reflected"),
        }
    ]
    audit["rationale"] = {
        "mesh_choices": audit_placeholder("MeSH descriptor decisions: accepted/rejected and why"),
        "text_word_choices": audit_placeholder("text-word choices and reasons"),
        "pre_mesh_vocabulary_domain_choices": audit_placeholder("pre-MeSH vocabulary/domain decisions"),
        "concept_gate_and_omitted_block_choices": audit_placeholder("concept-gate and omitted-block decisions"),
        "methodological_filters_or_limits": audit_placeholder("filter/limit decisions and source"),
        "sensitivity_vs_precision": audit_placeholder("sensitivity vs precision: chosen design and reason"),
        "qa": audit_placeholder("QA summary: drift, final-qa, filter-check"),
    }
    audit["peer_review_attention_points"] = [audit_placeholder("peer-review attention point: high-impact decision")]
    placeholders.extend(["search_structure", "decision_ledger", "rationale", "peer_review_attention_points"])

    # Capture dropped zero-hit phrases: embed the PubMed-reported phrases as a hint, but leave the
    # removed-vs-kept call to the agent (a `decision` trigger word forces authoring before render).
    if zero_hit:
        sanitized = "; ".join(p.replace("[", "(").replace("]", ")") for p in zero_hit)
        removed = audit_placeholder(f"record the removed/kept decision for these PubMed zero-hit phrases: {sanitized}")
        filled.append("tiab_expansion.zero_hit_phrases (evidence)")
    else:
        removed = audit_placeholder("zero-hit phrases removed + documented during final hygiene, or none (record the decision)")
    audit["tiab_expansion"] = {
        "morphology_review": [
            {
                "phrase_family": audit_placeholder("singular/plural phrase family reviewed, or none"),
                "explicit_forms": audit_placeholder("explicit singular/plural forms present, or none"),
                "wildcard_candidate": audit_placeholder("phrase-final, phrase-anchored/concept-specific wildcard candidate tested, or not applicable"),
                "tested": audit_placeholder("yes/no/not applicable"),
                "decision": audit_placeholder("morphology decision: wildcard retained / explicit forms retained / wildcard not applicable"),
                "rationale": audit_placeholder("reason for morphology decision"),
            }
        ],
        "proximity_candidates_tested": audit_placeholder("proximity review decision: exact phrase(s), Boolean AND, and proximity widths tested, or not applicable"),
        "proximity_expressions_added": audit_placeholder("proximity expressions retained, or none"),
        "proximity_expressions_tested_but_rejected": audit_placeholder("proximity expressions tested but rejected with reason, or none"),
        "proximity_not_applicable_rationale": audit_placeholder("reason proximity was not applicable, or not applicable"),
        "zero_hit_terms_removed": removed,
        "zero_hit_terms_kept": audit_placeholder("zero-hit terms kept by user choice as intentional, or none"),
    }
    placeholders.append("tiab_expansion.proximity_review (decision)")
    placeholders.append("tiab_expansion.morphology_review (decision)")
    placeholders.append("tiab_expansion.zero_hit_terms (decision)")

    # Omit reporting_notes.date_searched: the renderer falls back to top-level date_searched,
    # so a date placeholder is authored once rather than duplicated.
    audit["reporting_notes"] = {
        "database": "PubMed",
        "audit_workbook": audit_workbook or "not exported",
        "remaining_caveats": audit_placeholder("remaining caveats and recall-risk reasons"),
    }
    if sources.get("manifest"):
        audit["reporting_notes"]["run_manifest"] = sources["manifest"]  # type: ignore[index]
    placeholders.append("reporting_notes.remaining_caveats")

    receipt = {
        "operation": "audit-scaffold",
        "fields_filled": filled,
        "placeholder_fields": placeholders,
        "placeholder_count": len(placeholders),
        "sources_used": sources,
        "note": AUDIT_SCAFFOLD_NOTE,
    }
    return audit, receipt


def run_audit_scaffold(args: argparse.Namespace) -> dict[str, object]:
    sources: dict[str, str] = {}
    manifest_data = None
    if args.manifest:
        manifest_data = load_json_file(args.manifest)
        sources["manifest"] = args.manifest
    final_search_data = None
    if args.final_search_json:
        final_search_data = load_json_file(args.final_search_json)
        sources["final_search"] = args.final_search_json
    strategy_text = None
    if args.strategy_file:
        strategy_text = read_text_source(args.strategy_file)
        sources["strategy_file"] = args.strategy_file
    validate_data = None
    if args.validate_json:
        validate_data = load_json_file(args.validate_json)
        sources["validate"] = args.validate_json
    variants_data = None
    if args.variants_json:
        variants_data = load_json_file(args.variants_json)
        sources["variants"] = args.variants_json
    seed_fetch_data = None
    if args.seed_fetch_json:
        seed_fetch_data = load_json_file(args.seed_fetch_json)
        sources["seed_fetch"] = args.seed_fetch_json
    seed_mine_data = None
    if args.seed_mine_json:
        seed_mine_data = load_json_file(args.seed_mine_json)
        sources["seed_mine"] = args.seed_mine_json
    related_data = None
    if args.related_json:
        related_data = load_json_file(args.related_json)
        sources["related"] = args.related_json
    recall_data = None
    if args.recall_json:
        recall_data = load_json_file(args.recall_json)
        sources["recall"] = args.recall_json
    blocks_data = None
    if args.blocks_file:
        blocks_data = load_benchmark_or_blocks_json(args.blocks_file)
        validate_recall_blocks(blocks_data)
        sources["blocks_file"] = args.blocks_file

    audit, receipt = build_audit_scaffold(
        topic_slug=args.topic_slug or "",
        manifest_data=manifest_data,
        date_searched=args.date_searched,
        final_search_data=final_search_data,
        strategy_text=strategy_text,
        validate_data=validate_data,
        variants_data=variants_data,
        seed_fetch_data=seed_fetch_data,
        seed_mine_data=seed_mine_data,
        related_data=related_data,
        recall_data=recall_data,
        seed_status=args.seed_status,
        audit_workbook=args.audit_workbook,
        sources=sources,
        blocks_data=blocks_data,
    )
    output = scaffold_resolve_output(Path(args.output), args.if_exists)
    dump_json_to_path(output, audit)
    receipt["output"] = str(output)
    return receipt


def doctor(client: NcbiClient, test_query: str) -> dict[str, object]:
    search_result = esearch(client, test_query, retmax=0, retstart=0, sort=None)
    return {
        "ok": True,
        "checks": {
            "email_configured": bool(client.email),
            "tool": client.tool,
            "api_key_present": bool(client.api_key),
            "api_key_used": search_result.get("request_info", {}).get("api_key_used", False),
            "rate_limit_per_second": client.rate_limit_per_second,
            "test_query": test_query,
            "test_count": search_result.get("count", 0),
            "warnings": search_result.get("warnings", {}),
        },
        "query_translation_hook": search_result.get("query_translation_hook", {}),
        "request_info": client.metadata(),
    }


def write_json(data: dict[str, object]) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    json.dump(data, sys.stdout, indent=2, ensure_ascii="utf" not in encoding)
    sys.stdout.write("\n")


def dump_json_to_path(path: Path, data: dict[str, object]) -> None:
    """Write the full result JSON to a file (used by --output). Overwrites; tool outputs are regenerated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _hook_codes(hook: object) -> list[str]:
    if not isinstance(hook, dict):
        return []
    codes: list[str] = []
    for issue in hook.get("issues", []) or []:
        if isinstance(issue, dict) and issue.get("code"):
            code = str(issue["code"])
            if code not in codes:
                codes.append(code)
    return codes


COMPACT_NOT_FOUND_CAP = 50


def _hook_details(hook: object) -> list[dict[str, object]]:
    """Issue code + evidence (the actual not-found phrases / field tags) from a hook, so compact
    output surfaces the actionable payload instead of only the bare code."""
    if not isinstance(hook, dict):
        return []
    details: list[dict[str, object]] = []
    for issue in hook.get("issues", []) or []:
        if isinstance(issue, dict) and issue.get("code") and issue.get("evidence"):
            details.append({"code": str(issue["code"]), "evidence": str(issue["evidence"])})
    return details


def _not_found_phrases(node: dict[str, object]) -> tuple[list[str], int]:
    """Complete deduped zero-hit / not-found phrase list from the raw PubMed errorlist
    (``phrasesnotfound``) and warninglist (``quotedphrasesnotfound``)."""
    items: list[str] = []
    errors = node.get("errors") if isinstance(node, dict) else None
    warnings = node.get("warnings") if isinstance(node, dict) else None
    if isinstance(errors, dict):
        items += normalize_warning_items(errors.get("phrasesnotfound"))
    if isinstance(warnings, dict):
        items += normalize_warning_items(warnings.get("quotedphrasesnotfound"))
    deduped = list(dict.fromkeys(item for item in items if item))
    return deduped[:COMPACT_NOT_FOUND_CAP], len(deduped)


def _qa_signal(node: dict[str, object]) -> dict[str, object]:
    """QA-visible signal from a result or sub-result node (search, per-batch-result, per-variant).

    Surfaces the actionable payload, not just codes: the actual not-found phrases (so zero-hit
    cleanup needs no full-output rerun) and per-issue evidence, alongside the warning/error/drift
    status.
    """
    hook = node.get("query_translation_hook") or {}
    warnings = node.get("warnings") or {}
    errors = node.get("errors") or {}
    phrases, total = _not_found_phrases(node)
    signal: dict[str, object] = {
        "warning_count": len(warnings) if isinstance(warnings, dict) else 0,
        "error_count": len(errors) if isinstance(errors, dict) else 0,
        "drift_ok": bool(hook.get("ok", True)) if isinstance(hook, dict) else True,
        "drift_review": bool(hook.get("review_recommended", False)) if isinstance(hook, dict) else False,
        "drift_codes": _hook_codes(hook),
    }
    details = _hook_details(hook)
    if details:
        signal["drift_details"] = details
    if phrases:
        signal["phrases_not_found"] = phrases
        signal["phrases_not_found_total"] = total
    return signal


def _precmd_signal(result: dict[str, object]) -> tuple[bool, list[str]]:
    pre = result.get("pre_command_hook") or {}
    if not isinstance(pre, dict):
        return True, []
    return bool(pre.get("ok", True)), _hook_codes(pre)


COMPACT_TOP_TERMS = 20
COMPACT_TOP_RECORDS = 20
COMPACT_RECORD_MESH = 8
COMPACT_PMIDS = 50


def _trim_terms(ranked_terms: list[object]) -> list[dict[str, object]]:
    trimmed: list[dict[str, object]] = []
    for row in ranked_terms[:COMPACT_TOP_TERMS]:
        if isinstance(row, dict):
            trimmed.append(
                {
                    "term": row.get("term"),
                    "field": row.get("field"),
                    "coverage": row.get("coverage"),
                    "lift": row.get("lift"),
                    "noise_risk": row.get("noise_risk"),
                }
            )
    return trimmed


def _count_rows_with_totals(rows: object, *, limit: int = COMPACT_TOP_TERMS) -> dict[str, object]:
    source_rows = [row for row in (rows or []) if isinstance(row, dict)]
    compact_rows: list[dict[str, object]] = []
    for row in source_rows[:limit]:
        compact: dict[str, object] = {"term": row.get("term"), "count": row.get("count")}
        for key in ("major_count", "in_strategy", "sources"):
            if key in row:
                compact[key] = row.get(key)
        compact_rows.append(compact)
    return {
        "rows": compact_rows,
        "total": len(source_rows),
        "shown": len(compact_rows),
        "omitted": max(0, len(source_rows) - len(compact_rows)),
    }


def _pmid_list_with_totals(pmids: object, *, limit: int = COMPACT_PMIDS) -> dict[str, object]:
    values = [str(pmid) for pmid in (pmids or [])]
    return {
        "pmids": values[:limit],
        "total": len(values),
        "shown": min(limit, len(values)),
        "omitted": max(0, len(values) - limit),
    }


def _mesh_names(record: dict[str, object]) -> list[str]:
    names: list[str] = []
    for heading in record.get("mesh_headings", []) or []:
        if isinstance(heading, dict):
            name = str(heading.get("name", "")).strip()
        else:
            name = str(heading).strip()
        if name:
            names.append(name)
    return names


def _record_summary(record: dict[str, object]) -> dict[str, object]:
    mesh_names = _mesh_names(record)
    return {
        "pmid": record.get("pmid", ""),
        "title": record.get("title", ""),
        "year": record.get("year", ""),
        "journal": record.get("journal", ""),
        "publication_types": record.get("publication_types", []),
        "abstract_present": bool(str(record.get("abstract", "")).strip()),
        "mesh_headings": mesh_names[:COMPACT_RECORD_MESH],
        "mesh_heading_total": len(mesh_names),
        "mesh_heading_omitted": max(0, len(mesh_names) - COMPACT_RECORD_MESH),
    }


def _record_summaries(records: object, *, limit: int = COMPACT_TOP_RECORDS) -> dict[str, object]:
    source_records = [record for record in (records or []) if isinstance(record, dict)]
    compact_records = [_record_summary(record) for record in source_records[:limit]]
    return {
        "records": compact_records,
        "total": len(source_records),
        "shown": len(compact_records),
        "omitted": max(0, len(source_records) - len(compact_records)),
    }


def _record_count_rows(records: object, key: str, *, limit: int = COMPACT_TOP_TERMS) -> dict[str, object]:
    counts: Counter[str] = Counter()
    for record in (records or []):
        if not isinstance(record, dict):
            continue
        if key == "mesh_headings":
            values = _mesh_names(record)
        else:
            values = [str(value) for value in (record.get(key, []) or []) if value]
        counts.update(value for value in values if value)
    rows = [{"term": term, "count": count} for term, count in counts.most_common()]
    return _count_rows_with_totals(rows, limit=limit)


def summarize_result(command: str, result: dict[str, object]) -> dict[str, object]:
    """Pure projection of a full result dict to a compact, QA-preserving summary for stdout.

    Never mutates ``result`` and never changes search behavior: it only chooses which fields to
    print. Verbose payloads (full query text, query_translation, long PMID/term arrays) are
    dropped from stdout but remain in the full ``--output`` JSON. Every QA signal is preserved:
    counts, warning/error counts and codes, translation-drift status, seed retrieved/missed,
    relative recall and bottleneck. Truncated views always report totals so nothing is hidden.

    ``ok`` flags hard failures only (pre-command errors, PubMed errorlist entries, and missed
    known-item seeds); advisory warnings and translation-drift heuristics are surfaced via their
    own fields (``warning_count``, ``drift_ok``, ``drift_codes``) and do not flip ``ok``.
    """
    if command in {"fetch", "mine", "sample"}:
        raise ValueError(
            f"{command} is a record-content command and does not support compact analytical summaries."
        )

    precmd_ok, precmd_codes = _precmd_signal(result)
    summary: dict[str, object] = {"operation": result.get("operation", command)}
    ok = precmd_ok

    if command == "search":
        qa = _qa_signal(result)
        summary.update(
            {
                "count": result.get("count"),
                "retmax": result.get("retmax"),
                "pmids_returned": len(result.get("pmids") or []),
                **qa,
            }
        )
        ok = precmd_ok and qa["error_count"] == 0
    elif command == "batch":
        rows = []
        any_drift = False
        for item in result.get("results") or []:
            qa = _qa_signal(item if isinstance(item, dict) else {})
            any_drift = any_drift or not qa["drift_ok"]
            row: dict[str, object] = {
                "label": item.get("label") if isinstance(item, dict) else None,
                "count": item.get("count") if isinstance(item, dict) else None,
                "warning_count": qa["warning_count"],
                "drift_ok": qa["drift_ok"],
                "drift_codes": qa["drift_codes"],
            }
            for key in ("drift_details", "phrases_not_found", "phrases_not_found_total"):
                if key in qa:
                    row[key] = qa[key]
            rows.append(row)
        summary.update({"query_count": result.get("query_count"), "results": rows, "any_drift": any_drift})
        # any_drift is advisory and surfaced as its own field; it does not flip ok.
    elif command == "variants":
        rows = []
        for item in result.get("results") or []:
            if not isinstance(item, dict):
                continue
            qa = _qa_signal(item)
            row: dict[str, object] = {
                "label": item.get("label"),
                "count": item.get("count"),
                "count_delta_from_baseline": item.get("count_delta_from_baseline"),
                "percent_of_baseline": item.get("percent_of_baseline"),
                "drift_codes": qa["drift_codes"],
            }
            for key in ("role", "decision_status", "seed_recall_percent", "seed_pmids_missed", "estimated_nnr"):
                if key in item:
                    row[key] = item[key]
            rows.append(row)
        summary.update(
            {
                "variant_count": result.get("variant_count"),
                "baseline_label": result.get("baseline_label"),
                "results": rows,
            }
        )
    elif command == "validate":
        qa = _qa_signal(result)
        provided = result.get("provided_pmids") or []
        retrieved = result.get("retrieved_pmids") or []
        missed = result.get("missed_pmids") or []
        summary.update(
            {
                "provided_count": len(provided),
                "retrieved_count": len(retrieved),
                "missed_count": len(missed),
                "retrieved_pmids": retrieved,
                "missed_pmids": missed,
                "recall_percent": round((len(retrieved) / len(provided)) * 100, 2) if provided else None,
                **qa,
            }
        )
        ok = precmd_ok and len(missed) == 0
    elif command == "recall":
        block_recall = [
            {
                "label": b.get("label"),
                "recall_percent": b.get("recall_percent"),
                "bottleneck": b.get("bottleneck", False),
            }
            for b in (result.get("block_recall") or [])
            if isinstance(b, dict)
        ]
        bottleneck_block = next((b["label"] for b in block_recall if b["bottleneck"]), None)
        miss_diagnosis = result.get("miss_diagnosis") or []
        summary.update(
            {
                "benchmark_source": result.get("benchmark_source"),
                "benchmark_size": result.get("benchmark_size"),
                "relative_recall_percent": result.get("relative_recall_percent"),
                "retrieved_count": result.get("retrieved_count"),
                "missed_count": result.get("missed_count"),
                "missed_pmids": result.get("missed_pmids") or [],
                "block_recall": block_recall,
                "bottleneck_block": bottleneck_block,
                "miss_diagnosis_count": len(miss_diagnosis),
                "and_interaction_count": sum(1 for m in miss_diagnosis if isinstance(m, dict) and m.get("and_interaction")),
            }
        )
    elif command == "related":
        candidates = result.get("candidate_pmids") or []
        top_overlap = max(
            (int(c.get("seed_overlap_count", 0) or 0) for c in candidates if isinstance(c, dict)),
            default=0,
        )
        summary.update(
            {
                "seed_count": len(result.get("seed_pmids") or []),
                "links_used": result.get("links_used"),
                "link_counts": result.get("link_counts"),
                "candidate_count": result.get("candidate_count"),
                "candidate_count_before_cap": result.get("candidate_count_before_cap"),
                "max_per_seed": result.get("max_per_seed"),
                "max_total": result.get("max_total"),
                "top_overlap": top_overlap,
            }
        )
    elif command == "term-rank":
        ranked = result.get("ranked_terms") or []
        summary.update(
            {
                "relevant_record_count": result.get("relevant_record_count"),
                "fields": result.get("fields"),
                "candidates_scored": result.get("candidates_scored"),
                "candidates_unscored": result.get("candidates_unscored"),
                "top_terms": _trim_terms(ranked),
                "ranked_terms_total": len(ranked),
                "ranked_terms_shown": min(COMPACT_TOP_TERMS, len(ranked)),
                "noise_risk_count": sum(1 for r in ranked if isinstance(r, dict) and r.get("noise_risk")),
            }
        )

    summary["ok"] = bool(ok)
    summary["precmd_ok"] = precmd_ok
    if precmd_codes:
        summary["precmd_codes"] = precmd_codes
    return summary


def emit(command: str, result: dict[str, object], args: argparse.Namespace) -> None:
    """Serialize a command result: full JSON by default; compact summary to stdout when
    --summary or --output is given; full JSON to the --output file when requested.

    A pure passthrough to write_json(result) when neither flag is present, so commands that
    do not expose the flags keep their existing verbose output unchanged.
    """
    output_path = getattr(args, "output", None)
    if output_path:
        dump_json_to_path(Path(output_path), result)
    if getattr(args, "summary", False) or output_path:
        summary = summarize_result(command, result)
        if output_path:
            summary["output"] = str(output_path)
        write_json(summary)
    else:
        write_json(result)


RECORD_CONTENT_DECISION_WARNING = (
    "Do not make relevance, scope, noise, term-discovery, or concept-role decisions "
    "from this receipt. Inspect the saved full JSON, including abstracts where available."
)


def emit_record_content_receipt(command: str, result: dict[str, object], args: argparse.Namespace) -> None:
    output_path = getattr(args, "output", None)
    if not output_path:
        raise ValueError(f"{command} requires --output for full record-content JSON.")

    dump_json_to_path(Path(output_path), result)
    precmd_ok, precmd_codes = _precmd_signal(result)
    receipt: dict[str, object] = {
        "operation": command,
        "status": "saved_full_json",
        "ok": bool(precmd_ok),
        "precmd_ok": bool(precmd_ok),
        "output": str(output_path),
        "stdout_role": "receipt_only",
        "full_json_review_required": True,
        "decision_warning": RECORD_CONTENT_DECISION_WARNING,
    }
    if precmd_codes:
        receipt["precmd_codes"] = precmd_codes
    if getattr(args, "summary", False):
        receipt["tolerated_flag"] = (
            "--summary ignored: record-content commands are always receipt-only; "
            "full JSON is in --output."
        )

    if command == "fetch":
        requested = result.get("requested_pmids") or []
        found = result.get("found_pmids") or []
        missing = result.get("missing_pmids") or []
        receipt.update(
            {
                "requested_count": len(requested),
                "found_count": len(found),
                "missing_count": len(missing),
                "missing_pmids": missing,
                "records_saved": len(result.get("records") or []),
            }
        )
        receipt["ok"] = bool(precmd_ok and len(missing) == 0)
    elif command == "mine":
        requested = result.get("requested_pmids") or []
        found = result.get("found_pmids") or []
        missing = result.get("missing_pmids") or []
        receipt.update(
            {
                "requested_count": len(requested),
                "found_count": len(found),
                "missing_count": len(missing),
                "missing_pmids": missing,
                "records_saved": result.get("record_count"),
                "strategy_provided": bool(result.get("strategy_provided", False)),
            }
        )
        receipt["ok"] = bool(precmd_ok and len(missing) == 0)
    elif command == "sample":
        search = result.get("search") if isinstance(result.get("search"), dict) else {}
        qa = _qa_signal(search)
        pmids = search.get("pmids") or []
        records = result.get("records") or []
        receipt.update(
            {
                "search_count": search.get("count"),
                "retmax": search.get("retmax"),
                "pmids_returned": len(pmids),
                "records_saved": len(records),
                "warning_count": qa["warning_count"],
                "error_count": qa["error_count"],
            }
        )
        receipt["ok"] = bool(precmd_ok and qa["error_count"] == 0)
    elif command == "term-diff":
        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        mesh_only = result.get("mesh_only_sample") if isinstance(result.get("mesh_only_sample"), dict) else {}
        tiab_only = result.get("tiab_only_sample") if isinstance(result.get("tiab_only_sample"), dict) else {}
        receipt.update(
            {
                "counts": counts,
                "mesh_only_records_saved": len(mesh_only.get("records") or []),
                "tiab_only_records_saved": len(tiab_only.get("records") or []),
            }
        )
        receipt["ok"] = bool(precmd_ok)
    else:
        raise ValueError(f"{command} is not a record-content command.")

    write_json(receipt)


def add_compact_output_arguments(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact QA summary to stdout instead of full JSON (counts, warning/error codes, drift, seed/recall signals). Get full data with --output.",
    )
    command_parser.add_argument(
        "--output",
        help="Write the full result JSON to this path; stdout then shows the compact summary. Record the path with manifest_tool.py.",
    )


def add_record_output_arguments(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument(
        "--output",
        required=True,
        help="Write full record-content JSON to this path. Stdout prints only a minimal receipt.",
    )
    command_parser.add_argument(
        "--summary",
        action="store_true",
        help="Accepted but ignored: record-content commands (fetch/mine/sample) are always receipt-only; "
        "full data is written to --output. Tolerated so a stray --summary does not hard-fail a build.",
    )


def add_query_input_arguments(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument("query", nargs="?", help="PubMed query string. Use '-' to read from stdin.")
    command_parser.add_argument("--query-file", help="Read the PubMed query from a UTF-8 text file. Use '-' for stdin.")
    command_parser.add_argument("--query-stdin", action="store_true", help="Read the PubMed query from stdin.")


def parse_term_rank_fields(value: str, parser: argparse.ArgumentParser) -> list[str]:
    fields: list[str] = []
    for item in str(value).split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name not in TERM_RANK_FIELDS:
            parser.error(
                f"Unknown --fields value: {item!r}. Only {', '.join(TERM_RANK_FIELDS)} are supported. "
                "Phrases, acronyms, and author keywords are scored within the tiab layer; there is no "
                "separate keywords/acronym/phrase field."
            )
        if name not in fields:
            fields.append(name)
    if not fields:
        parser.error("Provide at least one --fields value (tiab and/or mesh).")
    return fields


def parse_related_links(value: str, parser: argparse.ArgumentParser) -> list[str]:
    links: list[str] = []
    for item in str(value).split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name not in RELATED_LINKNAMES:
            parser.error(f"Unknown --links value: {item!r}. Choose from: {', '.join(RELATED_LINKNAMES)}.")
        if name not in links:
            links.append(name)
    if not links:
        parser.error(f"Provide at least one --links value ({', '.join(RELATED_LINKNAMES)}).")
    return links


def run_selftest() -> dict[str, object]:
    """Offline robustness self-checks (no network).

    Guards the improvement-1 hardening invariants so they cannot silently regress
    in a deployed copy of the skill: record-content commands tolerate a stray
    --summary (and still require --output), query files decode across encodings,
    and NCBI retries are surfaced. Returns a structured report; exit code is set
    by the caller from ``ok``.
    """
    import contextlib
    import io
    import tempfile

    checks: list[dict[str, object]] = []

    def record(name: str, fn) -> None:
        try:
            checks.append({"name": name, "ok": True, "detail": fn() or "ok"})
        except Exception as exc:  # report any failure as a failed check, never raise
            checks.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"})

    parser = build_parser()

    def _summary_tolerated_parse() -> str:
        for argv in (
            ["fetch", "--pmids", "1", "--output", "o.json", "--summary"],
            ["mine", "--pmids", "1", "--output", "o.json", "--summary"],
            ["sample", "robot[tiab]", "--output", "o.json", "--summary"],
        ):
            assert parser.parse_args(argv).summary is True
        return "fetch/mine/sample accept --summary"

    def _output_still_required() -> str:
        for argv in (["fetch", "--pmids", "1"], ["mine", "--pmids", "1"], ["sample", "robot[tiab]"]):
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    parser.parse_args(argv)
                except SystemExit:
                    continue
            raise AssertionError(f"{argv} should require --output")
        return "--output still required on record-content commands"

    def _summary_receipt_note() -> str:
        result = {
            "requested_pmids": ["1"], "found_pmids": ["1"], "missing_pmids": [],
            "records": [{"pmid": "1"}],
            "pre_command_hook": {"name": "pre_pubmed_command", "ok": True, "issues": []},
        }
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "rc.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                emit_record_content_receipt("fetch", result, argparse.Namespace(output=str(out), summary=True))
            receipt = json.loads(buf.getvalue())
            assert receipt.get("stdout_role") == "receipt_only"
            assert "tolerated_flag" in receipt
            assert out.exists()
        return "receipt notes tolerated --summary; full JSON still saved"

    def _encoding_tolerance() -> str:
        sample = "café tumour[tiab] OR ulcer*[tiab]"
        done: list[str] = []
        with tempfile.TemporaryDirectory() as d:
            for enc, label in (("utf-8-sig", "utf-8-bom"), ("utf-16", "utf-16")):
                p = Path(d) / f"{label}.txt"
                p.write_bytes(sample.encode(enc))
                assert read_text_source(str(p)).strip() == sample, label
                done.append(label)
            p = Path(d) / "crlf.txt"
            p.write_bytes(sample.replace(" ", "\r\n").encode("utf-8"))
            got = read_text_source(str(p))
            assert "café" in got and "tumour[tiab]" in got
            done.append("crlf")
        return "decodes " + ", ".join(done)

    def _retry_visibility() -> str:
        assert "retries_performed" in NcbiClient().metadata()
        return "metadata() exposes retries_performed"

    record("tolerated_summary_parse", _summary_tolerated_parse)
    record("record_output_required", _output_still_required)
    record("tolerated_summary_receipt", _summary_receipt_note)
    record("query_encoding_tolerance", _encoding_tolerance)
    record("ncbi_retry_visibility", _retry_visibility)

    return {
        "operation": "selftest",
        "ok": all(c["ok"] for c in checks),
        "network": False,
        "passed": sum(1 for c in checks if c["ok"]),
        "total": len(checks),
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PubMed E-utilities helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Run PubMed ESearch.")
    add_query_input_arguments(search_parser)
    search_parser.add_argument("--retmax", type=int, default=20)
    search_parser.add_argument("--retstart", type=int, default=0)
    search_parser.add_argument("--sort", choices=["pub_date", "Author", "JournalName", "relevance"], default=None)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch PubMed records by PMID.")
    fetch_parser.add_argument("--pmids", nargs="+", required=True)
    add_record_output_arguments(fetch_parser)

    related_parser = subparsers.add_parser(
        "related",
        help="Expand seed PMIDs into a candidate relevant set via PubMed eLink (similar articles, cited-by, references).",
    )
    related_parser.add_argument("--pmids", nargs="+", required=True, help="Seed PMIDs to expand.")
    related_parser.add_argument(
        "--links",
        default="similar",
        help="Comma-separated link types to follow: similar, citedin, refs (default: similar).",
    )
    related_parser.add_argument(
        "--max-per-seed",
        type=int,
        default=RELATED_MAX_PER_SEED,
        help="Maximum neighbors kept per seed per link type (default: %(default)s).",
    )
    related_parser.add_argument(
        "--max-total",
        type=int,
        default=RELATED_MAX_TOTAL,
        help="Hard cap on the deduplicated candidate set (default: %(default)s).",
    )

    mine_parser = subparsers.add_parser("mine", help="Fetch seed PMIDs and mine MeSH, keywords, phrases, and acronyms.")
    mine_parser.add_argument("--pmids", nargs="+", required=True)
    mine_parser.add_argument("--strategy", help="Optional existing strategy text for gap checks.")
    mine_parser.add_argument("--strategy-file", help="Optional UTF-8 strategy file for gap checks.")
    mine_parser.add_argument("--max-phrases", type=int, default=80)
    mine_parser.add_argument("--max-acronyms", type=int, default=60)
    mine_parser.add_argument("--min-phrase-count", type=int, default=1)
    add_record_output_arguments(mine_parser)

    term_rank_parser = subparsers.add_parser(
        "term-rank",
        help="Rank tiab/MeSH terms by enrichment in a relevant/seed set vs. PubMed background.",
    )
    term_rank_source = term_rank_parser.add_mutually_exclusive_group(required=True)
    term_rank_source.add_argument("--pmids", nargs="+", help="Relevant/seed PMIDs to fetch and analyse.")
    term_rank_source.add_argument("--mine-json", help="JSON output from the mine command; its found PMIDs become the relevant set.")
    term_rank_source.add_argument("--relevant-query-file", help="UTF-8 file with a PubMed query defining a pilot relevant set. Use '-' for stdin.")
    term_rank_parser.add_argument(
        "--exclude-pmids",
        nargs="*",
        default=None,
        help="PMIDs to drop from the resolved relevant set (e.g. seeds excluded at pre-gate triage as out-of-scope/retracted). Combine with --mine-json to reuse mined seeds minus the excluded ones.",
    )
    term_rank_parser.add_argument(
        "--only-pmids",
        nargs="*",
        default=None,
        help="Restrict the resolved relevant set to these accepted PMIDs (whitelist/intersection).",
    )
    term_rank_parser.add_argument("--strategy", help="Optional existing strategy text to flag terms already present.")
    term_rank_parser.add_argument("--strategy-file", help="Optional UTF-8 strategy file to flag terms already present.")
    term_rank_parser.add_argument(
        "--fields",
        default="tiab,mesh",
        help="Comma-separated scoring layers: only tiab and/or mesh (default both). Phrases, "
        "acronyms, and author keywords are scored within tiab; there is no separate "
        "keywords/acronym/phrase field.",
    )
    term_rank_parser.add_argument(
        "--max-terms",
        type=int,
        default=DEFAULT_TERM_RANK_MAX_TERMS,
        help="Maximum candidate terms to score with a PubMed background count (caps API calls).",
    )
    term_rank_parser.add_argument(
        "--relevant-retmax",
        type=int,
        default=TERM_RANK_RELEVANT_QUERY_CAP,
        help="Maximum records to fetch when --relevant-query-file is used.",
    )
    term_rank_parser.add_argument(
        "--pubmed-total",
        type=int,
        default=PUBMED_TOTAL_ESTIMATE,
        help="Approximate PubMed corpus size used as the lift denominator.",
    )

    sample_parser = subparsers.add_parser("sample", help="Search PubMed and fetch a small sample.")
    add_query_input_arguments(sample_parser)
    sample_parser.add_argument("--retmax", type=int, default=5)
    sample_parser.add_argument("--sort", choices=["pub_date", "Author", "JournalName", "relevance"], default=None)
    add_record_output_arguments(sample_parser)

    term_diff_parser = subparsers.add_parser(
        "term-diff",
        help="Bramer reciprocal gap analysis for one concept block: run (MeSH) NOT (tiab) and (tiab) NOT (MeSH) "
        "to surface [tiab] terms missed by the MeSH layer and MeSH/indexing gaps missed by free text.",
    )
    term_diff_parser.add_argument("--mesh-query", help="The block's controlled-vocabulary (MeSH) sub-query.")
    term_diff_parser.add_argument("--mesh-query-file", help="UTF-8 file with the MeSH sub-query. Use '-' for stdin.")
    term_diff_parser.add_argument("--tiab-query", help="The block's free-text ([tiab]) sub-query.")
    term_diff_parser.add_argument("--tiab-query-file", help="UTF-8 file with the [tiab] sub-query. Use '-' for stdin.")
    term_diff_parser.add_argument("--retmax", type=int, default=15, help="Records fetched per differential side for inspection (default: %(default)s).")
    term_diff_parser.add_argument("--sort", choices=["pub_date", "Author", "JournalName", "relevance"], default=None)
    add_record_output_arguments(term_diff_parser)

    validate_parser = subparsers.add_parser("validate", help="Check whether a query retrieves supplied seed PMIDs.")
    add_query_input_arguments(validate_parser)
    validate_parser.add_argument("--pmids", nargs="+", required=True)

    recall_parser = subparsers.add_parser(
        "recall",
        help="Estimate relative recall of a strategy against a benchmark relevant set, with per-block miss diagnosis.",
    )
    add_query_input_arguments(recall_parser)
    recall_source = recall_parser.add_mutually_exclusive_group(required=True)
    recall_source.add_argument("--benchmark-pmids", nargs="+", help="Benchmark relevant PMIDs (e.g. an independent gold standard).")
    recall_source.add_argument("--benchmark-json", help="JSON from related/mine, or a bare PMID list, defining the benchmark set.")
    recall_source.add_argument("--benchmark-query-file", help="UTF-8 file with a query defining the benchmark set. Use '-' for stdin.")
    recall_source.add_argument(
        "--pilot-query-file",
        help="No-seed convenience: UTF-8 file with a high-precision pilot query. Its top results are the benchmark "
        "anchors; add --auto-expand to expand them via `related` into a strategy-independent candidate set. Use '-' for stdin.",
    )
    recall_parser.add_argument(
        "--auto-expand",
        action="store_true",
        help="With --pilot-query-file, expand the pilot anchors via PubMed similar/citation links (the recommended, "
        "less-circular benchmark) instead of using the pilot's own hits directly.",
    )
    recall_parser.add_argument(
        "--pilot-retmax",
        type=int,
        default=30,
        help="With --pilot-query-file, maximum pilot anchors to retrieve (default: %(default)s).",
    )
    recall_parser.add_argument(
        "--links",
        default="similar,citedin,refs",
        help="With --pilot-query-file --auto-expand, comma-separated link types to expand: similar, citedin, refs (default: %(default)s).",
    )
    recall_parser.add_argument(
        "--max-per-seed",
        type=int,
        default=RELATED_MAX_PER_SEED,
        help="With --auto-expand, max neighbors kept per anchor per link type (default: %(default)s).",
    )
    recall_parser.add_argument(
        "--max-total",
        type=int,
        default=RELATED_MAX_TOTAL,
        help="With --auto-expand, hard cap on the deduplicated candidate set (default: %(default)s).",
    )
    recall_parser.add_argument(
        "--anchor-sample-output",
        help="With --pilot-query-file, also fetch a small sample of the pilot anchors to this JSON path so they can be inspected (anchors are probably-relevant, not validated).",
    )
    recall_parser.add_argument(
        "--min-seed-overlap",
        type=int,
        default=1,
        help="When --benchmark-json or --pilot-query-file --auto-expand resolves a related candidate set, keep only candidates with at least this seed_overlap_count (default: %(default)s).",
    )
    recall_parser.add_argument(
        "--benchmark-retmax",
        type=int,
        default=BENCHMARK_QUERY_CAP,
        help="Maximum records fetched when --benchmark-query-file is used (default: %(default)s).",
    )
    recall_parser.add_argument("--blocks-file", help="JSON list of {label, query} concept blocks (or a {label: query} map) for per-block miss diagnosis.")
    recall_parser.add_argument(
        "--exclude-pmids",
        nargs="*",
        default=None,
        help="PMIDs to drop from the resolved benchmark set (e.g. seeds excluded at pre-gate triage as out-of-scope/retracted, or noise from a related expansion). Combine with --benchmark-json to reuse a candidate set minus the excluded ones.",
    )
    recall_parser.add_argument(
        "--only-pmids",
        nargs="*",
        default=None,
        help="Restrict the resolved benchmark set to these accepted PMIDs (whitelist/intersection).",
    )

    batch_parser = subparsers.add_parser("batch", help="Run multiple PubMed ESearch count checks.")
    batch_parser.add_argument("queries_file", help="JSON or text batch file. Use '-' to read from stdin.")
    batch_parser.add_argument("--retmax", type=int, default=0)
    batch_parser.add_argument("--sort", choices=["pub_date", "Author", "JournalName", "relevance"], default=None)

    variants_parser = subparsers.add_parser("variants", help="Compare labelled sensitive/focused/precision strategy variants.")
    variants_parser.add_argument("variants_file", help="JSON or text variants file. Use '-' to read from stdin.")
    variants_parser.add_argument("--retmax", type=int, default=0)
    variants_parser.add_argument("--sort", choices=["pub_date", "Author", "JournalName", "relevance"], default=None)
    variants_parser.add_argument("--baseline-label", help="Variant label to use as the comparison baseline. Defaults to file baseline/main or first variant.")
    variants_parser.add_argument("--seed-pmids", nargs="+", help="Optional known relevant PMIDs to validate against each variant.")
    variants_parser.add_argument("--labelled-samples", help="Optional JSON file keyed by variant label with PMID-level relevance labels for pilot precision/NNR estimates.")

    audit_parser = subparsers.add_parser("audit-workbook", help="Create an XLSX audit workbook from mine, variants, and/or term-rank JSON outputs.")
    audit_parser.add_argument("--mine-json", help="JSON output from the mine command.")
    audit_parser.add_argument("--variants-json", help="JSON output from the variants command.")
    audit_parser.add_argument("--term-rank-json", help="JSON output from the term-rank command.")
    audit_parser.add_argument("--output", required=True, help="Path for the .xlsx workbook to create.")

    scaffold_parser = subparsers.add_parser(
        "audit-scaffold",
        help="Build a partial audit JSON from saved tool outputs + run_manifest.json (mechanical fields filled; judgment fields left as placeholders for audit_markdown.py).",
    )
    scaffold_parser.add_argument("--output", required=True, help="Path for the audit JSON to create (then render with audit_markdown.py).")
    scaffold_parser.add_argument("--manifest", help="run_manifest.json for discovery (CLI checks, evidence files, search dates).")
    scaffold_parser.add_argument("--final-search-json", help="Saved --output JSON of the delivered/post-hygiene search (result count + ATM translation).")
    scaffold_parser.add_argument("--strategy-file", help="UTF-8 file with the final PubMed strategy text.")
    scaffold_parser.add_argument("--validate-json", help="Saved validate --output JSON (seed retrieved/missed).")
    scaffold_parser.add_argument("--variants-json", help="Saved variants --output JSON (chosen/focused variant).")
    scaffold_parser.add_argument("--seed-fetch-json", help="Saved fetch --output JSON from pre-gate seed triage.")
    scaffold_parser.add_argument("--seed-mine-json", help="Saved mine --output JSON from pre-gate seed mining.")
    scaffold_parser.add_argument("--related-json", help="Saved related --output JSON for seed-set expansion.")
    scaffold_parser.add_argument("--recall-json", help="Saved recall --output JSON for relative-recall estimation.")
    scaffold_parser.add_argument("--blocks-file", help="JSON list of {label, query} concept blocks (or a {label: query} map) to populate concept_blocks for the numbered line set; counts are matched from labelled manifest search entries.")
    scaffold_parser.add_argument("--audit-workbook", help="Path of an exported .xlsx audit workbook, if any.")
    scaffold_parser.add_argument("--topic-slug", default="", help="Topic slug for the audit title (defaults to the manifest topic_slug).")
    scaffold_parser.add_argument("--date-searched", help="Override audit date searched (YYYY-MM-DD), useful for local/reporting-date alignment.")
    scaffold_parser.add_argument(
        "--seed-status",
        choices=["yes", "no", "unknown"],
        default="unknown",
        help="Seed status when no --validate-json is given. Default: unknown (emit a placeholder rather than guess no-seed).",
    )
    scaffold_parser.add_argument(
        "--if-exists",
        choices=["fail", "suffix", "overwrite"],
        default="fail",
        help="How to handle an existing --output. Default: fail (protects an audit you have already filled in).",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Check NCBI environment settings and run a tiny PubMed test.")
    doctor_parser.add_argument("--test-query", default="asthma[tiab]")

    subparsers.add_parser("selftest", help="Run offline robustness self-checks (no network).")

    for compact_parser in (
        search_parser,
        related_parser,
        term_rank_parser,
        validate_parser,
        recall_parser,
        batch_parser,
        variants_parser,
    ):
        add_compact_output_arguments(compact_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = NcbiClient()
    preflight: dict[str, object] | None = None

    try:
        if args.command == "search":
            query = resolve_query(args, parser)
            preflight = pre_command_hook(client, args, query=query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = esearch(client, query, args.retmax, args.retstart, args.sort)
            emit(args.command, attach_hook(result, preflight), args)
        elif args.command == "fetch":
            preflight = pre_command_hook(client, args)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            emit_record_content_receipt(args.command, attach_hook(efetch(client, args.pmids), preflight), args)
        elif args.command == "related":
            links = parse_related_links(args.links, parser)
            preflight = pre_command_hook(client, args)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = related_pmids(
                client,
                args.pmids,
                links=links,
                max_per_seed=max(1, args.max_per_seed),
                max_total=max(1, args.max_total),
            )
            emit(args.command, attach_hook(result, preflight), args)
        elif args.command == "mine":
            if args.strategy and args.strategy_file:
                parser.error("Use only one of --strategy or --strategy-file.")
            strategy_text = args.strategy or ""
            if args.strategy_file:
                strategy_text = read_text_source(args.strategy_file)
            preflight = pre_command_hook(client, args)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = mine_seed_pmids(
                client,
                args.pmids,
                strategy_text=strategy_text,
                max_phrases=max(0, args.max_phrases),
                max_acronyms=max(0, args.max_acronyms),
                min_phrase_count=max(1, args.min_phrase_count),
            )
            emit_record_content_receipt(args.command, attach_hook(result, preflight), args)
        elif args.command == "term-rank":
            if args.strategy and args.strategy_file:
                parser.error("Use only one of --strategy or --strategy-file.")
            fields = parse_term_rank_fields(args.fields, parser)
            strategy_text = args.strategy or ""
            if args.strategy_file:
                strategy_text = read_text_source(args.strategy_file)
            pmids: list[str] = []
            relevant_query: str | None = None
            if args.pmids:
                pmids = [str(pmid) for pmid in args.pmids]
            elif args.mine_json:
                mine_payload = load_json_file(args.mine_json)
                pmids = [
                    str(pmid)
                    for pmid in (mine_payload.get("found_pmids") or mine_payload.get("requested_pmids") or [])
                ]
            else:
                relevant_query = normalize_query(read_text_source(args.relevant_query_file))
                if not relevant_query:
                    parser.error("Relevant query file is empty.")
            preflight = pre_command_hook(client, args, query=relevant_query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            if relevant_query is not None:
                search_result = esearch(client, relevant_query, max(1, args.relevant_retmax), 0, None)
                pmids = [str(pmid) for pmid in search_result.get("pmids", [])]
            exclude_list = [str(pmid) for pmid in (args.exclude_pmids or [])]
            only_list = [str(pmid) for pmid in (args.only_pmids or [])]
            pre_filter = dedup_preserving_order([str(pmid) for pmid in pmids])
            pmids, _removed = filter_pmids(pmids, only=only_list or None, exclude=exclude_list or None)
            exclude_set = set(exclude_list)
            excluded_present = [pmid for pmid in pre_filter if pmid in exclude_set]
            if not pmids:
                write_json({"error": "No relevant PMIDs resolved for term ranking.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 1
            fetch_result = efetch(client, pmids)
            result = term_rank(
                client,
                list(fetch_result.get("records", [])),
                fields=fields,
                max_terms=max(1, args.max_terms),
                strategy_text=strategy_text,
                pubmed_total=args.pubmed_total,
            )
            result["relevant_pmids"] = pmids
            if excluded_present:
                result["excluded_pmids"] = excluded_present
            emit(args.command, attach_hook(result, preflight), args)
        elif args.command == "sample":
            query = resolve_query(args, parser)
            preflight = pre_command_hook(client, args, query=query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = sample(client, query, args.retmax, args.sort)
            emit_record_content_receipt(args.command, attach_hook(result, preflight), args)
        elif args.command == "term-diff":
            mesh_query = resolve_named_query(args.mesh_query, args.mesh_query_file, "mesh", parser)
            tiab_query = resolve_named_query(args.tiab_query, args.tiab_query_file, "tiab", parser)
            preflight = pre_command_hook(
                client, args, queries=[{"label": "mesh", "query": mesh_query}, {"label": "tiab", "query": tiab_query}]
            )
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = term_diff(client, mesh_query, tiab_query, max(1, args.retmax), args.sort)
            emit_record_content_receipt(args.command, attach_hook(result, preflight), args)
        elif args.command == "validate":
            query = resolve_query(args, parser)
            preflight = pre_command_hook(client, args, query=query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = validate(client, query, args.pmids)
            emit(args.command, attach_hook(result, preflight), args)
        elif args.command == "recall":
            query = resolve_query(args, parser)
            blocks = None
            if args.blocks_file:
                raw_blocks = load_benchmark_or_blocks_json(args.blocks_file)
                validate_recall_blocks(raw_blocks)
                blocks = parse_variant_items(raw_blocks)
            if args.auto_expand and not args.pilot_query_file:
                parser.error("--auto-expand only applies to --pilot-query-file.")
            benchmark_query: str | None = None
            pilot_query: str | None = None
            pilot_meta: dict[str, object] | None = None
            benchmark_source = ""
            benchmark_seed_pmids: list[str] = []
            if args.benchmark_pmids:
                benchmark_seed_pmids = [str(pmid) for pmid in args.benchmark_pmids]
                benchmark_source = "benchmark-pmids"
            elif args.benchmark_json:
                payload = load_benchmark_or_blocks_json(args.benchmark_json)
                benchmark_seed_pmids = extract_benchmark_pmids(payload, min_seed_overlap=max(0, args.min_seed_overlap))
                assert_numeric_pmids(benchmark_seed_pmids, source=f"--benchmark-json {args.benchmark_json}")
                benchmark_source = f"benchmark-json:{args.benchmark_json}"
            elif args.benchmark_query_file:
                benchmark_query = normalize_query(read_text_source(args.benchmark_query_file))
                if not benchmark_query:
                    parser.error("Benchmark query file is empty.")
                benchmark_source = "benchmark-query"
            else:
                pilot_query = normalize_query(read_text_source(args.pilot_query_file))
                if not pilot_query:
                    parser.error("Pilot query file is empty.")
                benchmark_source = (
                    f"pilot-expansion:{args.pilot_query_file}" if args.auto_expand else f"pilot-query:{args.pilot_query_file}"
                )
            scan_queries: list[dict[str, object]] = [{"label": "strategy", "query": query}]
            if benchmark_query:
                scan_queries.append({"label": "benchmark-query", "query": benchmark_query})
            if pilot_query:
                scan_queries.append({"label": "pilot-query", "query": pilot_query})
            for block in blocks or []:
                scan_queries.append({"label": str(block.get("label", "")), "query": str(block.get("query", ""))})
            preflight = pre_command_hook(client, args, query=query, queries=scan_queries)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            if benchmark_query is not None:
                benchmark_search = esearch(client, benchmark_query, max(1, args.benchmark_retmax), 0, None)
                benchmark_seed_pmids = [str(pmid) for pmid in benchmark_search.get("pmids", [])]
            if pilot_query is not None:
                pilot_search = esearch(client, pilot_query, max(1, args.pilot_retmax), 0, None)
                anchors = dedup_preserving_order([str(pmid) for pmid in pilot_search.get("pmids", [])])
                if not anchors:
                    write_json({"error": "Pilot query returned no anchors for no-seed recall estimation.", "pre_command_hook": preflight, "request_info": client.metadata()})
                    return 1
                pilot_meta = {
                    "pilot_query_file": args.pilot_query_file,
                    "auto_expand": bool(args.auto_expand),
                    "anchor_count": len(anchors),
                    "anchors": anchors[:50],
                    "note": (
                        "Pilot anchors are probably-relevant, not validated — inspect them before trusting this benchmark. "
                        "No-seed recall is a heuristic, not absolute search sensitivity."
                    ),
                }
                if args.anchor_sample_output:
                    anchor_records = efetch(client, anchors[: min(len(anchors), 10)])
                    Path(args.anchor_sample_output).write_text(json.dumps(anchor_records, indent=2), encoding="utf-8")
                    pilot_meta["anchor_sample_output"] = args.anchor_sample_output
                if args.auto_expand:
                    links = parse_related_links(args.links, parser)
                    related_result = related_pmids(
                        client,
                        anchors,
                        links=links,
                        max_per_seed=max(1, args.max_per_seed),
                        max_total=max(1, args.max_total),
                    )
                    benchmark_seed_pmids = extract_benchmark_pmids(related_result, min_seed_overlap=max(0, args.min_seed_overlap))
                    pilot_meta["links_used"] = links
                    pilot_meta["candidate_count"] = len(benchmark_seed_pmids)
                else:
                    benchmark_seed_pmids = anchors
            exclude_list = [str(pmid) for pmid in (args.exclude_pmids or [])]
            only_list = [str(pmid) for pmid in (args.only_pmids or [])]
            pre_filter = dedup_preserving_order([str(pmid) for pmid in benchmark_seed_pmids])
            benchmark_seed_pmids, _removed = filter_pmids(benchmark_seed_pmids, only=only_list or None, exclude=exclude_list or None)
            exclude_set = set(exclude_list)
            excluded_present = [pmid for pmid in pre_filter if pmid in exclude_set]
            if not benchmark_seed_pmids:
                write_json({"error": "No benchmark PMIDs resolved for relative-recall estimation.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 1
            result = relative_recall(
                client,
                query,
                benchmark_seed_pmids,
                benchmark_source=benchmark_source,
                blocks=blocks,
            )
            if excluded_present:
                result["excluded_pmids"] = excluded_present
            if pilot_meta is not None:
                result["pilot_expansion"] = pilot_meta
            emit(args.command, attach_hook(result, preflight), args)
        elif args.command == "batch":
            queries = parse_batch_queries(read_text_source(args.queries_file))
            preflight = pre_command_hook(client, args, queries=queries)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = batch_search(client, queries, args.retmax, args.sort)
            emit(args.command, attach_hook(result, preflight), args)
        elif args.command == "variants":
            queries, file_baseline = parse_variant_queries(read_text_source(args.variants_file))
            labelled_samples = parse_labelled_samples(read_text_source(args.labelled_samples)) if args.labelled_samples else None
            preflight = pre_command_hook(client, args, queries=queries)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = compare_variants(
                client,
                queries,
                retmax=max(0, args.retmax),
                sort=args.sort,
                baseline_label=args.baseline_label or file_baseline,
                seed_pmids=args.seed_pmids,
                labelled_samples=labelled_samples,
            )
            emit(args.command, attach_hook(result, preflight), args)
        elif args.command == "audit-workbook":
            if not args.mine_json and not args.variants_json and not args.term_rank_json:
                parser.error("Provide --mine-json, --variants-json, --term-rank-json, or a combination.")
            mine_data = load_json_file(args.mine_json) if args.mine_json else None
            variants_data = load_json_file(args.variants_json) if args.variants_json else None
            term_rank_data = load_json_file(args.term_rank_json) if args.term_rank_json else None
            write_json(
                build_audit_workbook(
                    output_path=args.output,
                    mine_data=mine_data,
                    variants_data=variants_data,
                    mine_source=args.mine_json or "",
                    variants_source=args.variants_json or "",
                    term_rank_data=term_rank_data,
                    term_rank_source=args.term_rank_json or "",
                )
            )
        elif args.command == "audit-scaffold":
            write_json(run_audit_scaffold(args))
        elif args.command == "doctor":
            test_query = normalize_query(args.test_query)
            if not test_query:
                parser.error("--test-query is empty.")
            preflight = pre_command_hook(client, args, query=test_query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            write_json(attach_hook(doctor(client, test_query), preflight))
        elif args.command == "selftest":
            report = run_selftest()
            write_json(report)
            return 0 if report["ok"] else 1
        else:
            parser.error(f"Unknown command: {args.command}")
    except PubMedError as exc:
        data: dict[str, object] = {"error": str(exc), "request_info": client.metadata()}
        if preflight is not None:
            data["pre_command_hook"] = preflight
        write_json(data)
        return 1
    except (ET.ParseError, json.JSONDecodeError) as exc:
        data = {"error": f"Could not parse NCBI response: {exc}", "request_info": client.metadata()}
        if preflight is not None:
            data["pre_command_hook"] = preflight
        write_json(data)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
