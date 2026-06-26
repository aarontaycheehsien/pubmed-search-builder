# PRISMA-S 2021 Reporting Notes

PRISMA-S (Rethlefsen et al., 2021, Systematic Reviews) is the reporting extension for the literature search component of systematic reviews. The checklist has 16 items in four sections.

This skill produces a PubMed search strategy. It does not produce the full set of search-related reporting items needed by an evidence synthesis. The notes below say which items the skill addresses, which items the skill flags but cannot fully produce, and what the user should expect to add when reporting the full review.

When producing the final output, tag each reporting note with the PRISMA-S item number where applicable.

## Section 1: Information sources and methods

### Item 1. Database name

Within scope. State the database (PubMed) and the platform/interface used. Note that PubMed and MEDLINE are not equivalent: PubMed includes records not yet indexed for MEDLINE, in-process records, ahead-of-print records, and other content beyond MEDLINE.

```text
Database: PubMed (NLM interface, https://pubmed.ncbi.nlm.nih.gov/).
```

### Item 2. Multi-database searching

Out of scope for this skill, but flag the requirement. Most evidence syntheses require searching at least one further bibliographic database (e.g. Embase, CINAHL, the Cochrane Library, Web of Science, regional databases). State in the output that the PubMed strategy will need translation for each additional database, and that translation is non-trivial because syntax, controlled vocabulary, and field tags differ.

```text
Note: this strategy covers PubMed only. The review protocol should specify additional databases and the strategy must be translated for each.
```

### Items 3-7. Study registries, online resources and browsing, citation searching, contacts, other methods

Out of scope for this skill. Flag in the output that supplementary search methods are typically required for systematic reviews and similar evidence syntheses, including trial registries (ClinicalTrials.gov, ICTRP), grey literature sources, citation searching (forward and backward), reference list checking, hand-searching key journals, and contacting authors or experts. These are reported separately by the review team.

## Section 2: Search strategies

### Item 8. Full search strategies

Within scope and central. Report the **full** PubMed strategy as actually constructed, not a paraphrase. Include every line, every field tag, every Boolean operator, and every parenthesis. The strategy must be reproducible from the report alone.

### Item 9. Limits and restrictions

Within scope. Report every limit applied and the justification for each. Note recall risk where applicable. Examples:

```text
No language limits were applied.
No date limits were applied.
No article-type filters were applied.
No species or humans-only filter was applied.
```

or:

```text
A date limit of 2015 onwards was applied because [reason from the protocol]. This may exclude relevant earlier records.
A language limit to English was applied because [reason]. This is acknowledged as a recall-reducing restriction.
```

If no limits were applied, say so explicitly. Silence is not adequate reporting under PRISMA-S.

### Item 10. Search filters

Within scope where the strategy uses a methodological filter or search hedge. Where a validated filter is used (study design, evidence type, age group, etc.), cite the source, version, interface, and any adaptation.

Examples:

```text
A validated RCT filter was applied: Cochrane Highly Sensitive Search Strategy, sensitivity-maximising version (2008 revision), PubMed format.
```

```text
A validated diagnosis filter was applied: McMaster Health Information Research Unit (HIRU) Hedges, broad/sensitive version for PubMed.
```

```text
A systematic-review filter was applied: PubMed systematic[sb]. This was used instead of systematic review[pt] because systematic[sb] uses a broader search strategy as well as publication-type logic.
```

For each filter or hedge, report:

- filter name
- methodological purpose
- source
- version, such as sensitivity-maximising, specificity-maximising, broad, narrow, or balanced
- database and interface
- exact filter syntax used
- whether it was adapted
- what changed if adapted
- why the filter was needed
- recall risk
- whether seed PMIDs were lost when the filter was added

If a filter is adapted, state what was changed. Do not silently inline filter logic without attribution. Filters from the InterTASC ISSG Search Filter Resource should be cited with their source URL or publication, and inclusion in ISSG should not be treated as automatic endorsement.

