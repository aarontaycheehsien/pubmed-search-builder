import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pubmed_tool.py"
SPEC = importlib.util.spec_from_file_location("pubmed_tool", MODULE_PATH)
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


OK_HOOK = {"name": "query_translation_drift", "ok": True, "review_recommended": False, "issues": []}
DRIFT_HOOK = {
    "name": "query_translation_drift",
    "ok": False,
    "review_recommended": True,
    "issues": [{"severity": "warning", "code": "phrases_not_found", "message": "x"}],
}
OK_PRECMD = {"name": "pre_pubmed_command", "ok": True, "issues": []}


class SummarizeResultTests(unittest.TestCase):
    """Direct, network-free tests of the pure compact projection."""

    def test_search_drops_verbose_keeps_qa_and_does_not_mutate(self):
        full = {
            "query": "asthma[tiab]", "count": 12345, "retmax": 0, "retstart": 0,
            "pmids": ["1", "2"], "query_translation": "long translation text",
            "translations": [["a", "b"]], "warnings": {"w": 1}, "errors": {},
            "query_translation_hook": OK_HOOK, "request_info": {"tool": "t"},
            "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("search", full)
        self.assertEqual(s["operation"], "search")
        self.assertEqual(s["count"], 12345)
        self.assertEqual(s["pmids_returned"], 2)
        self.assertEqual(s["warning_count"], 1)
        self.assertTrue(s["ok"])
        for dropped in ("query", "query_translation", "translations", "pmids"):
            self.assertNotIn(dropped, s)
        # The full result object must be untouched by summarization.
        self.assertIn("query_translation", full)
        self.assertEqual(full["pmids"], ["1", "2"])

    def test_search_drift_and_errors_flip_ok_and_expose_codes(self):
        full = {
            "count": 0, "retmax": 0, "pmids": [], "warnings": {}, "errors": {"phrasesnotfound": ["zzz"]},
            "query_translation_hook": DRIFT_HOOK, "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("search", full)
        self.assertFalse(s["drift_ok"])
        self.assertIn("phrases_not_found", s["drift_codes"])
        self.assertEqual(s["error_count"], 1)
        self.assertFalse(s["ok"])  # ok is false here because of the PubMed errorlist entry, not the drift

    def test_drift_without_errors_does_not_flip_ok(self):
        # Translation drift is advisory (the skill treats it as a review prompt, not an error),
        # so it must not flip ok on its own; it is surfaced via drift_ok / drift_codes instead.
        full = {
            "count": 5, "retmax": 0, "pmids": ["1"], "warnings": {"w": 1}, "errors": {},
            "query_translation_hook": DRIFT_HOOK, "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("search", full)
        self.assertTrue(s["ok"])
        self.assertFalse(s["drift_ok"])
        self.assertIn("phrases_not_found", s["drift_codes"])
        self.assertEqual(s["warning_count"], 1)

    def test_precommand_codes_surface_in_summary(self):
        full = {
            "count": 1, "retmax": 0, "pmids": [], "warnings": {}, "errors": {},
            "query_translation_hook": OK_HOOK,
            "pre_command_hook": {"ok": False, "issues": [{"severity": "error", "code": "api_key_on_command_line", "message": "x"}]},
        }
        s = pubmed_tool.summarize_result("search", full)
        self.assertFalse(s["precmd_ok"])
        self.assertIn("api_key_on_command_line", s["precmd_codes"])
        self.assertFalse(s["ok"])

    def test_batch_summary_strips_per_query_text_and_flags_drift(self):
        full = {
            "query_count": 2,
            "results": [
                {"label": "A", "query": "q1", "count": 10, "pmids": ["1"], "query_translation": "t1", "warnings": {}, "query_translation_hook": OK_HOOK},
                {"label": "B", "query": "q2", "count": 0, "pmids": [], "query_translation": "t2", "warnings": {}, "query_translation_hook": DRIFT_HOOK},
            ],
            "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("batch", full)
        self.assertEqual(s["query_count"], 2)
        self.assertTrue(s["any_drift"])
        self.assertEqual([r["label"] for r in s["results"]], ["A", "B"])
        for r in s["results"]:
            self.assertNotIn("query", r)
            self.assertNotIn("query_translation", r)
            self.assertNotIn("pmids", r)
        self.assertIn("phrases_not_found", s["results"][1]["drift_codes"])

    def test_validate_summary_keeps_retrieved_and_missed_seeds(self):
        full = {
            "query": "q", "validation_query": "(q) AND (...)", "provided_pmids": ["1", "2", "3", "4"],
            "retrieved_pmids": ["1", "2", "3"], "missed_pmids": ["4"], "search_count": 3,
            "query_translation": "t", "warnings": {}, "query_translation_hook": OK_HOOK, "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("validate", full)
        self.assertEqual(s["retrieved_pmids"], ["1", "2", "3"])
        self.assertEqual(s["missed_pmids"], ["4"])
        self.assertEqual(s["provided_count"], 4)
        self.assertEqual(s["recall_percent"], 75.0)
        self.assertNotIn("validation_query", s)
        self.assertNotIn("query", s)
        self.assertFalse(s["ok"])  # a missed seed must mark the run not-ok

    def test_recall_summary_keeps_relative_recall_missed_and_bottleneck(self):
        full = {
            "operation": "recall", "query": "q", "benchmark_source": "benchmark-pmids", "benchmark_size": 3,
            "retrieved_count": 2, "missed_count": 1, "relative_recall_percent": 66.67,
            "retrieved_pmids": ["1", "2"], "missed_pmids": ["3"], "note": "caveat text", "request_info": {},
            "block_recall": [
                {"label": "pop", "query": "...", "retrieved_count": 3, "recall_percent": 100.0, "bottleneck": False},
                {"label": "intervention", "query": "...", "retrieved_count": 2, "recall_percent": 66.67, "bottleneck": True},
            ],
            "miss_diagnosis": [{"pmid": "3", "culprit_blocks": ["intervention"], "and_interaction": False}],
            "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("recall", full)
        self.assertEqual(s["relative_recall_percent"], 66.67)
        self.assertEqual(s["missed_count"], 1)
        self.assertEqual(s["missed_pmids"], ["3"])
        self.assertEqual(s["bottleneck_block"], "intervention")
        self.assertEqual(s["miss_diagnosis_count"], 1)
        self.assertEqual(s["and_interaction_count"], 0)
        self.assertNotIn("retrieved_pmids", s)  # large list dropped from stdout
        for b in s["block_recall"]:
            self.assertNotIn("query", b)

    def test_related_summary_drops_candidate_array_but_keeps_counts(self):
        full = {
            "operation": "related", "seed_pmids": ["1", "2"], "links_used": ["similar"],
            "max_per_seed": 20, "max_total": 100, "link_counts": {"similar": 40},
            "candidate_count": 30, "candidate_count_before_cap": 40,
            "candidate_pmids": [{"pmid": "9", "seed_overlap_count": 2}, {"pmid": "8", "seed_overlap_count": 1}],
            "note": "caveat", "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("related", full)
        self.assertEqual(s["candidate_count"], 30)
        self.assertEqual(s["candidate_count_before_cap"], 40)
        self.assertEqual(s["top_overlap"], 2)
        self.assertNotIn("candidate_pmids", s)

    def test_term_rank_summary_truncates_and_reports_totals(self):
        ranked = [
            {
                "term": f"t{i}", "field": "tiab", "coverage": round(1.0 - i / 100, 4), "lift": 5.0,
                "noise_risk": (i % 2 == 0), "background_query": "bq", "sources": ["phrase"],
                "in_strategy": False, "suggested_layer": "tiab",
            }
            for i in range(45)
        ]
        full = {
            "operation": "term-rank", "relevant_record_count": 50, "fields": ["tiab"],
            "candidates_scored": 45, "candidates_unscored": 5, "ranked_terms": ranked, "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("term-rank", full)
        self.assertEqual(s["ranked_terms_total"], 45)
        self.assertEqual(s["ranked_terms_shown"], 20)
        self.assertEqual(len(s["top_terms"]), 20)
        for t in s["top_terms"]:
            self.assertNotIn("background_query", t)
            self.assertNotIn("sources", t)
            self.assertIn("coverage", t)
            self.assertIn("lift", t)

    def test_variants_summary_keeps_missed_seeds_and_drops_text(self):
        full = {
            "operation": "variants", "variant_count": 2, "baseline_label": "main",
            "results": [
                {
                    "label": "main", "query": "q1", "count": 100, "pmids": [], "query_translation": "t",
                    "query_translation_hook": OK_HOOK, "warnings": {}, "count_delta_from_baseline": 0,
                    "percent_of_baseline": 100.0, "role": "sensitive", "decision_status": "selected",
                    "seed_pmids_retrieved": ["1", "2"], "seed_pmids_missed": [], "seed_recall_percent": 100.0,
                },
                {
                    "label": "focused", "query": "q2", "count": 80, "pmids": [], "query_translation": "t",
                    "query_translation_hook": OK_HOOK, "warnings": {}, "count_delta_from_baseline": -20,
                    "percent_of_baseline": 80.0, "role": "focused", "decision_status": "reserve",
                    "seed_pmids_retrieved": ["1"], "seed_pmids_missed": ["2"], "seed_recall_percent": 50.0,
                },
            ],
            "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("variants", full)
        self.assertEqual(s["baseline_label"], "main")
        focused = s["results"][1]
        self.assertEqual(focused["seed_pmids_missed"], ["2"])
        self.assertEqual(focused["seed_recall_percent"], 50.0)
        self.assertEqual(focused["role"], "focused")
        self.assertEqual(focused["count_delta_from_baseline"], -20)
        for dropped in ("query", "query_translation", "pmids"):
            self.assertNotIn(dropped, focused)

    def test_record_content_commands_do_not_support_compact_summaries(self):
        for command in ("fetch", "mine", "sample"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(ValueError, "record-content command"):
                    pubmed_tool.summarize_result(command, {"pre_command_hook": OK_PRECMD})


def stub_esearch(client, query, retmax=0, retstart=0, sort=None):
    """Deterministic, network-free esearch replacement for main()-level tests."""
    uids = re.findall(r"(\d+)\[uid\]", query)
    pmids = uids[:1] if uids else ["100", "101"]
    return {
        "query": query,
        "count": len(uids) if uids else 2,
        "retmax": retmax,
        "retstart": retstart,
        "pmids": pmids,
        "query_translation": query,
        "translations": [],
        "warnings": {},
        "errors": {},
        "query_translation_hook": dict(OK_HOOK),
        "request_info": {"tool": "test"},
    }


def stub_efetch(client, pmids):
    """Deterministic, network-free efetch replacement for mine/sample integration tests."""
    records = []
    requested_pmids = [str(value) for value in pmids]
    for pmid in requested_pmids:
        if pmid == "404":
            continue
        records.append(
            {
                "pmid": pmid,
                "title": f"Title {pmid}",
                "abstract": f"Abstract for {pmid}",
                "journal": "Test Journal",
                "journal_iso": "Test J",
                "year": "2024",
                "doi": "",
                "publication_types": ["Journal Article"],
                "mesh_headings": [
                    {"ui": "D001", "major_topic": "N", "name": "Robotics", "qualifiers": []},
                    {"ui": "D002", "major_topic": "Y", "name": "Homes for the Aged", "qualifiers": []},
                ],
                "keywords": ["robot pets", "care homes"],
            }
        )
    found_pmids = [record["pmid"] for record in records]
    return {
        "operation": "fetch",
        "requested_pmids": requested_pmids,
        "found_pmids": found_pmids,
        "missing_pmids": [pmid for pmid in requested_pmids if pmid not in set(found_pmids)],
        "records": records,
        "request_info": {"tool": "test"},
    }


class EmitIntegrationTests(unittest.TestCase):
    """End-to-end via main() with stubbed network: proves compact mode never changes the object."""

    def setUp(self):
        self._orig = pubmed_tool.esearch
        self._orig_efetch = pubmed_tool.efetch
        pubmed_tool.esearch = stub_esearch
        pubmed_tool.efetch = stub_efetch
        self.addCleanup(lambda: setattr(pubmed_tool, "esearch", self._orig))
        self.addCleanup(lambda: setattr(pubmed_tool, "efetch", self._orig_efetch))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = pubmed_tool.main(argv)
        text = out.getvalue().strip()
        return rc, (json.loads(text) if text else None)

    def test_default_stdout_is_full_and_backward_compatible(self):
        rc, data = self.run_main(["search", "asthma[tiab]", "--retmax", "0"])
        self.assertEqual(rc, 0)
        for key in ("query", "query_translation", "query_translation_hook", "request_info"):
            self.assertIn(key, data)

    def test_summary_stdout_omits_query_and_translation(self):
        rc, data = self.run_main(["search", "asthma[tiab]", "--retmax", "0", "--summary"])
        self.assertEqual(rc, 0)
        self.assertNotIn("query", data)
        self.assertNotIn("query_translation", data)
        self.assertIn("count", data)
        self.assertIn("ok", data)

    def test_output_writes_full_json_and_object_is_unchanged(self):
        _, full_default = self.run_main(["search", "asthma[tiab]", "--retmax", "0"])
        out_path = str(Path(self.tmp.name) / "search.json")
        rc, compact = self.run_main(["search", "asthma[tiab]", "--retmax", "0", "--summary", "--output", out_path])
        self.assertEqual(rc, 0)
        full_file = json.loads(Path(out_path).read_text(encoding="utf-8"))
        # The serialized full object must be identical with and without compact mode.
        self.assertEqual(full_default, full_file)
        self.assertEqual(compact["output"], out_path)
        self.assertNotIn("query_translation", compact)

    def test_output_alone_implies_compact_stdout(self):
        out_path = str(Path(self.tmp.name) / "s2.json")
        rc, stdout_obj = self.run_main(["search", "asthma[tiab]", "--retmax", "0", "--output", out_path])
        self.assertEqual(rc, 0)
        self.assertNotIn("query_translation", stdout_obj)  # stdout compact even without --summary
        self.assertIn("count", stdout_obj)
        full_file = json.loads(Path(out_path).read_text(encoding="utf-8"))
        self.assertIn("query_translation", full_file)  # file holds the full object

    def test_recall_compact_via_main_reports_required_fields(self):
        rc, data = self.run_main(
            ["recall", "(asthma) AND (child)", "--benchmark-pmids", "1", "2", "3", "--summary"]
        )
        self.assertEqual(rc, 0)
        self.assertIn("relative_recall_percent", data)
        self.assertIn("missed_count", data)
        self.assertIn("bottleneck_block", data)
        self.assertNotIn("retrieved_pmids", data)

    def test_record_content_commands_require_output_and_reject_summary(self):
        parser = pubmed_tool.build_parser()
        valid_cases = [
            ["fetch", "--pmids", "1", "--output", "fetch.json"],
            ["mine", "--pmids", "1", "--output", "mine.json"],
            ["sample", "robot[tiab]", "--output", "sample.json"],
        ]
        for argv in valid_cases:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertTrue(args.output)

        invalid_cases = [
            ["fetch", "--pmids", "1"],
            ["mine", "--pmids", "1"],
            ["sample", "robot[tiab]"],
            ["fetch", "--pmids", "1", "--summary", "--output", "fetch.json"],
            ["mine", "--pmids", "1", "--summary", "--output", "mine.json"],
            ["sample", "robot[tiab]", "--summary", "--output", "sample.json"],
        ]
        for argv in invalid_cases:
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    parser.parse_args(argv)

    def test_fetch_output_writes_full_json_and_receipt_stdout(self):
        out_path = str(Path(self.tmp.name) / "fetch.json")
        rc, receipt = self.run_main(["fetch", "--pmids", "1", "404", "--output", out_path])
        self.assertEqual(rc, 0)
        full_file = json.loads(Path(out_path).read_text(encoding="utf-8"))
        self.assertEqual(full_file["operation"], "fetch")
        self.assertEqual(full_file["missing_pmids"], ["404"])
        self.assertIn("abstract", full_file["records"][0])
        self.assertEqual(receipt["operation"], "fetch")
        self.assertEqual(receipt["stdout_role"], "receipt_only")
        self.assertTrue(receipt["full_json_review_required"])
        self.assertEqual(receipt["output"], out_path)
        self.assertEqual(receipt["missing_pmids"], ["404"])
        self.assertNotIn("records", receipt)
        self.assertNotIn("Abstract for", json.dumps(receipt))

    def test_mine_output_writes_full_json_and_receipt_stdout(self):
        out_path = str(Path(self.tmp.name) / "mine.json")
        rc, receipt = self.run_main(["mine", "--pmids", "1", "404", "--output", out_path])
        self.assertEqual(rc, 0)
        full_file = json.loads(Path(out_path).read_text(encoding="utf-8"))
        self.assertEqual(full_file["missing_pmids"], ["404"])
        self.assertIn("abstract", full_file["records"][0])
        self.assertEqual(full_file["records"][0]["abstract"], "Abstract for 1")
        self.assertEqual(receipt["output"], out_path)
        self.assertEqual(receipt["stdout_role"], "receipt_only")
        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["missing_pmids"], ["404"])
        for forbidden in ("records", "mesh_heading_counts", "phrase_counts", "candidate_tiab_terms"):
            self.assertNotIn(forbidden, receipt)
        self.assertNotIn("Abstract for", json.dumps(receipt))

    def test_sample_output_writes_full_json_and_receipt_stdout(self):
        out_path = str(Path(self.tmp.name) / "sample.json")
        rc, receipt = self.run_main(["sample", "robot[tiab]", "--output", out_path])
        self.assertEqual(rc, 0)
        full_file = json.loads(Path(out_path).read_text(encoding="utf-8"))
        self.assertEqual(full_file["operation"], "sample")
        self.assertIn("query_translation", full_file["search"])
        self.assertIn("abstract", full_file["records"][0])
        self.assertEqual(receipt["output"], out_path)
        self.assertEqual(receipt["stdout_role"], "receipt_only")
        self.assertEqual(receipt["search_count"], 2)
        self.assertEqual(receipt["records_saved"], 2)
        for forbidden in ("records", "mesh_heading_counts", "publication_type_counts", "query_translation"):
            self.assertNotIn(forbidden, receipt)
        self.assertNotIn("Abstract for", json.dumps(receipt))

    def test_record_content_summary_is_rejected_by_main(self):
        cases = [
            ["fetch", "--pmids", "1", "--summary", "--output", "fetch.json"],
            ["mine", "--pmids", "1", "--summary", "--output", "mine.json"],
            ["sample", "robot[tiab]", "--summary", "--output", "sample.json"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                err = io.StringIO()
                with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                    pubmed_tool.main(argv)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("--summary", err.getvalue())


class ZeroHitCompactTests(unittest.TestCase):
    """Compact summaries must surface the actual not-found phrases, not just the code."""

    def test_search_surfaces_not_found_phrases_and_drift_details(self):
        hook = {
            "name": "query_translation_drift", "ok": False, "review_recommended": True,
            "issues": [{"severity": "warning", "code": "phrases_not_found", "message": "...", "evidence": '"a", "b"'}],
        }
        full = {
            "count": 5, "retmax": 0, "pmids": [],
            "errors": {"phrasesnotfound": ['"a"', '"b"']},
            "warnings": {"quotedphrasesnotfound": ['"c"']},
            "query_translation_hook": hook, "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("search", full)
        self.assertEqual(s["phrases_not_found"], ['"a"', '"b"', '"c"'])  # errorlist + warninglist, deduped
        self.assertEqual(s["phrases_not_found_total"], 3)
        self.assertTrue(any(d["code"] == "phrases_not_found" and "a" in d["evidence"] for d in s["drift_details"]))

    def test_batch_row_surfaces_not_found_phrases(self):
        full = {
            "query_count": 1,
            "results": [{
                "label": "blk", "count": 0, "query": "q", "query_translation": "t",
                "warnings": {"quotedphrasesnotfound": ['"c"']}, "errors": {"phrasesnotfound": ['"a"']},
                "query_translation_hook": {"ok": False, "issues": [{"code": "phrases_not_found", "evidence": '"a"'}]},
            }],
            "pre_command_hook": OK_PRECMD,
        }
        row = pubmed_tool.summarize_result("batch", full)["results"][0]
        self.assertEqual(row["phrases_not_found"], ['"a"', '"c"'])
        self.assertIn("drift_details", row)

    def test_validate_surfaces_quoted_phrases_not_found(self):
        full = {
            "provided_pmids": ["1"], "retrieved_pmids": ["1"], "missed_pmids": [],
            "warnings": {"quotedphrasesnotfound": ['"x"']},
            "query_translation_hook": {"ok": False, "issues": []}, "pre_command_hook": OK_PRECMD,
        }
        s = pubmed_tool.summarize_result("validate", full)
        self.assertEqual(s["phrases_not_found"], ['"x"'])

    def test_clean_search_omits_phrase_fields(self):
        full = {"count": 5, "retmax": 0, "pmids": [], "warnings": {}, "errors": {},
                "query_translation_hook": OK_HOOK, "pre_command_hook": OK_PRECMD}
        s = pubmed_tool.summarize_result("search", full)
        self.assertNotIn("phrases_not_found", s)
        self.assertNotIn("drift_details", s)


if __name__ == "__main__":
    unittest.main()
