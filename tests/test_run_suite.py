"""Suite aggregation, the derived floor strategy, and regression detection."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "evals", ROOT / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


naive_baseline = load_module("naive_baseline_test", ROOT / "evals" / "naive_baseline.py")
run_suite = load_module("run_suite_test", ROOT / "evals" / "run_suite.py")
import pubmed_tool  # noqa: E402

PROTOCOL = {
    "scope_version": 1,
    "searchable_scope": {
        "concepts": [
            {"role": "essential", "id": "condition", "label": "Asthma", "term_families": ["asthma", "bronchial asthma"]},
            {"role": "essential", "id": "population", "label": "Children", "term_families": ["child", "paediatric"]},
            {"role": "optional", "id": "outcome", "label": "Mortality", "term_families": ["mortality"]},
        ]
    },
}


class NaiveBaselineTests(unittest.TestCase):
    def test_essential_concepts_are_or_ed_within_and_and_ed_across(self):
        compiled = naive_baseline.compile_from_protocol(PROTOCOL)
        query = compiled["query"]
        self.assertIn("asthma[tiab]", query)
        self.assertIn('"bronchial asthma"[tiab]', query)
        self.assertIn("\nAND\n", query)
        self.assertEqual(len(compiled["blocks"]), 2)

    def test_optional_concepts_are_excluded_from_the_floor(self):
        self.assertNotIn("mortality", naive_baseline.compile_from_protocol(PROTOCOL)["query"])

    def test_multi_word_and_hyphenated_terms_are_quoted(self):
        compiled = naive_baseline.compile_from_protocol(
            {"searchable_scope": {"concepts": [
                {"role": "essential", "id": "c", "term_families": ["rotator cuff", "rotator-cuff", "supraspinatus"]}
            ]}}
        )
        self.assertIn('"rotator cuff"[tiab]', compiled["query"])
        self.assertIn('"rotator-cuff"[tiab]', compiled["query"])
        self.assertIn("supraspinatus[tiab]", compiled["query"])

    def test_duplicate_terms_are_collapsed(self):
        compiled = naive_baseline.compile_from_protocol(
            {"searchable_scope": {"concepts": [
                {"role": "essential", "id": "c", "term_families": ["asthma", "Asthma", "asthma"]}
            ]}}
        )
        self.assertEqual(compiled["query"].count("[tiab]"), 1)

    def test_compilation_is_deterministic(self):
        first = naive_baseline.compile_from_protocol(PROTOCOL)
        second = naive_baseline.compile_from_protocol(PROTOCOL)
        self.assertEqual(first["sha256"], second["sha256"])

    def test_an_unrefined_placeholder_protocol_is_refused(self):
        """A fixture nobody finished must not enter a results table as 0% recall."""
        with self.assertRaises(naive_baseline.NaiveBaselineError) as ctx:
            naive_baseline.compile_from_protocol(
                {"searchable_scope": {"concepts": [
                    {"role": "essential", "id": "review-topic",
                     "term_families": ["Virus metagenomics in farm animals"]}
                ]}}
            )
        self.assertIn("unrefined", str(ctx.exception))

    def test_a_single_short_term_family_is_not_treated_as_unrefined(self):
        compiled = naive_baseline.compile_from_protocol(
            {"searchable_scope": {"concepts": [
                {"role": "essential", "id": "c", "term_families": ["emicizumab"]}
            ]}}
        )
        self.assertIn("emicizumab[tiab]", compiled["query"])

    def test_a_protocol_without_essential_concepts_is_refused(self):
        with self.assertRaises(naive_baseline.NaiveBaselineError):
            naive_baseline.compile_from_protocol({"searchable_scope": {"concepts": []}})

    def test_bundled_fixtures_either_compile_or_report_why_not(self):
        compiled = unrefined = 0
        for path in sorted((ROOT / "evals" / "datasets").glob("**/*.json")):
            if path.name.endswith(".blocks.json"):
                continue
            fixture = json.loads(path.read_text(encoding="utf-8-sig"))
            if "id" not in fixture:
                continue
            try:
                naive_baseline.compile_from_fixture(fixture)
                compiled += 1
            except naive_baseline.NaiveBaselineError as exc:
                self.assertIn("unrefined", str(exc), fixture["id"])
                unrefined += 1
        self.assertTrue(compiled, "no fixture produced a floor strategy")
        self.assertEqual(compiled + unrefined, 20)


class SummaryTests(unittest.TestCase):
    def _row(self, topic, source, recall, **extra):
        row = {
            "id": topic, "ok": True, "strategy_source": source,
            "recall_reachable_percent": recall, "gold_in_pubmed": 10, "retrieved": int(recall / 10),
            "strategy_sha256": f"{topic}-sha", "zero_recall": recall == 0.0,
        }
        row.update(extra)
        return row

    def test_sources_are_summarised_separately_and_never_pooled(self):
        rows = [self._row("a", "naive", 60.0), self._row("b", "generated", 90.0)]
        summary = run_suite.summarize(rows)
        self.assertEqual(set(summary["by_strategy_source"]), {"naive", "generated"})
        self.assertEqual(summary["by_strategy_source"]["naive"]["mean_recall_percent"], 60.0)
        self.assertEqual(summary["by_strategy_source"]["generated"]["mean_recall_percent"], 90.0)
        self.assertNotIn("mean_recall_percent", summary)

    def test_failed_topics_are_counted_but_not_scored(self):
        rows = [self._row("a", "naive", 80.0), {"id": "b", "ok": False, "error": "unrefined"}]
        summary = run_suite.summarize(rows)
        self.assertEqual(summary["topics_total"], 2)
        self.assertEqual(summary["topics_scored"], 1)
        self.assertEqual(summary["topics_failed"], ["b"])

    def test_topics_below_the_recall_threshold_are_counted(self):
        rows = [self._row("a", "naive", 79.9), self._row("b", "naive", 80.0)]
        self.assertEqual(run_suite.summarize(rows)["by_strategy_source"]["naive"]["topics_below_80"], 1)


class RegressionTests(unittest.TestCase):
    def _card(self, topic, source, recall, sha="sha"):
        return {"topics": [{
            "id": topic, "ok": True, "strategy_source": source,
            "recall_reachable_percent": recall, "strategy_sha256": sha,
        }]}

    def test_a_recall_drop_is_reported_as_a_regression(self):
        result = run_suite.compare(self._card("a", "naive", 70.0), self._card("a", "naive", 90.0))
        self.assertTrue(result["available"])
        self.assertEqual(len(result["regressions"]), 1)
        self.assertEqual(result["regressions"][0]["delta"], -20.0)

    def test_an_improvement_is_not_a_regression(self):
        result = run_suite.compare(self._card("a", "naive", 95.0), self._card("a", "naive", 90.0))
        self.assertEqual(result["regressions"], [])
        self.assertEqual(len(result["improvements"]), 1)

    def test_noise_within_tolerance_is_not_a_regression(self):
        result = run_suite.compare(self._card("a", "naive", 89.8), self._card("a", "naive", 90.0))
        self.assertEqual(result["regressions"], [])

    def test_a_different_strategy_source_is_not_compared(self):
        """A generated strategy scoring under the floor is a finding, not a regression."""
        result = run_suite.compare(self._card("a", "generated", 70.0), self._card("a", "naive", 90.0))
        self.assertEqual(result["compared_topics"], 0)
        self.assertEqual(result["regressions"], [])

    def test_a_first_run_has_nothing_to_compare(self):
        self.assertFalse(run_suite.compare(self._card("a", "naive", 90.0), None)["available"])


class StrategyResolutionTests(unittest.TestCase):
    def _fixture(self, root, **extra):
        fixture = {"id": "TOPIC", "suite": "test", "review_protocol": PROTOCOL, **extra}
        path = root / "TOPIC.json"
        path.write_text(json.dumps(fixture), encoding="utf-8")
        return path, fixture

    def test_auto_prefers_a_generated_strategy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path, fixture = self._fixture(root)
            generated = root / "gen" / "TOPIC"
            generated.mkdir(parents=True)
            (generated / "final_strategy.txt").write_text("asthma[tiab]", encoding="utf-8")
            source, strategy, _blocks = run_suite.resolve_strategy(path, fixture, "auto", root / "gen")
            self.assertEqual(source, "generated")
            self.assertEqual(strategy.read_text(encoding="utf-8"), "asthma[tiab]")

    def test_auto_falls_back_to_the_fixture_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "TOPIC.strategy.txt").write_text("baseline[tiab]", encoding="utf-8")
            path, fixture = self._fixture(root, strategy_file="TOPIC.strategy.txt")
            source, strategy, _blocks = run_suite.resolve_strategy(path, fixture, "auto", None)
            self.assertEqual(source, "baseline")
            self.assertEqual(strategy.read_text(encoding="utf-8"), "baseline[tiab]")

    def test_auto_derives_the_floor_when_nothing_else_exists(self):
        with tempfile.TemporaryDirectory() as td:
            path, fixture = self._fixture(Path(td))
            with mock.patch.object(run_suite, "DERIVED_DIR", Path(td) / "derived"):
                source, strategy, blocks = run_suite.resolve_strategy(path, fixture, "auto", None)
            self.assertEqual(source, "naive")
            self.assertIn("asthma[tiab]", strategy.read_text(encoding="utf-8"))
            self.assertIsNotNone(blocks)

    def test_requesting_a_missing_baseline_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            path, fixture = self._fixture(Path(td))
            with self.assertRaises(FileNotFoundError):
                run_suite.resolve_strategy(path, fixture, "baseline", None)


class EutilsErrorTests(unittest.TestCase):
    """E-utilities reports backend failures inside HTTP 200 bodies."""

    def test_a_backend_error_payload_is_detected(self):
        raw = b'{"header":{"type":"esearch"},"esearchresult":{"ERROR":"Search Backend failed: timeout"}}'
        self.assertIn("Search Backend failed", pubmed_tool.eutils_hard_error(raw))

    def test_a_top_level_error_is_detected(self):
        self.assertEqual(pubmed_tool.eutils_hard_error(b'{"ERROR":"boom"}'), "boom")

    def test_a_normal_response_is_not_an_error(self):
        self.assertIsNone(pubmed_tool.eutils_hard_error(b'{"esearchresult":{"count":"7","idlist":["1"]}}'))

    def test_an_unmatched_phrase_list_is_not_a_hard_error(self):
        """errorlist reports phrases PubMed could not match -- ordinary, useful output."""
        raw = b'{"esearchresult":{"count":"7","errorlist":{"phrasesnotfound":["zzz"]}}}'
        self.assertIsNone(pubmed_tool.eutils_hard_error(raw))

    def test_non_json_payloads_are_left_alone(self):
        self.assertIsNone(pubmed_tool.eutils_hard_error(b"<?xml version='1.0'?><PubmedArticleSet/>"))

    class _Response:
        def __init__(self, body): self.body = body
        def read(self): return self.body
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def _client(self, bodies, cache_dir):
        from pubmed_search_builder.infrastructure.cache import ResponseCache
        from pubmed_search_builder.infrastructure.transport import StdlibTransport

        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return self._Response(bodies[min(len(calls) - 1, len(bodies) - 1)])

        cache = ResponseCache(Path(cache_dir))
        client = pubmed_tool.NcbiClient(
            transport=StdlibTransport(opener=opener, sleeper=lambda _s: None), cache=cache
        )
        return client, cache, calls

    ERROR_BODY = b'{"esearchresult":{"ERROR":"Search Backend failed"}}'
    GOOD_BODY = b'{"esearchresult":{"count":"7","idlist":["1"]}}'

    def test_a_persistent_error_is_raised_and_never_cached(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(pubmed_tool.time, "sleep"):
            client, cache, _calls = self._client([self.ERROR_BODY], td)
            with self.assertRaises(pubmed_tool.PubMedError):
                client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma"})
            # A cached outage would answer this query for the whole TTL.
            self.assertIsNone(cache.get("esearch.fcgi", {"db": "pubmed", "term": "asthma"}))
            self.assertEqual(cache.stats()["writes"], 0)

    def test_a_transient_error_is_retried_rather_than_failing_the_query(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(pubmed_tool.time, "sleep"):
            client, cache, calls = self._client([self.ERROR_BODY, self.GOOD_BODY], td)
            body = client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma"})
            self.assertEqual(body, self.GOOD_BODY)
            self.assertEqual(len(calls), 2)
            # Only the successful payload is cached.
            self.assertEqual(cache.get("esearch.fcgi", {"db": "pubmed", "term": "asthma"}), self.GOOD_BODY)

    def test_retries_are_bounded(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(pubmed_tool.time, "sleep"):
            client, _cache, calls = self._client([self.ERROR_BODY], td)
            with self.assertRaises(pubmed_tool.PubMedError):
                client.request("esearch.fcgi", {"db": "pubmed", "term": "asthma"})
            self.assertEqual(len(calls), pubmed_tool.EUTILS_ERROR_RETRIES + 1)


if __name__ == "__main__":
    unittest.main()
