import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from pubmed_search_builder.domain.review_profiles import compile_review_profile


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("review_discovery", SCRIPTS / "review_discovery.py")
review_discovery = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(review_discovery)


def profile():
    return compile_review_profile(
        {
            "protocol_id": "review-target",
            "scope_version": 1,
            "evidence_target": {
                "mode": "evidence-syntheses",
                "eligible_types": ["systematic-review", "meta-analysis"],
                "protocols": "exclude",
                "narrative_reviews": "screen",
                "methods_papers": "exclude",
            },
        }
    )


class ReviewDiscoveryTests(unittest.TestCase):
    def test_discover_keeps_per_branch_provenance(self):
        original_search = review_discovery.pubmed_tool.esearch
        original_fetch = review_discovery.pubmed_tool.efetch

        def search(_client, query, **_kwargs):
            pmids = ["1"] if "systematic[sb]" in query else ["1", "2"]
            return {"count": len(pmids), "pmids": pmids, "query_translation": query, "query_translation_hook": {}}

        def fetch(_client, pmids):
            return {"records": [{"pmid": pmid, "title": f"Review {pmid}", "publication_types": []} for pmid in pmids]}

        review_discovery.pubmed_tool.esearch = search
        review_discovery.pubmed_tool.efetch = fetch
        try:
            result = review_discovery.discover(object(), profile=profile(), topic_query="asthma", retmax_per_branch=20)
        finally:
            review_discovery.pubmed_tool.esearch = original_search
            review_discovery.pubmed_tool.efetch = original_fetch
        self.assertEqual(result["artifact_type"], "review-discovery/evidence")
        self.assertEqual(result["candidate_count"], 2)
        self.assertGreaterEqual(len(result["records"][0]["retrieved_by"]), 1)

    def test_classification_requires_human_review_and_allowed_type(self):
        candidates = {"records": [{"pmid": "1", "title": "Review"}]}
        decisions = {
            "records": [
                {
                    "pmid": "1",
                    "decision": "include",
                    "title_abstract_reviewed": True,
                    "eligibility_reason": "Matches the protocol.",
                    "record_kind": "completed-synthesis",
                    "declared_synthesis_type": "systematic-review",
                }
            ]
        }
        result = review_discovery.classify(candidates=candidates, decisions=decisions, profile=profile())
        self.assertEqual(result["included_pmids"], ["1"])
        decisions["records"][0]["declared_synthesis_type"] = "scoping-review"
        with self.assertRaisesRegex(review_discovery.ReviewDiscoveryError, "eligible"):
            review_discovery.classify(candidates=candidates, decisions=decisions, profile=profile())

    def test_evaluation_reports_per_type_misses(self):
        classification = {
            "records": [
                {"pmid": "1", "decision": "include", "declared_synthesis_type": "systematic-review"},
                {"pmid": "2", "decision": "include", "declared_synthesis_type": "meta-analysis"},
            ]
        }
        result = review_discovery.evaluate(profile=profile(), classification=classification, retrieved_pmids=["1"], topic_only_count=12)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missed_pmids"], ["2"])
        self.assertEqual(result["per_synthesis_type"]["meta-analysis"]["relative_recall"], 0.0)

    def test_sources_command_and_pmid_list_are_offline_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = root / "sources.json"
            self.assertEqual(review_discovery.main(["sources", "--output", str(sources)]), 0)
            payload = json.loads(sources.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact_type"], "review-retrieval/sources")
            self.assertEqual(payload["sources"], list(review_discovery.SOURCES))
            pmids = root / "pmids.json"
            pmids.write_text('["1", 2, "1"]', encoding="utf-8")
            self.assertEqual(review_discovery._load_pmid_list(pmids), ["1", "2"])


if __name__ == "__main__":
    unittest.main()
