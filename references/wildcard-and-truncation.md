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
cat*[tiab]
man*[tiab]
care*[tiab]
arm*[tiab]
pain*[tiab]
rat*[tiab]
```

Risky does not mean forbidden. It means test before keeping.

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

## The 600-variant cap

PubMed retrieves at most the first 600 variants of a truncated stem (per the PubMed User Guide entry on wildcards). When a stem expands to more than 600 variants, the additional variants are silently dropped: PubMed does not return an error, and the search appears to run normally.

This is a **sensitivity hazard**. A short or generic stem can silently exclude common wanted variants.

Practical implications:

- Test short stems (`care*`, `pain*`, `cell*`, `gene*`) with the PubMed script to confirm whether expected variants are reached.
- Use the longest concept-specific stem feasible. `neurostimulat*` is safer than `stimulat*`. `paediatric*` is safer than `pediat*`.
- When the cap is plausibly hit, replace or supplement the wildcard with **explicit phrase variants** for the common forms you care about. The phrase variants act as a safety net when the cap silently truncates the wildcard expansion.
- Note that PubMed's wildcard implementation (since the 2024 update, NLM Tech Bull. 2024 May-Jun) supports wildcards in the middle of terms and multiple wildcards per term (`organi*ation*`, `colo*r`); these are useful but increase the variant-count risk.

## Truncation and proximity are mutually exclusive

PubMed proximity searches (`"word1 word2"[field:~N]`) cannot include truncation. If a wildcard appears inside the double-quoted terms of a proximity expression, PubMed ignores the proximity operator and treats the search as ordinary phrase/wildcard search. Choose one or the other in a given expression.

Pattern: use proximity for distinctive multi-word concepts where word order varies, and use wildcards for predictable morphology of single tokens. Combine them across `OR` arms within the concept block, not within a single expression.
