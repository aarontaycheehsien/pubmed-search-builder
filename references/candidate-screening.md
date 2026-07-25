# Candidate Evidence Screening

Use this reference after retrieval scope version 1 is locked and before candidate records influence objective term mining or validation.

## Purpose

Build a candidate evidence set without allowing seeds, PubMed neighbors, or a pilot query to redefine the review. Keep four evidence roles distinct:

- **User seed:** supplied as likely relevant, but still checked against the locked scope.
- **Discovery record:** screened in and permitted to contribute title/abstract, keyword, and MeSH candidates.
- **Held-out validation record:** screened in but frozen before term mining; use only to test retrieval.
- **Heuristic neighbor:** unscreened or uncertain related/citation record; may support a clearly labelled heuristic benchmark, never term mining or claims of relevance.

## Required sequence

1. Validate, compile, and lock `review_protocol_v1.json` before fetching or mining candidate records. Instantiate its `candidate_ledger_template_v1.json` before screening protocol-declared seeds.
2. Collect candidate PMIDs from supplied seeds, PubMed similar articles, citation links, or independently identified prior-review included studies. With no seeds, use the six orthogonal pilots below rather than one defining pilot.
3. Fetch candidate metadata to saved JSON. Inspect titles and abstracts where available; receipt-only stdout is not screening evidence.
4. Compile the screening rubric from the locked protocol and screen every candidate with `scripts/screening_tool.py` (below) as `include`, `exclude`, or `uncertain` against the locked scope. Each decision records a verdict per criterion, quoted evidence supporting it, and how the decision was made.
5. Assign one use role: `discovery`, `holdout`, `both`, `heuristic`, or `neither`.
6. Save and validate `candidate_ledger.json` with `scripts/candidate_ledger.py`. When roles have not already been frozen, use `--allocate-holdout --ledger-output <path>` for a deterministic allocation.
7. Mine only records that the validator marks eligible for discovery.

## Screening against a frozen rubric

Screening is the pivot of the workflow — only included records teach the search new vocabulary, and a subset becomes the held-out set the strategy is measured against. A decision plus a reason string only demonstrates that the form was filled in. `scripts/screening_tool.py` requires the decision to be supported by the record.

```bash
# Freeze the protocol's eligibility criteria as an immutable, hash-bound rubric.
python scripts/screening_tool.py compile-rubric --protocol review_protocol_v1.json \
  --scope-version 1 --output screening_rubric_v1.json

# One pending assessment per criterion per record, bound to each record's content hash.
python scripts/screening_tool.py prepare --rubric screening_rubric_v1.json \
  --records-file candidate_records.json --scope-version 1 --round 1 --output screening_worksheet_1.json

# After screening: verify verdicts, quoted evidence, and decision consistency.
python scripts/screening_tool.py validate screening_worksheet_1.json --rubric screening_rubric_v1.json \
  --records-file candidate_records.json --scope-version 1 --output screening_validation_1.json

python scripts/screening_tool.py to-ledger screening_worksheet_1.json --rubric screening_rubric_v1.json \
  --records-file candidate_records.json --scope-version 1 \
  --candidate-ledger-template protocol_v1/candidate_ledger_template_v1.json --output candidate_ledger.json
```

Each criterion takes one of four verdicts: `yes`, `no`, `unclear`, or `not_reported`. `unclear` and `not_reported` are distinct and both meaningful: the record is ambiguous, versus the record never addresses the criterion.

Evidence is a quotation plus the field it came from (`title`, `abstract`, `keywords`, `mesh_headings`). The validator checks the quotation appears verbatim in that field of the hash-bound record, so an unsupported quotation is no easier to write than an unsupported reason was. Whitespace and casing are normalised; invented text is not accepted.

