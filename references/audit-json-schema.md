# Audit JSON Input Schema

This is a human-readable guide to the structured JSON consumed by `scripts/audit_markdown.py`. It is not a formal JSON Schema validator. Unknown fields are ignored, and missing fields render as `not performed` unless a renderer default exists.

## Value conventions

- The input must be a JSON object.
- Strings, numbers, booleans, lists, and objects are accepted. Lists render as semicolon-separated text in compact fields or as repeated bullets/tables where supported.
- Placeholder-like bracket text such as `[reason]` is rejected by default outside fenced strategy blocks. Use real values, `not performed`, `not available`, or `not applicable`; use `--allow-placeholders` only for drafts.
- PubMed field tags such as `[tiab]` and `[Mesh]` are safe when used as strategy syntax or descriptor syntax.

## Top-level fields

| Field | Type | Purpose and aliases |
|---|---|---|
| `title` | string | Optional Markdown title. Falls back to `topic`, then `review_question`, then `PubMed search audit`. |
| `topic` | string | Review topic and default output filename slug. Alias: `review_question`. |
| `date_searched` | string | Date used in result-count wording and default output filename. Alias: `reporting_notes.date_searched`. |
| `output_dir` | string | Default output directory when `--output` is omitted. Alias: `working_output_folder`. |
| `audit_markdown_path` | string | Output path used when `--output` is omitted. Aliases: `audit_markdown_file`, `reporting_notes.audit_markdown_path`, `reporting_notes.audit_markdown_file`. |
| `search_structure` | object | Concept structure, concept-gate status, omitted concepts, and filters or limits. |
| `concepts` | array | Concept records. Alias: `search_structure.concepts`. |
| `user_decisions` | array | User-facing decisions about optional concepts, filters, or limits. Alias: `optional_concept_decisions`. |
| `decision_ledger` | array | Main audit decision table. |
| `final_strategy` | string | Final PubMed strategy. Aliases: `strategy`, `final_pubmed_strategy`. |
| `result_count` | string or number | Final topic-only count. Aliases: `final_count`, `pubmed_cli_checks.final_combined_topic_only_strategy`. |
| `pubmed_cli_checks` | object or array | Count table for concept blocks and final strategies. Alias: `count_checks`. |
| `tiab_expansion` | object | Title/abstract, proximity, and wildcard expansion log. Alias: `title_abstract_expansion`. |
| `rationale` | object | Narrative rationale fields. |
| `seed_validation` | object | Seed PMID retrieval and validation notes. |
| `peer_review_attention_points` | array | Numbered PRESS-style review attention points. |
| `reporting_notes` | object | Database, restrictions, output paths, caveats, and other-database notes. |

## Nested objects

### `search_structure`

Use these keys:

- `concept_gate_status`
- `concepts_inside_or_blocks`
- `omitted_or_reserve_concepts`
- `methodological_filters_or_limits`

### `concepts[]`

Each concept may include:

- `name` or `concept`
- `scope` or `description`
- `coverage` or `layers`
- `mesh_review`, with aliases `mesh` or `mesh_descriptors_considered`

### `concepts[].mesh_review`

Supported keys:

- `sweep_inputs`
- `sweep_outputs_and_candidate_sources`
- `details_tree_inspected`
- `candidates_accepted`
- `candidates_rejected`
- `candidates_deferred_or_reserved`
- `scr_or_atm_mappings_resolved`
- `entry_terms_harvested_as_tiab`
- `entry_terms_omitted`
- `counts_tested`

### `user_decisions[]`

Each item may include:

- `concept`, `label`, or `decision_point`
- `offered_because` or `rationale`
- `decision`, `user_decision`, or `status`
- `handling` or `final_handling`

The seed decision line also reads `seed_status`, `seed_validation.seed_pmids_provided`, `seed_validation.seed_pmids_tested`, or top-level `seed_pmids`. The limits line reads `limit_decisions` or `filter_decisions`.

### `decision_ledger[]`

Each table row may include:

- `decision_point`
- `options_considered`
- `evidence_or_test_used`
- `decision_made`
- `rationale_or_recall_risk_note` or `rationale`
- `reflected_in_strategy_or_report` or `reflected_in`

### Strategy counts and variants

Use these optional top-level keys:

- `topic_plus_filter_count` or `filter_count`
- `focused_variant_count` or `precision_variant_count`
- `main_variant_chosen` or `chosen_variant`

For PubMed query translation notes, use `atm_translations` or `pubmed_query_translations` as an array of objects with `query`, `translation`, and `added_explicitly`.

For seed-derived MeSH notes, use `mesh_derived_from_seed_records` or `seed_mesh`.

### `pubmed_cli_checks`

This may be an object whose keys are row labels and whose values are counts or notes:

```json
{
  "Final combined topic-only strategy": 8421,
  "Topic-plus-filter strategy": "not applicable"
}
```

It may also be a list of objects with `label` or `query_tested`, plus `count`.

### `tiab_expansion`

Supported keys:

- `pre_mesh_brainstorm_required`
- `domain_framing_question_asked`
- `brainstormed_vocabulary_families_accepted`
- `brainstormed_vocabulary_families_rejected`
- `brainstormed_vocabulary_families_deferred`
- `mesh_entry_derived_tiab_variants_added`
- `seed_derived_tiab_variants_added`
- `sample_record_derived_tiab_variants_added`
- `acronyms_and_abbreviations_added`
- `acronyms_and_abbreviations_tested_but_rejected`
- `singular_plural_variants_added`
- `spelling_variants_added`
- `hyphenation_variants_added`
- `proximity_expressions_added`
- `proximity_expressions_tested_but_rejected`
- `wildcard_stems_added`
- `wildcard_stems_tested_but_rejected`

### `rationale`

Supported keys:

- `mesh_choices`
- `text_word_choices`
- `pre_mesh_vocabulary_domain_choices`
- `concept_gate_and_omitted_block_choices`
- `methodological_filters_or_limits`
- `sensitivity_vs_precision`
- `qa`

### `seed_validation`

Supported keys:

- `seed_pmids_tested`
- `retrieved`
- `missed`
- `reason_for_misses`
- `revisions_made_after_seed_testing`
- `seeds_judged_out_of_scope`

If no `seed_pmids_tested` or top-level `seed_pmids` are supplied, the rendered report states that no seed PMIDs were provided and that known-item recall was unavailable.

### `reporting_notes`

Supported keys:

- `database`
- `date_searched`
- `limits_filters_validated_filters_used`
- `restrictions_and_justifications`
- `audit_markdown_file` or `audit_markdown_path`
- `audit_workbook`
- `remaining_caveats`
- `other_databases`

See `references/audit-example.json` for a complete minimal working example.
