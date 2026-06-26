import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pubmed_tool.py"
SPEC = importlib.util.spec_from_file_location("pubmed_tool", MODULE_PATH)
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


def mesh_record(pmid, names):
    return {"pmid": pmid, "title": "", "abstract": "", "keywords": [], "mesh_headings": [{"name": name} for name in names]}


class TermRankTests(unittest.TestCase):
    def run_mesh_term_rank(self, *, max_terms, background, pubmed_total=1_000_000):
        records = [
            mesh_record("1", ["Asthma", "Status Asthmaticus"]),
            mesh_record("2", ["Asthma", "Respiratory Sounds"]),
            mesh_record("3", ["Asthma"]),
        ]
        calls = []

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            calls.append(query)
            return {"count": background.get(query, 1000), "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}

        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch
        try:
            result = pubmed_tool.term_rank(
                FakeClient(),
                records,
                fields=["mesh"],
                max_terms=max_terms,
                strategy_text="",
                pubmed_total=pubmed_total,
            )
        finally:
            pubmed_tool.esearch = original
        return result, calls

    def test_mesh_coverage_lift_and_ranking_order(self):
        background = {
            '"Asthma"[Mesh]': 200_000,
            '"Status Asthmaticus"[Mesh]': 50_000,
            '"Respiratory Sounds"[Mesh]': 80_000,
        }
        result, calls = self.run_mesh_term_rank(max_terms=10, background=background)

        self.assertEqual(result["relevant_record_count"], 3)
        self.assertEqual(result["candidates_scored"], 3)
        self.assertEqual(len(calls), 3)

        terms = result["ranked_terms"]
        self.assertEqual(
            [row["term"] for row in terms], ["Asthma", "Status Asthmaticus", "Respiratory Sounds"]
        )

        asthma, status, sounds = terms
        self.assertEqual(asthma["relevant_df"], 3)
        self.assertEqual(asthma["coverage"], 1.0)
        self.assertEqual(asthma["background_count"], 200_000)
        self.assertEqual(asthma["lift"], 5.0)
        self.assertFalse(asthma["noise_risk"])

        self.assertEqual(status["coverage"], 0.3333)
        self.assertEqual(status["lift"], 6.67)
        self.assertEqual(sounds["lift"], 4.17)
        # Equal coverage is broken by higher lift first.
        self.assertGreater(status["lift"], sounds["lift"])

    def test_background_calls_capped_by_max_terms(self):
        background = {
            '"Asthma"[Mesh]': 200_000,
            '"Status Asthmaticus"[Mesh]': 50_000,
            '"Respiratory Sounds"[Mesh]': 80_000,
        }
        result, calls = self.run_mesh_term_rank(max_terms=2, background=background)

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["candidates_considered"], 3)
        self.assertEqual(result["candidates_scored"], 2)
        self.assertEqual(result["candidates_unscored"], 1)

    def test_tiab_document_frequency_is_per_record_and_flags_in_strategy(self):
        records = [
            {"pmid": "1", "title": "", "abstract": "machine learning improves machine learning outcomes", "keywords": [], "mesh_headings": []},
            {"pmid": "2", "title": "", "abstract": "deep learning and machine learning methods", "keywords": [], "mesh_headings": []},
            {"pmid": "3", "title": "", "abstract": "unrelated clinical topic without the phrase", "keywords": [], "mesh_headings": []},
        ]

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 300_000, "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}

        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch
        try:
            result = pubmed_tool.term_rank(
                FakeClient(),
                records,
                fields=["tiab"],
                max_terms=50,
                strategy_text='("machine learning"[tiab])',
                pubmed_total=1_000_000,
            )
        finally:
            pubmed_tool.esearch = original

        by_term = {row["term"]: row for row in result["ranked_terms"]}
        self.assertIn("machine learning", by_term)
        ml = by_term["machine learning"]
        # Appears twice in record 1 but is counted once there -> df 2 across records 1 and 2.
        self.assertEqual(ml["relevant_df"], 2)
        self.assertEqual(ml["coverage"], 0.6667)
        self.assertEqual(ml["field"], "tiab")
        self.assertTrue(ml["in_strategy"])

    def test_zero_background_count_marks_term_and_skips_lift(self):
        records = [mesh_record("1", ["Novelconceptium"]), mesh_record("2", ["Novelconceptium"])]

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 0, "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}

        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch
        try:
            result = pubmed_tool.term_rank(
                FakeClient(), records, fields=["mesh"], max_terms=10, strategy_text="", pubmed_total=1_000_000
            )
        finally:
            pubmed_tool.esearch = original

        row = result["ranked_terms"][0]
        self.assertIsNone(row["lift"])
        self.assertTrue(row["background_zero"])
        self.assertFalse(row["noise_risk"])


