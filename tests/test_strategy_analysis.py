import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("strategy_analysis_test", ROOT / "scripts" / "strategy_analysis.py")
strategy_analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(strategy_analysis)


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


class StrategyAnalysisTests(unittest.TestCase):
    def test_focused_variant_reduction_threshold_boundary_and_override(self):
        block = {"label": "optional", "role": "optional", "fragility": "fragile"}
        empty_known_items = {"lost_due_to_full": []}

        below = strategy_analysis.recommend_block(
            block, empty_known_items, empty_known_items, {"reduction_percent": 9.99}
        )
        at_default = strategy_analysis.recommend_block(
            block, empty_known_items, empty_known_items, {"reduction_percent": 10.0}
        )
        at_override = strategy_analysis.recommend_block(
            block,
            empty_known_items,
            empty_known_items,
            {"reduction_percent": 5.0},
            focused_variant_min_reduction_percent=5.0,
        )

        self.assertEqual(below["disposition"], "handle-at-screening")
        self.assertEqual(at_default["disposition"], "focused-variant-only")
        self.assertEqual(at_override["disposition"], "focused-variant-only")
        with self.assertRaisesRegex(strategy_analysis.StrategyAnalysisError, "between 0 and 100"):
            strategy_analysis.recommend_block(
                block,
                empty_known_items,
                empty_known_items,
                {"reduction_percent": 5.0},
                focused_variant_min_reduction_percent=101,
            )

    def test_protocol_policy_marks_only_declared_variant_adoptable(self):
        with tempfile.TemporaryDirectory() as tmp:
            protocol = Path(tmp) / "review_protocol_v1.json"
            protocol.write_text(json.dumps({
                "dsl_version": 1, "protocol_id": "demo", "scope_version": 1,
                "focused_variants": [{"id": "focused-priority"}],
            }), encoding="utf-8")
            policy = strategy_analysis.protocol_policy(str(protocol), 1)
            self.assertEqual(policy["permitted_focused_variant_ids"], ["focused-priority"])
            self.assertEqual(len(policy["protocol_sha256"]), 64)

    def test_protocol_bound_blocks_require_registry_ids_and_labels(self):
        registry = {
            "allocation": {"block_id": "allocation", "label": "Allocation method", "role": "essential"},
        }
        valid = [{"block_id": "allocation", "label": "Allocation method", "query": "allocat*[tiab]"}]
        strategy_analysis.bind_blocks_to_registry(valid, registry)
        with self.assertRaisesRegex(strategy_analysis.StrategyAnalysisError, "label does not match"):
            strategy_analysis.bind_blocks_to_registry(
                [{"block_id": "allocation", "label": "Renamed", "query": "allocat*[tiab]"}], registry
            )
        with self.assertRaisesRegex(strategy_analysis.StrategyAnalysisError, "not declared"):
            strategy_analysis.bind_blocks_to_registry(
                [{"block_id": "new_scope", "label": "New", "query": "new[tiab]"}], registry
            )

    def test_concept_ablation_reports_evidence_and_requested_dispositions(self):
        blocks = [
            {"label": "optional A", "query": "A[tiab]", "role": "optional", "fragility": "fragile"},
            {"label": "required B", "query": "B[tiab]", "role": "required", "fragility": "stable"},
        ]

        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            has_a, has_b = "A[tiab]" in query, "B[tiab]" in query
            if " NOT " in query:
                count = 900 if has_b else 20
                pmids = ["90"] if retmax else []
            elif has_a and has_b:
                count, pmids = 100, []
            elif has_b:
                count, pmids = 1000, []
            else:
                count, pmids = 120, []
            return {"count": count, "pmids": pmids}

        def fake_retrieve(client, query, pmids):
            has_a, has_b = "A[tiab]" in query, "B[tiab]" in query
            if has_a and has_b:
                return {"1"}
            if has_b:
                return {"1", "2"}
            return {"1"}

        with (
            mock.patch.object(strategy_analysis.pubmed_tool, "esearch", side_effect=fake_search),
            mock.patch.object(strategy_analysis.pubmed_tool, "retrieve_against_pmids", side_effect=fake_retrieve),
            mock.patch.object(strategy_analysis.pubmed_tool, "efetch", return_value={"records": [{"pmid": "90"}]}),
        ):
            result = strategy_analysis.concept_ablation(
                FakeClient(), blocks, development_pmids=["1", "2"], holdout_pmids=[], scope_version=1, sample_size=5
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["decision_thresholds"]["focused_variant_min_reduction_percent"], 10.0)
        by_label = {row["label"]: row for row in result["analyses"]}
        self.assertEqual(by_label["optional A"]["recommendation"]["disposition"], "handle-at-screening")
        self.assertEqual(by_label["optional A"]["development"]["lost_due_to_full"], ["2"])
        self.assertEqual(by_label["optional A"]["differential_sample"]["records"][0]["pmid"], "90")
        self.assertEqual(by_label["required B"]["recommendation"]["disposition"], "keep-as-required")

    def test_two_strand_keeps_main_authoritative_and_reports_focused_losses(self):
        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            if " NOT " in query:
                main_unique = query.index("MAIN") < query.index(" NOT ")
                return {"count": 700 if main_unique else 0, "pmids": ["9"] if main_unique and retmax else []}
            return {"count": 300 if "NARROW" in query else 1000, "pmids": []}

        def fake_retrieve(client, query, pmids):
            return {"1"} if "NARROW" in query else {"1", "2"}

        with (
            mock.patch.object(strategy_analysis.pubmed_tool, "esearch", side_effect=fake_search),
            mock.patch.object(strategy_analysis.pubmed_tool, "retrieve_against_pmids", side_effect=fake_retrieve),
            mock.patch.object(strategy_analysis.pubmed_tool, "efetch", return_value={"records": [{"pmid": "9"}]}),
        ):
            result = strategy_analysis.two_strand(
                FakeClient(),
                "MAIN[tiab]",
                [{"label": "priority", "query": "NARROW[tiab]", "rationale": "Prioritize likely direct reports"}],
                development_pmids=["1", "2"],
                holdout_pmids=[],
                scope_version=1,
                sample_size=5,
            )

        self.assertTrue(result["safeguards"]["main_is_authoritative"])
        self.assertTrue(result["safeguards"]["focused_cannot_replace_main"])
        self.assertEqual(result["development"]["focused_losses"], ["2"])
        self.assertEqual(result["estimated_screening_workload"]["focused_reduction_percent"], 70.0)
        self.assertEqual(result["records_unique_to_main"]["count"], 700)

    def test_empirical_fragility_calculates_metrics_and_very_fragile_recommendation(self):
        concepts = [{"label": "allocation", "exact_query": "EXACT[tiab]", "descriptive_query": "DESC[tiab]", "mesh_query": '"Allocation"[Mesh]'}]
        records = [
            {"pmid": "1", "year": "1995", "title": "Exact allocation", "abstract": "legacy method", "keywords": ["legacy"], "mesh_headings": []},
            {"pmid": "2", "year": "2005", "title": "Operational method", "abstract": "description", "keywords": ["method"], "mesh_headings": []},
            {"pmid": "3", "year": "2015", "title": "Procedure", "abstract": "description", "keywords": ["procedure"], "mesh_headings": []},
            {"pmid": "4", "year": "2024", "title": "Implicit process", "abstract": "", "keywords": ["process"], "mesh_headings": []},
        ]

        def fake_retrieve(client, query, pmids):
            if "EXACT" in query and "DESC" in query:
                return {"1", "2", "3"}
            if "EXACT" in query:
                return {"1"}
            if "DESC" in query:
                return {"1", "2", "3"}
            return {"1", "2"}

        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            if " NOT " in query:
                return {"count": 4900, "pmids": ["99"] if retmax else []}
            return {"count": 5000 if "DESC" in query else 100, "pmids": []}

        with (
            mock.patch.object(strategy_analysis.pubmed_tool, "retrieve_against_pmids", side_effect=fake_retrieve),
            mock.patch.object(strategy_analysis.pubmed_tool, "esearch", side_effect=fake_search),
            mock.patch.object(strategy_analysis.pubmed_tool, "efetch", side_effect=[{"records": records}, {"records": [{"pmid": "99"}]}]),
        ):
            result = strategy_analysis.empirical_fragility(
                FakeClient(), concepts, development_pmids=["1", "2", "3", "4"], holdout_pmids=[], scope_version=1
            )
        row = result["concepts"][0]
        self.assertEqual(row["metrics"]["explicit_title_abstract_naming_percent"], 25.0)
        self.assertEqual(row["metrics"]["mesh_coverage_percent"], 50.0)
        self.assertEqual(row["metrics"]["additional_descriptive_coverage_percent"], 50.0)
        self.assertEqual(row["metrics"]["noise_added_by_safety_layer"], 4900)
        self.assertEqual(row["empirical_recommendation"], "very-fragile")

    def test_human_fragility_override_requires_reason(self):
        concept = {"label": "x", "exact_query": "X[tiab]", "descriptive_query": "Y[tiab]", "human_override": "stable"}
        with (
            mock.patch.object(strategy_analysis.pubmed_tool, "efetch", return_value={"records": [{"pmid": "1", "year": "2020"}]}),
            mock.patch.object(strategy_analysis.pubmed_tool, "retrieve_against_pmids", return_value={"1"}),
            mock.patch.object(strategy_analysis.pubmed_tool, "esearch", return_value={"count": 10, "pmids": []}),
        ):
            with self.assertRaises(strategy_analysis.StrategyAnalysisError):
                strategy_analysis.empirical_fragility(
                    FakeClient(), [concept], development_pmids=["1"], holdout_pmids=[], scope_version=1
                )


if __name__ == "__main__":
    unittest.main()
