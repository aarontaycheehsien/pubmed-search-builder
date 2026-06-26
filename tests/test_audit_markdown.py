import contextlib
import io
import json
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "audit_markdown.py"
SPEC = importlib.util.spec_from_file_location("audit_markdown", MODULE_PATH)
audit_markdown = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit_markdown)


def sample_data():
    return {
        "topic": "Asthma in children",
        "date_searched": "2026-05-18",
        "search_structure": {
            "framework": "PICO - intervention effectiveness; comparator and outcome omitted from main search",
            "concept_gate_status": "completed",
            "and_block_admission_summary": "Asthma passed as condition anchor; pediatric population passed as scope anchor",
            "concepts_inside_or_blocks": "pediatric spelling variants",
            "methodological_filters_or_limits": "none",
        },
        "concepts": [
            {
                "name": "Asthma",
                "scope": "condition",
                "coverage": "MeSH + tiab",
                "mesh_review": {
                    "sweep_inputs": ["asthma"],
                    "candidates_accepted": ['"Asthma"[Mesh]'],
                    "counts_tested": "combined concept block 192246",
                },
            }
        ],
        "decision_ledger": [
            {
                "decision_point": "Seed PMID handling",
                "options_considered": "no seeds",
                "evidence_or_test_used": "user answer",
                "decision_made": "proceed without seeds",
                "rationale": "validation limited",
                "reflected_in": "Seed PMID validation",
            }
        ],
        "final_strategy": '("Asthma"[Mesh] OR asthma[tiab])',
        "result_count": 192246,
        "pubmed_cli_checks": {"Final combined topic-only strategy": 192246},
        "seed_validation": {"seed_pmids_provided": "no"},
        "reporting_notes": {
            "database": "PubMed",
            "limits_filters_validated_filters_used": "none",
            "remaining_caveats": "not peer reviewed",
        },
    }


