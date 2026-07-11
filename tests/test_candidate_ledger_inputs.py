import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pubmed_tool_ledger", ROOT / "scripts" / "pubmed_tool.py")
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


class CandidateLedgerInputTests(unittest.TestCase):
    def write_ledger(self, root: Path, records: list[dict]) -> Path:
        path = root / "candidate_ledger.json"
        path.write_text(json.dumps({"scope_version": 2, "records": records}), encoding="utf-8")
        return path

    def test_discovery_and_validation_roles_are_separated(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.write_ledger(
                Path(td),
                [
                    {"pmid": "1", "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "yes", "use": "discovery"},
                    {"pmid": "2", "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "yes", "use": "holdout"},
                    {"pmid": "3", "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "yes", "use": "both"},
                ],
            )
            discovery, discovery_meta = pubmed_tool.candidate_ledger_pmids(str(ledger), "discovery")
            validation, validation_meta = pubmed_tool.candidate_ledger_pmids(str(ledger), "validation")
            self.assertEqual(discovery, ["1", "3"])
            self.assertEqual(validation, ["2"])
            self.assertFalse(discovery_meta["independent"])
            self.assertTrue(validation_meta["independent"])

    def test_validation_falls_back_to_both_and_marks_non_independent(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.write_ledger(
                Path(td),
                [{"pmid": "3", "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "yes", "use": "both"}],
            )
            pmids, metadata = pubmed_tool.candidate_ledger_pmids(str(ledger), "validation")
            self.assertEqual(pmids, ["3"])
            self.assertFalse(metadata["independent"])

    def test_ledger_native_cli_sources_parse(self):
        parser = pubmed_tool.build_parser()
        self.assertEqual(parser.parse_args(["mine", "--candidate-ledger", "c.json", "--output", "o.json"]).candidate_ledger, "c.json")
        self.assertEqual(parser.parse_args(["term-rank", "--candidate-ledger", "c.json"]).candidate_ledger, "c.json")
        self.assertEqual(parser.parse_args(["validate", "x[tiab]", "--candidate-ledger", "c.json"]).candidate_ledger, "c.json")
        self.assertEqual(parser.parse_args(["recall", "x[tiab]", "--candidate-ledger", "c.json"]).candidate_ledger, "c.json")


if __name__ == "__main__":
    unittest.main()
