import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("candidate_ledger", ROOT / "scripts" / "candidate_ledger.py")
candidate_ledger = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(candidate_ledger)


class CandidateLedgerTests(unittest.TestCase):
    def test_valid_ledger_separates_discovery_holdout_and_heuristic(self):
        data = {
            "scope_version": 1,
            "records": [
                {
                    "pmid": "1",
                    "provenance": "user-seed",
                    "decision": "include",
                    "title_abstract_reviewed": True,
                    "eligibility_reason": "In scope",
                    "use": "discovery",
                },
                {
                    "pmid": "2",
                    "provenance": "prior-review",
                    "decision": "include",
                    "title_abstract_reviewed": True,
                    "eligibility_reason": "In scope",
                    "use": "holdout",
                },
                {
                    "pmid": "3",
                    "provenance": "similar",
                    "decision": "uncertain",
                    "title_abstract_reviewed": True,
                    "eligibility_reason": "Abstract insufficient",
                    "use": "heuristic",
                },
            ],
        }
        issues, summary = candidate_ledger.validate_ledger(data)
        self.assertEqual(issues, [])
        self.assertEqual(summary["eligible_discovery_pmids"], ["1"])
        self.assertEqual(summary["holdout_pmids"], ["2"])
        self.assertEqual(summary["heuristic_pmids"], ["3"])
        self.assertTrue(summary["independent_holdout_available"])

    def test_unscreened_or_uncertain_record_cannot_drive_discovery(self):
        data = {
            "scope_version": 1,
            "records": [
                {
                    "pmid": "1",
                    "provenance": "similar",
                    "decision": "uncertain",
                    "title_abstract_reviewed": False,
                    "eligibility_reason": "",
                    "use": "discovery",
                }
            ],
        }
        issues, _ = candidate_ledger.validate_ledger(data)
        self.assertTrue(any("uncertain records" in issue for issue in issues))
        self.assertTrue(any("requires decision include" in issue for issue in issues))
        self.assertTrue(any("requires title/abstract review" in issue for issue in issues))

    def test_cli_writes_passing_validation_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "candidate_ledger.json"
            receipt = Path(tmp) / "receipt.json"
            ledger.write_text(
                json.dumps(
                    {
                        "scope_version": 2,
                        "records": [
                            {
                                "pmid": "9",
                                "provenance": "pilot-anchor",
                                "decision": "include",
                                "title_abstract_reviewed": True,
                                "eligibility_reason": "Matches scope",
                                "use": "both",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(candidate_ledger.main([str(ledger), "--output", str(receipt)]), 0)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["non_independent_validation_pmids"], ["9"])


if __name__ == "__main__":
    unittest.main()
