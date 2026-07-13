# Review Protocol DSL

Use the versioned review-protocol DSL when a protocol must pre-resolve scope decisions for an unattended or reproducible build. The protocol is the human-authored source of truth; compiled files are disposable workflow inputs and must never be edited as a substitute for revising the protocol.

## Root sections

A version `1` protocol contains:

- `dsl_version`, `protocol_id`, and `scope_version`;
- `version_change`, identifying the prior scope version, reason, and decision source;
- `review`, containing the plain-language question and framework slots;
- `eligibility`, containing explicit inclusion and exclusion criteria;
- `searchable_scope.concepts`, with stable IDs, concept roles, eligibility/framework links, definitions, rationale, provisional fragility, and optional term families;
- `screening_only.properties`, for eligibility properties that are unsafe as required search blocks;
- `filters_and_limits.decisions` and `date_boundaries`;
- `seeds.records`, with candidate roles rather than assumed eligibility;
- `priorities`, separating the recall policy from workload-based selection; and
- optional `information_source_mode` and `external_validation`, selecting `pubmed-only` (the default) or a registry-based PubMed leak check; and
- `focused_variants`, which may prioritize screening but cannot replace the recall-first main strategy.

See `schemas/review-protocol.schema.json` for the binding field and value constraints.

## Validate, compile, and verify

```bash
python scripts/protocol_tool.py validate review_protocol_v1.json --mode draft
python scripts/protocol_tool.py validate review_protocol_v1.json --mode lock
python scripts/protocol_tool.py compile review_protocol_v1.json --output-dir protocol_v1 --receipt protocol_v1/protocol_compile_v1.json
python scripts/protocol_tool.py verify review_protocol_v1.json --receipt protocol_v1/protocol_compile_v1.json
```

`draft` validation permits unresolved authoring work reported by the tool. `lock` validation is the pre-search gate: it must pass before candidate records, MeSH, or PubMed results influence vocabulary or structure.

Compilation writes deterministic workflow inputs such as:

- `concept_ledger_vN.json`;
- `candidate_ledger_template_vN.json`;
- `block_registry_vN.json`;
- `critic_packet_vN.json`;
- `audit_outline_vN.json`; and
- `protocol_compile_vN.json`.

The compile receipt binds generated files to the exact protocol content. Run `verify` before resuming or handing off a build so stale or manually edited derived artifacts cannot pass as current protocol evidence.

## Scope changes

When evidence challenges a concept role, eligibility interpretation, date boundary, filter, or limit:

1. stop adoption of the proposed change;
2. revise the source protocol;
3. increment `scope_version` by one;
4. set `version_change.previous_scope_version`, `reason`, and `decision_source`;
5. rerun lock validation and compilation; and
6. re-screen or re-probe every affected downstream artifact.

Vocabulary expansion inside an unchanged concept does not require a new scope version. Adding, removing, redefining, or changing the role of a concept does.

## Legacy artifacts

Use the migration command for an older retrieval-scope JSON:

```bash
python scripts/protocol_tool.py migrate-scope retrieval_scope_v1.json --output review_protocol_v1.json --report protocol_migration_report.json
```

Migration is intentionally conservative. Review every reported ambiguity and placeholder, then run `validate --mode lock`; a mechanically migrated file is not automatically an approved protocol.
