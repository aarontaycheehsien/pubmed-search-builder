import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pubmed_tool.py"
SPEC = importlib.util.spec_from_file_location("pubmed_tool", MODULE_PATH)
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


class DesignLedgerTests(unittest.TestCase):
    def test_parse_old_and_new_variant_formats(self):
        old_queries, old_baseline = pubmed_tool.parse_variant_queries(json.dumps({"main": "asthma[tiab]"}))
        self.assertIsNone(old_baseline)
        self.assertEqual(old_queries, [{"label": "main", "query": "asthma[tiab]"}])

        new_queries, new_baseline = pubmed_tool.parse_variant_queries(
            json.dumps(
                {
                    "baseline_label": "main_sensitive",
                    "variants": [
                        {
                            "label": "main_sensitive",
                            "role": "sensitive",
                            "query": "asthma[tiab]",
                            "hypothesis": "maximise recall",
                            "decision_status": "selected",
                        }
                    ],
                }
            )
        )
        self.assertEqual(new_baseline, "main_sensitive")
        self.assertEqual(new_queries[0]["role"], "sensitive")
        self.assertEqual(new_queries[0]["hypothesis"], "maximise recall")
        self.assertEqual(new_queries[0]["decision_status"], "selected")

    def test_labelled_sample_nnr_calculation(self):
        samples = pubmed_tool.parse_labelled_samples(
            json.dumps(
                {
                    "main_sensitive": {
                        "sample_description": "random pilot sample",
                        "labels": {"1": True, "2": False, "3": "yes"},
                    },
                    "zero_relevant": [{"pmid": "4", "relevant": False}],
                }
            )
        )
        self.assertEqual(samples["main_sensitive"]["labelled_sample_size"], 3)
        self.assertEqual(samples["main_sensitive"]["relevant_labelled_records"], 2)
        self.assertEqual(samples["main_sensitive"]["estimated_precision"], 0.6667)
        self.assertEqual(samples["main_sensitive"]["estimated_nnr"], 1.5)
        self.assertIsNone(samples["zero_relevant"]["estimated_nnr"])
        self.assertIn("undefined/infinite", samples["zero_relevant"]["estimated_nnr_note"])

        missing = pubmed_tool.default_labelled_sample_summary()
        self.assertEqual(missing["estimated_nnr_note"], "not estimable; no labelled sample supplied")

    def test_compare_variants_attaches_seed_validation_and_sample_estimates(self):
        original_esearch = pubmed_tool.esearch

        def fake_esearch(client, query, retmax, retstart=0, sort=None):
            if "[uid]" in query:
                pmids = ["111", "222"] if "main[tiab]" in query else ["111"]
                return {"count": len(pmids), "retmax": retmax, "pmids": pmids, "query_translation_hook": {"issues": []}}
            if "main[tiab]" in query:
                return {"count": 100, "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}
            return {"count": 60, "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}

        pubmed_tool.esearch = fake_esearch
        try:
            result = pubmed_tool.compare_variants(
                FakeClient(),
                [
                    {"label": "main", "role": "sensitive", "query": "main[tiab]", "decision_status": "selected"},
                    {"label": "focused", "role": "focused", "query": "focused[tiab]", "decision_status": "reserve"},
                ],
                retmax=0,
                sort=None,
                baseline_label="main",
                seed_pmids=["111", "222"],
                labelled_samples={"focused": pubmed_tool.labelled_sample_summary({"labels": {"10": True, "11": False}}, "focused")},
            )
        finally:
            pubmed_tool.esearch = original_esearch

        main, focused = result["results"]
        self.assertEqual(main["seed_pmids_retrieved"], ["111", "222"])
        self.assertEqual(main["seed_recall_percent"], 100.0)
        self.assertEqual(focused["seed_pmids_missed"], ["222"])
        self.assertEqual(focused["seed_recall_percent"], 50.0)
        self.assertEqual(focused["estimated_nnr"], 2.0)
        self.assertEqual(main["estimated_nnr_note"], "not estimable; no labelled sample supplied")

    def test_audit_workbook_includes_design_ledger_columns(self):
        variants_data = {
            "operation": "variants",
            "variant_count": 1,
            "baseline_label": "main",
            "results": [
                {
                    "label": "main",
                    "role": "sensitive",
                    "decision_status": "selected",
                    "decision_reason": "Best known-item recall",
                    "count": 100,
                    "count_delta_from_baseline": 0,
                    "percent_of_baseline": 100.0,
                    "seed_pmids_retrieved": ["111"],
                    "seed_pmids_missed": [],
                    "seed_recall_percent": 100.0,
                    "labelled_sample_size": 2,
                    "relevant_labelled_records": 1,
                    "estimated_precision": 0.5,
                    "estimated_nnr": 2.0,
                    "estimated_nnr_note": "estimated from labelled pilot sample",
                    "hypothesis": "maximise recall",
                    "changes_from_baseline": "none",
                    "recall_risk": "low",
                    "workload_rationale": "baseline",
                    "query_translation_hook": {"issues": []},
                    "query": "asthma[tiab]",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "audit.xlsx"
            result = pubmed_tool.build_audit_workbook(
                output_path=str(output),
                mine_data=None,
                variants_data=variants_data,
                mine_source="",
                variants_source="variants.json",
            )
            self.assertTrue(output.exists())
            self.assertIn("Design Ledger", result["sheets"])
            with zipfile.ZipFile(output) as archive:
                workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
                sheet_xml = "\n".join(
                    archive.read(name).decode("utf-8")
                    for name in archive.namelist()
                    if name.startswith("xl/worksheets/sheet")
                )
            self.assertIn("Design Ledger", workbook_xml)
            self.assertIn("Estimated NNR", sheet_xml)
            self.assertIn("Decision reason", sheet_xml)

    def test_legacy_variants_workbook_keeps_compact_variants_sheet(self):
        variants_data = {
            "operation": "variants",
            "variant_count": 1,
            "baseline_label": "main",
            "results": [
                {
                    "label": "main",
                    "count": 10,
                    "count_delta_from_baseline": 0,
                    "percent_of_baseline": 100.0,
                    "retmax": 0,
                    "query_translation_hook": {"issues": []},
                    "query": "asthma[tiab]",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "legacy.xlsx"
            pubmed_tool.build_audit_workbook(
                output_path=str(output),
                mine_data=None,
                variants_data=variants_data,
                mine_source="",
                variants_source="variants.json",
            )
            with zipfile.ZipFile(output) as archive:
                variants_sheet = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
                ledger_sheet = archive.read("xl/worksheets/sheet3.xml").decode("utf-8")
            self.assertIn("Retmax", variants_sheet)
            self.assertNotIn("Decision status", variants_sheet)
            self.assertIn("Decision status", ledger_sheet)


if __name__ == "__main__":
    unittest.main()
