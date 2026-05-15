# Title/Abstract Expansion

For high-sensitivity PubMed searching, `[tiab]` expansion is essential.

Recent records may lack MeSH indexing. Authors may use language that differs from MeSH. Indexing may be inconsistent. Acronyms may appear without full forms.

## Sources for `[tiab]` variants

Use:

- MeSH preferred descriptors
- MeSH entry terms
- MeSH scope notes
- narrower MeSH descriptors
- related MeSH descriptors
- seed paper titles
- seed paper abstracts
- author keywords, where available
- PubMed sample records
- common clinical or disciplinary synonyms
- acronyms and abbreviations
- acronym expansions
- spelling variants
- hyphenated and non-hyphenated forms
- singular and plural forms
- adjective and noun forms
- eponyms
- lay terms
- older terminology
- newer terminology
- drug generic names, brand names, and class names
- device, procedure, or intervention variants
- Greek-letter, spelled-out, and symbol variants
- Roman numeral and Arabic numeral variants

## Variant checklist

For each important phrase, consider:

```text
full phrase
short phrase
acronym
acronym with punctuation
singular
plural
hyphenated form
non-hyphenated form
closed compound
open compound
UK spelling
US spelling
noun form
adjective form
older term
newer term
eponym
lay term
technical term
truncated stem
word-order variant
```

Do not assume one exact phrase is enough.

## Plural handling

Do not assume PubMed will automatically handle plurals when terms are field-tagged with `[tiab]`.

Use one of three approaches.

### 1. Safe wildcard stem

```text
ulcer*[tiab]
injur*[tiab]
wound*[tiab]
amputat*[tiab]
intervention*[tiab]
```

### 2. Explicit singular and plural phrase variants

```text
"pressure injury"[tiab]
OR "pressure injuries"[tiab]
OR "pressure ulcer"[tiab]
OR "pressure ulcers"[tiab]
```

### 3. Phrase variants plus wildcard stems

```text
"phantom limb"[tiab]
OR "phantom limbs"[tiab]
OR "phantom limb pain"[tiab]
OR amputat*[tiab]
OR postamputat*[tiab]
```

## Phrase loosening

For distinctive multi-word concepts, include exact phrases and looser variants.

Example:

```text
"shared decision making"[tiab]
OR "shared decision-making"[tiab]
OR "shared decision"[tiab]
OR "decision sharing"[tiab]
OR ((shared[tiab] OR sharing[tiab]) AND decision*[tiab])
```

Use looser constructions when exact phrases may miss records.

Do not use loose constructions that overwhelm the concept unless PubMed testing suggests they rescue relevant records or remain acceptable when combined with another concept block.

## Proximity searching (preferred for many phrase-loosening cases)

PubMed has supported proximity searching since November 2022 (NLM Tech Bull. 2022 Novâ€“Dec). Syntax:

```text
"word1 word2"[field:~N]
```

- `field` must be `[ti]`, `[tiab]`, or `[ad]`. Other fields are not supported.
- `N` is the maximum number of words that may appear between the search terms, in any order.
- Two or more terms inside the double quotes.

Examples:

```text
"shared decision making"[tiab:~2]
"rationing healthcare"[tiab:~2]
"hip pain"[ti:~4]
```

Important behaviour:

- Automatic Term Mapping is **not** applied to proximity searches.
- Truncation/wildcards (`*`) inside the quoted terms cause the proximity operator to be ignored. Choose either proximity or wildcards in a given expression, not both.
- Stopwords inside quoted proximity terms are searched as regular words.
- A higher `N` increases recall but also noise. Test multiple values of `N`.

When to prefer proximity over loose Boolean:

- distinctive multi-word concepts where word order varies in the literature (e.g. "shared decision making" / "decision making shared with patient")
- where `(X OR Y) AND Z*[tiab]` constructions retrieve too much unrelated noise
- where the exact phrase variants are numerous and brittle

When **not** to use proximity:

- when one of the words in the phrase needs truncation that proximity cannot accommodate
- when the concept is well captured by a tight exact phrase plus a few hyphenation variants
- when a MeSH heading already covers the concept reliably

Pattern combining proximity with the rest of a concept block:

```text
(
  "Decision Making, Shared"[Mesh]
  OR "shared decision making"[tiab]
  OR "shared decision-making"[tiab]
  OR "shared decisionmaking"[tiab]
  OR "shared decision"[tiab:~2]
  OR "decision shared"[tiab:~2]
)
```

Test proximity expressions with the PubMed script before retaining them, in the same way as wildcards: check that they retrieve plausible records, that they capture seed PMIDs where applicable, and that the noise level is acceptable when combined with another concept block.

## Acronyms

Include common acronyms as candidates.

For ambiguous acronyms:

1. test the acronym alone
2. test it inside the concept block
3. test it with another essential concept
4. inspect sample records
5. keep it if it plausibly retrieves relevant records
6. restrict to `[ti]` only if `[tiab]` is catastrophically noisy

Do not discard acronyms solely because they are ambiguous.
