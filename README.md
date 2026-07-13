# PubMed Search Builder

**High-sensitivity Boolean search strategy development for PubMed - built for evidence syntheses.**

A comprehensive toolkit for building, testing, and validating PubMed search strategies that prioritize **recall over precision**. It locks conceptual scope before record evidence, prescreens candidate studies, mines MeSH and author language, validates with held-out records when possible, and runs a versioned PRESS-informed internal critic/revision loop before human peer review.

Used for systematic reviews, scoping reviews, rapid reviews, evidence maps, and narrative syntheses where missing relevant records is costlier than screening extra noise.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Review Protocol DSL](#review-protocol-dsl)
- [Core Concepts](#core-concepts)
- [Bundled Tools](#bundled-tools)
- [Workflow](#workflow)
- [Examples](#examples)
- [Requirements](#requirements)
- [API Key Setup](#api-key-setup)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/aarontaycheehsien/pubmed-search-builder.git
cd pubmed-search-builder
```

### 2. Set up environment
```bash
cp .env.example .env
# Edit .env and add your NCBI email (recommended) and API key (optional)
```

### 3. Test installation
```bash
python scripts/pubmed_tool.py doctor
```

This confirms your NCBI email/API key and runs a test query without exposing credentials.

---

## Review Protocol DSL

For unattended, resumable, or audited builds, encode scope decisions in a versioned `review_protocol*.json` rather than a free-form prompt. Validate and compile it before PubMed work:

```bash
python scripts/protocol_tool.py validate review_protocol_v1.json --mode lock
python scripts/protocol_tool.py compile review_protocol_v1.json --output-dir protocol_v1 --receipt protocol_v1/protocol_compile_v1.json
python scripts/protocol_tool.py verify review_protocol_v1.json --receipt protocol_v1/protocol_compile_v1.json
```

The source protocol remains authoritative. Compilation creates deterministic concept, candidate, block, critic, and audit inputs; revise and increment the protocol scope version instead of editing those generated files. See [`references/protocol-dsl.md`](references/protocol-dsl.md) and [`schemas/review-protocol.schema.json`](schemas/review-protocol.schema.json).

---

## Core Concepts

### High-Sensitivity Searching

The canonical workflow and high-sensitivity search model live in [`references/workflow.md`](references/workflow.md). In short, the toolkit combines controlled vocabulary, title/abstract terms, proximity expressions, and wildcard candidates for each essential concept, then tests the resulting blocks for recall and noise.

### PRESS Peer Review

All strategies produced by this toolkit are drafts. They must be peer-reviewed by a second information specialist using the **PRESS** framework (McGowan et al., 2016, *J Clin Epidemiol*) before being run as a final search.

---

## Bundled Tools

### PubMed E-utilities (`scripts/pubmed_tool.py`)

Query PubMed, fetch records, discover candidate studies through similar articles/citation chaining, validate records and blocks, estimate relative recall against a labelled benchmark, rank candidate terms from screened discovery records, and test strategy variants.

**Common commands:**

```bash
# Count-test a single term
python scripts/pubmed_tool.py search "asthma[tiab]" --retmax 0

# Fetch detailed metadata for known PMIDs
python scripts/pubmed_tool.py fetch --pmids 24102982 21171099 --output seed_fetch.json

# Discover candidate PMIDs (screen them before term mining)
python scripts/pubmed_tool.py related --pmids 24102982 21171099 --links similar,citedin

# Discover candidate companion reports and group shared trial registrations
python scripts/pubmed_tool.py study-family --candidate-ledger candidate_ledger.json

# Sample a few records from a query
python scripts/pubmed_tool.py sample --query-file asthma_block.txt --retmax 3 --output sample_asthma_block.json

# Validate whether a strategy retrieves known seed PMIDs
python scripts/pubmed_tool.py validate "(asthma[Mesh] OR asthma[tiab])" --pmids 24102982 21171099

# Estimate relative recall against a benchmark set, with per-concept-block miss diagnosis
python scripts/pubmed_tool.py recall --query-file strategy.txt --benchmark-json related.json --blocks-file blocks.json

# Rank tiab/MeSH terms from role-safe screened discovery records
python scripts/pubmed_tool.py term-rank --candidate-ledger candidate_ledger.json --fields tiab,mesh

# Batch-test multiple variants (queries.json or tab-delimited text)
python scripts/pubmed_tool.py batch queries.json

# Check NCBI email/API-key configuration without exposing secrets
python scripts/pubmed_tool.py doctor

# Offline robustness self-checks (no network): tolerant flags, encoding, retry visibility
python scripts/pubmed_tool.py selftest
```

**Features:**

- **Query translation analysis**: Automatic inspection of PubMed's translation and query mapping
- **Evidence-preserving record output**: `fetch`, `mine`, and `sample` require `--output`, save full JSON, and print only receipt-style stdout
- **API key protection**: Blocks exposure of API keys in queries or output
- **Rate limiting**: Automatic handling of 3 req/sec (no key) vs 10 req/sec (with key)

### MeSH RDF Tools (`scripts/mesh_tool.py`)

Lookup MeSH descriptors and supplementary concepts by term, inspect entry terms and relationships, and run SPARQL queries against NLM's MeSH RDF.

**Common commands:**

```bash
# Lookup a descriptor by label (exact, contains, startswith)
python scripts/mesh_tool.py lookup --label "Diabetes Mellitus" --match exact

# Get full details: entry terms, broader/narrower, qualifiers
python scripts/mesh_tool.py details --descriptor D003920 --include terms,seealso,qualifiers

# Sweep for all variants of a concept
python scripts/mesh_tool.py sweep --concept "bipolar disorder" --variant "bipolar affective disorder" --details

# Run raw SPARQL queries on MeSH
python scripts/mesh_tool.py sparql "SELECT ?label WHERE { ?x rdf:type meshv:Descriptor ; rdfs:label ?label } LIMIT 10"
```

### Strategy QA (`scripts/hooks_tool.py`)

Pre-submission checks for recall hazards and methodological filter alignment.

```bash
# Final QA: check for recall hazards, missing MeSH/[tiab] layers, etc.
python scripts/hooks_tool.py final-qa --strategy-file my_strategy.txt

# Check whether you should add a methodological filter
python scripts/hooks_tool.py filter-check --text-file protocol.txt
```

### Concept ablation and strategy strands (`scripts/strategy_analysis.py`)

Test every proposed `AND` block by removing it, measuring known-item and workload effects, and fetching differential samples. For fragile topics, compare an authoritative recall-first strategy with a reasoned focused prioritization strand.

```bash
python scripts/strategy_analysis.py concept-ablation --blocks-file blocks.json --candidate-ledger candidate_ledger.json --scope-version 1 --output concept_ablation.json
python scripts/strategy_analysis.py two-strand --main-strategy-file final_main_strategy.txt --narrowing-blocks-file focused_blocks.json --candidate-ledger candidate_ledger.json --scope-version 1 --output two_strand.json
python scripts/strategy_analysis.py fragility-score --concepts-file fragility_concepts.json --candidate-ledger candidate_ledger.json --concept-ablation-json concept_ablation.json --scope-version 1 --output fragility_score.json
```

For no-seed builds, `scripts/no_seed_discovery.py` runs six orthogonal pilot families, writes a provenance-blinded screening file and a separate source map, tracks study/vocabulary saturation across rounds, and freezes the discovery/holdout ledger only after saturation. Pilot-family overlap is reported only as an internal convergence diagnostic; the families are dependent and are not valid capture occasions, so the tool does not report a Chao or literature-completeness estimate.

After candidate screening, `scripts/vocabulary_learning.py` extracts terms from newly included records, keeps excluded-record terminology diagnostic-only, blocks scope-changing proposals, and retests accepted within-concept additions against holdouts and differential samples.

For strategy variants, `scripts/screening_burden.py` builds reproducible complete-frame stratified samples, estimates weighted precision with confidence intervals, reports records screened per relevant report, and permits burden-based selection only among variants meeting the independent held-out recall requirement.

Every critic or vocabulary revision also passes `scripts/revision_guard.py`: the named defect must be fixed without losing prior held-out retrieval, adding an unauthorized required block, introducing syntax/translation drift, silently changing scope, or omitting before/after workload counts. Failed revisions automatically keep the baseline authoritative or remain labelled experimental-only.

### Optional Trial-Registry Sentinel (`scripts/registry_sentinel.py`)

The default workflow remains PubMed-only. When a locked protocol enables `pubmed-plus-external-validation`, the registry sentinel can query ClinicalTrials.gov API v2, import a user-obtained WHO ICTRP CSV/XML export, deduplicate and screen trials, link publications, and test eligible confidently linked PMIDs against the final PubMed strategy. Registry records stay outside PubMed term mining. Eligible linked PMID misses block handoff; non-PubMed, unpublished, registry-only, and ongoing trials are reported as coverage findings rather than PubMed query failures.

See [`references/external-trial-registry-validation.md`](references/external-trial-registry-validation.md) for commands, access conditions, ledger fields, and interpretation.

### Audit Markdown (`scripts/audit_markdown.py`)

Render structured audit notes to the required Markdown audit report without
printing the whole report into the terminal.

```bash
python scripts/audit_markdown.py audit.json --output audit_2026-05-18.md
python scripts/audit_markdown.py audit.json --output audit_2026-05-18.md --if-exists suffix
```

By default, the tool writes the full audit report to disk and prints only a
small JSON receipt with the output path, byte count, placeholder count, and
section count. Use `--print-report` only when the full Markdown should be
printed.

### Run Manifest (`scripts/manifest_tool.py`)

Maintain a canonical `run_manifest.json` provenance ledger for a build - an
append-only record of every successful command, its output path and hash, input
hashes, scope version, date, result count, and any superseded file. No network access.

```bash
python scripts/manifest_tool.py init --manifest run_manifest.json --topic-slug demo
python scripts/workflow_tool.py --manifest run_manifest.json --kind search --output search.json --input q.txt --scope-version 1 -- python scripts/pubmed_tool.py search --query-file q.txt --retmax 0 --output search.json
python scripts/manifest_tool.py show --manifest run_manifest.json --validate --check-files --require-complete-loop
python scripts/manifest_tool.py report --manifest run_manifest.json
```

`workflow_tool.py` registers a stage only when its process succeeds. The complete-loop gate parses
validation and final-QA artifacts, verifies hashes, and requires an evidence-backed version-2 critic.

---

## Workflow

See [`references/workflow.md`](references/workflow.md) for the authoritative scope lock → candidate screening → objective evidence → critic/revision loop → audit/human PRESS handoff.

The README is only a user-facing overview; use the reference workflow when building or auditing a strategy.

---

## Examples

### Example 1: Asthma in Children

**Question:** What is the evidence for treatment of asthma in children?

**Concept blocks:**
- Concept 1: Asthma (MeSH + text-word variants)
- Concept 2: Pediatric populations (MeSH + text-word variants)

**Strategy outline:**
```text
(
  "Asthma"[Mesh]
  OR asthma[tiab]
  OR asthm*[tiab]
)
AND
(
  "Child"[Mesh]
  OR child[tiab] OR children[tiab]
  OR "pediatric"[tiab] OR "paediatric"[tiab]
  OR pediatric*[tiab]
)
```

### Example 2: Diagnostic Accuracy

**Question:** What is the sensitivity and specificity of CT imaging for detecting renal artery stenosis?

**Concept blocks:**
- Concept 1: Renal artery stenosis
- Concept 2: CT imaging
- Methodological filter: Diagnostic accuracy studies, if required by the protocol (for example, a broad/sensitive McMaster HIRU diagnostic hedge or a PubMed Clinical Queries diagnostic filter)

See `references/validated-methodological-filters-and-hedges.md` for methodological filter guidance.

---

## Requirements

- **Python 3.10+**
- **NCBI email address** (recommended; see below)
- **NCBI API key** (optional but recommended; see below)
- **Internet connection** (for NCBI and NLM APIs)

No additional Python packages required. All tools use only the Python standard library (`urllib`, `json`, `xml`, etc.).

---

## API Key Setup

### Why you should set an NCBI email

NCBI recommends including an email address in E-utilities requests for compliance and contact purposes. See [NCBI Documentation](https://www.ncbi.nlm.nih.gov/books/NBK25497/#_chapter1_Setting_Up_Email_and_API_Key).

### Setting your email

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your email:
   ```
   NCBI_EMAIL=your.email@example.com
   ```

3. Test:
   ```bash
   python scripts/pubmed_tool.py doctor
   ```

### Optional: Getting an NCBI API key

Higher rate limits (10 req/sec vs 3 req/sec) are available with an API key.

1. Visit: https://www.ncbi.nlm.nih.gov/account/register/
2. Log in or create an account
3. Go to Account Settings -> API Key Management
4. Generate a key
5. Add to `.env`:
   ```
   NCBI_API_KEY=YOUR_NCBI_API_KEY
   ```

**Security note**: Never commit your `.env` file to version control. The `.gitignore` already excludes `.env` and `.env.*` files.

---

## Documentation

- **[SKILL.md](SKILL.md)**: Activation contract, routing rules, guardrails, and final report template
- **[references/protocol-dsl.md](references/protocol-dsl.md)**: Versioned review-protocol schema, validation, compilation, verification, and migration
- **[references/workflow.md](references/workflow.md)**: Detailed step-by-step workflow
- **[references/framework-selection.md](references/framework-selection.md)**: Question-type-to-framework selection (PICO, PECO, PIRD, PCC, SPIDER, etc.)
- **[references/concept-analysis-and-gating.md](references/concept-analysis-and-gating.md)**: Concept-analysis ledger, AND-block admission test, and the concept gate
- **[references/candidate-screening.md](references/candidate-screening.md)**: Candidate-study screening, discovery/holdout roles, and evidence-set integrity
- **[references/press-critic.md](references/press-critic.md)**: PRESS-informed internal critic schema, routing, and pass criteria
- **[references/goal-tracking.md](references/goal-tracking.md)**: Goal tracking state rules, pre-goal intake, blockers, and completion audit
- **[references/mesh-and-pubmed-tools.md](references/mesh-and-pubmed-tools.md)**: Tool usage and the tool-to-stage map
- **[references/tiab-expansion.md](references/tiab-expansion.md)**: Title/abstract expansion sources and strategies
- **[references/wildcard-and-truncation.md](references/wildcard-and-truncation.md)**: Wildcard safety, current PubMed wildcard limits, and testing
- **[references/bramer-reciprocal-gap-analysis.md](references/bramer-reciprocal-gap-analysis.md)**: Conditional controlled-vocabulary/text-word gap analysis
- **[references/seed-pmid-validation.md](references/seed-pmid-validation.md)**: Post-scope seed discovery, screening, term mining, and validation
- **[references/external-trial-registry-validation.md](references/external-trial-registry-validation.md)**: Optional ClinicalTrials.gov/ICTRP sentinel for external PubMed leak detection
- **[references/validated-methodological-filters-and-hedges.md](references/validated-methodological-filters-and-hedges.md)**: Cochrane, McMaster, and other validated filters
- **[references/anti-patterns.md](references/anti-patterns.md)**: Catalogued LLM failure modes with literature anchors
- **[references/audit-template.md](references/audit-template.md)**: Complete audit report Markdown template
- **[references/prisma-s-reporting.md](references/prisma-s-reporting.md)**: PRISMA-S 2021 reporting checklist
- **[references/examples.md](references/examples.md)**: Example search strategies

---

## Contributing

We welcome contributions! Areas of interest:

- Additional validated methodological filters (diagnostic accuracy, prognosis, qualitative, etc.)
- Improvements to MeSH/PubMed tool logic
- New reference documentation and examples
- Bug reports and feature requests

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Citation

If you use this toolkit in a publication, please cite:

```bibtex
@software{tay_pubmed_search_builder_2026,
  title = {PubMed Search Builder: High-Sensitivity Boolean Search Strategy Development},
  author = {Tay, Aaron},
  year = {2026},
  version = {1.0.0},
  url = {https://github.com/aarontaycheehsien/pubmed-search-builder}
}
```

---

## Acknowledgments

This toolkit is informed by:

- **PRESS** (McGowan et al., 2016, *J Clin Epidemiol*): Peer Review of Electronic Search Strategies
- **PRISMA-S** (Rethlefsen et al., 2021, *Syst Rev*): PRISMA extension for reporting search strategies
- **Cochrane Handbook**: Validated search hedges and methodological filters
- **HIRU Hedges** (McMaster University): Health Information Research Unit validated filters

---

## Support

For issues, questions, or suggestions:

1. Check the [documentation](references/) and [examples](references/examples.md)
2. Open a GitHub issue with a clear description
3. Include tool output (from `doctor` or query results) if reporting a bug

---

## Links

- [NCBI E-utilities Documentation](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
- [MeSH Database](https://meshb.nlm.nih.gov/)
- [PubMed Advanced Search](https://pubmed.ncbi.nlm.nih.gov/advanced/)
- [PRESS Checklist](http://www.cadth.ca/resources/finding-evidence/press)
- [PRISMA Statement](http://www.prisma-statement.org/)
