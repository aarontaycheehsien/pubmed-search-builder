#!/usr/bin/env python3
"""PubMed wildcard rules that fail silently or look like an outage.

Both rules below were confirmed against live PubMed ESearch:

* A word-final asterisk truncates only when at least four characters precede it, counted from
  the start of its term or quoted phrase. Otherwise PubMed drops the asterisk and searches the
  bare word, with no error or warning: ``cat*[tiab]`` runs as ``"cat"[Title/Abstract]``,
  ``"cat* scratch"[tiab]`` as ``"cat scratch"``, while ``"scratch cat*"[tiab]`` keeps its
  truncation. A mid-word wildcard (``ca*t``) is not truncation and has no such minimum.
* A query with more than 256 asterisks is rejected with an HTTP 200 "Search Backend failed ...
  temporarily unavailable ... number of wildcards (*) exceeds 256" response, which reads like a
  transient outage rather than a problem with the query.
"""

from __future__ import annotations

import re
from typing import Any

MIN_TRUNCATION_PREFIX = 4
MAX_WILDCARDS = 256

_FIELD_TAG = re.compile(r"\[[^\]]*\]")
_TERM = re.compile(r'"([^"]*)"|([^\s()"]+)')
_WORD_BEFORE = re.compile(r"([A-Za-z0-9][A-Za-z0-9'-]*)$")


def wildcard_terms(query: str) -> list[dict[str, Any]]:
    """Every asterisk in the query with the term or phrase it belongs to.

    Field tags are removed first so their contents are never read as search terms.
    """

    text = _FIELD_TAG.sub(" ", str(query or ""))
    found: list[dict[str, Any]] = []
    for match in _TERM.finditer(text):
        segment = match.group(1) if match.group(1) is not None else match.group(2)
        for position, character in enumerate(segment):
            if character != "*":
                continue
            prefix = segment[:position]
            following = segment[position + 1 : position + 2]
            word = _WORD_BEFORE.search(prefix)
            found.append(
                {
                    "term": segment.strip(),
                    "word": word.group(1) if word else "",
                    "word_final": not (following.isalnum()),
                    "prefix_length": len(re.sub(r"[\s*]", "", prefix)),
                }
            )
    return found


def short_truncations(query: str) -> list[str]:
    """Terms whose word-final truncation PubMed silently ignores (too few leading characters)."""

    return sorted(
        {
            item["term"]
            for item in wildcard_terms(query)
            if item["word_final"] and item["prefix_length"] < MIN_TRUNCATION_PREFIX
        }
    )


def wildcard_count(query: str) -> int:
    return str(query or "").count("*")


def dropped_truncations(query: str, translation: str) -> list[str]:
    """Words whose truncation is absent from PubMed's translation of the query."""

    translated = str(translation or "").casefold()
    if not translated.strip():
        return []
    dropped = {
        f"{item['word']}*"
        for item in wildcard_terms(query)
        if item["word_final"] and item["word"] and f"{item['word']}*".casefold() not in translated
    }
    return sorted(dropped)
