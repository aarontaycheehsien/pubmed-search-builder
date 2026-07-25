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
                    {"pmid": "1", "provenance": "user-seed", "decision": "include", "use": "discovery", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                    {"pmid": "2", "provenance": "user-seed", "decision": "exclude", "use": "neither", "title_abstract_reviewed": True, "eligibility_reason": "wrong condition"},
                    {"pmid": "3", "provenance": "user-seed", "decision": "include", "use": "holdout", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
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

    def extract(self, config=None, **kwargs):
        return vocabulary.extract_learning(
            self.scope,
            self.ledger,
            self.records,
            config or self.config,
            scope_version=1,
            **kwargs,
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
        self.assertTrue(result["no_harm_checks_complete"])
        self.assertEqual(result["proposals"][0]["effective_decision"], "adopted")
        self.assertEqual(len(result["proposals"][0]["no_harm"]["checks"]), 7)

    def test_no_effect_revision_is_automatically_reverted(self):
        extraction = self.extract()
        proposal = extraction["proposals"][0]
        proposal.update({"decision": "accepted", "decision_reason": "candidate", "within_locked_concept_attested": True})
        extraction["proposals"] = [proposal]
        blocks = self.write("blocks_no_effect.json", [{"label": "condition", "query": "asthma[tiab]"}])
        with (
            mock.patch.object(vocabulary.pubmed_tool, "retrieve_against_pmids", return_value=set()),
            mock.patch.object(vocabulary.pubmed_tool, "esearch", return_value={"count": 0, "pmids": [], "query_translation_hook": {"issues": []}}),
        ):
            result = vocabulary.retest_learning(FakeClient(), extraction, blocks, scope_version=1, sample_size=5)
        row = result["proposals"][0]
        self.assertEqual(row["effective_decision"], "revert-to-baseline")
        self.assertIn("named-defect-fixed", row["no_harm"]["failed_checks"])
        self.assertEqual(result["accepted_term_count"], 0)
        self.assertEqual(result["reverted_term_count"], 1)

    def test_failed_revision_requires_label_to_remain_experimental(self):
        extraction = self.extract()
        proposal = extraction["proposals"][0]
        proposal.update({
            "decision": "accepted", "decision_reason": "candidate", "within_locked_concept_attested": True,
            "retain_experimental_if_failed": True, "experimental_variant_id": "exp-term", "experimental_variant_label": "Experimental term",
        })
        extraction["proposals"] = [proposal]
        blocks = self.write("blocks_experimental.json", [{"label": "condition", "query": "asthma[tiab]"}])
        with (
            mock.patch.object(vocabulary.pubmed_tool, "retrieve_against_pmids", return_value=set()),
            mock.patch.object(vocabulary.pubmed_tool, "esearch", return_value={"count": 0, "pmids": [], "query_translation_hook": {"issues": []}}),
        ):
            result = vocabulary.retest_learning(FakeClient(), extraction, blocks, scope_version=1, sample_size=5)
        row = result["proposals"][0]
        self.assertEqual(row["effective_decision"], "experimental-only")
        self.assertEqual(row["no_harm"]["experimental_variant"]["variant_id"], "exp-term")
        self.assertEqual(result["experimental_term_count"], 1)

    def test_accepted_term_without_within_concept_attestation_is_rejected(self):
        extraction = self.extract()
        extraction["proposals"] = [extraction["proposals"][0]]
        extraction["proposals"][0].update({"decision": "accepted", "decision_reason": "test"})
        blocks = self.write("blocks.json", [{"label": "condition", "query": "asthma[tiab]"}])
        with self.assertRaises(vocabulary.VocabularyLearningError):
            vocabulary.retest_learning(FakeClient(), extraction, blocks, scope_version=1, sample_size=5)

    def test_missing_record_is_retried_after_blocker_is_fixed(self):
        records = self.write("records_missing.json", {"records": []})
        first = vocabulary.extract_learning(
            self.scope, self.ledger, records, self.config, scope_version=1
        )
        self.assertEqual(first["processed_included_pmids"], [])
        self.assertTrue(first["processing_blockers"])
        second = vocabulary.extract_learning(
            self.scope,
            self.ledger,
            self.records,
            self.config,
            scope_version=1,
            previous_learning=first,
        )
        self.assertEqual(second["processed_included_pmids"], ["1"])
        self.assertTrue(second["proposals"])

    def test_invalid_unscreened_ledger_cannot_drive_proposals(self):
        invalid = self.write(
            "invalid_ledger.json",
            {"scope_version": 1, "records": [{"pmid": "1", "decision": "include", "use": "discovery"}]},
        )
        with self.assertRaises(vocabulary.VocabularyLearningError):
            vocabulary.extract_learning(
                self.scope, invalid, self.records, self.config, scope_version=1
            )


class BoundedReviewShortlistTests(unittest.TestCase):
    """Candidate generation is unbounded; the reviewable artifact must not be."""

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
                    {"pmid": "1", "provenance": "user-seed", "decision": "include", "use": "discovery", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                    {"pmid": "3", "provenance": "user-seed", "decision": "include", "use": "holdout", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                ],
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
        # One record carrying far more candidate terms than any review budget.
        self.records = self.write(
            "wide_records.json",
            {
                "records": [
                    {
                        "pmid": "1",
                        "title": " ".join(f"alpha{index} beta{index} gamma{index}" for index in range(40)),
                        "abstract": " ".join(f"delta{index} epsilon{index} zeta{index}" for index in range(40)),
                        "keywords": [f"keyword phrase {index}" for index in range(30)],
                        "mesh_headings": [f"Mesh Heading {index}" for index in range(30)],
                    },
                    {"pmid": "3", "title": "Held out asthma", "abstract": "", "keywords": [], "mesh_headings": []},
                ]
            },
        )

    def write(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def extract(self, config=None, **kwargs):
        return vocabulary.extract_learning(
            self.scope, self.ledger, self.records, config or self.config, scope_version=1, **kwargs
        )

    def test_shortlist_is_capped_and_reconciles_with_total_generated(self):
        result = self.extract(max_review_terms_per_concept=10)
        generation = result["candidate_generation"]
        self.assertEqual(len(result["proposals"]), 10)
        self.assertEqual(generation["promoted_for_review"], 10)
        self.assertGreater(generation["total_generated"], 100)
        self.assertEqual(
            generation["promoted_for_review"] + generation["below_review_threshold"],
            generation["total_generated"],
        )
        self.assertTrue(generation["reconciled"])

    def test_budget_is_split_across_extraction_layers(self):
        result = self.extract(max_review_terms_per_concept=12)
        layers = {item["extraction_layer"] for item in result["proposals"]}
        # mesh/keyword/phrase all have candidates here; none may monopolise the budget.
        self.assertGreaterEqual(len(layers), 3)
        for layer in layers:
            selected = [item for item in result["proposals"] if item["extraction_layer"] == layer]
            self.assertLessEqual(len(selected), 6)

    def test_withheld_candidates_carry_no_disposition(self):
        result = self.extract(max_review_terms_per_concept=5)
        below = result["below_review_threshold"]
        self.assertNotIn("decision", below)
        self.assertNotIn("rejected", below)
        self.assertIn("not a relevance judgement", below["note"])
        self.assertEqual(
            below["count"], sum(len(group["normalized_terms"]) for group in below["fingerprints"])
        )

    def test_shortlisted_proposals_carry_local_ranking_evidence(self):
        result = self.extract(max_review_terms_per_concept=5)
        for proposal in result["proposals"]:
            self.assertIsInstance(proposal["relevant_df"], int)
            self.assertGreaterEqual(proposal["coverage"], 0.0)
            self.assertLessEqual(proposal["coverage"], 1.0)
        self.assertFalse(result["review_selection"]["pubmed_lift_computed"])

    def test_withheld_tail_is_not_reproposed_next_round(self):
        first = self.extract(max_review_terms_per_concept=5)
        withheld = {
            term
            for group in first["below_review_threshold"]["fingerprints"]
            for term in group["normalized_terms"]
        }
        self.assertTrue(withheld)
        # A later round reprocessing the same record must not resurface the retained tail.
        ledger = self.write(
            "ledger_round2.json",
            {
                "scope_version": 1,
                "records": [
                    {"pmid": "1", "provenance": "user-seed", "decision": "include", "use": "discovery", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                    {"pmid": "4", "provenance": "user-seed", "decision": "include", "use": "discovery", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                    {"pmid": "3", "provenance": "user-seed", "decision": "include", "use": "holdout", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                ],
            },
        )  # noqa: E501
        records = self.write(
            "records_round2.json",
            {
                "records": json.loads(Path(self.records).read_text(encoding="utf-8"))["records"]
                + [{"pmid": "4", "title": "novel terminology appears here", "abstract": "", "keywords": [], "mesh_headings": []}]
            },
        )
        config = self.write(
            "config_round2.json",
            {
                "scope_version": 1,
                "concepts": [{"label": "condition", "existing_terms": ["asthma"]}],
                "record_concept_assignments": {"1": ["condition"], "4": ["condition"]},
            },
        )
        second = vocabulary.extract_learning(
            self.scope, ledger, records, config, scope_version=1, previous_learning=first,
            max_review_terms_per_concept=5,
        )
        resurfaced = {item["normalized_term"] for item in second["proposals"]} & withheld
        self.assertEqual(resurfaced, set())


class CrossConceptAttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scope = self.write(
            "two_concept_scope.json",
            {"scope_version": 1, "essential_blocks": ["condition", "intervention"]},
        )
        self.ledger = self.write(
            "ledger.json",
            {
                "scope_version": 1,
                "records": [
                    {"pmid": "1", "provenance": "user-seed", "decision": "include", "use": "discovery", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                ],
            },
        )
        self.records = self.write(
            "records.json",
            {
                "records": [
                    {"pmid": "1", "title": "Inhaled corticosteroid asthma trial", "abstract": "", "keywords": ["bronchial hyperreactivity"], "mesh_headings": []},
                ]
            },
        )
        self.config = self.write(
            "two_concept_config.json",
            {
                "scope_version": 1,
                "concepts": [{"label": "condition", "existing_terms": ["asthma"]}],
                "record_concept_assignments": {"1": ["condition", "intervention"]},
            },
        )

    def write(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def extract(self, **kwargs):
        return vocabulary.extract_learning(
            self.scope, self.ledger, self.records, self.config, scope_version=1, **kwargs
        )

    def test_terms_proposed_under_several_concepts_are_flagged_for_the_reviewer(self):
        result = self.extract()
        shared = [item for item in result["proposals"] if item["also_proposed_for_concepts"]]
        self.assertTrue(shared, "a record assigned to two concepts proposes its terms under both")
        for proposal in shared:
            self.assertNotIn(proposal["concept"], proposal["also_proposed_for_concepts"])


if __name__ == "__main__":
    unittest.main()
