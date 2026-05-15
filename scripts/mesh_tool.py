#!/usr/bin/env python3
"""Small MeSH RDF helper for the pubmed-search-builder skill."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict


LOOKUP_BASE = "https://id.nlm.nih.gov/mesh/lookup"
SPARQL_URL = "https://id.nlm.nih.gov/mesh/sparql"


class MeshError(Exception):
    pass


def request_json(url: str, params: dict[str, str]) -> object:
    encoded = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{encoded}", method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "pubmed-search-builder/1.0")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise MeshError(f"MeSH HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise MeshError(f"MeSH request failed: {exc.reason}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MeshError(f"Could not parse MeSH JSON response: {exc}") from exc


def read_lines(path: str) -> list[str]:
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    values = []
    for line in text.splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            values.append(value)
    return values


def resource_id(resource: str) -> str:
    return resource.rstrip("/").rsplit("/", 1)[-1]


def sparql_bindings(data: object) -> list[dict[str, object]]:
    if not isinstance(data, dict):
        return []
    results = data.get("results", {})
    if not isinstance(results, dict):
        return []
    bindings = results.get("bindings", [])
    return bindings if isinstance(bindings, list) else []


def term_descriptor_candidates(term_resource: str, limit: int) -> list[dict[str, str]]:
    query = f"""
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?descriptor ?descriptorLabel ?concept ?conceptLabel WHERE {{
  ?concept ?p <{term_resource}> .
  OPTIONAL {{ ?concept rdfs:label ?conceptLabel . }}
  {{
    ?descriptor meshv:concept ?concept .
  }}
  UNION
  {{
    ?descriptor meshv:preferredConcept ?concept .
  }}
  ?descriptor rdfs:label ?descriptorLabel .
}}
LIMIT {limit}
""".strip()
    result = sparql(query, limit=limit, offset=0, inference=False)
    candidates = []
    for binding in sparql_bindings(result.get("results", {})):
        descriptor = binding.get("descriptor", {})
        descriptor_label = binding.get("descriptorLabel", {})
        concept = binding.get("concept", {})
        concept_label = binding.get("conceptLabel", {})
        if not isinstance(descriptor, dict):
            continue
        descriptor_uri = str(descriptor.get("value", ""))
        if not descriptor_uri:
            continue
        candidates.append(
            {
                "descriptor": resource_id(descriptor_uri),
                "resource": descriptor_uri,
                "label": str(descriptor_label.get("value", "")) if isinstance(descriptor_label, dict) else "",
                "concept": str(concept.get("value", "")) if isinstance(concept, dict) else "",
                "concept_label": str(concept_label.get("value", "")) if isinstance(concept_label, dict) else "",
            }
        )
    return candidates


def lookup(label: str, match: str, limit: int) -> dict[str, object]:
    data = request_json(
        f"{LOOKUP_BASE}/descriptor",
        {"label": label, "match": match, "limit": str(limit)},
    )
    return {"operation": "lookup", "label": label, "match": match, "results": data}


def terms(label: str, match: str, limit: int) -> dict[str, object]:
    data = request_json(
        f"{LOOKUP_BASE}/term",
        {"label": label, "match": match, "limit": str(limit)},
    )
    return {"operation": "terms", "label": label, "match": match, "results": data}


def details(descriptor: str, include: str) -> dict[str, object]:
    data = request_json(
        f"{LOOKUP_BASE}/details",
        {"descriptor": descriptor, "includes": include},
    )
    return {"operation": "details", "descriptor": descriptor, "include": include, "details": data}


def sweep(concept: str, variants: list[str], limit: int, include_details: bool) -> dict[str, object]:
    labels = []
    for value in [concept, *variants]:
        cleaned = " ".join(value.split())
        if cleaned and cleaned.lower() not in {item.lower() for item in labels}:
            labels.append(cleaned)

    matches = ["exact", "contains", "startswith"]
    raw_searches = []
    candidates: dict[str, dict[str, object]] = {}
    candidate_sources: defaultdict[str, list[str]] = defaultdict(list)

    for label in labels:
        for match in matches:
            descriptor_result = lookup(label, match, limit)
            raw_searches.append(
                {
                    "source": "descriptor",
                    "label": label,
                    "match": match,
                    "results": descriptor_result.get("results", []),
                }
            )
            for item in descriptor_result.get("results", []):
                if not isinstance(item, dict):
                    continue
                resource = str(item.get("resource", ""))
                if not resource:
                    continue
                descriptor_id = resource_id(resource)
                candidates.setdefault(
                    descriptor_id,
                    {
                        "descriptor": descriptor_id,
                        "resource": resource,
                        "label": item.get("label", ""),
                    },
                )
                candidate_sources[descriptor_id].append(f"descriptor:{match}:{label}")

            term_result = terms(label, match, limit)
            raw_searches.append(
                {
                    "source": "term",
                    "label": label,
                    "match": match,
                    "results": term_result.get("results", []),
                }
            )
            for item in term_result.get("results", []):
                if not isinstance(item, dict):
                    continue
                term_resource = str(item.get("resource", ""))
                descriptor_hits = []
                if term_resource:
                    descriptor_hits = term_descriptor_candidates(term_resource, limit=10)
                for descriptor_hit in descriptor_hits:
                    descriptor_id = descriptor_hit["descriptor"]
                    candidates.setdefault(
                        descriptor_id,
                        {
                            "descriptor": descriptor_id,
                            "resource": descriptor_hit["resource"],
                            "label": descriptor_hit["label"],
                        },
                    )
                    candidate_sources[descriptor_id].append(
                        f"term:{match}:{label}:{item.get('label', '')}"
                    )

    candidate_list = []
    for descriptor_id, candidate in sorted(candidates.items(), key=lambda item: str(item[1].get("label", "")).lower()):
        entry = dict(candidate)
        entry["sources"] = sorted(set(candidate_sources[descriptor_id]))
        if include_details:
            entry["details"] = details(descriptor_id, "terms,seealso,qualifiers").get("details", {})
        candidate_list.append(entry)

    return {
        "operation": "sweep",
        "concept": concept,
        "variants": variants,
        "matches_used": matches,
        "candidate_count": len(candidate_list),
        "candidates": candidate_list,
        "raw_searches": raw_searches,
        "review_required": [
            "Inspect each plausible candidate descriptor with details before selecting MeSH terms.",
            "Check entry terms for [tiab] expansion.",
            "Check related descriptors and tree context before deciding explosion/noexp.",
            "Test accepted and rejected candidate descriptors in PubMed with --retmax 0.",
            "Document rejected descriptors with reason: too broad, too narrow, wrong sense, obsolete, duplicate, or noisy.",
        ],
    }


def sparql(query: str, limit: int, offset: int, inference: bool) -> dict[str, object]:
    data = request_json(
        SPARQL_URL,
        {
            "query": query,
            "format": "JSON",
            "limit": str(limit),
            "offset": str(offset),
            "inference": "true" if inference else "false",
        },
    )
    return {
        "operation": "sparql",
        "query": query,
        "limit": limit,
        "offset": offset,
        "inference": inference,
        "results": data,
    }


def write_json(data: dict[str, object]) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MeSH RDF helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lookup_parser = subparsers.add_parser("lookup", help="Search MeSH descriptors by label.")
    lookup_parser.add_argument("--label", required=True)
    lookup_parser.add_argument("--match", choices=["exact", "contains", "startswith"], default="contains")
    lookup_parser.add_argument("--limit", type=int, default=10)

    details_parser = subparsers.add_parser("details", help="Fetch descriptor details.")
    details_parser.add_argument("--descriptor", required=True)
    details_parser.add_argument("--include", default="terms,seealso,qualifiers")

    terms_parser = subparsers.add_parser("terms", help="Search MeSH entry terms.")
    terms_parser.add_argument("--label", required=True)
    terms_parser.add_argument("--match", choices=["exact", "contains", "startswith"], default="contains")
    terms_parser.add_argument("--limit", type=int, default=10)

    sweep_parser = subparsers.add_parser("sweep", help="Aggressively search MeSH descriptors and entry terms for a concept plus variants.")
    sweep_parser.add_argument("--concept", required=True)
    sweep_parser.add_argument("--variant", action="append", default=[], help="Additional synonym/acronym/spelling/seed term. Repeat as needed.")
    sweep_parser.add_argument("--variants-file", help="Optional newline-delimited variants file. Use '-' for stdin.")
    sweep_parser.add_argument("--limit", type=int, default=20)
    sweep_parser.add_argument("--details", action="store_true", help="Fetch details for every candidate descriptor.")

    sparql_parser = subparsers.add_parser("sparql", help="Run a MeSH RDF SPARQL query.")
    sparql_parser.add_argument("query")
    sparql_parser.add_argument("--limit", type=int, default=100)
    sparql_parser.add_argument("--offset", type=int, default=0)
    sparql_parser.add_argument("--inference", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "lookup":
            write_json(lookup(args.label, args.match, args.limit))
        elif args.command == "details":
            write_json(details(args.descriptor, args.include))
        elif args.command == "terms":
            write_json(terms(args.label, args.match, args.limit))
        elif args.command == "sweep":
            variants = list(args.variant)
            if args.variants_file:
                variants.extend(read_lines(args.variants_file))
            write_json(sweep(args.concept, variants, args.limit, args.details))
        elif args.command == "sparql":
            write_json(sparql(args.query, args.limit, args.offset, args.inference))
        else:
            parser.error(f"Unknown command: {args.command}")
    except MeshError as exc:
        write_json({"error": str(exc)})
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
