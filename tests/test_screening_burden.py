import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("screening_burden_test", ROOT / "scripts" / "screening_burden.py")
burden = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(burden)


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


class ScreeningBurdenTests(unittest.TestCase):
    def test_stratified_sample_is_reproducible_and_reuses_shared_labels(self):
        variants = [{"label": "main", "query": "MAIN"}, {"label": "focused", "query": "FOCUSED"}]
        retrieval_sets = {
            "main": {"label": "main", "query": "MAIN", "total_count": 6, "ranked_pmids": ["1", "2", "3", "4", "5", "6"], "source": "test"},
            "focused": {"label": "focused", "query": "FOCUSED", "total_count": 3, "ranked_pmids": ["1", "2", "3"], "source": "test"},
        }
        records = [{"pmid": str(value), "title": f"Record {value}"} for value in range(1, 7)]
        with (
            mock.patch.object(burden, "complete_retrieval_sets", return_value=retrieval_sets),
            mock.patch.object(burden.pubmed_tool, "efetch", return_value={"records": records}),
        ):
            first = burden.sample_variants(
                FakeClient(), variants, "main", scope_version=1, sample_size=4, rank_bands=2, seed="fixed", retrieval_sets_file=None, auto_retrieval_limit=10
            )
            second = burden.sample_variants(
                FakeClient(), variants, "main", scope_version=1, sample_size=4, rank_bands=2, seed="fixed", retrieval_sets_file=None, auto_retrieval_limit=10
            )
        first_samples = [[row["sample_pmids"] for row in variant["strata"]] for variant in first["variants"]]
        second_samples = [[row["sample_pmids"] for row in variant["strata"]] for variant in second["variants"]]
        self.assertEqual(first_samples, second_samples)
        shared = next(item for item in first["label_queue"] if item["pmid"] in {"1", "2", "3"} and len(item["appearances"]) > 1)
        self.assertEqual({appearance["variant"] for appearance in shared["appearances"]}, {"main", "focused"})

    def labelled_sample(self):
        labels = [
            {"pmid": "1", "label": "likely-relevant", "label_reason": "likely in scope"},
            {"pmid": "2", "label": "likely-relevant", "label_reason": "likely in scope"},
            {"pmid": "3", "label": "irrelevant", "label_reason": "wrong population"},
            {"pmid": "4", "label": "uncertain", "label_reason": "abstract insufficient"},
        ]
        strata = [{"stratum": "shared:rank-1-of-1", "population_size": 100, "sample_size": 4, "sample_pmids": ["1", "2", "3", "4"]}]
        return {
            "operation": "screening-burden-sample",
            "scope_version": 1,
            "baseline_label": "main",
            "label_queue": labels,
            "variants": [
                {"label": "main", "query": "MAIN", "total_count": 100, "strata": strata},
                {"label": "focused", "query": "FOCUSED", "total_count": 50, "strata": [{**strata[0], "population_size": 50}]},
            ],
        }

    def test_estimates_precision_ci_burden_and_excludes_recall_failing_variant(self):
        def fake_retrieve(client, query, pmids):
            return {"10", "11"} if query == "MAIN" else {"10"}

        with mock.patch.object(burden.pubmed_tool, "retrieve_against_pmids", side_effect=fake_retrieve):
            result = burden.estimate_burden(
                FakeClient(), self.labelled_sample(), scope_version=1, heldout_pmids=["10", "11"], heldout_source="test", minimum_recall=1.0
            )
        main, focused = result["variants"]
        self.assertAlmostEqual(main["precision_estimate"], 2 / 3, places=5)
        self.assertIsNotNone(main["precision_confidence_interval_95"]["lower"])
        self.assertEqual(main["estimated_records_screened_per_relevant_report"], 1.5)
        self.assertEqual(main["uncertain_label_precision_bounds"]["lower_uncertain_as_irrelevant"], 0.5)
        self.assertTrue(main["recall_requirement_met"])
        self.assertFalse(focused["recall_requirement_met"])
        self.assertFalse(result["selection"]["burden_used_for_selection"])
        self.assertIsNone(result["selection"]["recommended_variant_label"])

    def test_burden_selects_only_when_multiple_variants_meet_recall(self):
        with mock.patch.object(burden.pubmed_tool, "retrieve_against_pmids", return_value={"10", "11"}):
            result = burden.estimate_burden(
                FakeClient(), self.labelled_sample(), scope_version=1, heldout_pmids=["10", "11"], heldout_source="test", minimum_recall=1.0
            )
        self.assertTrue(result["selection"]["burden_used_for_selection"])
        self.assertEqual(result["selection"]["recommended_variant_label"], "focused")

    def test_diagnostic_only_variant_cannot_be_selected_by_burden(self):
        sample = self.labelled_sample()
        sample["variants"][0]["protocol_status"] = "main-authoritative"
        sample["variants"][1]["protocol_status"] = "diagnostic-only"
        with mock.patch.object(burden.pubmed_tool, "retrieve_against_pmids", return_value={"10", "11"}):
            result = burden.estimate_burden(
                FakeClient(), sample, scope_version=1, heldout_pmids=["10", "11"], heldout_source="test", minimum_recall=1.0
            )
        self.assertFalse(result["selection"]["burden_used_for_selection"])
        self.assertIsNone(result["selection"]["recommended_variant_label"])
        self.assertEqual(result["selection"]["diagnostic_only_variant_labels"], ["focused"])

    def test_auto_sampling_rejects_incomplete_top_result_frame(self):
        with mock.patch.object(burden.pubmed_tool, "esearch", return_value={"count": 100, "pmids": []}):
            with self.assertRaises(burden.ScreeningBurdenError):
                burden.complete_retrieval_sets(
                    FakeClient(), [{"label": "main", "query": "MAIN"}], retrieval_sets_file=None, auto_retrieval_limit=10
                )


if __name__ == "__main__":
    unittest.main()
