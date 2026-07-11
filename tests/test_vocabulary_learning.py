import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("vocabulary_learning_test", ROOT / "scripts" / "vocabulary_learning.py")
vocabulary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(vocabulary)


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


class VocabularyLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scope = self.write("scope.json", {"scope_version": 1, "essential_blocks": ["condition"]})
        self.ledger = self.write(
            "ledger.json",
            {
                "scope_version": 1,
                "records": [
                    {"pmid": "1", "decision": "include", "use": "discovery", "eligibility_reason": "in scope"},
                    {"pmid": "2", "decision": "exclude", "use": "neither", "eligibility_reason": "wrong condition"},
                    {"pmid": "3", "decision": "include", "use": "holdout", "eligibility_reason": "in scope"},
                ],
            },
        )
        self.records = self.write(
            "records.json",
            {
                "records": [
                    {"pmid": "1", "title": "Asthma study", "abstract": "", "keywords": ["bronchial hyperreactivity"], "mesh_headings": []},
                    {"pmid": "2", "title": "Other disease", "abstract": "", "keywords": ["forbidden marker"], "mesh_headings": []},
                    {"pmid": "3", "title": "Held out asthma", "abstract": "", "keywords": [], "mesh_headings": []},
                ]
            },
        )
        self.config = self.write(
            "config.json",
            {
                "scope_version": 1,
                "concepts": [{"label": "condition", "existing_terms": ["asthma"]}],
                "record_concept_assignments": {"1": ["condition"]},
            },
        )

    def write(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def extract(self, config=None):
        return vocabulary.extract_learning(
            self.scope,
            self.ledger,
            self.records,
            config or self.config,
            scope_version=1,
        )

    def test_extracts_only_new_included_terms_and_diagnoses_excluded_separately(self):
        result = self.extract()
        proposal_terms = {item["normalized_term"] for item in result["proposals"]}
        self.assertIn("bronchial hyperreactivity", proposal_terms)
        self.assertNotIn("forbidden marker", proposal_terms)
        excluded_terms = {item["term"] for item in result["excluded_record_diagnosis"]["frequent_terminology"]}
        self.assertIn("forbidden marker", excluded_terms)
        self.assertFalse(result["excluded_record_diagnosis"]["used_for_proposals"])
        self.assertEqual(result["holdout_pmids_frozen"], ["3"])

    def test_new_concept_assignment_requires_scope_reentry(self):
        config = self.write(
            "new_concept.json",
            {"scope_version": 1, "concepts": [], "record_concept_assignments": {"1": ["outcome"]}},
        )
        result = self.extract(config)
        self.assertTrue(result["scope_reentry_required"])
        self.assertEqual(result["proposals"], [])
        self.assertEqual(result["scope_challenges"][0]["type"], "new-concept")

    def test_accepted_term_is_retested_against_holdout_and_differential_sample(self):
        extraction = self.extract()
        proposal = next(item for item in extraction["proposals"] if item["normalized_term"] == "bronchial hyperreactivity")
        proposal["decision"] = "accepted"
        proposal["decision_reason"] = "Observed in a newly included report and remains within condition"
        proposal["within_locked_concept_attested"] = True
        extraction["proposals"] = [proposal]
        blocks = self.write("blocks.json", [{"label": "condition", "query": "asthma[tiab]"}])

        def fake_retrieve(client, query, pmids):
            return {"3"} if "bronchial" in query else set()

        with (
            mock.patch.object(vocabulary.pubmed_tool, "retrieve_against_pmids", side_effect=fake_retrieve),
            mock.patch.object(vocabulary.pubmed_tool, "esearch", return_value={"count": 5, "pmids": ["9"], "query_translation": "ok"}),
            mock.patch.object(vocabulary.pubmed_tool, "efetch", return_value={"records": [{"pmid": "9", "title": "Differential"}]}),
        ):
            result = vocabulary.retest_learning(FakeClient(), extraction, blocks, scope_version=1, sample_size=5)
        retest = result["proposals"][0]["retest"]
        self.assertEqual(retest["holdout_test"]["rescued_pmids"], ["3"])
        self.assertEqual(retest["differential_sample"]["count"], 5)
        self.assertEqual(retest["differential_sample"]["records"][0]["pmid"], "9")
        self.assertTrue(result["all_accepted_terms_retested"])

    def test_accepted_term_without_within_concept_attestation_is_rejected(self):
        extraction = self.extract()
        extraction["proposals"] = [extraction["proposals"][0]]
        extraction["proposals"][0].update({"decision": "accepted", "decision_reason": "test"})
        blocks = self.write("blocks.json", [{"label": "condition", "query": "asthma[tiab]"}])
        with self.assertRaises(vocabulary.VocabularyLearningError):
            vocabulary.retest_learning(FakeClient(), extraction, blocks, scope_version=1, sample_size=5)


if __name__ == "__main__":
    unittest.main()
