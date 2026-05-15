# Reviewing an Existing PubMed Strategy

Use this mode when the user provides a draft PubMed strategy.

Review using PRESS-style categories and script-based testing.

## 1. Translation of the question

Check whether the strategy correctly captures the review question.

Ask:

- Are the essential concepts represented?
- Are unnecessary PICO elements included?
- Are outcomes or comparators unnecessarily reducing recall?
- Are study-design filters justified?

## 2. Boolean and proximity logic

Check:

- parentheses
- operator precedence
- line structure
- excessive `AND`
- misplaced `OR`
- risky `NOT`
- overly narrow phrase logic
- proximity operators, if used

## 3. Subject headings

Use the MeSH script to check:

- missing MeSH headings
- incorrect MeSH headings
- too-broad headings
- too-narrow headings
- missing narrower headings
- entry terms
- explosion decisions
- inappropriate `[Majr]`
- inappropriate subheadings

## 4. Text words

Check for missing:

- synonyms
- MeSH entry terms as `[tiab]`
- seed-paper title/abstract terminology
- acronyms and abbreviations
- singular and plural forms
- UK and US spellings
- hyphenation variants
- older and newer terms
- wildcard stems

## 5. Spelling, syntax, and line structure

Check:

- PubMed field tags
- quotation marks
- parentheses
- truncation syntax
- invalid tags
- ambiguous nesting
- line numbering, if applicable

## 6. Limits, methodological filters, and hedges

Check recall risk from:

- date limits
- language limits
- article-type filters
- age filters
- humans-only filters
- full-text filters
- study-design filters
- evidence-type filters
- `NOT`
- `[Majr]`
- MeSH subheadings

For every methodological filter or hedge, check:

- Is the filter needed for the review question or protocol?
- Is the filter validated?
- Is it appropriate for PubMed rather than Ovid MEDLINE, Embase, CINAHL, CENTRAL, or another interface?
- Is the sensitivity-maximising, specificity-maximising, or balanced version being used?
- Is that choice justified for evidence synthesis?
- Is the source cited?
- Was the filter modified or translated?
- If modified, is the change reported and is the performance caveat stated?
- Did the filter cause loss of seed PMIDs?
- Is the filter being used in a database where it is unnecessary or inappropriate?

Preferred source families include Cochrane HSSS for RCTs, McMaster HIRU Hedges, PubMed Clinical Queries where appropriate, and ISSG-listed validated filters. See `validated-methodological-filters-and-hedges.md`.

## 7. Validation

If seed PMIDs are provided:

- test whether the draft retrieves them
- diagnose misses
- revise if appropriate

If no seed PMIDs are provided:

- use the MeSH script checks
- use the PubMed script block testing
- inspect sample retrievals
- state that validation is limited

## Review output

Use:

```markdown
## Diagnosis

[Summary of main issues]

## Revised strategy

```text
...
```

## Explanation of changes

- [change]
- [change]

## Tool checks performed

- MeSH checks:
- PubMed checks:

## Methodological filters / hedges

- Filter used:
- Purpose:
- Source:
- Version:
- PubMed appropriate: yes/no
- Adapted: yes/no
- Topic-only versus topic-plus-filter tested: yes/no
- Seed PMID loss caused by filter:

## Seed PMID validation

- Seed PMIDs provided:
- Retrieved:
- Missed:
- Revisions made:

## Remaining sensitivity risks

- [risk]
```
