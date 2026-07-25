#!/usr/bin/env python3
"""Criterion-level candidate screening with verifiable evidence.

Screening is the pivot of the whole workflow: only included records may teach the search new
vocabulary, and a subset of them becomes the held-out set the final strategy is measured
against. Every downstream claim -- discovered terminology, fragility, ablation, recall --
inherits whatever screening decided.

Until this tool existed the workflow only asked that each candidate carry a decision and some
reason text, so each run improvised its own screener. Two failure modes followed. A lexicon
rule can *exclude* a record for lacking already-known vocabulary, suppressing exactly the
unfamiliar terminology vocabulary learning is meant to find. And a reason string generated from
a title keyword satisfies a validator that only checks the field is non-empty, while the record
still asserts ``title_abstract_reviewed: true``.

The validator therefore checks evidence rather than form:

* the rubric is compiled from the locked protocol and hash-bound before screening begins;
* every criterion gets an explicit verdict -- ``yes``, ``no``, ``unclear``, ``not_reported``;
* quoted evidence must appear verbatim in the named field of the hash-bound record, so an
  unsupported quotation is no easier to write than an unsupported reason was;
* an include needs affirmative evidence on *every* required criterion; an exclude needs
  evidence for at least one decisive failure; anything else is forced to ``uncertain``, so
  missing information can never become a silent exclusion;
* decisions record how they were made, and a rule-only decision cannot supply a discovery or
  holdout record unless a human or model independently adjudicated it.

Rules remain useful -- they prioritise, triage, and pre-fill. They just cannot be the final
authority for the records that drive the evidence base.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import candidate_ledger

VERDICTS = {"yes", "no", "unclear", "not_reported"}
AFFIRMATIVE = "yes"
DECISIONS = {"include", "exclude", "uncertain"}

# How a decision was reached. `rule` is a mechanical screener with no human or model reading of
# the record; `human_verified_model` is a model assessment a human checked and stood behind.
DECIDED_BY = {"human", "model", "rule", "human_verified_model"}
# Provenance that may supply discovery/holdout records without further adjudication.
ADJUDICATED_BY = {"human", "model", "human_verified_model"}

# Fields a quotation may be drawn from. All are part of the hashed record content.
EVIDENCE_FIELDS = ("title", "abstract", "keywords", "mesh_headings")

REQUIRED_INCLUSION = "required-inclusion"
DECISIVE_EXCLUSION = "decisive-exclusion"

# Verifying that a quotation exists in the record does not establish that it *supports* the
# verdict it is attached to -- a screener could cite a real but irrelevant sentence. Nothing
# mechanical settles semantic support, but the cheap ways of faking evidence are checkable:
# a contentless fragment, a whole-abstract dump that points at nothing in particular, and a
# second reader whose evidence for the same conclusion has nothing in common with the first's.
MIN_EVIDENCE_CONTENT_TOKENS = 1
MAX_EVIDENCE_WORDS = 60

# Research boilerplate that carries no eligibility information on its own. A quotation made
# only of these words cites nothing, however genuinely it appears in the record.
NON_EVIDENTIAL_TOKENS = frozenset(
    {
        "a", "an", "the", "this", "that", "these", "those", "and", "or", "but", "not",
        "of", "in", "on", "at", "to", "for", "from", "with", "by", "as", "is", "are",
        "was", "were", "be", "been", "we", "our", "they", "their", "it", "its",
        "study", "studies", "trial", "trials", "paper", "article", "report", "reports",
        "reported", "research", "results", "result", "methods", "method", "conclusion",
        "conclusions", "background", "objective", "objectives", "purpose", "aim", "aims",
        "introduction", "discussion", "findings", "data", "analysis", "present", "presents",
        "using", "used", "use", "based", "however", "therefore", "thus", "also", "may",
    }
)


def content_tokens(text: str) -> list[str]:
    """Substantive words in a quotation: >=4 letters and not research boilerplate."""
    tokens: list[str] = []
    for raw in normalize_for_quote(text).split():
        word = "".join(character for character in raw if character.isalnum())
        if len(word) >= 4 and word not in NON_EVIDENTIAL_TOKENS:
            tokens.append(word)
    return tokens


class ScreeningError(ValueError):
    pass


# -- io ---------------------------------------------------------------------------------


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScreeningError(f"Could not read JSON {path}: {exc}") from exc


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


# -- record content ---------------------------------------------------------------------


def field_text(record: dict[str, Any], field: str) -> str:
    """Flatten one evidence field of a record to searchable text."""
    value = record.get(field)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("name") or item.get("term") or item.get("descriptor") or ""))
            else:
                parts.append(str(item))
        return " ; ".join(part for part in parts if part)
    return str(value)


def record_content(record: dict[str, Any]) -> dict[str, str]:
    return {field: field_text(record, field) for field in EVIDENCE_FIELDS}


def record_digest(record: dict[str, Any]) -> str:
    """Hash the record content a screener reads, so evidence stays bound to what was read."""
    content = record_content(record)
    content["pmid"] = str(record.get("pmid") or "")
    return digest(content)


def normalize_for_quote(text: str) -> str:
    """Collapse whitespace and case so a quotation survives copy/paste, not invention."""
    return " ".join(str(text).split()).casefold()


def quote_supported(record: dict[str, Any], field: str, quote: str) -> bool:
    if field not in EVIDENCE_FIELDS:
        return False
    needle = normalize_for_quote(quote)
    if not needle:
        return False
    return needle in normalize_for_quote(field_text(record, field))


def evidence_span_issue(record: dict[str, Any], field: str, quote: str) -> str | None:
    """Reject a quotation that cannot function as evidence, or ``None`` when it can.

    Existing in the record is necessary but not sufficient. A fragment of pure boilerplate
    cites nothing, and a span the length of the whole abstract points at nothing in
    particular; both are ways to satisfy an evidence requirement without reading anything.
    """
    if field not in EVIDENCE_FIELDS:
        return f"evidence field must be one of: {', '.join(EVIDENCE_FIELDS)}"
    if not quote_supported(record, field, quote):
        return f"quotes text absent from {field}: {quote[:60]!r}"
    words = normalize_for_quote(quote).split()
    if len(words) > MAX_EVIDENCE_WORDS:
        return (
            f"quotes {len(words)} words from {field}; an evidence span over {MAX_EVIDENCE_WORDS} "
            "words points at nothing in particular -- cite the sentence that decides the criterion"
        )
    if len(content_tokens(quote)) < MIN_EVIDENCE_CONTENT_TOKENS:
        return f"quotes only boilerplate from {field} and cites no substantive content: {quote[:60]!r}"
    return None


# -- rubric -----------------------------------------------------------------------------


def compile_rubric(protocol: dict[str, Any], *, scope_version: int, protocol_path: str) -> dict[str, Any]:
    """Freeze the protocol's eligibility criteria as an immutable screening rubric."""
    if protocol.get("scope_version") != scope_version:
        raise ScreeningError("Protocol scope_version does not match --scope-version")
    eligibility = protocol.get("eligibility")
    if not isinstance(eligibility, dict):
        raise ScreeningError("Protocol requires an eligibility object to compile a screening rubric")

    criteria: list[dict[str, Any]] = []
    for role, key in ((REQUIRED_INCLUSION, "inclusion"), (DECISIVE_EXCLUSION, "exclusion")):
        entries = eligibility.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                raise ScreeningError(f"eligibility.{key} entries must be objects")
            criterion_id = str(entry.get("id") or "").strip()
            if not criterion_id:
                raise ScreeningError(f"eligibility.{key} entry requires an id")
            criteria.append(
                {
                    "id": criterion_id,
                    "role": role,
                    "label": str(entry.get("label") or criterion_id),
                    "description": str(entry.get("description") or ""),
                    "affirmative_meaning": (
                        "criterion is met by this record"
                        if role == REQUIRED_INCLUSION
                        else "this exclusion applies to this record"
                    ),
                }
            )
    if not criteria:
        raise ScreeningError("Protocol eligibility defines no inclusion or exclusion criteria")
    if len({item["id"] for item in criteria}) != len(criteria):
        raise ScreeningError("Protocol eligibility repeats a criterion id")

    rubric = {
        "operation": "screening-rubric-compile",
        "artifact_type": "screening/rubric",
        "artifact_version": 1,
        "ok": True,
        "scope_version": scope_version,
        "protocol_id": protocol.get("protocol_id"),
        "protocol_sha256": digest(protocol),
        "generated_from": {"path": str(protocol_path), "sha256": digest(protocol)},
        "verdicts": sorted(VERDICTS),
        "decision_rule": {
            "include": "every required-inclusion criterion is 'yes' with supporting evidence, and no decisive-exclusion criterion is 'yes'",
            "exclude": "at least one decisive failure with supporting evidence: a decisive-exclusion 'yes', or a required-inclusion 'no'",
            "uncertain": "anything else, including any required criterion left 'unclear' or 'not_reported'",
        },
        "criteria": criteria,
    }
    rubric["rubric_sha256"] = digest(rubric["criteria"])
    return rubric


