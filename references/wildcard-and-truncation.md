# Wildcard and Truncation Guidance

Use wildcard and truncation aggressively for candidate generation, but retain stems based on PubMed testing.

Do not treat wildcard expansion as automatically good. Treat it as a tool for discovering and capturing predictable variants.

## Use wildcards to capture

- plural forms
- adjectival forms
- noun forms
- verb forms
- predictable morphology
- UK and US spelling variants where feasible
- older and newer word endings

## Usually reasonable candidate stems

These are candidate stems that are often reasonable after context and PubMed testing; they are not universally safe. By default, prefer the longest phrase-anchored or concept-specific stem feasible.

```text
amputat*[tiab]
postamputat*[tiab]
neuromodulat*[tiab]
neurostimulat*[tiab]
rehabilitat*[tiab]
prosthe*[tiab]
diabet*[tiab]
random*[tiab]
screen*[tiab]
ulcer*[tiab]
injur*[tiab]
ischemi*[tiab]
ischaemi*[tiab]
pediatric*[tiab]
paediatric*[tiab]
```

## Risky stems

```text
care*[tiab]
pain*[tiab]
cell*[tiab]
gene*[tiab]
mani*[tiab]
rate*[tiab]
```

Risky does not mean forbidden. It means test before keeping.

## Stems PubMed will not truncate

A word-final asterisk truncates only when at least four characters precede it, counted from the start of its term or quoted phrase. With fewer, PubMed silently drops the asterisk and searches the bare word. It gives no error or warning, so the intended variants are simply lost. Confirmed against live PubMed:

| Query | PubMed searches |
|---|---|
| `cat*[tiab]` | `"cat"[Title/Abstract]` |
| `il6*[tiab]` | `"il6"[Title/Abstract]` |
| `tb*` | `"tb"[All Fields]` |
| `"cat* scratch"[tiab]` | `"cat scratch"[Title/Abstract]` |
| `"scratch cat*"[tiab]` | `"scratch cat*"[Title/Abstract]` (truncated: the phrase supplies more than four leading characters) |

A mid-word wildcard such as `ca*t` or `colo*r` is not truncation and has no such minimum. Final QA (`hooks_tool.py final-qa`) rejects a word-final stem shorter than four characters as an error. The query-translation hook on every PubMed search reports `truncation_dropped` whenever an asterisk is missing from PubMed's translation. Spell out the variants (`cat[tiab] OR cats[tiab]`) or lengthen the stem.

## Candidate-generation rules

When considering truncation:

1. Prefer the longest stem that captures the desired variants.
2. Avoid very short stems unless unavoidable.
3. Prefer phrase-anchored or concept-specific stems over generic stems.
4. Pair wildcard stems with phrase variants when needed.
5. Consider both UK and US spelling when one stem cannot capture both safely.
6. Use explicit singular/plural forms when wildcarding is unsafe.

Broad single-token stems are candidates only. Test them in context before calling them safe or retaining them in a final strategy.

Example:

```text
neurostimulat*[tiab]
```

is usually safer than:

```text
stimulat*[tiab]
```

Example:

```text
postamputat*[tiab]
OR "post-amputation"[tiab]
OR "post amputation"[tiab]
```

is better than relying on only one exact phrase.

For quoted `[tiab]` phrases with predictable phrase-final singular/plural morphology, test a phrase-final wildcard candidate when it may affect recall:

```text
"immune checkpoint inhibitor*"[tiab]
OR "triple negative breast cancer*"[tiab]
```

Explicit singular/plural phrase variants remain acceptable, but only after judgment or testing shows that wildcarding is unsafe, unnecessary, or no better than the explicit forms.

## Wildcard testing protocol

For wildcard stems that may affect recall, use the PubMed script to test:

1. the wildcard alone
2. the wildcard inside its concept block
3. the full search with and without the wildcard
4. whether the wildcard retrieves seed PMIDs
5. whether sample records are plausible
6. whether the wildcard causes overwhelming unrelated noise

## Keep stems when they

- rescue seed PMIDs
- retrieve plausible relevant records
- capture expected morphology
- capture singular and plural forms
- capture terminology used in PubMed samples
- remain acceptable when combined with another strong concept block

## Remove, narrow, or replace stems when they

- add overwhelming unrelated noise
- do not rescue seed PMIDs
- do not retrieve plausible relevant records
- are too short or semantically unstable
- are better replaced by explicit phrase variants

## Wildcard caveat

Wildcarded terms and field-tagged terms can alter or bypass PubMed Automatic Term Mapping.

Do not assume a wildcarded term maps to MeSH.

Do not assume a wildcarded phrase behaves like an untagged PubMed query.

For high sensitivity, explicitly include:

```text
MeSH terms
OR
title/abstract variants
OR
wildcard stems
```

## Current PubMed wildcard limits

Current PubMed Help no longer documents the older variant-expansion cap. Do not warn that PubMed silently drops variants after a fixed expansion count.

Current practical limits and behaviours:

- Terms must have at least 4 characters before the first wildcard (`colo*`).
- Wildcards can appear in the middle of terms and phrases, and multiple wildcards can be used in the same term or phrase (`organi*ation*`, `colo*r`, `"colo* cancer*"`).
- PubMed searches wildcarded terms for possible variations, which can add unintended noise.
- Wildcards turn off Automatic Term Mapping, including MeSH mapping and explosion.
- NLM Office Hours in June 2024 stated a limit of 256 wildcard operators per query. Live ESearch confirms it: a query with 257 asterisks fails with "Search Backend failed ... Search is temporarily unavailable ... Cannot search because the number of wildcards (*) exceeds 256". The message looks like a transient outage but is a query error. `pubmed_tool.py` blocks such a query before sending it and never retries this error, and final QA rejects it.

Practical implications:

- Test short stems (`care*`, `pain*`, `cell*`, `gene*`) with the PubMed script for noise and expected retrieval.
- Use the longest phrase-anchored or concept-specific stem feasible. `neurostimulat*` is safer than `stimulat*`. `paediatric*` is safer than `pediat*`.
- Replace or supplement noisy short stems with explicit phrase variants for important common forms.
- Check PubMed Search Details because wildcarding can change translation and suppress Automatic Term Mapping.

## Truncation and proximity are mutually exclusive

PubMed proximity searches (`"word1 word2"[field:~N]`) cannot include truncation. If a wildcard appears inside the double-quoted terms of a proximity expression, PubMed ignores the proximity operator and treats the search as ordinary phrase/wildcard search. Choose one or the other in a given expression.

Pattern: use proximity for distinctive multi-word concepts where word order varies, and use wildcards for predictable morphology of single tokens. Combine them across `OR` arms within the concept block, not within a single expression.