class AuditMarkdownTests(unittest.TestCase):
    def test_writes_markdown_and_returns_compact_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "audit.md"
            summary = audit_markdown.write_audit_markdown(
                data=sample_data(),
                output=str(output),
                if_exists="fail",
                allow_placeholders=False,
            )
            self.assertTrue(output.exists())
            self.assertEqual(summary["operation"], "audit-markdown")
            self.assertEqual(summary["output_path"], str(output))
            self.assertEqual(summary["placeholder_count"], 0)

            text = output.read_text(encoding="utf-8")
            self.assertIn("**Framework:** PICO - intervention effectiveness", text)
            self.assertIn("**AND-block admission summary:** Asthma passed", text)
            self.assertIn("## Final PubMed strategy (draft)", text)
            self.assertIn('"Asthma"[Mesh] OR asthma[tiab]', text)
            self.assertIn("## Decision ledger", text)
            self.assertIn(f"**Audit Markdown file:** {output}", text)
            self.assertNotIn("## Stage Trace", text)

    def test_overlay_json_deep_merges_before_render(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.json"
            overlay_path = Path(tmpdir) / "overlay.json"
            output = Path(tmpdir) / "audit.md"

            data = sample_data()
            data["reporting_notes"]["remaining_caveats"] = "[decision caveat]"
            audit_path.write_text(json.dumps(data), encoding="utf-8")
            overlay_path.write_text(
                json.dumps(
                    {
                        "reporting_notes": {
                            "remaining_caveats": "not peer reviewed",
                            "run_manifest": "run_manifest.json",
                        }
                    }
                ),
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = audit_markdown.main(
                    [str(audit_path), "--overlay-json", str(overlay_path), "--output", str(output)]
                )

            self.assertEqual(rc, 0)
            text = output.read_text(encoding="utf-8")
            self.assertIn("**Database:** PubMed", text)  # existing nested field preserved
            self.assertIn("**Remaining caveats:** not peer reviewed", text)
            self.assertIn("**Run manifest:** run_manifest.json", text)
            self.assertNotIn("[decision caveat]", text)

    def test_validate_only_checks_without_writing_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "audit.md"
            summary = audit_markdown.validate_audit_markdown(
                data=sample_data(),
                output=str(output),
                allow_placeholders=False,
            )

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["operation"], "audit-markdown-validate")
            self.assertEqual(summary["output_path"], str(output))
            self.assertEqual(summary["placeholder_count"], 0)
            self.assertFalse(output.exists())

    def test_validate_only_reports_placeholders_and_line_set_drift(self):
        data = sample_data()
        data["rationale"] = {"mesh_choices": "Review [reason] before final handoff."}
        data["concept_blocks"] = [{"label": "Other", "query": "other[tiab]", "count": 1}]

        summary = audit_markdown.validate_audit_markdown(
            data=data,
            output="audit.md",
            allow_placeholders=False,
        )

        self.assertFalse(summary["ok"])
        self.assertGreater(summary["placeholder_count"], 0)
        self.assertGreater(summary["line_set_issue_count"], 0)
        self.assertTrue(any("line-set drift" in issue or "not present" in issue for issue in summary["issues"]))

    def test_validate_only_cli_respects_overlay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.json"
            overlay_path = Path(tmpdir) / "overlay.json"
            output = Path(tmpdir) / "audit.md"
            data = sample_data()
            data["reporting_notes"]["remaining_caveats"] = "[decision caveat]"
            audit_path.write_text(json.dumps(data), encoding="utf-8")
            overlay_path.write_text(
                json.dumps({"reporting_notes": {"remaining_caveats": "not peer reviewed"}}),
                encoding="utf-8",
            )

            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = audit_markdown.main(
                    [
                        str(audit_path),
                        "--overlay-json",
                        str(overlay_path),
                        "--output",
                        str(output),
                        "--validate-only",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertFalse(output.exists())
            self.assertTrue(json.loads(out.getvalue())["ok"])

    def test_known_empty_lists_render_as_none(self):
        data = sample_data()
        data["seed_validation"] = {
            "seed_pmids_tested": ["1"],
            "retrieved": ["1"],
            "missed": [],
            "reason_for_misses": "none",
            "revisions_made_after_seed_testing": "none",
            "seeds_judged_out_of_scope": [],
        }
        data["pre_gate_seed_triage"] = {
            "malformed_entries_excluded": [],
            "missing_not_found_pmids_excluded": [],
        }
        data["relative_recall"] = {"retrieved_pmids": [], "missed_pmids": []}

        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))

        self.assertIn("- Missed: none", markdown)
        self.assertIn("- Seeds judged out of scope, if any: none", markdown)
        self.assertIn("- **Malformed entries excluded:** none", markdown)
        self.assertIn("- **Missing/not-found PMIDs excluded:** none", markdown)
        self.assertIn("- **Retrieved PMIDs:** none", markdown)
        self.assertIn("- **Missed PMIDs:** none", markdown)

    def test_stage_trace_renders_when_present(self):
        data = sample_data()
        data["stage_trace"] = [
            {
                "stage": "Concept gate",
                "reference_files": ["references/framework-selection.md", "references/concept-analysis-and-gating.md"],
                "action_taken": "Summarized candidate concepts before MeSH lookup",
                "blocked_actions": "MeSH/PubMed exploration; optional safety block testing",
                "decision_needed": "Whether to test a safety focused variant",
                "user_protocol_decision": "User chose not to test the focused variant",
            }
        ]
        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))

        self.assertIn("## Stage Trace", markdown)
        self.assertIn("| Stage | Reference files | Action taken | Blocked actions | Decision needed | User/protocol decision |", markdown)
        self.assertIn("Concept gate", markdown)
        self.assertIn("references/framework-selection.md; references/concept-analysis-and-gating.md", markdown)
        self.assertIn("optional safety block testing", markdown)
        self.assertIn("User chose not to test the focused variant", markdown)

    def test_existing_output_fails_by_default_and_suffixes_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "audit.md"
            output.write_text("existing", encoding="utf-8")

            with self.assertRaises(audit_markdown.AuditMarkdownError):
                audit_markdown.write_audit_markdown(
                    data=sample_data(),
                    output=str(output),
                    if_exists="fail",
                    allow_placeholders=False,
                )

            summary = audit_markdown.write_audit_markdown(
                data=sample_data(),
                output=str(output),
                if_exists="suffix",
                allow_placeholders=False,
            )
            self.assertEqual(summary["output_path"], str(Path(tmpdir) / "audit_2.md"))

    def test_rejects_unresolved_placeholder_like_text_outside_strategy(self):
        data = sample_data()
        data["rationale"] = {"mesh_choices": "Review [reason] before final handoff."}
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(audit_markdown.AuditMarkdownError):
                audit_markdown.write_audit_markdown(
                    data=data,
                    output=str(Path(tmpdir) / "audit.md"),
                    if_exists="fail",
                    allow_placeholders=False,
                )

    def test_pubmed_field_tags_inside_strategy_are_not_placeholder_errors(self):
        data = sample_data()
        data["final_strategy"] = '("Asthma"[Mesh] OR asthma[Title/Abstract] OR child*[tiab])'
        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))
        self.assertEqual(audit_markdown.unresolved_placeholders(markdown), [])

    def test_press_coverage_renders_with_defaults_and_no_placeholder_error(self):
        markdown = audit_markdown.render_audit_markdown(sample_data(), Path("audit.md"))
        self.assertIn("## PRESS 2015 element coverage", markdown)
        self.assertIn("| PRESS 2015 element | Coverage | Notes / supporting section |", markdown)
        for element in audit_markdown.PRESS_2015_ELEMENTS:
            self.assertIn(element, markdown)
        # Absent input must default to "not performed", never a placeholder error.
        self.assertEqual(audit_markdown.unresolved_placeholders(markdown), [])

    def test_press_coverage_uses_supplied_values(self):
        data = sample_data()
        data["press_2015_element_coverage"] = [
            {"element": "1", "coverage": "addressed", "notes": "see Search structure"},
            {"element": "3", "coverage": "addressed", "notes": "see MeSH descriptors considered"},
        ]
        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))
        self.assertIn("| 1. Translation of the research question | addressed | see Search structure |", markdown)
        self.assertIn("| 3. Subject headings | addressed | see MeSH descriptors considered |", markdown)
        # Unspecified elements still fall back to the default status.
        self.assertIn("| 2. Boolean and proximity operators | not performed | not performed |", markdown)

    def test_press_coverage_section_is_rendered_before_seed_validation(self):
        markdown = audit_markdown.render_audit_markdown(sample_data(), Path("audit.md"))
        self.assertLess(
            markdown.index("## PRESS 2015 element coverage"),
            markdown.index("## Seed PMID validation"),
        )

    def test_seed_and_recall_template_sections_render_with_defaults(self):
        markdown = audit_markdown.render_audit_markdown(sample_data(), Path("audit.md"))
        self.assertIn("### Pre-gate seed triage", markdown)
        self.assertIn("### Seed-set expansion (related)", markdown)
        self.assertIn("### Relative-recall estimation", markdown)
        self.assertIn("not applicable - no usable seeds", markdown)
        self.assertEqual(audit_markdown.unresolved_placeholders(markdown), [])

    def test_seed_and_recall_template_sections_render_supplied_data(self):
        data = sample_data()
        data["pre_gate_seed_triage"] = {
            "requested_seed_entries": ["123", "bad-id", "456"],
            "normalized_unique_numeric_pmids": ["123", "456"],
            "malformed_entries_excluded": ["bad-id"],
            "fetched_seed_records": [
                {"pmid": "123", "title": "Robot pets in care homes", "year": "2024", "publication_types": ["Journal Article"]}
            ],
            "evidence_file_reviewed": "seed_fetch.json",
            "record_content_reviewed": "yes",
            "abstracts_reviewed": "yes",
            "receipt_only_stdout_used_as_decision_evidence": "no",
            "decision_supported": "yes",
            "missing_not_found_pmids_excluded": ["456"],
            "retracted_seeds": "none",
            "likely_out_of_scope_seeds": "none",
            "user_protocol_decision_when_paused": "not applicable",
        }
        data["seed_set_expansion"] = {
            "expansion_run": "Yes",
            "links_used": ["similar", "citedin"],
            "link_counts": {"similar": 20, "citedin": 3},
            "max_per_seed": 10,
            "max_total": 50,
            "candidate_count": 18,
            "candidate_count_before_cap": 23,
            "high_overlap_candidate_pmids": ["999 (seed_overlap_count=2; via=similar)"],
            "how_related_set_evidence_was_used": "fed high-overlap candidates to term-rank",
        }
        data["relative_recall"] = {
            "check_run": "Yes",
            "benchmark_source": "seed-expansion heuristic (related)",
            "benchmark_size": 10,
            "relative_recall_percent": 90.0,
            "retrieved_count": 9,
            "missed_count": 1,
            "retrieved_pmids": ["1", "2"],
            "missed_pmids": ["3"],
            "bottleneck_block": "robot pet block",
            "block_recall": [
                {"label": "robot pet block", "retrieved_count": 8, "recall_percent": 80.0, "bottleneck": True}
            ],
            "miss_diagnosis": [{"pmid": "3", "culprit_blocks": ["robot pet block"], "and_interaction": False}],
        }
        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))

        self.assertLess(markdown.index("### MeSH derived from seed records"), markdown.index("### Pre-gate seed triage"))
        self.assertLess(markdown.index("### Pre-gate seed triage"), markdown.index("### Seed-set expansion (related)"))
        self.assertLess(markdown.index("### Seed-set expansion (related)"), markdown.index("### MeSH derived from PubMed query translations"))
        self.assertLess(markdown.index("### PubMed CLI checks"), markdown.index("### Relative-recall estimation"))
        self.assertIn("Robot pets in care homes", markdown)
        self.assertIn("seed_fetch.json", markdown)
        self.assertIn("999 (seed_overlap_count=2; via=similar)", markdown)
        self.assertIn("seed-expansion heuristic (related)", markdown)
        self.assertIn("| robot pet block | 8 | 80.0 | yes |", markdown)
        self.assertIn("| 3 | robot pet block | no |", markdown)

    def test_record_content_evidence_table_renders_when_supplied(self):
        data = sample_data()
        data["decision_ledger"].append(
            {
                "decision_point": "Pre-gate seed scope decision",
                "options_considered": "retain or exclude seed",
                "evidence_or_test_used": "seed_fetch.json",
                "decision_made": "retain",
                "record_content_decision": True,
                "evidence_file_reviewed": "seed_fetch.json",
                "record_content_reviewed": "yes",
                "abstracts_reviewed": "yes",
                "receipt_only_stdout_used_as_decision_evidence": "no",
                "decision_supported": "yes",
            }
        )
        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))
        self.assertIn("## Record-content evidence reviewed", markdown)
        self.assertIn("Pre-gate seed scope decision", markdown)
        self.assertIn("seed_fetch.json", markdown)
        self.assertIn("Receipt-only stdout used as decision evidence", markdown)

    def test_record_content_decision_requires_reviewed_json_path(self):
        data = sample_data()
        data["decision_ledger"].append(
            {
                "decision_point": "Sample noise decision",
                "record_content_decision": True,
                "record_content_reviewed": "yes",
                "abstracts_reviewed": "yes",
                "receipt_only_stdout_used_as_decision_evidence": "no",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(audit_markdown.AuditMarkdownError, "evidence_file_reviewed"):
                audit_markdown.write_audit_markdown(
                    data=data,
                    output=str(Path(tmpdir) / "audit.md"),
                    if_exists="fail",
                    allow_placeholders=False,
                )

    def test_record_content_decision_rejects_receipt_only_stdout_evidence(self):
        data = sample_data()
        data["decision_ledger"].append(
            {
                "decision_point": "Term-discovery decision",
                "record_content_decision": True,
                "evidence_file_reviewed": "seed_mine.json",
                "record_content_reviewed": "yes",
                "abstracts_reviewed": "yes",
                "receipt_only_stdout_used_as_decision_evidence": "yes",
                "decision_supported": "yes",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(audit_markdown.AuditMarkdownError, "receipt-only stdout"):
                audit_markdown.write_audit_markdown(
                    data=data,
                    output=str(Path(tmpdir) / "audit.md"),
                    if_exists="fail",
                    allow_placeholders=False,
                )


def line_set_data():
    data = sample_data()
    data["concept_blocks"] = [
        {"label": "Asthma", "query": '("Asthma"[Mesh] OR asthma[tiab])', "count": 250000},
        {"label": "Children", "query": '("Child"[Mesh] OR child*[tiab])', "count": 1500000},
    ]
    data["combination"] = "1 AND 2"
    data["final_strategy"] = '("Asthma"[Mesh] OR asthma[tiab]) AND ("Child"[Mesh] OR child*[tiab])'
    data["result_count"] = 42000
    return data


class LineSetAndAppendixTests(unittest.TestCase):
    def test_line_set_renders_numbered_rows_and_combination(self):
        markdown = audit_markdown.render_audit_markdown(line_set_data(), Path("audit.md"))
        self.assertIn("## Search strategy (numbered line set)", markdown)
        self.assertIn("| Line | Concept | Search query | Results |", markdown)
        self.assertIn("#1", markdown)
        self.assertIn("#2", markdown)
        self.assertIn("Topic (combined)", markdown)
        self.assertIn("#1 AND #2", markdown)
        self.assertIn("250000", markdown)
        # Pipe-free field tags survive table escaping.
        self.assertIn('"Asthma"[Mesh] OR asthma[tiab]', markdown)
        self.assertEqual(audit_markdown.unresolved_placeholders(markdown), [])

    def test_line_set_omitted_when_no_blocks(self):
        markdown = audit_markdown.render_audit_markdown(sample_data(), Path("audit.md"))
        self.assertNotIn("## Search strategy (numbered line set)", markdown)
        # ...but the PRISMA-S appendix is always present.
        self.assertIn("## PRISMA-S appendix (PubMed)", markdown)

    def test_line_set_flags_block_not_in_final_strategy(self):
        data = line_set_data()
        data["concept_blocks"][1]["query"] = '("Adolescent"[Mesh] OR teen*[tiab])'  # not in final_strategy
        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))
        self.assertIn("Line-set consistency warnings", markdown)
        self.assertIn("block #2 query is not present in the final strategy", markdown)

    def test_line_set_includes_filter_lines(self):
        data = line_set_data()
        data["methodological_filter"] = {
            "query": "(randomized controlled trial[pt] OR randomized[tiab])",
            "source": "Cochrane HSSS",
            "version": "sensitivity-maximising 2008",
            "count": 900000,
        }
        data["topic_plus_filter_count"] = 12000
        markdown = audit_markdown.render_audit_markdown(data, Path("audit.md"))
        self.assertIn("Methodological filter", markdown)
        self.assertIn("Topic + filter", markdown)
        self.assertIn("#3 AND #4", markdown)
        self.assertIn("Cochrane HSSS", markdown)  # surfaced in the PRISMA-S Item 10 line

    def test_prisma_s_appendix_renders_all_items_with_defaults(self):
        markdown = audit_markdown.render_audit_markdown(sample_data(), Path("audit.md"))
        for marker in [
            "## PRISMA-S appendix (PubMed)",
            "Database (Item 1)",
            "Multi-database searching (Item 2)",
            "Full search strategy (Item 8)",
            "Limits and restrictions (Item 9)",
            "Search filters (Item 10)",
            "Date of final search (Item 13)",
            "Peer review (Item 14)",
            "Total records and deduplication (Items 15-16)",
        ]:
            self.assertIn(marker, markdown)
        self.assertIn("No methodological search filter was applied.", markdown)
        self.assertEqual(audit_markdown.unresolved_placeholders(markdown), [])

    def test_emit_appendix_writes_standalone_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.json"
            audit_out = Path(tmpdir) / "audit.md"
            appendix_out = Path(tmpdir) / "appendix.md"
            audit_path.write_text(json.dumps(line_set_data()), encoding="utf-8")

            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = audit_markdown.main(
                    [str(audit_path), "--output", str(audit_out), "--emit-appendix", str(appendix_out)]
                )
            self.assertEqual(rc, 0)
            receipt = json.loads(out.getvalue())
            self.assertEqual(receipt["appendix_path"], str(appendix_out))

            appendix = appendix_out.read_text(encoding="utf-8")
            # Standalone artifact = line set + PRISMA-S appendix only (no full audit sections).
            self.assertIn("## Search strategy (numbered line set)", appendix)
            self.assertIn("## PRISMA-S appendix (PubMed)", appendix)
            self.assertNotIn("## Decision ledger", appendix)
            self.assertIn("#1 AND #2", appendix)


if __name__ == "__main__":
    unittest.main()
