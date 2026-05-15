---
name: pubmed-search-builder
description: "Use this skill when formulating, reviewing, testing, or improving high-sensitivity Boolean search strategies for PubMed for systematic reviews, scoping reviews, evidence maps, rapid reviews, and other evidence syntheses where recall matters more than precision. Includes bundled PubMed E-utilities and MeSH RDF scripts for controlled vocabulary lookup, text-word expansion, wildcard and proximity testing, seed PMID validation, and PRESS-style review."
---

# PubMed High-Sensitivity Search Builder

## Core Goal

Build, review, test, and improve high-sensitivity PubMed Boolean strategies for evidence syntheses. Minimize missed relevant records. Precision is secondary, but noise should be tested, explained, and controlled where it can be controlled without damaging recall.

Do not simply convert the user's natural-language topic into a Boolean string. Use this workflow:

```text
question
-> optional seed PMIDs
-> essential concept selection
-> MeSH lookup
-> PubMed exploration
-> text-word, proximity, and wildcard candidate generation
-> concept-block testing
-> seed PMID validation, if seeds were provided
-> revision
-> documented draft strategy for human peer review
```

For high-sensitivity PubMed searching, use this mental model:

```text
(MeSH layer OR title/abstract layer OR proximity/wildcard layer)
AND
(MeSH layer OR title/abstract layer OR proximity/wildcard layer)
```

MeSH does not replace free text. Free text does not replace MeSH. Proximity and wildcards do not replace either.

## Bundled Tools

Use the bundled scripts from this skill directory. They output JSON by default.

### PubMed E-utilities

Use `scripts/pubmed_tool.py` for PubMed search, fetch, sample inspection, and seed validation:

```bash
python scripts/pubmed_tool.py search "asthma[tiab]" --retmax 5
python scripts/pubmed_tool.py search --query-file query.txt --retmax 0
python scripts/pubmed_tool.py search --query-stdin --retmax 0
python scripts/pubmed_tool.py fetch --pmids 24102982
python scripts/pubmed_tool.py sample "asthma[tiab]" --retmax 3
python scripts/pubmed_tool.py validate "(asthma[Mesh] OR asthma[tiab])" --pmids 24102982 21171099
python scripts/pubmed_tool.py batch queries.json
python scripts/pubmed_tool.py doctor
```

Use `--query-file` or `--query-stdin` for long PubMed strategies to avoid shell quoting problems. Use `batch` for count testing multiple blocks or strategy variants; batch input may be a JSON object of label-to-query pairs, a JSON array of `{ "label": "...", "query": "..." }` objects, a JSON array of query strings, or tab-delimited text lines (`label<TAB>query`). Use `doctor` to confirm NCBI email/tool/API-key status and run a tiny live PubMed check without printing the API key or email value.

`pubmed_tool.py` includes two automatic hooks:

- `pre_command_hook`: blocks API keys on the command line, warns about long inline queries, reminds count-only testing to use `--retmax 0`, and warns on very large `retmax` values.
- `post_search_log`: writes local JSONL search logs with timestamp, query, count, query translation, warnings, and email/API-key configured status. It never writes the NCBI email or API-key value. Default path: `%USERPROFILE%\.codex\pubmed-search-builder\logs\pubmed-search-log.jsonl`. Override with `PUBMED_SEARCH_BUILDER_LOG`; disable with `PUBMED_SEARCH_BUILDER_LOG_DISABLED=1`.

The script uses these NCBI settings from environment variables or Windows user environment variables:

- `NCBI_EMAIL` should be set by the local user to comply with NCBI E-utilities contact guidance.
- `NCBI_TOOL` defaults to `codex-search-strategy-check`.
- `NCBI_API_KEY` is read only from the environment.

Do not put NCBI API keys in queries, command-line arguments, scripts, examples, or files intended for source control. Command output and local search logs record only whether an email or API key was configured, never the email or key value.

Rate limiting is 3 requests/second without `NCBI_API_KEY` and 10 requests/second when `NCBI_API_KEY` is set.

### MeSH RDF

Use `scripts/mesh_tool.py` for MeSH descriptor, term, detail, and SPARQL checks:

```bash
python scripts/mesh_tool.py lookup --label Ofloxacin --match exact
python scripts/mesh_tool.py details --descriptor D015242 --include terms,seealso,qualifiers
python scripts/mesh_tool.py terms --label Pyrin --match exact
python scripts/mesh_tool.py sweep --concept "bipolar disorder" --variant "bipolar affective disorder" --details
python scripts/mesh_tool.py sparql "SELECT * WHERE { ?s ?p ?o } LIMIT 5"
```

### Strategy Hooks

Use `scripts/hooks_tool.py` for non-network checks before final output:

```bash
python scripts/hooks_tool.py final-qa --strategy-file final_strategy.txt
python scripts/hooks_tool.py filter-check --text-file protocol_or_strategy.txt
```

Run `final-qa` before presenting a final draft. It flags recall hazards such as `[Majr]`, unexplained `NOT`, language/date/species/age/publication-type/full-text limits, short wildcards, proximity with truncation, and missing MeSH or `[tiab]` layers.