def load_rubric(path: str | Path, *, scope_version: int) -> dict[str, Any]:
    rubric = read_json(path)
    if not isinstance(rubric, dict) or rubric.get("operation") != "screening-rubric-compile":
        raise ScreeningError("Rubric artifact is not a compiled screening rubric")
    if rubric.get("scope_version") != scope_version:
        raise ScreeningError("Rubric scope_version does not match --scope-version")
    if rubric.get("rubric_sha256") != digest(rubric.get("criteria")):
        raise ScreeningError("Rubric criteria do not match rubric_sha256; recompile from the protocol")
    return rubric


# -- worksheet --------------------------------------------------------------------------


def records_from_file(path: str | Path) -> list[dict[str, Any]]:
    raw = read_json(path)
    if isinstance(raw, dict):
        raw = raw.get("records")
    if not isinstance(raw, list):
        raise ScreeningError("Records file must contain a records list or be a list")
    records = [item for item in raw if isinstance(item, dict) and str(item.get("pmid") or "").strip().isdigit()]
    if not records:
        raise ScreeningError("Records file contains no records with a numeric pmid")
    return records


def prepare_worksheet(
    rubric: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    scope_version: int,
    round_number: int,
    records_path: str,
) -> dict[str, Any]:
    """Emit one pending assessment per criterion per record, bound to the record's content."""
    rows: list[dict[str, Any]] = []
    for record in records:
        pmid = str(record.get("pmid")).strip()
        rows.append(
            {
                "pmid": pmid,
                "record_sha256": record_digest(record),
                "provenance": str(record.get("provenance") or "other"),
                "assessments": [
                    {
                        "criterion_id": criterion["id"],
                        "role": criterion["role"],
                        "verdict": "pending",
                        "evidence": [],
                        "note": "",
                    }
                    for criterion in rubric["criteria"]
                ],
                "decision": "pending",
                "decided_by": "",
                "adjudicated_by": "",
                "eligibility_reason": "",
            }
        )
    return {
        "operation": "screening-worksheet",
        "artifact_type": "screening/worksheet",
        "artifact_version": 1,
        "ok": True,
        "scope_version": scope_version,
        "round": round_number,
        "protocol_id": rubric.get("protocol_id"),
        "rubric_sha256": rubric["rubric_sha256"],
        "records_source": {"path": str(records_path), "sha256": digest(records)},
        "records": rows,
        "note": (
            "Fill every assessment verdict and attach evidence quoted verbatim from the named record "
            "field. Leave a decision 'uncertain' when the record does not settle a required criterion; "
            "absence of information is not an exclusion."
        ),
    }


