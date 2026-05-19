#!/usr/bin/env python3
"""Small MeSH RDF helper for the pubmed-search-builder skill."""

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
from collections import defaultdict
from pathlib import Path


LOOKUP_BASE = "https://id.nlm.nih.gov/mesh/lookup"
MESH_BASE = "http://id.nlm.nih.gov/mesh/"
SPARQL_URL = "https://id.nlm.nih.gov/mesh/sparql"
DEFAULT_MAX_TERM_DESCRIPTOR_LOOKUPS = 40
DEFAULT_MAX_DETAIL_CANDIDATES = 30
DEFAULT_MAX_TREE_DESCENDANTS = 100
DEFAULT_MAX_TREE_SIBLINGS = 100
DEFAULT_EMAIL = ""
DEFAULT_TOOL = "codex-search-strategy-check"
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_RETRIES = 3
REQUEST_BACKOFF_SECONDS = 1.0
REQUEST_CACHE: dict[tuple[str, tuple[tuple[str, str], ...]], object] = {}
ENV_FILE_CACHE: dict[str, str] | None = None


class MeshError(Exception):
    pass


def parse_env_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
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


def mesh_user_agent() -> str:
    tool = read_env("NCBI_TOOL", DEFAULT_TOOL)
    email = read_env("NCBI_EMAIL", DEFAULT_EMAIL)
    user_agent = f"{tool}/1.0 pubmed-search-builder-mesh/1.0"
    if email:
        user_agent = f"{user_agent} ({email})"
    return user_agent


def retry_delay(attempt: int) -> float:
    return REQUEST_BACKOFF_SECONDS * (2**attempt)


def transient_http_error(exc: urllib.error.HTTPError) -> bool:
    return exc.code in {408, 429, 500, 502, 503, 504}


