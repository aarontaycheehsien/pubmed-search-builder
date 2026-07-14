# Executable Workflow Contract

This file is generated from `pubmed_search_builder.workflow.stages`. Do not edit it manually.

| Stage | Legacy aliases | Required inputs | Accepted input types | Required outputs | Accepted output types | Condition |
| --- | --- | --- | --- | --- | --- | --- |
| `intake` | question-intake, seed-intake | — | — | — | — | always |
| `scope-lock` | concept-gate | protocol | protocol: legacy/unknown, protocol/receipt | scope | scope: protocol/receipt, legacy/unknown | always |
| `review-discovery` | prior-review-discovery | scope | — | review-profile, review-candidates | review-profile: review-retrieval/profile; review-candidates: review-discovery/evidence | when-evidence-synthesis-targeted |
| `candidate-discovery` | limited-seed-evidence | scope | — | candidates | — | always |
| `candidate-screening` | — | candidates | — | candidate-ledger | review-classification: review-classification/evidence | always |
| `objective-evidence` | mesh-exploration, text-word-expansion | candidate-ledger | — | evidence | — | always |
| `block-testing` | pre-mesh-brainstorm | evidence | — | block-analysis | — | always |
| `validation` | — | block-analysis | — | validation | review-filter-evaluation: review-filter/evaluation | always |
| `critic-review` | — | validation | — | critic | — | always |
| `revision` | — | critic | — | revision | — | when-critic-revises |
| `final-qa` | — | critic | — | qa | — | always |
| `audit-output` | — | qa | — | audit | audit: audit/evidence, artifact/markdown | always |
| `peer-review-handoff` | — | audit | — | handoff | handoff: artifact/markdown, artifact/file, workflow/receipt | always |

## Protocol-driven conditional outputs

| Protocol fact | Stage | Required output role |
| --- | --- | --- |
| no seed records | `candidate-discovery` | `pilot-saturation` |
| evidence-synthesis target | `review-discovery` | `review-profile`, `review-candidates` |
| evidence-synthesis target | `candidate-screening` | `review-classification` |
| evidence-synthesis target | `validation` | `review-filter-evaluation` |
| fragile essential concept | `block-testing` | `two-strand`, `screening-burden` |
| enabled external validation | `validation` | `external-validation` |
