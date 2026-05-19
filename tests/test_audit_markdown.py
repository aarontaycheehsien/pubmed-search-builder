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
            "concept_gate_status": "completed",
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
            self.assertIn("## Final PubMed strategy (draft)", text)
            self.assertIn('"Asthma"[Mesh] OR asthma[tiab]', text)
            self.assertIn("## Decision ledger", text)
            self.assertIn(f"**Audit Markdown file:** {output}", text)

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


if __name__ == "__main__":
    unittest.main()
