# Optional External Trial-Registry Validation

Use this stage to detect PubMed query leaks for reviews where intervention trials are eligible. It is optional and does not turn this skill into a multi-database review search.

## Operating modes

- `pubmed-only` is the default. Make no registry API calls and state that review-level completeness was not assessed.
- `pubmed-plus-external-validation` enables a registry sentinel whose purpose is `pubmed-leak-detection`. Registry records stay outside PubMed discovery and term mining.

Encode the choice in the locked protocol:

```json
{
  "information_source_mode": "pubmed-plus-external-validation",
  "external_validation": {
    "status": "enabled",
    "purpose": "pubmed-leak-detection",
    "sources": ["clinicaltrials.gov", "who-ictrp"]
  }
}
```

ClinicalTrials.gov API v2 is public and normally requires no API key. Save the full query, interface URL, run timestamp, API data timestamp, pagination, normalized records, and unmodified response pages. WHO states that ICTRP portal downloads are available at no charge, but do not assume unrestricted automated web-service access: the formal real-time web service is partner-based and may carry a cost. Import a user-obtained CSV/XML export and record access limitations.

Official interfaces: [ClinicalTrials.gov API](https://clinicaltrials.gov/data-about-studies/learn-about-api), [WHO ICTRP downloads](https://www.who.int/tools/clinical-trials-registry-platform/network/who-data-set/downloading-records-from-the-ictrp-database), and [WHO ICTRP web service](https://www.who.int/tools/clinical-trials-registry-platform/the-ictrp-search-portal/ictrp-search-portal-web-service).

## Workflow

Use a registry query simplified to condition and intervention concepts. Avoid publication-type, indexing, outcome, age, completion, results, or other filters unless the protocol justifies them.

```bash
python scripts/registry_sentinel.py clinicaltrials-search \
  --query 'borderline personality disorder AND psychotherapy' \
  --scope-version 1 --protocol-file review_protocol_v1.json \
  --output registry_ctgov.json

python scripts/registry_sentinel.py ictrp-import \
  --input ictrp_export.csv --scope-version 1 \
  --protocol-file review_protocol_v1.json --output registry_ictrp.json

python scripts/registry_sentinel.py merge \
  --inputs registry_ctgov.json registry_ictrp.json --scope-version 1 \
  --protocol-file review_protocol_v1.json --output registry_ledger.json
```

Screen the trial-level ledger manually against the locked eligibility criteria. Set every record to `include`, `exclude`, or `uncertain` and provide an eligibility reason; then run `screen`. Do not let registry records contribute vocabulary.

Link publications using explicit registry PMIDs and manually verified links. A links file contains `links`, each with `registry_id` or `trial_id`, optional `pmid`, citation, `link_method`, `confidence`, and `pubmed_reachability`. Ambiguous links remain uncertain and do not enter the PubMed denominator.

`clinicaltrials-search` seeds linked publications from the ClinicalTrials.gov `referencesModule`, classified by reference `type`: only `RESULT`/`DERIVED` references (publications *of* the trial) are seeded as high-confidence links. `BACKGROUND` references (literature the trial merely cites) and untyped references are seeded as `uncertain` (`link_method: registry-background-citation`) so a cited background paper the strategy legitimately does not retrieve cannot register as a missed trial report. Promote a background reference to a confident link only by manual verification.

```bash
python scripts/registry_sentinel.py screen --ledger registry_ledger_adjudicated.json \
  --scope-version 1 --protocol-file review_protocol_v1.json --output registry_screened.json
python scripts/registry_sentinel.py link-pubmed --ledger registry_screened.json \
  --links-file publication_links.json --scope-version 1 \
  --protocol-file review_protocol_v1.json --output registry_linked.json
python scripts/registry_sentinel.py evaluate-pubmed --ledger registry_linked.json \
  --retrieved-pmids-file final_strategy_retrieved_pmids.json --scope-version 1 \
  --protocol-file review_protocol_v1.json --output registry_pubmed_benchmark.json
```

## Interpretation

- Eligible linked PMID retrieved: weak positive relative-recall evidence.
- Eligible linked PMID missed: PubMed leak; investigate and resolve before handoff.
- Eligible published report without a PMID: coverage limitation, not a PubMed query failure.
- Registry results only, completed without results, ongoing, terminated, or unknown: separate evidence/surveillance findings, not PubMed misses.
- No eligible registry trials: no reassurance.

Do not mix registry trials with the orthogonal-pilot overlap diagnostic. Only screened eligible, confidently linked PubMed PMIDs form the external benchmark. High relative recall does not prove completeness, because registry coverage, registration practices, publication linkage, and eligibility screening are imperfect.

## Audit and completion

Record each source as completed, declined, unavailable, or not applicable; the query/import details and dates; source and deduplicated counts; screening decisions; publication-link methods and confidence; publication-status classes; benchmark denominator, hits, and misses; and access limitations.

In external-validation mode, unresolved eligible linked PMID misses block handoff. Non-PubMed and unpublished findings do not block the PubMed strategy, but must be reported. In PubMed-only mode, registries are not required and the handoff must explicitly say that no review-level completeness claim was made.
