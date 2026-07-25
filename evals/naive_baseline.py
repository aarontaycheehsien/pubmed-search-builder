#!/usr/bin/env python3
"""Compile a deterministic floor strategy from a fixture's own review protocol.

Only two of the bundled fixtures ship a baseline strategy, so a suite score across all of them
had nothing to score. This module supplies the missing comparison point without inventing one:
each essential concept's ``term_families`` are OR-ed as title/abstract terms and the concepts
are AND-ed together.

What it is: a reproducible floor -- what the protocol's own vocabulary retrieves with no MeSH
layer, no entry-term expansion, no wildcard or proximity testing, and no critic loop. Two
properties make it usable as evidence. It is derived only from the protocol, never from the gold
set, so it cannot be tuned toward the answer key. And it is deterministic, so a change in a
fixture's score is a change in PubMed or in the fixture, never in the baseline.

What it is not: the skill's recall. The skill's contribution is precisely the layers this floor
omits, so reporting a floor score as the skill's performance would understate it as badly as
reporting a hand-tuned strategy would overstate it. Every row the suite prints carries its
strategy source for that reason.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ESSENTIAL = "essential"

# `make_fixture.py` seeds a fixture with a default protocol whose only term family is the review
# title, expecting the author to refine it. An unrefined family reaches PubMed as one long
# phrase and retrieves nothing, which would enter a results table as 0% recall -- a fixture that
# was never finished, reported as a measurement of the search. Detected and refused instead.
UNREFINED_MIN_WORDS = 4


class NaiveBaselineError(ValueError):
    pass


def unrefined_reason(concept: dict[str, Any]) -> str | None:
    """Flag a concept whose term families are still the generated placeholder."""
    families = concept.get("term_families")
    if not isinstance(families, list) or len(families) != 1:
        return None
    only = " ".join(str(families[0]).split())
    if len(only.split()) < UNREFINED_MIN_WORDS:
        return None
    return (
        f"concept {concept.get('id') or concept.get('label')!r} has a single term family that is a "
        f"full sentence ({only[:60]!r}); refine the protocol's searchable_scope before scoring"
    )


def tiab_clause(term: str) -> str:
    """Render one term family entry as a title/abstract clause."""
    cleaned = " ".join(str(term).split())
    if not cleaned:
        return ""
    # Quote anything that is not a single bare token; PubMed treats an unquoted multi-word
    # string as a phrase search anyway, but quoting keeps the emitted query unambiguous.
    if " " in cleaned or "-" in cleaned:
        return f'"{cleaned}"[tiab]'
    return f"{cleaned}[tiab]"


def concept_block(concept: dict[str, Any]) -> str:
    families = concept.get("term_families")
    if not isinstance(families, list) or not families:
        raise NaiveBaselineError(
            f"essential concept {concept.get('id') or concept.get('label')!r} has no term_families"
        )
    clauses: list[str] = []
    seen: set[str] = set()
    for term in families:
        clause = tiab_clause(str(term))
        key = clause.casefold()
        if clause and key not in seen:
            seen.add(key)
            clauses.append(clause)
    if not clauses:
        raise NaiveBaselineError(f"concept {concept.get('id')!r} produced no usable term clauses")
    return "(\n  " + "\n  OR ".join(clauses) + "\n)"


def compile_from_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    scope = protocol.get("searchable_scope")
    if not isinstance(scope, dict):
        raise NaiveBaselineError("review_protocol has no searchable_scope")
    concepts = [
        item
        for item in scope.get("concepts", [])
        if isinstance(item, dict) and item.get("role") == ESSENTIAL
    ]
    if not concepts:
        raise NaiveBaselineError("review_protocol declares no essential searchable concepts")
    unrefined = [reason for reason in (unrefined_reason(concept) for concept in concepts) if reason]
    if unrefined:
        raise NaiveBaselineError("protocol is unrefined: " + "; ".join(unrefined))
    blocks = [concept_block(concept) for concept in concepts]
    query = "\nAND\n".join(blocks) + "\n"
    return {
        "query": query,
        "sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "concepts": [
            {
                "id": concept.get("id"),
                "label": concept.get("label"),
                "term_count": len(concept.get("term_families") or []),
            }
            for concept in concepts
        ],
        "blocks": [
            {"label": str(concept.get("label") or concept.get("id") or f"block {index}"), "query": block}
            for index, (concept, block) in enumerate(zip(concepts, blocks), start=1)
        ],
        "derivation": (
            "essential concepts -> OR term_families as [tiab] -> AND across concepts; "
            "no MeSH, entry-term expansion, wildcard, proximity, or critic revision"
        ),
    }


def compile_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    protocol = fixture.get("review_protocol")
    if not isinstance(protocol, dict):
        raise NaiveBaselineError(
            f"fixture {fixture.get('id')!r} has no structured review_protocol to derive a baseline from"
        )
    result = compile_from_protocol(protocol)
    result["fixture_id"] = fixture.get("id")
    return result


def write_strategy(compiled: dict[str, Any], directory: Path, topic_id: str) -> tuple[Path, Path | None]:
    """Persist the derived strategy and its concept blocks for per-block bottleneck diagnosis."""
    directory.mkdir(parents=True, exist_ok=True)
    strategy_path = directory / f"{topic_id}.naive.strategy.txt"
    strategy_path.write_text(compiled["query"], encoding="utf-8")
    blocks_path: Path | None = None
    if compiled.get("blocks"):
        blocks_path = directory / f"{topic_id}.naive.blocks.json"
        blocks_path.write_text(
            json.dumps(compiled["blocks"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return strategy_path, blocks_path
