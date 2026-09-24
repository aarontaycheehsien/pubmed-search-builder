"""A search update re-runs the frozen strategy and reports drift instead of repairing it."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("search_update_test", ROOT / "scripts" / "search_update.py")
search_update = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(search_update)
pubmed_tool = search_update.pubmed_tool

STRATEGY = '("Virtual Reality"[Mesh] OR "virtual reality"[tiab]) AND "Students, Nursing"[Mesh]'
TRANSLATION = '("virtual reality"[MeSH Terms] OR "virtual reality"[Title/Abstract]) AND "students, nursing"[MeSH Terms]'


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


def esearch_result(query, *, count, translation=TRANSLATION, pmids=(), errors=None, hook_issues=()):
    return {
        "query": query, "count": count, "pmids": list(pmids), "query_translation": translation,
        "translations": [], "warnings": {}, "errors": errors or {},
        "query_translation_hook": {"issues": list(hook_issues)},
    }


class SearchUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.strategy = self.root / "final_strategy.txt"
        self.strategy.write_text(STRATEGY, encoding="utf-8")
        self.baseline = self.root / "final_search.json"
        self.baseline.write_text(json.dumps(esearch_result(STRATEGY, count=410)), encoding="utf-8")

    def run_check(self, *, translation=TRANSLATION, retrieved=("11", "12"), errors=None, validation=("11", "12")):
        calls = []

        def fake_esearch(client, query, retmax, retstart, sort):
            calls.append((query, retmax))
            if "[crdt]" in query:
                return esearch_result(query, count=3, translation=translation, pmids=["101", "102", "103"][:retmax])
            return esearch_result(query, count=431, translation=translation, errors=errors)

        with mock.patch.object(pubmed_tool, "esearch", side_effect=fake_esearch), mock.patch.object(
            pubmed_tool, "retrieve_against_pmids", return_value=set(retrieved)
        ):
            result = search_update.check(
                FakeClient(), strategy_path=self.strategy, baseline_path=self.baseline,
                last_searched="2026-03-01", until="2026-09-25", date_field="crdt",
                validation_pmids=list(validation), validation_source="explicit-pmids",
            )
        return result, calls

    def test_an_unchanged_strategy_returns_new_records_and_a_prisma_s_statement(self):
        result, calls = self.run_check()
        self.assertEqual(result["verdict"], "no-drift")
        self.assertEqual(result["new_records"], {"count": 3, "pmids": ["101", "102", "103"]})
        self.assertEqual(result["count_change"], 21)
        self.assertIn('"2026/03/01"[crdt] : "2026/09/25"[crdt]', result["update_window"]["query"])
        self.assertIn("updated on 2026-09-25", result["prisma_s_update"])
        self.assertIn("3 records retrieved for screening", result["prisma_s_update"])
        report = search_update.render_report(result)
        self.assertIn("**Verdict:** no-drift", report)

    def test_a_changed_mesh_translation_requires_review_instead_of_being_fixed(self):
        drifted = TRANSLATION.replace('"virtual reality"[MeSH Terms]', '"virtual reality"[MeSH Terms] OR "augmented reality"[MeSH Terms]')
        result, _ = self.run_check(translation=drifted)
        self.assertEqual(result["verdict"], "review-required")
        self.assertTrue(result["translation_drift"]["translation_changed"])
        self.assertIn("existing-strategy review", result["required_actions"][0])
        self.assertIn("Translation changed since the build:** yes", search_update.render_report(result))

    def test_a_term_newly_not_found_is_drift(self):
        result, _ = self.run_check(errors={"phrasesnotfound": ["retired heading"]})
        self.assertEqual(result["verdict"], "review-required")
        self.assertEqual(result["translation_drift"]["notices_appeared"], {"phrasesnotfound": ["retired heading"]})

    def test_a_validation_record_now_missed_requires_review(self):
        result, _ = self.run_check(retrieved=("11",))
        self.assertEqual(result["verdict"], "review-required")
        self.assertEqual(result["validation"]["missed"], ["12"])

    def test_a_different_strategy_is_not_an_update(self):
        self.strategy.write_text(STRATEGY + ' OR "vr"[tiab]', encoding="utf-8")
        with self.assertRaisesRegex(search_update.SearchUpdateError, "differs from the baseline"):
            self.run_check()

    def test_an_inverted_window_is_refused(self):
        with self.assertRaisesRegex(search_update.SearchUpdateError, "after the end"):
            search_update.check(
                FakeClient(), strategy_path=self.strategy, baseline_path=self.baseline,
                last_searched="2026-10-01", until="2026-09-25", date_field="crdt",
                validation_pmids=[], validation_source="",
            )

    def test_cli_writes_result_report_and_receipt(self):
        output = self.root / "search_update.json"
        report = self.root / "search_update.md"

        def fake_esearch(client, query, retmax, retstart, sort):
            count = 2 if "[crdt]" in query else 410
            return esearch_result(query, count=count, pmids=["101", "102"][:retmax] if "[crdt]" in query else [])

        with mock.patch.object(pubmed_tool, "esearch", side_effect=fake_esearch):
            code = search_update.main([
                "check", "--strategy-file", str(self.strategy), "--baseline-search", str(self.baseline),
                "--last-searched", "2026-03-01", "--until", "2026-09-25", "--output", str(output), "--report", str(report),
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["new_records"]["count"], 2)
        self.assertIn("PRISMA-S update statement", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