Existing in the record is necessary but not sufficient. Two further floors reject quotations that cannot function as evidence at all: a span made only of function words and research boilerplate cites nothing, and a span over 60 words points at nothing in particular rather than at the sentence that decides the criterion. The validation summary also reports `distinct_evidence_spans` against `verified_evidence_spans`, and lists `single_span_records` — records where one span was reused as the sole evidence for three or more criteria. That is not rejected, because a dense sentence can legitimately settle two criteria at once, but it is the signature of a quotation pasted once rather than read per criterion.

These floors remove the cheap ways to fake evidence. None of them establishes that a quotation *supports* the verdict it is attached to — a screener can cite a real, substantive, but irrelevant sentence. That is what the agreement check tests, and why it is required.

Decisions must follow from the verdicts, and evidence requirements are criterion-specific:

- **include** — every required-inclusion criterion is `yes` *and* carries supporting evidence, and no decisive exclusion applies.
- **exclude** — at least one decisive failure (a decisive exclusion `yes`, or a required inclusion `no`) with supporting evidence. Only the failure the decision rests on needs evidence.
- **uncertain** — everything else. Any required criterion left `unclear` or `not_reported` forces `uncertain`, so absent information can never become a silent exclusion.

### Decision provenance and rule-based screening

Every decision records `decided_by`: `human`, `model`, `rule`, or `human_verified_model`. A hardcoded PMID list is a legitimate way to encode decisions a reviewer already made — what matters is that the artifact preserves how they were reached.

Rules may prioritise, triage, and pre-fill. They may not be the final authority for records that carry evidence roles: a `rule` decision with no `adjudicated_by` cannot take `discovery`, `holdout`, or `both`. `to-ledger` demotes such a record to `heuristic`, and `candidate_ledger.py` refuses a ledger that forces one into an evidence role.

This is the guardrail against circular screening. A lexicon that excludes records lacking already-known vocabulary suppresses exactly the unfamiliar terminology vocabulary learning exists to find. The restriction is not that rules mention search terms — legitimate eligibility criteria overlap with search vocabulary by nature — but that a rule alone cannot finalise the records the evidence base is built from.

### Agreement check (required)

An agreement check is not optional polish. Verifying that a quotation exists in a record cannot show that it supports the verdict; only a second independent reading tests that, so the completion gate requires one covering at least 15% of screened records with every flagged record adjudicated.

```bash
# Select the records to re-screen independently, then screen them into a replicate worksheet.
python scripts/screening_tool.py sample screening_worksheet_1.json --fraction 0.15 --output screening_sample_1.json

python scripts/screening_tool.py agreement screening_worksheet_1.json \
  --replicate screening_worksheet_1_replicate.json --output screening_agreement_1.json

# Adjudicate everything it flagged (set `adjudicated_by` on those records), then build the ledger.
python scripts/screening_tool.py to-ledger screening_worksheet_1.json --rubric screening_rubric_v1.json \
  --records-file candidate_records.json --scope-version 1 \
  --agreement screening_agreement_1.json --output candidate_ledger.json
```

The sample is stratified by decision. A simple random sample of a screening set is mostly obvious excludes and measures very little; stratifying puts includes and uncertains — where errors actually cost recall — into the check.

The report gives raw agreement and a confusion matrix alongside Cohen's κ, because κ alone hides which cell the disagreements fall in. It also reports **`evidence_divergence`**: records where both screenings reached the *same* decision but cited evidence with no substantive word in common. Decision-level agreement is blind to this — κ is 1.0 while one reader is pointing at text that is not the reason. It is the only mechanical signal that a real quotation may still be the wrong one.

`to-ledger --agreement` refuses to build the ledger until every record in `adjudication_pmids` — disagreements and evidence divergences alike — carries `adjudicated_by` in the worksheet. It then carries the agreement summary into `screening_provenance.agreement`, which is what the completion gate reads.

After screening, use `active-vocabulary-learning.md`. Only newly included `discovery`/`both` records may generate proposals. Excluded records receive a separate diagnostic and never supply proposed search terms. Assign every included record to existing locked concepts before extraction; an unknown concept or changed eligibility interpretation requires scope re-entry.

Do not feed a related-record set directly to `term-rank` merely because a PMID has high seed overlap or similarity. Those scores prioritize screening; they do not establish eligibility.