class TermRankRelevantQueryCliTests(unittest.TestCase):
    """Exercise the --relevant-query-file CLI resolution path (no-seed entry point)."""

    PILOT = '"asthma"[tiab] AND "child"[tiab]'

    def _records(self):
        return [
            {"pmid": "11", "title": "", "abstract": "", "keywords": [], "mesh_headings": [{"name": "Asthma"}]},
            {"pmid": "12", "title": "", "abstract": "", "keywords": [], "mesh_headings": [{"name": "Asthma"}, {"name": "Child"}]},
        ]

    def _run(self, argv, pilot_pmids=("11", "12")):
        calls = {"esearch": [], "efetch": []}

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            calls["esearch"].append({"query": query, "retmax": retmax})
            if retmax > 0:  # the pilot relevant-set resolution call
                return {"count": len(pilot_pmids), "retmax": retmax, "pmids": list(pilot_pmids)}
            return {"count": 1000, "retmax": retmax, "pmids": []}  # per-term background count

        def fake_efetch(client, pmids):
            calls["efetch"].append(list(pmids))
            return {"records": self._records()}

        orig_esearch, orig_efetch = pubmed_tool.esearch, pubmed_tool.efetch
        pubmed_tool.esearch = fake_esearch
        pubmed_tool.efetch = fake_efetch
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                code = pubmed_tool.main(argv)
        finally:
            pubmed_tool.esearch = orig_esearch
            pubmed_tool.efetch = orig_efetch
        return code, buffer.getvalue(), calls

    def test_relevant_query_file_resolves_pilot_set_and_ranks(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = Path(tmp) / "pilot.txt"
            pilot.write_text(self.PILOT, encoding="utf-8")
            code, out, calls = self._run(
                ["term-rank", "--relevant-query-file", str(pilot), "--fields", "mesh", "--relevant-retmax", "50"]
            )

        self.assertEqual(code, 0)
        # First esearch resolves the pilot query, capped by --relevant-retmax.
        self.assertEqual(calls["esearch"][0]["query"], pubmed_tool.normalize_query(self.PILOT))
        self.assertEqual(calls["esearch"][0]["retmax"], 50)
        # Resolved PMIDs flow into efetch, then into ranking.
        self.assertEqual(calls["efetch"], [["11", "12"]])
        payload = json.loads(out)
        self.assertEqual(payload["operation"], "term-rank")
        self.assertEqual(payload["relevant_record_count"], 2)

    def test_empty_relevant_query_file_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = Path(tmp) / "empty.txt"
            pilot.write_text("   \n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                self._run(["term-rank", "--relevant-query-file", str(pilot), "--fields", "mesh"])

    def test_relevant_query_with_no_hits_returns_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = Path(tmp) / "pilot.txt"
            pilot.write_text('"nonexistentconceptium"[tiab]', encoding="utf-8")
            code, out, calls = self._run(
                ["term-rank", "--relevant-query-file", str(pilot), "--fields", "mesh"],
                pilot_pmids=(),
            )

        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))
        self.assertEqual(calls["efetch"], [])


