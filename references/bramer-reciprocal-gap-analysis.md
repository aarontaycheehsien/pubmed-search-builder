# Bramer Reciprocal Gap Analysis

Use this reference when a draft concept block has both a controlled-vocabulary layer and a text-word layer, and the search would benefit from checking what each layer uniquely retrieves. This is a diagnostic term-discovery method adapted from Bramer et al. 2018; it is not a final-search structure.

## When to run

Run Bramer reciprocal gap analysis when it is likely to improve term discovery or explain layer complementarity, especially when:

- the concept is central, high-risk, or vocabulary-sensitive
- no seed PMIDs are available
- MeSH-only and text-word-only counts differ sharply
- the concept uses unstable language, acronyms, devices, procedures, social/behavioral terms, or newly emerging terminology
- controlled vocabulary coverage is weak, new, sparse, or inconsistent
- the audit needs stronger evidence that both layers were tested

Record a reasoned waiver instead when the concept is simple, stable, well covered by MeSH and text words, and prior MeSH sweeps, ATM checks, seed validation, block counts, or sample inspection already explain the vocabulary.

## Diagnostic queries

Build the two layer-specific query files from the draft concept block:

```text
(MeSH/SCR layer) NOT (text-word layer)
(text-word layer) NOT (MeSH/SCR layer)
```

Use `[Mesh]`, `[Mesh:noexp]`, and `[Supplementary Concept]` terms in the controlled-vocabulary layer as actually drafted. Use `[tiab]`, proximity, wildcard, spelling, hyphenation, acronym, and phrase variants in the text-word layer as actually drafted.

Run both directions in one call with `pubmed_tool.py term-diff`, which builds the two gap queries, reports `counts` (mesh, tiab, overlap, combined, mesh_only, tiab_only), and fetches a sample of each side to inspect (a record-content command — requires `--output`):

```bash
python scripts/pubmed_tool.py term-diff --mesh-query-file concept_mesh.txt --tiab-query-file concept_text.txt --retmax 15 --output diff_concept.json
```

Building the gap-query files by hand and running `search`/`sample`/`batch` (see `mesh-and-pubmed-tools.md`) is equally valid when you want finer control.

The `NOT` operator is allowed here only because these are temporary diagnostic gap queries. Do not copy diagnostic `NOT` into the final strategy unless the protocol independently justifies an exclusion and final QA records that recall risk.

## How to interpret

Inspect samples from both gap sets. Counts alone are not enough.

- `MeSH/SCR NOT text-word` records may reveal missing title/abstract synonyms, older terminology, acronyms, spelling or hyphenation variants, or text-word phrases derived from entry terms.
- `text-word NOT MeSH/SCR` records may reveal missing descriptors, supplementary concepts, ATM mappings, recent unindexed records, or text-word-only concepts with no reliable controlled-vocabulary coverage.
- Both directions may also reveal wrong-sense terms, broad descriptors, noisy acronyms, or variants that should be rejected rather than added.

Do not add a term only because it appears in a gap set. Add it only after confirming scope and PubMed behavior, and classify it as a within-block synonym, descriptor/SCR candidate, rejected noise, or deferred/reserve term.

## Audit requirements

For each essential concept, record one of `performed`, `waived`, `not applicable`, or `not performed`.

When performed, record:

- `MeSH/SCR NOT text-word` count
- `text-word NOT MeSH/SCR` count
- sample size and saved sample JSON paths when record content informed a decision
- terms or descriptors discovered
- terms or descriptors rejected
- rationale for each accepted or rejected candidate

When waived, record the reason. When no controlled-vocabulary layer or no text-word layer exists, mark the check `not applicable` and explain why.

This per-concept status is machine-checkable. Register the essential blocks (`state register-blocks`), tag each `term-diff`/gap entry to its block (`add --block <label> ...`), or record a waiver (`state waive-requirement <label> bramer_gap "<reason>"`); then `manifest_tool.py show --require-gap-analysis` fails at handoff if any block was neither analysed nor waived. This gate is **opt-in and separate from `--require-coverage`**, reflecting the conditional nature of the check. See `references/mesh-and-pubmed-tools.md`.

## Reference

Bramer WM, de Jonge GB, Rethlefsen ML, Mast F, Kleijnen J. A systematic approach to searching: an efficient and complete method to develop literature searches. *J Med Libr Assoc*. 2018. doi:10.5195/jmla.2018.283.
