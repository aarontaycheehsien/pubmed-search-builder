#!/usr/bin/env python3
"""Small PubMed E-utilities helper for the pubmed-search-builder skill."""

from __future__ import annotations

import argparse
import json
import os
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
INLINE_QUERY_WARNING_LENGTH = 1400
HUGE_RETMAX_WARNING = 1000
QUERY_TRANSLATION_MAX_ISSUES = 5
QUERY_TRANSLATION_EVIDENCE_LIMIT = 240
ATM_EXPANSION_RATIO_WARNING = 4.0
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
NO_LABELLED_SAMPLE_NOTE = "not estimable; no labelled sample supplied"
ZERO_RELEVANT_SAMPLE_NOTE = "undefined/infinite; zero relevant labelled records"
TRUE_RELEVANCE_VALUES = {"1", "true", "yes", "y", "relevant", "include", "included"}
FALSE_RELEVANCE_VALUES = {"0", "false", "no", "n", "irrelevant", "exclude", "excluded", "not relevant"}
SAMPLE_METADATA_KEYS = {"sample_description", "description", "method", "sampling_method", "note", "notes"}


class PubMedError(Exception):
    pass


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
            items = [{"label": str(label), "query": str(query)} for label, query in data.items()]
        elif isinstance(data, list):
            items = []
            for index, item in enumerate(data, start=1):
                if isinstance(item, str):
                    items.append({"label": f"query_{index}", "query": item})
                elif isinstance(item, dict):
                    query = item.get("query")
                    if query is None:
                        raise PubMedError(f"Batch item {index} is missing a query field.")
                    label = item.get("label") or item.get("name") or f"query_{index}"
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

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:2000]
            raise PubMedError(f"NCBI HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise PubMedError(f"NCBI request failed: {exc.reason}") from exc

        self._last_request = time.monotonic()
        return data

    def metadata(self) -> dict[str, object]:
        return {
            "tool": self.tool,
            "email_configured": bool(self.email),
            "api_key_used": bool(self.api_key),
            "rate_limit_per_second": self.rate_limit_per_second,
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
    return {
        "query": query,
        "count": int(result.get("count", 0)),
        "retmax": int(result.get("retmax", retmax)),
        "retstart": int(result.get("retstart", retstart)),
        "pmids": result.get("idlist", []),
        "query_translation": query_translation,
        "translations": translations,
        "warnings": warnings,
        "query_translation_hook": query_translation_drift_hook(query, query_translation, translations, warnings),
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
    return {
        "requested_pmids": pmids,
        "records": records,
        "request_info": client.metadata(),
    }


def sample(client: NcbiClient, query: str, retmax: int, sort: str | None) -> dict[str, object]:
    search_result = esearch(client, query, retmax=retmax, retstart=0, sort=sort)
    pmids = list(search_result.get("pmids", []))
    fetch_result = efetch(client, pmids) if pmids else {"requested_pmids": [], "records": []}
    return {
        "search": search_result,
        "records": fetch_result.get("records", []),
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
        query = item.get("query")
        if query is None:
            raise PubMedError(f"Variant item {index} is missing a query field.")
        label = label_override or item.get("label") or item.get("name") or f"query_{index}"
        source = item
    else:
        raise PubMedError(f"Variant item {index} must be a string or object.")

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
) -> dict[str, object]:
    sheets: list[tuple[str, list[list[object]]]] = []
    summary = [
        ["Field", "Value"],
        ["Generated UTC", datetime.now(timezone.utc).replace(microsecond=0).isoformat()],
        ["Mine JSON", mine_source or "not supplied"],
        ["Variants JSON", variants_source or "not supplied"],
        ["Seed records", mine_data.get("record_count", "") if mine_data else ""],
        ["Requested PMIDs", list_text(mine_data.get("requested_pmids", [])) if mine_data else ""],
        ["Found PMIDs", list_text(mine_data.get("found_pmids", [])) if mine_data else ""],
        ["Missing PMIDs", list_text(mine_data.get("missing_pmids", [])) if mine_data else ""],
        ["Variant count", variants_data.get("variant_count", "") if variants_data else ""],
        ["Baseline variant", variants_data.get("baseline_label", "") if variants_data else ""],
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

    output = Path(output_path)
    write_xlsx(output, sheets)
    return {
        "operation": "audit-workbook",
        "output": str(output),
        "sheet_count": len(sheets),
        "sheets": [name for name, _ in sheets],
    }


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


def add_query_input_arguments(command_parser: argparse.ArgumentParser) -> None:
    command_parser.add_argument("query", nargs="?", help="PubMed query string. Use '-' to read from stdin.")
    command_parser.add_argument("--query-file", help="Read the PubMed query from a UTF-8 text file. Use '-' for stdin.")
    command_parser.add_argument("--query-stdin", action="store_true", help="Read the PubMed query from stdin.")


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

    mine_parser = subparsers.add_parser("mine", help="Fetch seed PMIDs and mine MeSH, keywords, phrases, and acronyms.")
    mine_parser.add_argument("--pmids", nargs="+", required=True)
    mine_parser.add_argument("--strategy", help="Optional existing strategy text for gap checks.")
    mine_parser.add_argument("--strategy-file", help="Optional UTF-8 strategy file for gap checks.")
    mine_parser.add_argument("--max-phrases", type=int, default=80)
    mine_parser.add_argument("--max-acronyms", type=int, default=60)
    mine_parser.add_argument("--min-phrase-count", type=int, default=1)

    sample_parser = subparsers.add_parser("sample", help="Search PubMed and fetch a small sample.")
    add_query_input_arguments(sample_parser)
    sample_parser.add_argument("--retmax", type=int, default=5)
    sample_parser.add_argument("--sort", choices=["pub_date", "Author", "JournalName", "relevance"], default=None)

    validate_parser = subparsers.add_parser("validate", help="Check whether a query retrieves supplied seed PMIDs.")
    add_query_input_arguments(validate_parser)
    validate_parser.add_argument("--pmids", nargs="+", required=True)

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

    audit_parser = subparsers.add_parser("audit-workbook", help="Create an XLSX audit workbook from mine and/or variants JSON outputs.")
    audit_parser.add_argument("--mine-json", help="JSON output from the mine command.")
    audit_parser.add_argument("--variants-json", help="JSON output from the variants command.")
    audit_parser.add_argument("--output", required=True, help="Path for the .xlsx workbook to create.")

    doctor_parser = subparsers.add_parser("doctor", help="Check NCBI environment settings and run a tiny PubMed test.")
    doctor_parser.add_argument("--test-query", default="asthma[tiab]")

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
            write_json(attach_hook(result, preflight))
        elif args.command == "fetch":
            preflight = pre_command_hook(client, args)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            write_json(attach_hook(efetch(client, args.pmids), preflight))
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
            write_json(attach_hook(result, preflight))
        elif args.command == "sample":
            query = resolve_query(args, parser)
            preflight = pre_command_hook(client, args, query=query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = sample(client, query, args.retmax, args.sort)
            write_json(attach_hook(result, preflight))
        elif args.command == "validate":
            query = resolve_query(args, parser)
            preflight = pre_command_hook(client, args, query=query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = validate(client, query, args.pmids)
            write_json(attach_hook(result, preflight))
        elif args.command == "batch":
            queries = parse_batch_queries(read_text_source(args.queries_file))
            preflight = pre_command_hook(client, args, queries=queries)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = batch_search(client, queries, args.retmax, args.sort)
            write_json(attach_hook(result, preflight))
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
            write_json(attach_hook(result, preflight))
        elif args.command == "audit-workbook":
            if not args.mine_json and not args.variants_json:
                parser.error("Provide --mine-json, --variants-json, or both.")
            mine_data = load_json_file(args.mine_json) if args.mine_json else None
            variants_data = load_json_file(args.variants_json) if args.variants_json else None
            write_json(
                build_audit_workbook(
                    output_path=args.output,
                    mine_data=mine_data,
                    variants_data=variants_data,
                    mine_source=args.mine_json or "",
                    variants_source=args.variants_json or "",
                )
            )
        elif args.command == "doctor":
            test_query = normalize_query(args.test_query)
            if not test_query:
                parser.error("--test-query is empty.")
            preflight = pre_command_hook(client, args, query=test_query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            write_json(attach_hook(doctor(client, test_query), preflight))
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