def request_json(url: str, params: dict[str, str]) -> object:
    cache_key = (url, tuple(sorted(params.items())))
    if cache_key in REQUEST_CACHE:
        return REQUEST_CACHE[cache_key]

    encoded = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{encoded}", method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", mesh_user_agent())

    last_error: Exception | None = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if not transient_http_error(exc) or attempt == REQUEST_RETRIES:
                body = exc.read().decode("utf-8", errors="replace")[:2000]
                attempts = attempt + 1
                raise MeshError(f"MeSH HTTP {exc.code} after {attempts} attempt(s): {body}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt == REQUEST_RETRIES:
                raise MeshError(f"MeSH request failed after {attempt + 1} attempt(s): {exc.reason}") from exc
        except TimeoutError as exc:
            last_error = exc
            if attempt == REQUEST_RETRIES:
                raise MeshError(f"MeSH request timed out after {attempt + 1} attempt(s): {exc}") from exc
        except OSError as exc:
            last_error = exc
            if attempt == REQUEST_RETRIES:
                raise MeshError(f"MeSH request failed after {attempt + 1} attempt(s): {exc}") from exc
        time.sleep(retry_delay(attempt))
    else:
        raise MeshError(f"MeSH request failed: {last_error}") from last_error

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MeshError(f"Could not parse MeSH JSON response: {exc}") from exc
    REQUEST_CACHE[cache_key] = data
    return data


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
    return resource.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def mesh_resource(identifier: str) -> str:
    if identifier.startswith("http://") or identifier.startswith("https://"):
        return identifier
    return f"{MESH_BASE}{identifier}"


def tree_number_value(value: str) -> str:
    return resource_id(value)


def binding_value(binding: dict[str, object], name: str) -> str:
    value = binding.get(name, {})
    if not isinstance(value, dict):
        return ""
    return str(value.get("value", ""))


def unique_strings(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


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


def first_value(values: list[str]) -> str:
    return values[0] if values else ""


def descriptor_record_sort_key(record: dict[str, object]) -> tuple[str, int, str, str]:
    tree_numbers = record.get("tree_numbers", [])
    first_tree = tree_numbers[0] if isinstance(tree_numbers, list) and tree_numbers else ""
    return (
        first_tree.split(".", 1)[0],
        first_tree.count("."),
        first_tree,
        normalized_label(record.get("label", "")),
    )


def add_tree_number(record: dict[str, object], tree_number: str) -> None:
    if not tree_number:
        return
    values = record.setdefault("tree_numbers", [])
    if isinstance(values, list) and tree_number not in values:
        values.append(tree_number)
        values.sort(key=lambda value: (str(value).split(".", 1)[0], str(value).count("."), str(value)))


def descriptor_records_from_bindings(
    bindings: list[dict[str, object]],
    descriptor_var: str,
    label_var: str,
    tree_var: str = "tree",
) -> list[dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for binding in bindings:
        descriptor_uri = binding_value(binding, descriptor_var)
        if not descriptor_uri:
            continue
        descriptor_id = resource_id(descriptor_uri)
        record = records.setdefault(
            descriptor_id,
            {
                "descriptor": descriptor_id,
                "resource": descriptor_uri,
                "label": binding_value(binding, label_var),
                "tree_numbers": [],
            },
        )
        if not record.get("label"):
            record["label"] = binding_value(binding, label_var)
        add_tree_number(record, tree_number_value(binding_value(binding, tree_var)))
    return sorted(records.values(), key=descriptor_record_sort_key)


def term_entries(detail_data: object, preferred: bool | None = None) -> list[dict[str, object]]:
    if not isinstance(detail_data, dict):
        return []
    terms_data = detail_data.get("terms", [])
    if not isinstance(terms_data, list):
        return []

    entries = []
    seen = set()
    for item in terms_data:
        if not isinstance(item, dict):
            continue
        is_preferred = bool(item.get("preferred"))
        if preferred is not None and is_preferred is not preferred:
            continue
        resource = str(item.get("resource", ""))
        label = str(item.get("label", ""))
        key = (resource, label)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "term": resource_id(resource) if resource else "",
                "resource": resource,
                "label": label,
                "preferred": is_preferred,
            }
        )
    return entries


def mesh_metadata(descriptor: str) -> dict[str, list[str]]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label ?type ?scopeNote ?annotation ?historyNote ?publicMeSHNote WHERE {{
  mesh:{descriptor} rdfs:label ?label .
  OPTIONAL {{ mesh:{descriptor} a ?type . }}
  OPTIONAL {{
    mesh:{descriptor} meshv:preferredConcept ?preferredConcept .
    OPTIONAL {{ ?preferredConcept meshv:scopeNote ?scopeNote . }}
  }}
  OPTIONAL {{ mesh:{descriptor} meshv:annotation ?annotation . }}
  OPTIONAL {{ mesh:{descriptor} meshv:historyNote ?historyNote . }}
  OPTIONAL {{ mesh:{descriptor} meshv:publicMeSHNote ?publicMeSHNote . }}
}}
LIMIT 100
""".strip()
    result = sparql(query, limit=100, offset=0, inference=False)
    metadata: dict[str, list[str]] = {
        "labels": [],
        "types": [],
        "scope_notes": [],
        "annotations": [],
        "history_notes": [],
        "public_mesh_notes": [],
    }
    for binding in sparql_bindings(result.get("results", {})):
        metadata["labels"].append(binding_value(binding, "label"))
        metadata["types"].append(resource_id(binding_value(binding, "type")))
        metadata["scope_notes"].append(binding_value(binding, "scopeNote"))
        metadata["annotations"].append(binding_value(binding, "annotation"))
        metadata["history_notes"].append(binding_value(binding, "historyNote"))
        metadata["public_mesh_notes"].append(binding_value(binding, "publicMeSHNote"))

    return {key: unique_strings(values) for key, values in metadata.items()}


def resource_type(types: list[str], descriptor: str) -> str:
    priorities = [
        "TopicalDescriptor",
        "GeographicalDescriptor",
        "PublicationType",
        "SCR_Chemical",
        "SCR_Disease",
        "SCR_Organism",
        "SCR_Protocol",
    ]
    for candidate in priorities:
        if candidate in types:
            return candidate
    if types:
        return types[0]
    if descriptor.startswith("C"):
        return "SupplementaryConceptRecord"
    if descriptor.startswith("D"):
        return "Descriptor"
    return "unknown"


def tree_numbers_for_descriptor(descriptor: str) -> list[str]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
SELECT ?treeNumber WHERE {{
  mesh:{descriptor} meshv:treeNumber ?treeNumber .
}}
ORDER BY ?treeNumber
LIMIT 200
""".strip()
    result = sparql(query, limit=200, offset=0, inference=False)
    values = [
        tree_number_value(binding_value(binding, "treeNumber"))
        for binding in sparql_bindings(result.get("results", {}))
    ]
    return sorted(unique_strings(values), key=lambda value: (value.split(".", 1)[0], value.count("."), value))


def broader_descriptors(descriptor: str) -> list[dict[str, object]]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?broader ?broaderLabel ?tree WHERE {{
  mesh:{descriptor} meshv:broaderDescriptor ?broader .
  ?broader rdfs:label ?broaderLabel .
  OPTIONAL {{ ?broader meshv:treeNumber ?tree . }}
}}
ORDER BY ?broaderLabel ?tree
LIMIT 200
""".strip()
    result = sparql(query, limit=200, offset=0, inference=False)
    return descriptor_records_from_bindings(
        sparql_bindings(result.get("results", {})),
        "broader",
        "broaderLabel",
    )


def narrower_descriptors(descriptor: str) -> list[dict[str, object]]:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?narrower ?narrowerLabel ?tree WHERE {{
  ?narrower meshv:broaderDescriptor mesh:{descriptor} ;
            rdfs:label ?narrowerLabel .
  OPTIONAL {{ ?narrower meshv:treeNumber ?tree . }}
}}
ORDER BY ?narrowerLabel ?tree
LIMIT 500
""".strip()
    result = sparql(query, limit=500, offset=0, inference=False)
    return descriptor_records_from_bindings(
        sparql_bindings(result.get("results", {})),
        "narrower",
        "narrowerLabel",
    )


def descendant_descriptors(descriptor: str, max_descendants: int) -> tuple[list[dict[str, object]], bool]:
    query_limit = max_descendants + 1
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?descendant ?descendantLabel ?tree WHERE {{
  mesh:{descriptor} meshv:treeNumber ?rootTree .
  ?descendant meshv:treeNumber ?tree ;
              rdfs:label ?descendantLabel .
  FILTER(?descendant != mesh:{descriptor})
  FILTER(STRSTARTS(STR(?tree), CONCAT(STR(?rootTree), ".")))
}}
ORDER BY ?tree ?descendantLabel
LIMIT {query_limit}
""".strip()
    result = sparql(query, limit=query_limit, offset=0, inference=False)
    bindings = sparql_bindings(result.get("results", {}))
    records = descriptor_records_from_bindings(bindings, "descendant", "descendantLabel")
    return records[:max_descendants], len(records) > max_descendants or len(bindings) > max_descendants


def sibling_descriptor_groups(
    descriptor: str,
    max_siblings: int,
) -> tuple[list[dict[str, object]], bool]:
    query_limit = max_siblings + 1
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?parent ?parentLabel ?sibling ?siblingLabel ?tree WHERE {{
  mesh:{descriptor} meshv:broaderDescriptor ?parent .
  ?parent rdfs:label ?parentLabel .
  ?sibling meshv:broaderDescriptor ?parent ;
           rdfs:label ?siblingLabel .
  FILTER(?sibling != mesh:{descriptor})
  OPTIONAL {{ ?sibling meshv:treeNumber ?tree . }}
}}
ORDER BY ?parentLabel ?siblingLabel ?tree
LIMIT {query_limit}
""".strip()
    result = sparql(query, limit=query_limit, offset=0, inference=False)
    bindings = sparql_bindings(result.get("results", {}))
    groups: dict[str, dict[str, object]] = {}
    sibling_count = 0

    for binding in bindings:
        parent_uri = binding_value(binding, "parent")
        sibling_uri = binding_value(binding, "sibling")
        if not parent_uri or not sibling_uri:
            continue
        parent_id = resource_id(parent_uri)
        group = groups.setdefault(
            parent_id,
            {
                "broader_descriptor": {
                    "descriptor": parent_id,
                    "resource": parent_uri,
                    "label": binding_value(binding, "parentLabel"),
                },
                "siblings": {},
            },
        )
        siblings = group.get("siblings", {})
        if not isinstance(siblings, dict):
            continue
        sibling_id = resource_id(sibling_uri)
        if sibling_id not in siblings:
            sibling_count += 1
            siblings[sibling_id] = {
                "descriptor": sibling_id,
                "resource": sibling_uri,
                "label": binding_value(binding, "siblingLabel"),
                "tree_numbers": [],
            }
        add_tree_number(siblings[sibling_id], tree_number_value(binding_value(binding, "tree")))

    output = []
    for group in groups.values():
        siblings = group.get("siblings", {})
        sibling_list = []
        if isinstance(siblings, dict):
            sibling_list = sorted(siblings.values(), key=descriptor_record_sort_key)
        output.append(
            {
                "broader_descriptor": group["broader_descriptor"],
                "siblings": sibling_list,
            }
        )

    output.sort(key=lambda item: normalized_label(item["broader_descriptor"].get("label", "")))  # type: ignore[index]
    return output, sibling_count > max_siblings or len(bindings) > max_siblings


def split_descriptor_qualifier_mapping(identifier: str) -> tuple[str, str] | None:
    match = re.match(r"^(D\d+)(Q\d+)$", identifier)
    if not match:
        return None
    return match.group(1), match.group(2)


def resource_label(identifier: str) -> str:
    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?label WHERE {{
  mesh:{identifier} rdfs:label ?label .
}}
LIMIT 5
""".strip()
    result = sparql(query, limit=5, offset=0, inference=False)
    labels = [
        binding_value(binding, "label")
        for binding in sparql_bindings(result.get("results", {}))
    ]
    return first_value(unique_strings(labels))


def scr_mapping(descriptor: str) -> dict[str, object]:
    if not descriptor.startswith("C"):
        return {"status": "not_applicable"}

    query = f"""
PREFIX mesh: <http://id.nlm.nih.gov/mesh/>
PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?mapped ?mappedLabel WHERE {{
  mesh:{descriptor} meshv:preferredMappedTo ?mapped .
  OPTIONAL {{ ?mapped rdfs:label ?mappedLabel . }}
}}
ORDER BY ?mapped
LIMIT 100
""".strip()
    result = sparql(query, limit=100, offset=0, inference=False)
    mappings = []
    for binding in sparql_bindings(result.get("results", {})):
        mapped_uri = binding_value(binding, "mapped")
        if not mapped_uri:
            continue
        mapped_id = resource_id(mapped_uri)
        mapping: dict[str, object] = {
            "mapped_to": mapped_id,
            "resource": mapped_uri,
            "label": binding_value(binding, "mappedLabel"),
        }
        split_mapping = split_descriptor_qualifier_mapping(mapped_id)
        if split_mapping:
            descriptor_id, qualifier_id = split_mapping
            mapping["descriptor"] = {
                "descriptor": descriptor_id,
                "resource": mesh_resource(descriptor_id),
                "label": resource_label(descriptor_id),
            }
            mapping["qualifier"] = {
                "qualifier": qualifier_id,
                "resource": mesh_resource(qualifier_id),
                "label": resource_label(qualifier_id),
            }
        mappings.append(mapping)

    if not mappings:
        return {
            "status": "none_found",
            "mappings": [],
            "review_prompt": "No preferredMappedTo relationship was found in MeSH RDF; review this SCR manually before using it as controlled vocabulary.",
        }
    return {
        "status": "mapped",
        "mappings": mappings,
        "review_prompt": "For SCRs, review preferredMappedTo descriptors and keep the SCR text term in the [tiab]/substance layer when relevant.",
    }


def explosion_review_prompts(
    descriptor: str,
    preferred_label: str,
    resource_type_value: str,
    tree_numbers: list[str],
    broader: list[dict[str, object]],
    narrower: list[dict[str, object]],
    descendants: list[dict[str, object]],
    descendants_truncated: bool,
    sibling_groups: list[dict[str, object]],
    siblings_truncated: bool,
    mapping: dict[str, object],
) -> list[str]:
    label = preferred_label or descriptor
    prompts = []

    if resource_type_value.startswith("SCR") or descriptor.startswith("C"):
        prompts.append("This looks like a Supplementary Concept Record; review scr_mapping before deciding whether to search the SCR, its mapped descriptor, or both.")

    if not tree_numbers:
        prompts.append("No MeSH tree numbers were found, so a descriptor explosion/noexp decision cannot be made from tree context alone.")
    elif descendants:
        prompts.append(f"Review all returned descendants before using \"{label}\"[Mesh]; use explosion only when the descendant branches are in scope.")
        prompts.append(f"If descendant branches would add out-of-scope records, compare \"{label}\"[Mesh:noexp] or more specific descriptors.")
    else:
        prompts.append(f"No descendants were returned for \"{label}\" in the current MeSH tree evidence; [Mesh] and [Mesh:noexp] may retrieve similarly, but count-test if the choice matters.")

    if len(tree_numbers) > 1:
        prompts.append("This descriptor appears in multiple MeSH tree positions; review each branch before treating the explosion as a single-scope decision.")
    if broader:
        prompts.append("Use broader_descriptors and sibling_descriptors to decide whether a parent descriptor would be too broad or whether a sibling should be searched separately.")
    if narrower and not descendants:
        prompts.append("Direct narrower descriptors were returned even though no descendants were returned by tree-number prefix matching; inspect this discrepancy before finalizing explosion notes.")
    if descendants_truncated or siblings_truncated:
        prompts.append("Tree context was truncated by the requested max limit; rerun tree with a higher max before making a final explosion decision.")
    if mapping.get("status") == "mapped":
        prompts.append("For mapped SCRs, PubMed count-test the SCR label, mapped descriptor, and any useful entry terms separately before including or rejecting them.")

    if resource_type_value.startswith("SCR") or descriptor.startswith("C"):
        prompts.append(f"Run PubMed count tests with scripts/pubmed_tool.py search '\"{label}\"[Supplementary Concept]' --retmax 0, plus mapped descriptor and text-word checks when relevant.")
    else:
        prompts.append(f"Run PubMed count tests with scripts/pubmed_tool.py search '\"{label}\"[Mesh]' --retmax 0 and, when descendants or scope uncertainty exist, '\"{label}\"[Mesh:noexp]' --retmax 0.")
    prompts.append("Document accepted and plausible rejected descriptors with scope, descendant, sibling, and count-test rationale.")
    return prompts


def tree(descriptor: str, max_descendants: int, max_siblings: int) -> dict[str, object]:
    descriptor_id = resource_id(descriptor)
    detail_data = details(descriptor_id, "terms,seealso,qualifiers").get("details", {})
    if not isinstance(detail_data, dict):
        detail_data = {}

    metadata = mesh_metadata(descriptor_id)
    preferred_terms = term_entries(detail_data, preferred=True)
    preferred_label = first_value(metadata["labels"])
    if not preferred_label and preferred_terms:
        preferred_label = str(preferred_terms[0].get("label", ""))

    tree_numbers = tree_numbers_for_descriptor(descriptor_id)
    broader = broader_descriptors(descriptor_id)
    narrower = narrower_descriptors(descriptor_id)
    descendants, descendants_truncated = descendant_descriptors(descriptor_id, max_descendants)
    sibling_groups, siblings_truncated = sibling_descriptor_groups(descriptor_id, max_siblings)
    mapping = scr_mapping(descriptor_id)
    resource_type_value = resource_type(metadata["types"], descriptor_id)

    return {
        "operation": "tree",
        "descriptor": descriptor_id,
        "resource": mesh_resource(descriptor_id),
        "resource_type": resource_type_value,
        "preferred_label": preferred_label,
        "scope_note": first_value(metadata["scope_notes"]) or None,
        "annotation": first_value(metadata["annotations"]) or None,
        "history_note": first_value(metadata["history_notes"]) or None,
        "public_mesh_note": first_value(metadata["public_mesh_notes"]) or None,
        "entry_terms": term_entries(detail_data, preferred=False),
        "tree_numbers": tree_numbers,
        "broader_descriptors": broader,
        "narrower_descriptors": narrower,
        "descendants": descendants,
        "descendants_truncated": descendants_truncated,
        "sibling_descriptors": sibling_groups,
        "sibling_descriptors_truncated": siblings_truncated,
        "scr_mapping": mapping,
        "limits": {
            "max_descendants": max_descendants,
            "max_siblings": max_siblings,
        },
        "explosion_review_prompts": explosion_review_prompts(
            descriptor_id,
            preferred_label,
            resource_type_value,
            tree_numbers,
            broader,
            narrower,
            descendants,
            descendants_truncated,
            sibling_groups,
            siblings_truncated,
            mapping,
        ),
    }


def normalized_label(value: object) -> str:
    return " ".join(str(value).casefold().replace("-", " ").split())


def descriptor_type_rank(descriptor_id: str) -> int:
    if descriptor_id.startswith("D"):
        return 0
    if descriptor_id.startswith("C"):
        return 1
    return 2


def source_rank(source: str) -> int:
    parts = source.split(":", 2)
    if len(parts) < 2:
        return 99
    source_type, match = parts[0], parts[1]
    priorities = {
        ("descriptor", "exact"): 0,
        ("term", "exact"): 1,
        ("descriptor", "startswith"): 2,
        ("term", "startswith"): 3,
        ("descriptor", "contains"): 4,
        ("term", "contains"): 5,
    }
    return priorities.get((source_type, match), 99)


def candidate_sort_key(
    item: tuple[str, dict[str, object]],
    candidate_sources: defaultdict[str, list[str]],
    label_positions: dict[str, int],
) -> tuple[int, int, int, int, str]:
    descriptor_id, candidate = item
    sources = set(candidate_sources[descriptor_id])
    best_source = min((source_rank(source) for source in sources), default=99)
    label_position = label_positions.get(normalized_label(candidate.get("label", "")), 999)
    return (
        best_source,
        descriptor_type_rank(descriptor_id),
        label_position,
        -len(sources),
        normalized_label(candidate.get("label", "")),
    )


def sweep(
    concept: str,
    variants: list[str],
    limit: int,
    include_details: bool,
    max_term_descriptor_lookups: int,
    max_detail_candidates: int,
) -> dict[str, object]:
    labels = []
    for value in [concept, *variants]:
        cleaned = " ".join(value.split())
        if cleaned and cleaned.lower() not in {item.lower() for item in labels}:
            labels.append(cleaned)

    labels_normalized = {normalized_label(label): index for index, label in enumerate(labels)}
    matches = ["exact", "startswith", "contains"]
    raw_searches = []
    candidates: dict[str, dict[str, object]] = {}
    candidate_sources: defaultdict[str, list[str]] = defaultdict(list)
    term_descriptor_lookup_count = 0
    term_descriptor_lookup_skipped = 0
    seen_term_resources: set[str] = set()

    for match in matches:
        for label in labels:
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
                    if term_resource in seen_term_resources:
                        descriptor_hits = term_descriptor_candidates(term_resource, limit=10)
                    elif term_descriptor_lookup_count < max_term_descriptor_lookups:
                        seen_term_resources.add(term_resource)
                        term_descriptor_lookup_count += 1
                        descriptor_hits = term_descriptor_candidates(term_resource, limit=10)
                    else:
                        term_descriptor_lookup_skipped += 1
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
    detail_candidate_count = 0
    detail_candidate_skipped = 0
    for descriptor_id, candidate in sorted(
        candidates.items(),
        key=lambda item: candidate_sort_key(item, candidate_sources, labels_normalized),
    ):
        entry = dict(candidate)
        entry["sources"] = sorted(set(candidate_sources[descriptor_id]))
        if include_details:
            if detail_candidate_count < max_detail_candidates:
                detail_candidate_count += 1
                entry["details"] = details(descriptor_id, "terms,seealso,qualifiers").get("details", {})
            else:
                detail_candidate_skipped += 1
                entry["details_skipped"] = "Detail lookup skipped by --max-detail-candidates budget."
        candidate_list.append(entry)

    return {
        "operation": "sweep",
        "concept": concept,
        "variants": variants,
        "matches_used": matches,
        "candidate_ranking": "Sorted by match specificity, direct descriptor hits before term-derived hits, MeSH descriptors before supplementary concepts, then query-label order and label.",
        "candidate_count": len(candidate_list),
        "candidates": candidate_list,
        "raw_searches": raw_searches,
        "network_budget": {
            "request_cache_entries": len(REQUEST_CACHE),
            "max_term_descriptor_lookups": max_term_descriptor_lookups,
            "term_descriptor_lookups_used": term_descriptor_lookup_count,
            "term_descriptor_lookups_skipped": term_descriptor_lookup_skipped,
            "max_detail_candidates": max_detail_candidates,
            "detail_candidates_used": detail_candidate_count,
            "detail_candidates_skipped": detail_candidate_skipped,
        },
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

    tree_parser = subparsers.add_parser("tree", help="Fetch descriptor tree context, scope, entry terms, siblings, descendants, and SCR mapping.")
    tree_parser.add_argument("--descriptor", required=True)
    tree_parser.add_argument("--max-descendants", type=int, default=DEFAULT_MAX_TREE_DESCENDANTS)
    tree_parser.add_argument("--max-siblings", type=int, default=DEFAULT_MAX_TREE_SIBLINGS)

    sweep_parser = subparsers.add_parser("sweep", help="Aggressively search MeSH descriptors and entry terms for a concept plus variants.")
    sweep_parser.add_argument("--concept", required=True)
    sweep_parser.add_argument("--variant", action="append", default=[], help="Additional synonym/acronym/spelling/seed term. Repeat as needed.")
    sweep_parser.add_argument("--variants-file", help="Optional newline-delimited variants file. Use '-' for stdin.")
    sweep_parser.add_argument("--limit", type=int, default=20)
    sweep_parser.add_argument("--details", action="store_true", help="Fetch details for every candidate descriptor.")
    sweep_parser.add_argument(
        "--max-term-descriptor-lookups",
        type=int,
        default=DEFAULT_MAX_TERM_DESCRIPTOR_LOOKUPS,
        help="Maximum unique term-to-descriptor SPARQL lookups during sweep.",
    )
    sweep_parser.add_argument(
        "--max-detail-candidates",
        type=int,
        default=DEFAULT_MAX_DETAIL_CANDIDATES,
        help="Maximum candidate descriptors to enrich when --details is used.",
    )

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
        elif args.command == "tree":
            write_json(tree(args.descriptor, max(0, args.max_descendants), max(0, args.max_siblings)))
        elif args.command == "sweep":
            variants = list(args.variant)
            if args.variants_file:
                variants.extend(read_lines(args.variants_file))
            write_json(
                sweep(
                    args.concept,
                    variants,
                    args.limit,
                    args.details,
                    max(0, args.max_term_descriptor_lookups),
                    max(0, args.max_detail_candidates),
                )
            )
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