# -- decision logic ---------------------------------------------------------------------


def implied_decision(assessments: dict[str, str], criteria: list[dict[str, Any]]) -> str:
    """Decision entailed by the criterion verdicts alone."""
    for criterion in criteria:
        if criterion["role"] == DECISIVE_EXCLUSION and assessments.get(criterion["id"]) == AFFIRMATIVE:
            return "exclude"
    for criterion in criteria:
        if criterion["role"] != REQUIRED_INCLUSION:
            continue
        verdict = assessments.get(criterion["id"])
        if verdict == "no":
            return "exclude"
        if verdict != AFFIRMATIVE:
            # unclear / not_reported / missing: the record does not settle a required criterion.
            return "uncertain"
    return "include"


def decisive_failures(assessments: dict[str, str], criteria: list[dict[str, Any]]) -> list[str]:
    failures = []
    for criterion in criteria:
        verdict = assessments.get(criterion["id"])
        if criterion["role"] == DECISIVE_EXCLUSION and verdict == AFFIRMATIVE:
            failures.append(criterion["id"])
        elif criterion["role"] == REQUIRED_INCLUSION and verdict == "no":
            failures.append(criterion["id"])
    return failures


def validate_worksheet(
    worksheet: dict[str, Any],
    rubric: dict[str, Any],
    records: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    if worksheet.get("operation") != "screening-worksheet":
        return ["artifact is not a screening worksheet"], {}
    if worksheet.get("rubric_sha256") != rubric.get("rubric_sha256"):
        issues.append("worksheet was not screened against this rubric version")
    if worksheet.get("scope_version") != rubric.get("scope_version"):
        issues.append("worksheet scope_version does not match the rubric")

    criteria = rubric["criteria"]
    criterion_ids = {item["id"] for item in criteria}
    by_pmid = {str(item.get("pmid") or "").strip(): item for item in records}

    rows = worksheet.get("records")
    if not isinstance(rows, list) or not rows:
        return issues + ["worksheet records must be a non-empty list"], {}

    decision_counts: Counter[str] = Counter()
    provenance_counts: Counter[str] = Counter()
    verdict_counts: Counter[str] = Counter()
    evidence_spans = 0
    distinct_spans = 0
    single_span_records: list[str] = []
    rule_only: list[str] = []
    seen: set[str] = set()

    for index, row in enumerate(rows, start=1):
        prefix = f"record {index}"
        if not isinstance(row, dict):
            issues.append(f"{prefix} must be an object")
            continue
        pmid = str(row.get("pmid") or "").strip()
        if not pmid.isdigit():
            issues.append(f"{prefix} pmid must contain digits only")
            continue
        prefix = f"record {pmid}"
        if pmid in seen:
            issues.append(f"{prefix} appears more than once")
        seen.add(pmid)

        record = by_pmid.get(pmid)
        if record is None:
            issues.append(f"{prefix} has no matching record in the source records file")
            continue
        if row.get("record_sha256") != record_digest(record):
            issues.append(f"{prefix} record content changed after screening; re-screen against the current record")
            continue

        assessments = row.get("assessments")
        if not isinstance(assessments, list):
            issues.append(f"{prefix} assessments must be a list")
            continue
        verdicts: dict[str, str] = {}
        evidenced: set[str] = set()
        record_spans: set[str] = set()
        for item in assessments:
            if not isinstance(item, dict):
                issues.append(f"{prefix} assessment entries must be objects")
                continue
            criterion_id = str(item.get("criterion_id") or "")
            if criterion_id not in criterion_ids:
                issues.append(f"{prefix} assesses unknown criterion {criterion_id!r}")
                continue
            verdict = str(item.get("verdict") or "").strip()
            if verdict not in VERDICTS:
                issues.append(f"{prefix} criterion {criterion_id} verdict must be one of: {', '.join(sorted(VERDICTS))}")
                continue
            verdicts[criterion_id] = verdict
            verdict_counts[verdict] += 1
            spans = item.get("evidence")
            if spans in (None, ""):
                spans = []
            if not isinstance(spans, list):
                issues.append(f"{prefix} criterion {criterion_id} evidence must be a list")
                continue
            supported = 0
            for span in spans:
                if not isinstance(span, dict):
                    issues.append(f"{prefix} criterion {criterion_id} evidence entries must be objects")
                    continue
                field = str(span.get("field") or "")
                quote = str(span.get("quote") or "")
                problem = evidence_span_issue(record, field, quote)
                if problem:
                    issues.append(f"{prefix} criterion {criterion_id} {problem}")
                    continue
                supported += 1
                record_spans.add(normalize_for_quote(quote))
            evidence_spans += supported
            if supported:
                evidenced.add(criterion_id)

        distinct_spans += len(record_spans)
        # One span reused as the sole evidence for three or more criteria is the signature of a
        # quotation pasted once rather than read per criterion. Reported, not rejected: a single
        # dense sentence can legitimately settle two criteria at once.
        if len(record_spans) == 1 and len(evidenced) >= 3:
            single_span_records.append(pmid)

        missing = sorted(criterion_ids - set(verdicts))
        if missing:
            issues.append(f"{prefix} leaves criteria unassessed: {', '.join(missing)}")
            continue

        decision = str(row.get("decision") or "").strip()
        if decision not in DECISIONS:
            issues.append(f"{prefix} decision must be one of: {', '.join(sorted(DECISIONS))}")
            continue
        decision_counts[decision] += 1

        entailed = implied_decision(verdicts, criteria)
        if decision != entailed:
            issues.append(
                f"{prefix} records decision {decision!r} but its criterion verdicts entail {entailed!r}"
            )

        # Evidence requirements are criterion-specific: an inclusion must be affirmatively
        # supported on every required criterion, an exclusion needs only the decisive failure it
        # actually rests on.
        if decision == "include":
            unevidenced = sorted(
                criterion["id"]
                for criterion in criteria
                if criterion["role"] == REQUIRED_INCLUSION and criterion["id"] not in evidenced
            )
            if unevidenced:
                issues.append(
                    f"{prefix} is included without supporting evidence for required criteria: {', '.join(unevidenced)}"
                )
        elif decision == "exclude":
            failures = decisive_failures(verdicts, criteria)
            if not failures:
                issues.append(f"{prefix} is excluded without a decisive failed criterion")
            elif not any(criterion_id in evidenced for criterion_id in failures):
                issues.append(
                    f"{prefix} is excluded without supporting evidence for any decisive failure: {', '.join(failures)}"
                )

        decided_by = str(row.get("decided_by") or "").strip()
        if decided_by not in DECIDED_BY:
            issues.append(f"{prefix} decided_by must be one of: {', '.join(sorted(DECIDED_BY))}")
        provenance_counts[decided_by or "unset"] += 1
        adjudicated_by = str(row.get("adjudicated_by") or "").strip()
        if adjudicated_by and adjudicated_by not in ADJUDICATED_BY:
            issues.append(f"{prefix} adjudicated_by must be one of: {', '.join(sorted(ADJUDICATED_BY))}")
        if decided_by == "rule" and not adjudicated_by:
            rule_only.append(pmid)

        if not str(row.get("eligibility_reason") or "").strip():
            issues.append(f"{prefix} requires an eligibility_reason")

    summary = {
        "scope_version": worksheet.get("scope_version"),
        "round": worksheet.get("round"),
        "rubric_sha256": worksheet.get("rubric_sha256"),
        "record_count": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "decided_by_counts": dict(sorted(provenance_counts.items())),
        "verified_evidence_spans": evidence_spans,
        "distinct_evidence_spans": distinct_spans,
        "single_span_records": sorted(single_span_records, key=int),
        "rule_only_pmids": sorted(rule_only, key=int),
        "rule_only_count": len(rule_only),
        "note": (
            "Rule-only decisions may prioritise or triage, but cannot supply discovery or holdout "
            "records until a human or model adjudicates them. Verified spans exist in the record; "
            "whether they support their verdict is settled by the agreement check, not here."
        ),
    }
    return issues, summary


# -- ledger ------------------------------------------------------------------------------


def agreement_block(agreement_artifact: dict[str, Any], worksheet: dict[str, Any]) -> dict[str, Any]:
    """Summarise the agreement check and confirm everything it flagged was adjudicated."""
    if agreement_artifact.get("operation") != "screening-agreement":
        raise ScreeningError("--agreement expects a screening-agreement artifact")
    if agreement_artifact.get("rubric_sha256") != worksheet.get("rubric_sha256"):
        raise ScreeningError("agreement artifact was produced against a different rubric version")
    adjudicated = {
        str(row.get("pmid"))
        for row in worksheet.get("records", [])
        if isinstance(row, dict) and str(row.get("adjudicated_by") or "").strip()
    }
    flagged = [str(pmid) for pmid in agreement_artifact.get("adjudication_pmids", [])]
    unresolved = sorted(set(flagged) - adjudicated, key=int)
    if unresolved:
        raise ScreeningError(
            "the agreement check flagged records that this worksheet does not adjudicate: "
            + ", ".join(unresolved[:10])
            + ". Re-screen them and set adjudicated_by before building the ledger."
        )
    compared = int(agreement_artifact.get("compared_records") or 0)
    screened = len([row for row in worksheet.get("records", []) if isinstance(row, dict)])
    return {
        "compared_records": compared,
        "screened_records": screened,
        "coverage": round(compared / screened, 4) if screened else None,
        "raw_agreement": agreement_artifact.get("raw_agreement"),
        "cohen_kappa": agreement_artifact.get("cohen_kappa"),
        "confusion_matrix": agreement_artifact.get("confusion_matrix"),
        "disagreement_count": len(agreement_artifact.get("disagreements") or []),
        "evidence_divergence_count": len(agreement_artifact.get("evidence_divergence") or []),
        "adjudicated_pmids": sorted(set(flagged), key=int),
        "unresolved_adjudications": [],
    }


def to_ledger(
    worksheet: dict[str, Any],
    rubric: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    template: dict[str, Any] | None = None,
    agreement_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a validated worksheet into a candidate ledger the rest of the workflow consumes."""
    issues, _summary = validate_worksheet(worksheet, rubric, records)
    if issues:
        raise ScreeningError("worksheet is invalid: " + "; ".join(issues[:5]))

    by_pmid = {str(item.get("pmid") or "").strip(): item for item in records}
    ledger_records: list[dict[str, Any]] = []
    for row in worksheet["records"]:
        pmid = str(row["pmid"]).strip()
        decision = str(row["decision"])
        decided_by = str(row.get("decided_by") or "")
        adjudicated_by = str(row.get("adjudicated_by") or "")
        rule_only = decided_by == "rule" and not adjudicated_by
        if decision == "include":
            # A rule-only include is retained as a heuristic neighbour rather than promoted: it
            # can inform, but it must not seed vocabulary or become a validation target.
            use = "heuristic" if rule_only else "both"
        elif decision == "uncertain":
            use = "heuristic"
        else:
            use = "neither"
        ledger_records.append(
            {
                "pmid": pmid,
                "provenance": str(row.get("provenance") or by_pmid[pmid].get("provenance") or "other"),
                "decision": decision,
                "use": use,
                "title_abstract_reviewed": True,
                "eligibility_reason": str(row.get("eligibility_reason") or ""),
                "screening": {
                    "rubric_sha256": worksheet["rubric_sha256"],
                    "record_sha256": row["record_sha256"],
                    "decided_by": decided_by,
                    "adjudicated_by": adjudicated_by,
                    "evidence_backed": True,
                    "rule_only": rule_only,
                    "criterion_verdicts": {
                        str(item.get("criterion_id")): str(item.get("verdict"))
                        for item in row.get("assessments", [])
                        if isinstance(item, dict)
                    },
                },
            }
        )

    ledger: dict[str, Any] = {
        "scope_version": worksheet["scope_version"],
        "ledger_status": "screened",
        "screening_provenance": {
            "rubric_sha256": worksheet["rubric_sha256"],
            "worksheet_sha256": digest(worksheet),
            "round": worksheet.get("round"),
            "agreement": agreement_block(agreement_artifact, worksheet) if agreement_artifact else None,
        },
        "records": ledger_records,
    }
    if template:
        for key in ("artifact_type", "artifact_version", "protocol_id", "dsl_version", "generated_from"):
            if key in template:
                ledger[key] = template[key]
        ledger["artifact_type"] = "candidate-ledger"
    return ledger


# -- agreement ---------------------------------------------------------------------------


def stratified_sample(worksheet: dict[str, Any], *, fraction: float, seed: str) -> dict[str, Any]:
    """Select a re-adjudication sample stratified by decision.

    A simple random sample of a screening set is mostly obvious excludes, which measures very
    little. Sampling within each decision stratum puts includes and uncertains -- where errors
    actually cost recall -- into the check.
    """
    strata: dict[str, list[str]] = {}
    for row in worksheet.get("records", []):
        if isinstance(row, dict) and str(row.get("decision")) in DECISIONS:
            strata.setdefault(str(row["decision"]), []).append(str(row["pmid"]))
    selected: dict[str, list[str]] = {}
    for decision, pmids in sorted(strata.items()):
        ordered = sorted(pmids, key=lambda pmid: hashlib.sha256(f"{seed}:{pmid}".encode("utf-8")).hexdigest())
        take = min(len(ordered), max(1, math.ceil(len(ordered) * max(0.0, fraction))))
        selected[decision] = sorted(ordered[:take], key=int)
    return {
        "operation": "screening-agreement-sample",
        "ok": True,
        "scope_version": worksheet.get("scope_version"),
        "method": "sha256-deterministic stratified by decision",
        "seed": seed,
        "fraction": fraction,
        "stratum_totals": {decision: len(pmids) for decision, pmids in sorted(strata.items())},
        "selected_by_decision": selected,
        "pmids": sorted({pmid for pmids in selected.values() for pmid in pmids}, key=int),
    }


def cohen_kappa(matrix: dict[str, dict[str, int]], labels: list[str]) -> float | None:
    total = sum(matrix[row][column] for row in labels for column in labels)
    if not total:
        return None
    observed = sum(matrix[label][label] for label in labels) / total
    expected = 0.0
    for label in labels:
        row_total = sum(matrix[label][column] for column in labels)
        column_total = sum(matrix[row][label] for row in labels)
        expected += (row_total / total) * (column_total / total)
    if math.isclose(expected, 1.0):
        return None
    return round((observed - expected) / (1 - expected), 4)


def evidence_tokens_by_criterion(worksheet: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    """Content tokens each screening cited, per record per criterion."""
    result: dict[str, dict[str, set[str]]] = {}
    for row in worksheet.get("records", []):
        if not isinstance(row, dict):
            continue
        per_criterion: dict[str, set[str]] = {}
        for item in row.get("assessments", []):
            if not isinstance(item, dict):
                continue
            tokens: set[str] = set()
            for span in item.get("evidence") or []:
                if isinstance(span, dict):
                    tokens.update(content_tokens(str(span.get("quote") or "")))
            if tokens:
                per_criterion[str(item.get("criterion_id"))] = tokens
        result[str(row.get("pmid"))] = per_criterion
    return result


def evidence_divergence(original: dict[str, Any], replicate: dict[str, Any], agreed_pmids: list[str]) -> list[dict[str, Any]]:
    """Find records where both screenings agreed but rested the decision on unrelated text.

    This is the check a decision-level comparison cannot make. If two readers reach the same
    conclusion about the same record and cite evidence with no substantive word in common, at
    least one of them is pointing at text that is not the reason -- which is exactly the failure
    that survives verbatim-quotation checking.
    """
    first = evidence_tokens_by_criterion(original)
    second = evidence_tokens_by_criterion(replicate)
    findings: list[dict[str, Any]] = []
    for pmid in agreed_pmids:
        left, right = first.get(pmid, {}), second.get(pmid, {})
        diverged = sorted(
            criterion
            for criterion in set(left) & set(right)
            if not (left[criterion] & right[criterion])
        )
        if diverged:
            findings.append({"pmid": pmid, "criteria": diverged})
    return findings


def agreement(original: dict[str, Any], replicate: dict[str, Any]) -> dict[str, Any]:
    """Compare two independent screenings of the same records."""
    if original.get("rubric_sha256") != replicate.get("rubric_sha256"):
        raise ScreeningError("agreement requires both screenings to use the same rubric version")
    first = {str(row["pmid"]): str(row.get("decision")) for row in original.get("records", []) if isinstance(row, dict)}
    second = {str(row["pmid"]): str(row.get("decision")) for row in replicate.get("records", []) if isinstance(row, dict)}
    shared = sorted(set(first) & set(second), key=int)
    if not shared:
        raise ScreeningError("the two screenings share no records")

    labels = ["include", "exclude", "uncertain"]
    matrix = {row: {column: 0 for column in labels} for row in labels}
    disagreements: list[dict[str, str]] = []
    agreed_pmids: list[str] = []
    for pmid in shared:
        a, b = first[pmid], second[pmid]
        if a in labels and b in labels:
            matrix[a][b] += 1
        if a != b:
            disagreements.append({"pmid": pmid, "original": a, "replicate": b})
        else:
            agreed_pmids.append(pmid)

    diverged = evidence_divergence(original, replicate, agreed_pmids)
    agreed = sum(matrix[label][label] for label in labels)
    counted = sum(matrix[row][column] for row in labels for column in labels)
    return {
        "operation": "screening-agreement",
        "ok": True,
        "scope_version": original.get("scope_version"),
        "rubric_sha256": original.get("rubric_sha256"),
        "compared_records": len(shared),
        "raw_agreement": round(agreed / counted, 4) if counted else None,
        "cohen_kappa": cohen_kappa(matrix, labels),
        "confusion_matrix": matrix,
        "confusion_matrix_note": "rows are the original screening decision, columns the replicate",
        "disagreements": disagreements,
        "evidence_divergence": diverged,
        "evidence_divergence_note": (
            "Same decision, no shared substantive word between the two evidence bases. Verbatim "
            "quotation checking cannot catch a real but irrelevant quote; a second reader can."
        ),
        "adjudication_required": bool(disagreements) or bool(diverged),
        "adjudication_pmids": sorted(
            {item["pmid"] for item in disagreements} | {item["pmid"] for item in diverged}, key=int
        ),
        "note": (
            "Kappa alone hides which cell disagreements fall in. Adjudicate every disagreement and "
            "every evidence divergence, then re-run to-ledger from the adjudicated worksheet."
        ),
    }


# -- cli ---------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Criterion-level candidate screening with verifiable evidence.")
    sub = parser.add_subparsers(dest="command", required=True)

    rubric = sub.add_parser("compile-rubric", help="Freeze the locked protocol's eligibility criteria as a screening rubric.")
    rubric.add_argument("--protocol", required=True)
    rubric.add_argument("--scope-version", type=int, required=True)
    rubric.add_argument("--output", required=True)

    prepare = sub.add_parser("prepare", help="Create a pending screening worksheet for a record set.")
    prepare.add_argument("--rubric", required=True)
    prepare.add_argument("--records-file", required=True)
    prepare.add_argument("--scope-version", type=int, required=True)
    prepare.add_argument("--round", type=int, default=1)
    prepare.add_argument("--output", required=True)

    validate = sub.add_parser("validate", help="Verify criterion verdicts, quoted evidence, and decision consistency.")
    validate.add_argument("worksheet")
    validate.add_argument("--rubric", required=True)
    validate.add_argument("--records-file", required=True)
    validate.add_argument("--scope-version", type=int, required=True)
    validate.add_argument("--output")

    ledger = sub.add_parser("to-ledger", help="Convert a validated worksheet into a candidate ledger.")
    ledger.add_argument("worksheet")
    ledger.add_argument("--rubric", required=True)
    ledger.add_argument("--records-file", required=True)
    ledger.add_argument("--scope-version", type=int, required=True)
    ledger.add_argument("--candidate-ledger-template")
    ledger.add_argument(
        "--agreement",
        help="screening-agreement artifact. Records it flagged must be adjudicated in the worksheet, "
        "and its summary is carried into the ledger for the completion gate.",
    )
    ledger.add_argument("--output", required=True)

    sample = sub.add_parser("sample", help="Select a decision-stratified re-adjudication sample.")
    sample.add_argument("worksheet")
    sample.add_argument("--fraction", type=float, default=0.15)
    sample.add_argument("--seed", default="pubmed-search-builder")
    sample.add_argument("--output", required=True)

    agree = sub.add_parser("agreement", help="Compare two independent screenings of the same records.")
    agree.add_argument("worksheet")
    agree.add_argument("--replicate", required=True)
    agree.add_argument("--output", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compile-rubric":
            protocol = read_json(args.protocol)
            if not isinstance(protocol, dict):
                raise ScreeningError("Protocol must be a JSON object")
            result = compile_rubric(protocol, scope_version=args.scope_version, protocol_path=args.protocol)
            write_json(args.output, result)
            receipt = {
                "operation": result["operation"],
                "ok": True,
                "output": args.output,
                "scope_version": args.scope_version,
                "criterion_count": len(result["criteria"]),
                "rubric_sha256": result["rubric_sha256"],
            }
        elif args.command == "prepare":
            rubric = load_rubric(args.rubric, scope_version=args.scope_version)
            records = records_from_file(args.records_file)
            result = prepare_worksheet(
                rubric, records,
                scope_version=args.scope_version, round_number=args.round, records_path=args.records_file,
            )
            write_json(args.output, result)
            receipt = {
                "operation": result["operation"],
                "ok": True,
                "output": args.output,
                "record_count": len(result["records"]),
                "criterion_count": len(rubric["criteria"]),
                "pending_assessments": len(result["records"]) * len(rubric["criteria"]),
            }
        elif args.command == "validate":
            rubric = load_rubric(args.rubric, scope_version=args.scope_version)
            worksheet = read_json(args.worksheet)
            if not isinstance(worksheet, dict):
                raise ScreeningError("Worksheet must be a JSON object")
            issues, summary = validate_worksheet(worksheet, rubric, records_from_file(args.records_file))
            receipt = {
                "operation": "screening-worksheet-validate",
                "ok": not issues,
                "worksheet": args.worksheet,
                "issues": issues,
                "summary": summary,
            }
            if args.output:
                write_json(args.output, receipt)
            print(json.dumps(receipt, indent=2, ensure_ascii=False))
            return 0 if not issues else 1
        elif args.command == "to-ledger":
            rubric = load_rubric(args.rubric, scope_version=args.scope_version)
            worksheet = read_json(args.worksheet)
            template = read_json(args.candidate_ledger_template) if args.candidate_ledger_template else None
            agreement_artifact = read_json(args.agreement) if args.agreement else None
            result = to_ledger(
                worksheet, rubric, records_from_file(args.records_file),
                template=template, agreement_artifact=agreement_artifact,
            )
            ledger_issues, ledger_summary = candidate_ledger.validate_ledger(result)
            if ledger_issues:
                raise ScreeningError("generated ledger failed validation: " + "; ".join(ledger_issues[:5]))
            write_json(args.output, result)
            receipt = {
                "operation": "screening-to-ledger",
                "ok": True,
                "output": args.output,
                "record_count": len(result["records"]),
                "summary": ledger_summary,
            }
        elif args.command == "sample":
            worksheet = read_json(args.worksheet)
            result = stratified_sample(worksheet, fraction=args.fraction, seed=args.seed)
            write_json(args.output, result)
            receipt = {
                "operation": result["operation"],
                "ok": True,
                "output": args.output,
                "selected": len(result["pmids"]),
                "stratum_totals": result["stratum_totals"],
            }
        else:
            worksheet = read_json(args.worksheet)
            replicate = read_json(args.replicate)
            result = agreement(worksheet, replicate)
            write_json(args.output, result)
            receipt = {
                "operation": result["operation"],
                "ok": True,
                "output": args.output,
                "compared_records": result["compared_records"],
                "raw_agreement": result["raw_agreement"],
                "cohen_kappa": result["cohen_kappa"],
                "adjudication_required": result["adjudication_required"],
            }
    except (ScreeningError, OSError) as exc:
        receipt = {"operation": args.command, "ok": False, "error": str(exc)}
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if receipt.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