Run `filter-check` whenever the request, protocol, or strategy mentions a study-design/evidence-type intent such as RCTs, systematic reviews, qualitative studies, diagnostic accuracy, prognosis, observational studies, or economic evaluations. If a methodological filter is needed, read `references/validated-methodological-filters-and-hedges.md`, use `pubmed_tool.py batch` to compare topic-only and topic-plus-filter counts, validate seed PMID impact when seeds exist, and cite the validated filter source/version/interface/adaptation.

For the operational sequence and what to check at each step, read `references/mesh-and-pubmed-tools.md`. For methodological filters and search hedges, read `references/validated-methodological-filters-and-hedges.md` before adding any methodological filter.

Never fabricate MeSH descriptors, entry terms, PubMed counts, PMIDs, or validation results. If a script cannot be run because network access is unavailable, say so and mark the affected checks as not performed.

## First Response

At the start of a new strategy-building task, ask once whether the user has known relevant seed PMIDs. Make clear that seeds are optional and that the strategy can proceed without them. If the user already provided seeds, do not ask again.

If no seeds are provided, continue. Seeds are helpful but not compulsory.

## Concept Selection

Extract the review question into candidate concepts:

- population or problem
- intervention, exposure, phenomenon, or condition
- comparator, if essential
- outcome, if essential
- study type, if required
- setting, date, language, or population limits, if explicitly required by the protocol

Classify each concept as:

- essential concept: must be searched
- possible concept: may help but risks reducing recall
- omitted concept: deliberately excluded to preserve sensitivity
- filter concept: study design, evidence type, date, language, publication type, age group, species, or another limit

High sensitivity usually means using two or three essential concept blocks, not every PICO element. Be aggressive within `OR` blocks. Be cautious about adding more `AND` blocks.

Default structure:

```text
(concept 1)
AND
(concept 2)
AND
(optional concept 3)
```

Do not treat a study-design or evidence-type filter as an ordinary ad hoc `AND` block. If the protocol genuinely requires one, consult `references/validated-methodological-filters-and-hedges.md` and prefer a validated PubMed filter or hedge.

## Aggressive MeSH And PubMed Work

For every essential concept:

1. Build a variant list before selecting MeSH: user phrase, synonyms, acronyms, spelling variants, hyphen variants, older/newer terminology, seed-paper title/abstract terms, seed-paper MeSH headings, and PubMed ATM/query translation terms.
2. Run `mesh_tool.py sweep --concept "..." --variant "..." --details` for the concept and variants. The sweep runs exact, contains, and startswith descriptor searches plus exact, contains, and startswith entry-term searches.
3. Inspect every plausible candidate descriptor or supplementary concept returned by the sweep. Check preferred label, entry terms, related descriptors, allowable qualifiers where available, and whether it is too broad, too narrow, wrong sense, obsolete, duplicate, or noisy.
4. Run additional separate sweeps for subtypes, syndromes, device names, procedures, intervention families, drug classes, generic drug names, common acronyms, newer terminology, and older terminology. Do not assume a parent descriptor covers every clinically meaningful synonym.
5. Use MeSH RDF SPARQL when tree, broader/narrower, or descendant checks are needed to decide explosion versus `[Mesh:noexp]`.
6. Use `pubmed_tool.py search` with `--retmax 0` to count-test each accepted and rejected candidate descriptor, each text-word cluster, each wildcard stem, each concept block, and the combined strategy.
7. Use `pubmed_tool.py sample` to inspect whether retrieved records are plausible when a descriptor looks broad or ambiguous.
8. If seed PMIDs are provided, use `pubmed_tool.py fetch` to harvest assigned MeSH headings and compare them against the sweep candidates, then use `pubmed_tool.py validate` for retrieval checks.

Use `[Mesh]` for exploded MeSH headings unless there is a clear reason not to. Use `[Mesh:noexp]` only when deliberately avoiding narrower terms. Avoid `[Majr]` and MeSH subheadings for high-sensitivity searches unless explicitly justified.

The MeSH work is incomplete unless the final output documents accepted descriptors/supplementary concepts and rejected plausible candidates with reasons.

## Text Words, Proximity, And Wildcards

Generate `[tiab]` candidates aggressively, then retain them based on testing. Sources include MeSH entry terms, seed-record titles and abstracts, synonyms, acronyms, singular/plural forms, UK/US spellings, hyphenation variants, older and newer terminology, lay/technical variants, and safe wildcard stems.

Do not assume PubMed handles plurals or spelling variants automatically when terms are field-tagged with `[tiab]`. Field tags suppress Automatic Term Mapping.

PubMed proximity syntax:

```text
"word1 word2"[tiab:~N]
```

This retrieves the words within N words of each other in any order. Proximity is available for `[ti]`, `[tiab]`, and `[ad]`; Automatic Term Mapping does not apply; truncation and proximity cannot be combined inside the same expression.

PubMed wildcard/truncation has a 600-variant expansion cap. Use the longest concept-specific stem feasible, and pair wildcards with explicit phrase variants where the stem is short or risky. See `references/tiab-expansion.md` and `references/wildcard-and-truncation.md`.