### Item 11. Prior work

If the search strategy was based on, or adapted from, an existing strategy (e.g. a previous review on the same topic, a published Cochrane protocol, or a textbook example), cite the source. State whether terms were copied directly, adapted, or used as inspiration only.

### Item 12. Updates

If the search will be updated, state the planned update interval. If this is a one-off search, state that no updates are planned. Within scope to flag.

### Item 13. Dates of searches

Within scope. Report the date the final search was run, in `YYYY-MM-DD` format. If multiple runs were performed (e.g. development run, validation run, final run), report each.

```text
Search strategy developed: [date].
Final search run: [date].
```

## Section 3: Peer review

### Item 14. Peer review

Within scope to flag. State that the strategy was peer reviewed by a second information specialist using a structured instrument (typically PRESS, McGowan et al., 2016, J Clin Epidemiol), or state explicitly that no peer review has occurred.

```text
This draft strategy has not yet been peer reviewed. Per PRESS (McGowan et al., 2016), it should be peer reviewed by a second information specialist before being run as the final search.
```

If peer review has occurred, name the reviewer (or state that they wish to remain anonymous), the date, and any changes made in response.

## Section 4: Managing records

### Items 15-16. Total records and deduplication

Out of scope for the search-construction phase. Flag that the review team will report total records retrieved per database, total after deduplication, and the deduplication method (software, manual, or both) once the search has been run.

## Caveats to record

State plainly when relevant:

- the strategy is a draft and has not been peer reviewed
- Tool calls were unavailable, partial, or returned errors during construction
- hit counts were correct on the date tested but will change over time
- recent records may lack MeSH indexing and rely on text-word coverage
- noisy terms were retained for sensitivity
- zero-hit terms (no current PubMed records) were removed and documented by default (removal is recall-neutral since they match no records), or kept per an explicit user choice; exact duplicate terms were removed as recall-neutral cleanup
- limits and filters reduce recall and were applied for the stated reasons only
- methodological filters or hedges were validated, PubMed-appropriate, and reported with source/version/interface where used
- adapted filters may no longer have the published performance of the original
- any relative-recall estimate is a search-development QA aid relative to its benchmark, not a reported search sensitivity and not a substitute for PRESS peer review; a seed-expansion benchmark is a heuristic and was labelled as such

## Output template

Use this block in the final report, mapping each line to the PRISMA-S item number.

```text
Database (Item 1): PubMed (NLM interface).
Multi-database searching (Item 2): [out of scope for this strategy; see protocol for full database list].
Study registries / online resources / citation searching / contacts / other methods (Items 3-7): [reported separately by review team].
Full search strategy (Item 8): [reproduced verbatim above].
Limits and restrictions (Item 9): [list each, with justification and recall risk note].
Search filters (Item 10): [name each filter/hedge, source, version, interface, exact syntax, adaptations, reason for use, recall risk, and seed-PMID impact; or state none used].
Prior work (Item 11): [cite source if strategy was adapted; otherwise state none].
Updates (Item 12): [planned interval, or none].
Date of final search (Item 13): [YYYY-MM-DD].
Peer review (Item 14): [reviewer and date, or state not yet peer reviewed].
Total records and deduplication (Items 15-16): [to be reported by review team after the search is run].
```

## Reference

Rethlefsen ML, Kirtley S, Waffenschmidt S, et al. PRISMA-S: an extension to the PRISMA Statement for Reporting Literature Searches in Systematic Reviews. Syst Rev. 2021;10(1):39. DOI: https://doi.org/10.1186/s13643-020-01542-z

McGowan J, Sampson M, Salzwedel DM, Cogo E, Foerster V, Lefebvre C. PRESS Peer Review of Electronic Search Strategies: 2015 Guideline Statement. J Clin Epidemiol. 2016;75:40-46. DOI: https://doi.org/10.1016/j.jclinepi.2016.01.021

For methodological filters and hedges, see `validated-methodological-filters-and-hedges.md`.
