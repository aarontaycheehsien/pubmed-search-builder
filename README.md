# PubMed Search Builder

**High-sensitivity Boolean search strategy development for PubMed - built for evidence syntheses.**

A comprehensive toolkit for building, testing, and validating PubMed search strategies that prioritize **recall over precision**. Includes bundled tools for MeSH descriptor lookup, text-word expansion, wildcard testing, seed PMID validation, and PRESS-style peer review.

Used for systematic reviews, scoping reviews, rapid reviews, evidence maps, and narrative syntheses where missing relevant records is costlier than screening extra noise.

---

## Table of Contents

- [Quick Start](#quick-start)
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
git clone https://github.com/YOUR-USERNAME/pubmed-search-builder.git
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

## Core Concepts

### High-Sensitivity Searching

The canonical workflow and high-sensitivity search model live in [`references/workflow.md`](references/workflow.md). In short, the toolkit combines controlled vocabulary, title/abstract terms, proximity expressions, and wildcard candidates for each essential concept, then tests the resulting blocks for recall and noise.

### PRESS Peer Review

All strategies produced by this toolkit are drafts. They must be peer-reviewed by a second information specialist using the **PRESS** framework (McGowan et al., 2016, *J Clin Epidemiol*) before being run as a final search.

---

## Bundled Tools

### PubMed E-utilities (`scripts/pubmed_tool.py`)

Query PubMed, fetch records, validate seed PMIDs, and test strategy variants.

**Common commands:**

```bash
# Count-test a single term
python scripts/pubmed_tool.py search "asthma[tiab]" --retmax 0

# Fetch detailed metadata for known PMIDs
python scripts/pubmed_tool.py fetch --pmids 24102982 21171099

# Sample a few records from a query
python scripts/pubmed_tool.py sample "asthma[Mesh] OR asthma[tiab]" --retmax 3

# Validate whether a strategy retrieves known seed PMIDs
python scripts/pubmed_tool.py validate "(asthma[Mesh] OR asthma[tiab])" --pmids 24102982 21171099

# Batch-test multiple variants (queries.json or tab-delimited text)
python scripts/pubmed_tool.py batch queries.json

# Check NCBI email/API-key configuration without exposing secrets
python scripts/pubmed_tool.py doctor
```

**Features:**

- **Query translation analysis**: Automatic inspection of PubMed's translation and query mapping
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

### Audit Markdown (`scripts/audit_markdown.py`)

Render structured audit notes to the required Markdown audit report without
printing the whole report into the terminal.

```bash
python scripts/audit_markdown.py audit.json --output audit_2026-05-18.md
python scripts/audit_markdown.py audit.json --output audit_2026-05-18.md --if-exists fail
python scripts/audit_markdown.py references/audit-example.json --output audit_example.md
```

By default, the tool writes the full audit report to disk and prints only a
small JSON receipt with the output path, byte count, placeholder count, and
section count. If the output path already exists, it chooses a clear numeric
suffix by default; use `--if-exists fail` when a collision should stop the run.
Use `--print-report` only when the full Markdown should be printed.

Use [`references/audit-example.json`](references/audit-example.json) as a
starter input and [`references/audit-json-schema.md`](references/audit-json-schema.md)
for the minimal field contract.

---

## Workflow

See [`references/workflow.md`](references/workflow.md) for the authoritative step-by-step workflow, including the seed-pause rule, concept gate, MeSH and text-word expansion, PubMed testing, seed validation, revision, final QA, audit Markdown handoff, and PRESS peer-review framing.

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

- **Python 3.7+** (3.10+ recommended)
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
- **[references/workflow.md](references/workflow.md)**: Detailed step-by-step workflow
- **[references/goal-tracking.md](references/goal-tracking.md)**: Goal tracking state rules, pre-goal intake, blockers, and completion audit
- **[references/mesh-and-pubmed-tools.md](references/mesh-and-pubmed-tools.md)**: Tool usage and operational sequence
- **[references/tiab-expansion.md](references/tiab-expansion.md)**: Title/abstract expansion sources and strategies
- **[references/wildcard-and-truncation.md](references/wildcard-and-truncation.md)**: Wildcard safety, the 600-variant cap, and testing
- **[references/seed-pmid-validation.md](references/seed-pmid-validation.md)**: Seed PMID validation workflow
- **[references/validated-methodological-filters-and-hedges.md](references/validated-methodological-filters-and-hedges.md)**: Cochrane, McMaster, and other validated filters
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
@software{pubmed_search_builder_2024,
  title = {PubMed Search Builder: High-Sensitivity Boolean Search Strategy Development},
  author = {AUTHOR_NAME},
  year = {YEAR},
  url = {https://github.com/YOUR-USERNAME/pubmed-search-builder}
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
