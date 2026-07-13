import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "registry_sentinel_test", ROOT / "scripts" / "registry_sentinel.py"
)
registry = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(registry)


def trial(registry_id: str, *, status: str = "COMPLETED") -> dict:
    return {
        "registry_sources": ["clinicaltrials.gov"],
        "registry_ids": [registry_id],
        "primary_registry_id": registry_id,
        "title": f"Trial {registry_id}",
        "conditions": ["Condition"],
        "interventions": ["Intervention"],
        "recruitment_status": status,
        "has_registry_results": False,
        "eligibility_decision": "include",
        "eligibility_reason": "Eligible intervention trial",
        "linked_publications": [],
        "raw_record": {"id": registry_id},
    }


class ClinicalTrialsSearchTests(unittest.TestCase):
    def test_paginates_and_preserves_raw_pages(self):
        pages = [
            {
                "studies": [{
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000001", "briefTitle": "A"},
                        "statusModule": {"overallStatus": "COMPLETED"},
                    }
                }],
                "nextPageToken": "next",
            },
            {
                "studies": [{
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000002", "briefTitle": "B"},
                        "statusModule": {"overallStatus": "RECRUITING"},
                    }
                }]
            },
        ]
        urls = []

        def fetch(url):
            urls.append(url)
            return pages[len(urls) - 1]

        records, raw_pages = registry.clinicaltrials_search("condition AND therapy", page_size=1, fetcher=fetch)
        self.assertEqual([row["primary_registry_id"] for row in records], ["NCT00000001", "NCT00000002"])
        self.assertEqual(raw_pages, pages)
        self.assertIn("pageToken=next", urls[1])

    def test_repeated_page_token_is_rejected(self):
        with self.assertRaisesRegex(registry.RegistryError, "repeated a page token"):
            registry.clinicaltrials_search(
                "condition",
                fetcher=lambda _url: {"studies": [], "nextPageToken": "same"},
            )


class ImportMergeAndEvaluationTests(unittest.TestCase):
    def test_imports_ictrp_csv_and_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "trials.csv"
            csv_path.write_text(
                "TrialID,Public title,Recruitment Status\nACTRN1,Trial A,Completed\n",
                encoding="utf-8",
            )
            xml_path = root / "trials.xml"
            xml_path.write_text(
                "<records><record><trial_id>ISRCTN1</trial_id><title>Trial B</title></record></records>",
                encoding="utf-8",
            )
            self.assertEqual(registry.import_ictrp(str(csv_path))[0]["primary_registry_id"], "ACTRN1")
            self.assertEqual(registry.import_ictrp(str(xml_path))[0]["primary_registry_id"], "ISRCTN1")

    def test_merge_deduplicates_shared_registration_ids(self):
        left = trial("NCT00000001")
        right = trial("ACTRN1")
        left["registry_ids"].append("SHARED")
        right["registry_ids"].append("SHARED")
        right["registry_sources"] = ["who-ictrp"]
        merged = registry.merge_records([left, right])
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(merged[0]["registry_sources"]), {"clinicaltrials.gov", "who-ictrp"})
        self.assertEqual(len(merged[0]["source_records"]), 2)

    def test_confident_linked_pmids_form_denominator_and_misses_block(self):
        record = trial("NCT00000001")
        record["linked_publications"] = [
            {"pmid": "12345", "confidence": "high"},
            {"pmid": "67890", "confidence": "confirmed"},
            {"pmid": "99999", "confidence": "uncertain"},
        ]
        result = registry.evaluate([record], {"12345"})
        self.assertEqual(result["eligible_linked_pubmed_pmids"], 2)
        self.assertEqual(result["relative_recall_percent"], 50.0)
        self.assertEqual(result["unresolved_pubmed_misses"], ["67890"])
        self.assertEqual(result["ambiguous_link_count"], 1)

    def test_ctgov_references_classified_by_type(self):
        study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT00000001", "briefTitle": "A"},
                "statusModule": {"overallStatus": "COMPLETED"},
                "referencesModule": {
                    "references": [
                        {"pmid": "11111", "type": "RESULT", "citation": "Trial report"},
                        {"pmid": "22222", "type": "DERIVED", "citation": "Pooled analysis"},
                        {"pmid": "33333", "type": "BACKGROUND", "citation": "Cited prior work"},
                        {"pmid": "44444", "citation": "Untyped reference"},
                    ]
                },
            }
        }
        record = registry.normalize_ctgov(study)
        by_pmid = {pub["pmid"]: pub for pub in record["linked_publications"]}
        self.assertEqual(by_pmid["11111"]["confidence"], "high")
        self.assertEqual(by_pmid["22222"]["confidence"], "high")
        self.assertEqual(by_pmid["33333"]["confidence"], "uncertain")
        self.assertEqual(by_pmid["33333"]["link_method"], "registry-background-citation")
        # An untyped reference is not assumed to be a trial report.
        self.assertEqual(by_pmid["44444"]["confidence"], "uncertain")

        # Only the result/derived references enter the relative-recall denominator;
        # the background citation cannot register as a missed trial report.
        record["eligibility_decision"] = "include"
        record["eligibility_reason"] = "Eligible intervention trial"
        result = registry.evaluate([record], {"11111", "22222"})
        self.assertEqual(result["eligible_linked_pubmed_pmids"], 2)
        self.assertEqual(result["relative_recall_percent"], 100.0)
        self.assertEqual(result["missed_pmids"], [])
        self.assertFalse(result["unresolved_pubmed_misses"])

    def test_non_pubmed_and_empty_registry_results_are_not_query_failures(self):
        record = trial("NCT00000001")
        record["linked_publications"] = [{"pmid": "", "citation": "Journal report"}]
        self.assertEqual(registry.publication_class(record), "published-non-pubmed")
        record["eligibility_decision"] = "exclude"
        result = registry.evaluate([record], set())
        self.assertEqual(result["eligible_trials"], 0)
        self.assertIn("no reassurance", result["interpretation"].lower())

    def test_pending_screening_and_missing_reasons_are_rejected(self):
        record = trial("NCT00000001")
        record["eligibility_decision"] = "pending"
        with self.assertRaises(registry.RegistryError):
            registry.evaluate([record], set())
        record["eligibility_decision"] = "include"
        record["eligibility_reason"] = ""
        with self.assertRaises(registry.RegistryError):
            registry.evaluate([record], set())


class ProtocolBindingTests(unittest.TestCase):
    def test_registry_execution_requires_enabled_external_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "protocol.json"
            path.write_text(json.dumps({
                "scope_version": 1,
                "protocol_id": "test",
                "information_source_mode": "pubmed-only",
            }), encoding="utf-8")
            with self.assertRaisesRegex(registry.RegistryError, "does not enable"):
                registry.protocol_binding(str(path), 1)
            protocol = json.loads(path.read_text(encoding="utf-8"))
            protocol.update({
                "information_source_mode": "pubmed-plus-external-validation",
                "external_validation": {
                    "status": "enabled",
                    "purpose": "pubmed-leak-detection",
                    "sources": ["clinicaltrials.gov"],
                },
            })
            path.write_text(json.dumps(protocol), encoding="utf-8")
            binding = registry.protocol_binding(str(path), 1)
            self.assertEqual(binding["information_source_mode"], "pubmed-plus-external-validation")


if __name__ == "__main__":
    unittest.main()