class TermRankFilterTests(unittest.TestCase):
    """Exclude/only filters keep triage-excluded seeds out of the relevant set."""

    def test_filter_pmids_exclude_only_and_dedup(self):
        self.assertEqual(pubmed_tool.filter_pmids(["A", "B", "BAD", "B"], exclude=["BAD"]), (["A", "B"], ["BAD"]))
        self.assertEqual(pubmed_tool.filter_pmids(["A", "B", "BAD"], only=["A", "B"]), (["A", "B"], ["BAD"]))
        # only then exclude compose; order preserved.
        self.assertEqual(pubmed_tool.filter_pmids(["A", "A", "B", "C"], only=["A", "B"], exclude=["B"]), (["A"], ["C", "B"]))

    def _run_mine(self, found, extra_args):
        calls = {"efetch": []}

        def fake_efetch(client, pmids):
            calls["efetch"].append(list(pmids))
            return {"records": [{"pmid": p, "title": "", "abstract": "", "keywords": [], "mesh_headings": [{"name": "Asthma"}]} for p in pmids]}

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 1000, "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}

        orig_es, orig_ef = pubmed_tool.esearch, pubmed_tool.efetch
        pubmed_tool.esearch, pubmed_tool.efetch = fake_esearch, fake_efetch
        buffer = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                mine = Path(tmp) / "mine.json"
                mine.write_text(json.dumps({"found_pmids": found, "requested_pmids": found, "missing_pmids": []}), encoding="utf-8")
                with contextlib.redirect_stdout(buffer):
                    rc = pubmed_tool.main(["term-rank", "--mine-json", str(mine), "--fields", "mesh", *extra_args])
        finally:
            pubmed_tool.esearch, pubmed_tool.efetch = orig_es, orig_ef
        return rc, json.loads(buffer.getvalue()), calls

    def test_mine_json_exclude_drops_seed_and_records_provenance(self):
        rc, payload, calls = self._run_mine(["A", "B", "BAD"], ["--exclude-pmids", "BAD"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls["efetch"], [["A", "B"]])  # excluded seed never fetched/ranked
        self.assertEqual(payload["excluded_pmids"], ["BAD"])
        self.assertEqual(payload["relevant_pmids"], ["A", "B"])

    def test_mine_json_only_pmids_whitelist(self):
        rc, payload, calls = self._run_mine(["A", "B", "BAD"], ["--only-pmids", "A", "B"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls["efetch"], [["A", "B"]])
        self.assertEqual(payload["relevant_pmids"], ["A", "B"])

    def test_excluding_every_pmid_returns_error(self):
        rc, payload, calls = self._run_mine(["A"], ["--exclude-pmids", "A"])
        self.assertEqual(rc, 1)
        self.assertIn("error", payload)
        self.assertEqual(calls["efetch"], [])  # nothing fetched when the set is empty


class TermRankNoiseFilterTests(unittest.TestCase):
    """Boilerplate, statistical, and non-topical candidates are dropped before scoring."""

    def _rank(self, records, fields, max_terms=50):
        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 1000, "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}

        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch
        try:
            return pubmed_tool.term_rank(
                FakeClient(), records, fields=fields, max_terms=max_terms, strategy_text="", pubmed_total=1_000_000
            )
        finally:
            pubmed_tool.esearch = original

    def test_structured_abstract_headings_excluded_real_acronym_kept(self):
        records = [
            {"pmid": "1", "title": "", "abstract": "OBJECTIVES To assess COPD severity. METHODS We enrolled patients. RESULTS COPD severity rose. CONCLUSIONS COPD is serious.", "keywords": [], "mesh_headings": []},
            {"pmid": "2", "title": "", "abstract": "BACKGROUND COPD burden grows. RESULTS COPD prevalence varied.", "keywords": [], "mesh_headings": []},
        ]
        terms = {str(row["term"]).upper() for row in self._rank(records, ["tiab"])["ranked_terms"]}
        for junk in ("OBJECTIVES", "METHODS", "RESULTS", "CONCLUSIONS", "BACKGROUND"):
            self.assertNotIn(junk, terms)
        self.assertIn("COPD", terms)  # a genuine acronym is preserved

    def test_statistical_fragments_excluded_content_terms_kept(self):
        records = [
            {"pmid": "1", "title": "", "abstract": "type 2 diabetes outcomes were significant p 0 05 with 95 ci among covid 19 cases", "keywords": ["p53"], "mesh_headings": []},
            {"pmid": "2", "title": "", "abstract": "type 2 diabetes and covid 19 interact p 0 01", "keywords": ["p53"], "mesh_headings": []},
        ]
        terms = {str(row["term"]) for row in self._rank(records, ["tiab"])["ranked_terms"]}
        for junk in ("p 0", "0 05", "95 ci", "0 01"):
            self.assertNotIn(junk, terms)
        for kept in ("type 2 diabetes", "covid 19", "p53"):
            self.assertIn(kept, terms)

    def test_non_topical_mesh_and_keyword_excluded(self):
        records = [
            {"pmid": "1", "title": "", "abstract": "", "keywords": ["Queensland"], "mesh_headings": [{"name": "Asthma"}, {"name": "Queensland"}, {"name": "Humans"}, {"name": "Female"}]},
            {"pmid": "2", "title": "", "abstract": "", "keywords": [], "mesh_headings": [{"name": "Asthma"}, {"name": "Humans"}]},
        ]
        terms = {str(row["term"]) for row in self._rank(records, ["tiab", "mesh"])["ranked_terms"]}
        self.assertIn("Asthma", terms)
        for junk in ("Queensland", "Humans", "Female"):
            self.assertNotIn(junk, terms)

    def test_section_label_phrase_artifacts_excluded_topical_modifiers_kept(self):
        records = [
            {"pmid": "1", "title": "", "abstract": "RESULTS asthma improved after early intervention for child health", "keywords": [], "mesh_headings": []},
            {"pmid": "2", "title": "", "abstract": "RESULTS asthma improved after early intervention for child health", "keywords": [], "mesh_headings": []},
        ]
        terms = {str(row["term"]) for row in self._rank(records, ["tiab"])["ranked_terms"]}
        self.assertNotIn("results asthma", terms)  # section label at a phrase boundary
        # 'intervention' and 'child' are not boundary-noise words, so real phrases survive.
        self.assertIn("early intervention", terms)
        self.assertIn("child health", terms)


class TermRankFieldsValidationTests(unittest.TestCase):
    """`--fields` accepts only tiab and mesh; keywords/acronym/phrase are not selectable fields."""

    def _parse(self, value):
        return pubmed_tool.parse_term_rank_fields(value, argparse.ArgumentParser())

    def test_valid_fields_parse_and_dedupe(self):
        self.assertEqual(self._parse("tiab,mesh"), ["tiab", "mesh"])
        self.assertEqual(self._parse("mesh"), ["mesh"])
        self.assertEqual(self._parse("tiab, tiab"), ["tiab"])

    def test_keywords_field_rejected_with_guiding_message(self):
        buffer = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(buffer):
            self._parse("keywords")
        self.assertIn("tiab", buffer.getvalue())

    def test_mixed_with_unknown_field_rejected(self):
        with self.assertRaises(SystemExit):
            self._parse("tiab,mesh,keywords")


if __name__ == "__main__":
    unittest.main()
