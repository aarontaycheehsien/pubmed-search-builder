#!/usr/bin/env python3
"""Small PubMed E-utilities helper for the pubmed-search-builder skill."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_EMAIL = ""
DEFAULT_TOOL = "codex-search-strategy-check"
INLINE_QUERY_WARNING_LENGTH = 1400
HUGE_RETMAX_WARNING = 1000
LOG_PATH_ENV = "PUBMED_SEARCH_BUILDER_LOG"
LOG_DISABLED_ENV = "PUBMED_SEARCH_BUILDER_LOG_DISABLED"


class PubMedError(Exception):
    pass


def read_env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
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


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_text_source(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


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


def pre_command_hook(
    client: "NcbiClient",
    args: argparse.Namespace,
    *,
    query: str | None = None,
    queries: list[dict[str, str]] | None = None,
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
        elif args.command in {"search", "batch"} and retmax > 0:
            add_hook_issue(
                issues,
                "info",
                "count_only_preferred",
                "Use --retmax 0 when you only need block counts; retmax > 0 is appropriate for sample inspection.",
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
    return {
        "query": query,
        "count": int(result.get("count", 0)),
        "retmax": int(result.get("retmax", retmax)),
        "retstart": int(result.get("retstart", retstart)),
        "pmids": result.get("idlist", []),
        "query_translation": result.get("querytranslation", ""),
        "translations": result.get("translationset", []),
        "warnings": result.get("warninglist", {}),
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
        "request_info": client.metadata(),
    }


def batch_search(client: NcbiClient, queries: list[dict[str, str]], retmax: int, sort: str | None) -> dict[str, object]:
    results = []
    for item in queries:
        search_result = esearch(client, item["query"], retmax=retmax, retstart=0, sort=sort)
        results.append(
            {
                "label": item["label"],
                "query": item["query"],
                "count": search_result.get("count", 0),
                "retmax": search_result.get("retmax", retmax),
                "pmids": search_result.get("pmids", []),
                "query_translation": search_result.get("query_translation", ""),
                "warnings": search_result.get("warnings", {}),
            }
        )
    return {
        "query_count": len(results),
        "results": results,
        "request_info": client.metadata(),
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
        "request_info": client.metadata(),
    }


def default_log_path() -> Path:
    override = read_env(LOG_PATH_ENV, "")
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override)))
    return Path.home() / ".codex" / "pubmed-search-builder" / "logs" / "pubmed-search-log.jsonl"


def log_disabled() -> bool:
    return truthy(read_env(LOG_DISABLED_ENV, ""))


def search_log_payload(event_type: str, data: dict[str, object], client: NcbiClient) -> dict[str, object]:
    if event_type == "sample":
        search_data = data.get("search", {})
        if isinstance(search_data, dict):
            return {
                "event": event_type,
                "query": search_data.get("query", ""),
                "count": search_data.get("count", 0),
                "query_translation": search_data.get("query_translation", ""),
                "warnings": search_data.get("warnings", {}),
                "retmax": search_data.get("retmax", 0),
                "pmids": search_data.get("pmids", []),
                "request_info": client.metadata(),
            }
    if event_type == "batch":
        return {
            "event": event_type,
            "query_count": data.get("query_count", 0),
            "results": [
                {
                    "label": item.get("label", ""),
                    "query": item.get("query", ""),
                    "count": item.get("count", 0),
                    "query_translation": item.get("query_translation", ""),
                    "warnings": item.get("warnings", {}),
                }
                for item in data.get("results", [])
                if isinstance(item, dict)
            ],
            "request_info": client.metadata(),
        }
    if event_type == "validate":
        return {
            "event": event_type,
            "query": data.get("query", ""),
            "validation_query": data.get("validation_query", ""),
            "count": data.get("search_count", 0),
            "query_translation": data.get("query_translation", ""),
            "warnings": data.get("warnings", {}),
            "provided_pmids": data.get("provided_pmids", []),
            "retrieved_pmids": data.get("retrieved_pmids", []),
            "missed_pmids": data.get("missed_pmids", []),
            "request_info": client.metadata(),
        }
    return {
        "event": event_type,
        "query": data.get("query", ""),
        "count": data.get("count", 0),
        "query_translation": data.get("query_translation", ""),
        "warnings": data.get("warnings", {}),
        "retmax": data.get("retmax", 0),
        "pmids": data.get("pmids", []),
        "request_info": client.metadata(),
    }


def post_search_log(event_type: str, data: dict[str, object], client: NcbiClient) -> dict[str, object]:
    if log_disabled():
        return {"name": "post_pubmed_search_log", "written": False, "reason": "disabled"}

    path = default_log_path()
    entry = search_log_payload(event_type, data, client)
    entry["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    entry["api_key_used"] = bool(client.api_key)
    entry["rate_limit_per_second"] = client.rate_limit_per_second

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except OSError as exc:
        return {"name": "post_pubmed_search_log", "written": False, "path": str(path), "error": str(exc)}

    return {"name": "post_pubmed_search_log", "written": True, "path": str(path)}


def write_json(data: dict[str, object]) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
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
            result["post_search_log"] = post_search_log("search", result, client)
            write_json(attach_hook(result, preflight))
        elif args.command == "fetch":
            preflight = pre_command_hook(client, args)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            write_json(attach_hook(efetch(client, args.pmids), preflight))
        elif args.command == "sample":
            query = resolve_query(args, parser)
            preflight = pre_command_hook(client, args, query=query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = sample(client, query, args.retmax, args.sort)
            result["post_search_log"] = post_search_log("sample", result, client)
            write_json(attach_hook(result, preflight))
        elif args.command == "validate":
            query = resolve_query(args, parser)
            preflight = pre_command_hook(client, args, query=query)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = validate(client, query, args.pmids)
            result["post_search_log"] = post_search_log("validate", result, client)
            write_json(attach_hook(result, preflight))
        elif args.command == "batch":
            queries = parse_batch_queries(read_text_source(args.queries_file))
            preflight = pre_command_hook(client, args, queries=queries)
            if not preflight["ok"]:
                write_json({"error": "Pre-command hook blocked PubMed command.", "pre_command_hook": preflight, "request_info": client.metadata()})
                return 2
            result = batch_search(client, queries, args.retmax, args.sort)
            result["post_search_log"] = post_search_log("batch", result, client)
            write_json(attach_hook(result, preflight))
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
