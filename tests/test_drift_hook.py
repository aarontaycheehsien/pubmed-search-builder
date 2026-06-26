import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pubmed_tool.py"
SPEC = importlib.util.spec_from_file_location("pubmed_tool", MODULE_PATH)
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


def codes(result):
    return [issue["code"] for issue in result["issues"]]


def issue_with(result, code):
    for issue in result["issues"]:
        if issue["code"] == code:
            return issue
    return None


class DriftHookErrorListTests(unittest.TestCase):
    def test_phrases_not_found_deduplicated_with_occurrence_count(self):
        # Mirrors the real robopets case: each zero-hit term appears 3x in the query.
        errors = {"phrasesnotfound": ["NeCoRo", "JustoCat", "NeCoRo", "JustoCat", "NeCoRo", "JustoCat"]}
        result = pubmed_tool.query_translation_drift_hook(
            '("NeCoRo"[tiab] OR "JustoCat"[tiab])', "", [], {}, errors
        )

        self.assertIn("phrases_not_found", codes(result))
        issue = issue_with(result, "phrases_not_found")
        # Deduplicated to the unique terms...
        self.assertIn("NeCoRo", issue["evidence"])
        self.assertIn("JustoCat", issue["evidence"])
        self.assertEqual(issue["evidence"].count("NeCoRo"), 1)
        # ...with the total occurrence count surfaced so the duplication is visible.
        self.assertIn("6 total occurrences", issue["evidence"])
        self.assertTrue(result["review_recommended"])

    def test_single_occurrence_has_no_total_count_suffix(self):
        errors = {"phrasesnotfound": ["NeCoRo"]}
        result = pubmed_tool.query_translation_drift_hook('"NeCoRo"[tiab]', "", [], {}, errors)
        issue = issue_with(result, "phrases_not_found")
        self.assertEqual(issue["evidence"], "NeCoRo")

    def test_fields_not_found_reported(self):
        errors = {"fieldsnotfound": ["tiba"]}
        result = pubmed_tool.query_translation_drift_hook("cat[tiba]", "", [], {}, errors)
        self.assertIn("fields_not_found", codes(result))

    def test_no_error_list_yields_no_not_found_issue(self):
        for errors in ({}, None, {"phrasesnotfound": []}):
            result = pubmed_tool.query_translation_drift_hook("cat[tiab]", "cat[tiab]", [], {}, errors)
            self.assertNotIn("phrases_not_found", codes(result))
            self.assertNotIn("fields_not_found", codes(result))

    def test_hook_is_backward_compatible_without_errors_argument(self):
        # The errors parameter is optional; existing callers must still work.
        result = pubmed_tool.query_translation_drift_hook("cat[tiab]", "cat[tiab]", [], {})
        self.assertEqual(result["name"], "query_translation_drift")
        self.assertNotIn("phrases_not_found", codes(result))


if __name__ == "__main__":
    unittest.main()