For no-seed discovery, use `no_seed_discovery.py` and screen the generated file without opening its separate provenance map. Merge MeSH-led, exact-phrase-led, operational-description-led, prior-review-led, citation/registry-led, and historical-terminology-led candidates before screening. Reveal provenance only after decisions are saved. Continue rounds until both relevant-study and vocabulary novelty remain zero for the required consecutive rounds; a reached safety cap prevents a saturation claim.

## Ledger schema

```json
{
  "scope_version": 1,
  "records": [
    {
      "pmid": "12345678",
      "provenance": "user-seed",
      "decision": "include",
      "title_abstract_reviewed": true,
      "eligibility_reason": "Matches the locked population and intervention scope.",
      "use": "holdout",
      "screening": {
        "rubric_sha256": "<hash of the frozen rubric criteria>",
        "record_sha256": "<hash of the record content that was read>",
        "decided_by": "model",
        "adjudicated_by": "",
        "evidence_backed": true,
        "rule_only": false,
        "criterion_verdicts": {"inc_population": "yes", "inc_intervention": "yes", "exc_design": "no"}
      }
    }
  ]
}
```

Allowed provenance values are `user-seed`, `pilot-anchor`, `similar`, `citedin`, `reference`, `prior-review`, and `other`.

`screening_tool.py to-ledger` writes the `screening` block. Ledgers screened before it existed have no such block and still validate, but the validation summary reports them under `screening_provenance.evidence_roles_without_screening_provenance`, and the completion gate requires the block on every `discovery`, `holdout`, or `both` record. Re-screen those records rather than hand-writing the block.

Use roles mean:

- `discovery`: may contribute terms; not an independent validation record.
- `holdout`: may validate retrieval; never contribute terms before the final validation run.
- `both`: may contribute terms and validate, but validation is explicitly non-independent.
- `heuristic`: may appear only in a labelled heuristic benchmark.
- `neither`: retained for the screening audit but excluded from discovery and validation.

An `exclude` record must use `neither`. An `uncertain` record may use only `heuristic` or `neither`. A discovery, holdout, or both record must be screened `include`, have title/abstract review recorded, and carry a non-empty eligibility reason.

## Development and holdout allocation

Freeze the holdout before mining. When the confirmed relevant set is large and diverse enough, reserve a representative subset across eras, terminology, indexing status, and study types. As a practical heuristic, with at least six confirmed records reserve at least two records or about 20%, whichever is larger, unless that would make the discovery set unusably small.

After validation, pass the ledger itself to `pubmed_tool.py related`, `mine`, `term-rank`, `study-family`, `validate`, and `recall` with `--candidate-ledger`. The tool resolves role-safe PMIDs: discovery commands cannot consume holdouts, and validation prefers holdouts. Avoid copying PMID lists by hand.

Use `pubmed_tool.py study-family --candidate-ledger candidate_ledger.json` to discover candidate companion reports through similar/cited/reference links and group records sharing trial registration IDs. Every result remains `screening_status: pending`; family linkage is a discovery signal, not an inclusion decision.

When the set is too small, use `both` and state that known-item validation is non-independent. Never imply that re-finding records used for term discovery demonstrates sensitivity.

## Scope protection and re-entry

Classify a candidate against the current scope; do not widen the scope merely to include it. If several plausible records expose a structural mismatch, record a `scope-challenge` finding and route it through `references/press-critic.md`:

- lexical mismatch: revise vocabulary within the same scope version;
- block-role mismatch: reopen the concept gate and issue a new scope version;
- eligibility ambiguity: ask the user or follow the protocol before proceeding.

After a scope-version change, re-evaluate affected candidate decisions and record which ledger version supersedes the prior one.

## Audit requirements

Record candidate sources, counts by decision and use, evidence files reviewed, excluded/uncertain reasons, holdout allocation, whether validation is independent, and every ledger version. Keep heuristic neighbors separate from screened-in records throughout the audit.