## Seed PMID Validation

If seed PMIDs are provided, use them for both term discovery and validation:

- Fetch seed records and mine titles, abstracts, publication types, MeSH headings, and keywords.
- Validate whether the topic-only draft retrieves each in-scope seed.
- If a filter is used, validate the topic-only strategy and topic-plus-filter strategy separately.
- Diagnose missed seeds and revise where appropriate.

Do not overfit to seeds. If a seed is genuinely out of scope, report it rather than distorting the strategy.

See `references/seed-pmid-validation.md`.

## Reviewing An Existing Strategy

When the user provides an existing PubMed strategy, review it using PRESS-style categories:

- translation of the question
- Boolean and proximity logic
- subject headings
- text words
- spelling, syntax, and line structure
- limits, methodological filters, and hedges
- validation

Use the scripts to verify, not intuition. See `references/review-existing-strategy.md`.

## Stop Condition

Stop revising when:

- all in-scope seed PMIDs are retrieved, or misses are explained
- each essential concept has MeSH plus text-word coverage
- important plural, spelling, hyphenation, acronym, proximity, and wildcard candidates have been considered
- PubMed testing has been performed for concept blocks and the combined strategy
- if a methodological filter is used, topic-only and topic-plus-filter strategies have both been tested
- if seed PMIDs are supplied, any seed loss caused by the filter has been diagnosed
- `hooks_tool.py final-qa` has been run and all errors are resolved
- `hooks_tool.py filter-check` has been run when any methodological filter or evidence-type intent is present
- further expansion mainly adds unrelated noise
- remaining limitations are documented
- the strategy is flagged as a draft pending human peer review

## Final Output Format

Use this structure.

````markdown
## Search structure

Concept 1: [name]
Concept 2: [name]
Optional concept: [name, if used]
Methodological filter/hedge: [name, if used; otherwise state none]

## Final PubMed strategy (draft)

```text
(...)
AND
(...)
```

## Tool work performed

### MeSH checks
- [Descriptor checked]: [decision]
- Rejected plausible descriptors/supplementary concepts: [candidate and reason]

### PubMed checks
- [Block/query tested]: [result count or observed behaviour]

## Title/abstract, proximity, and wildcard expansion log

- Seed-derived `[tiab]` variants added: [list]
- MeSH-entry-derived `[tiab]` variants added: [list]
- Acronyms and abbreviations added: [list]
- Singular/plural variants added: [list]
- Spelling variants added: [list]
- Hyphenation variants added: [list]
- Proximity expressions added: [list]
- Wildcard stems added: [list]
- Wildcard stems tested but rejected: [list and reason]

## Rationale

- [Explain MeSH choices]
- [Explain text-word, proximity, and wildcard choices]
- [Explain omitted concepts]
- [Explain filters or limits]
- [Explain sensitivity versus precision trade-offs]

## Methodological filters / hedges

- Filter used: [name or none]
- Purpose: [RCT / diagnosis / prognosis / qualitative / systematic review / observational / economic / other]
- Source: [Cochrane HSSS / McMaster HIRU Hedges / PubMed Clinical Queries / ISSG / other]
- Version: [sensitivity-maximising / specificity-maximising / balanced / not stated]
- Interface: PubMed
- Adapted: yes/no
- If adapted, what changed: [details]
- Reason for using filter: [protocol/design requirement]
- Recall risk: [brief note]
- Topic-only result count: [if tested]
- Topic-plus-filter result count: [if tested]
- Seed PMID impact: [none lost / lost PMIDs listed / not tested]

## Seed PMID validation

Seed PMIDs provided: [yes/no]

If yes:
- Seed PMIDs tested: [list]
- Retrieved: [list]
- Missed: [list]
- Revisions made after seed testing: [summary]
- Seeds judged out of scope, if any: [list and reason]

If no:
- Validation was limited to MeSH checks, PubMed block testing, and inspection of sample retrievals.

## Peer review status

This is a draft strategy. Per PRESS (McGowan et al., 2016), it should be peer reviewed by a second information specialist before being run as the final search.

## Reporting notes

For PRISMA-S 2021 reporting items applicable to this skill, see `references/prisma-s-reporting.md`.

- Database: PubMed
- Date searched: [date]
- Limits, restrictions, filters, and validated hedges used: [state clearly with source, version, interface, and any adaptation]
- Restrictions and their justification: [state clearly]
- Remaining caveats: [state clearly]
````

## References

- `references/workflow.md`: full workflow.
- `references/mesh-and-pubmed-tools.md`: how to use the bundled scripts.
- `references/validated-methodological-filters-and-hedges.md`: validated filters and hedges.
- `references/tiab-expansion.md`: title/abstract expansion guidance.
- `references/wildcard-and-truncation.md`: wildcard risk and testing.
- `references/seed-pmid-validation.md`: seed validation workflow.
- `references/review-existing-strategy.md`: PRESS-style review workflow.
- `references/prisma-s-reporting.md`: reporting notes.
- `references/examples.md`: example patterns.
