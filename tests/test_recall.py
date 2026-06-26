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


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


def fake_esearch_factory(retrieved_by_query, calls):
    """Return an esearch stub. retrieved_by_query maps a query substring -> set of pmids it 'contains'.

    The combined query is "(<inner>) AND (<uid block>)"; we intersect the inner query's
    universe with the uids present in the uid block.
    """
    def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
        calls.append(query)
        # Identify which inner query this is by substring match.
        universe = set()
        for key, pmids in retrieved_by_query.items():
            if f"({key})" in query:
                universe = set(pmids)
                break
        # Parse uids present in the uid block.
        uids = set(re.findall(r"(\d+)\[uid\]", query))
        if not uids:  # plain esearch (benchmark-query path)
            return {"count": len(universe), "pmids": sorted(universe), "query_translation_hook": {"issues": []}}
        hit = sorted(universe & uids)
        return {"count": len(hit), "pmids": hit, "query_translation_hook": {"issues": []}}

    return fake_esearch


class RelativeRecallTests(unittest.TestCase):
    def run_recall(self, retrieved_by_query, benchmark, *, blocks=None):
        calls = []
        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch_factory(retrieved_by_query, calls)
        try:
            result = pubmed_tool.relative_recall(
                FakeClient(),
                "STRATEGY",
                benchmark,
                benchmark_source="test",
                blocks=blocks,
            )
        finally:
            pubmed_tool.esearch = original
        return result, calls

    def test_relative_recall_math_and_misses(self):
        # Strategy retrieves 2 of 4 benchmark records.
        retrieved = {"STRATEGY": {"1", "2"}}
        result, _ = self.run_recall(retrieved, ["1", "2", "3", "4"])
        self.assertEqual(result["benchmark_size"], 4)
        self.assertEqual(result["retrieved_count"], 2)
        self.assertEqual(result["missed_count"], 2)
        self.assertEqual(result["relative_recall_percent"], 50.0)
        self.assertEqual(result["retrieved_pmids"], ["1", "2"])
        self.assertEqual(result["missed_pmids"], ["3", "4"])
        self.assertIn("not absolute search sensitivity", result["note"])
        self.assertNotIn("block_recall", result)

    def test_benchmark_dedup(self):
        retrieved = {"STRATEGY": {"1"}}
        result, _ = self.run_recall(retrieved, ["1", "1", "2", "2"])
        self.assertEqual(result["benchmark_size"], 2)

    def test_block_recall_bottleneck_and_culprits(self):
        # Benchmark 1..4. Strategy = A AND B. A retrieves 1,2,3; B retrieves 1,2.
        # Full strategy retrieves 1,2. Misses 3 (B fails it) and 4 (A and B fail it).
        retrieved = {
            "STRATEGY": {"1", "2"},
            "A": {"1", "2", "3"},
            "B": {"1", "2"},
        }
        blocks = [{"label": "A", "query": "A"}, {"label": "B", "query": "B"}]
        result, _ = self.run_recall(retrieved, ["1", "2", "3", "4"], blocks=blocks)

        by_label = {row["label"]: row for row in result["block_recall"]}
        self.assertEqual(by_label["A"]["recall_percent"], 75.0)
        self.assertEqual(by_label["B"]["recall_percent"], 50.0)
        # B has the lowest recall -> bottleneck.
        self.assertTrue(by_label["B"]["bottleneck"])
        self.assertFalse(by_label["A"]["bottleneck"])

        diag = {row["pmid"]: row for row in result["miss_diagnosis"]}
        self.assertEqual(diag["3"]["culprit_blocks"], ["B"])
        self.assertEqual(sorted(diag["4"]["culprit_blocks"]), ["A", "B"])
        self.assertFalse(diag["3"]["and_interaction"])

    def test_and_interaction_flag(self):
        # Both blocks individually retrieve 9, but the full strategy misses it.
        retrieved = {
            "STRATEGY": set(),
            "A": {"9"},
            "B": {"9"},
        }
        blocks = [{"label": "A", "query": "A"}, {"label": "B", "query": "B"}]
        result, _ = self.run_recall(retrieved, ["9"], blocks=blocks)
        diag = result["miss_diagnosis"][0]
        self.assertEqual(diag["pmid"], "9")
        self.assertEqual(diag["culprit_blocks"], [])
        self.assertTrue(diag["and_interaction"])

    def test_uid_chunking_unions_results(self):
        # Benchmark larger than the chunk size triggers multiple esearch calls.
        original_chunk = pubmed_tool.RECALL_UID_CHUNK
        pubmed_tool.RECALL_UID_CHUNK = 2
        try:
            benchmark = ["1", "2", "3", "4", "5"]
            retrieved = {"STRATEGY": {"1", "3", "5"}}
            result, calls = self.run_recall(retrieved, benchmark)
        finally:
            pubmed_tool.RECALL_UID_CHUNK = original_chunk
        # ceil(5/2) = 3 chunked calls.
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["retrieved_pmids"], ["1", "3", "5"])
        self.assertEqual(result["relative_recall_percent"], 60.0)

    def test_empty_benchmark_raises(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.relative_recall(FakeClient(), "STRATEGY", [], benchmark_source="test")


class BenchmarkExtractionTests(unittest.TestCase):
    def test_extract_from_related_candidate_pmids_with_overlap_filter(self):
        payload = {
            "candidate_pmids": [
                {"pmid": "100", "seed_overlap_count": 2},
                {"pmid": "200", "seed_overlap_count": 1},
                {"pmid": "300", "seed_overlap_count": 3},
            ]
        }
        all_pmids = pubmed_tool.extract_benchmark_pmids(payload, min_seed_overlap=1)
        self.assertEqual(sorted(all_pmids), ["100", "200", "300"])
        high = pubmed_tool.extract_benchmark_pmids(payload, min_seed_overlap=2)
        self.assertEqual(sorted(high), ["100", "300"])

    def test_extract_from_mine_found_pmids(self):
        payload = {"found_pmids": ["11", "22"], "requested_pmids": ["11", "22", "33"]}
        self.assertEqual(pubmed_tool.extract_benchmark_pmids(payload, min_seed_overlap=1), ["11", "22"])

    def test_extract_from_bare_list(self):
        self.assertEqual(
            pubmed_tool.extract_benchmark_pmids(["5", "6"], min_seed_overlap=5), ["5", "6"]
        )


class RecallFilterCliTests(unittest.TestCase):
    """--exclude-pmids/--only-pmids filter the resolved benchmark set before recall is computed."""

    def _run(self, benchmark_args, extra):
        retrieved = {"1", "2"}  # the strategy retrieves PMIDs 1 and 2

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            uids = set(re.findall(r"(\d+)\[uid\]", query))
            hit = sorted(retrieved & uids)
            return {"count": len(hit), "retmax": retmax, "pmids": hit, "query_translation_hook": {"issues": []}}

        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                rc = pubmed_tool.main(["recall", "STRATEGY", *benchmark_args, *extra])
        finally:
            pubmed_tool.esearch = original
        return rc, json.loads(buffer.getvalue())

    def test_exclude_drops_benchmark_pmid_and_records_provenance(self):
        rc, payload = self._run(["--benchmark-pmids", "1", "2", "999"], ["--exclude-pmids", "999"])
        self.assertEqual(rc, 0)
        self.assertEqual(payload["benchmark_size"], 2)  # 999 dropped from the benchmark denominator
        self.assertEqual(payload["excluded_pmids"], ["999"])
        self.assertEqual(payload["relative_recall_percent"], 100.0)
        self.assertEqual(sorted(payload["retrieved_pmids"]), ["1", "2"])

    def test_only_pmids_whitelists_benchmark(self):
        rc, payload = self._run(["--benchmark-pmids", "1", "2", "999"], ["--only-pmids", "1", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(payload["benchmark_size"], 2)
        self.assertNotIn("999", payload["missed_pmids"])

    def test_excluding_all_benchmark_pmids_errors(self):
        rc, payload = self._run(["--benchmark-pmids", "1"], ["--exclude-pmids", "1"])
        self.assertEqual(rc, 1)
        self.assertIn("error", payload)


class RecallBlockValidationTests(unittest.TestCase):
    """Malformed --blocks-file values (e.g. PowerShell-serialized objects) fail fast."""

    def test_object_valued_query_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.validate_recall_blocks([{"label": "pop", "query": {"Length": 1, "Name": "f.txt"}}])

    def test_metadata_string_query_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.validate_recall_blocks([{"label": "pop", "query": "@{Mode=-a---; LastWriteTime=6/1/2026; Name=q.txt}"}])

    def test_empty_query_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.validate_recall_blocks([{"label": "pop", "query": "   "}])

    def test_map_object_value_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.validate_recall_blocks({"pop": {"Length": 1, "Name": "f.txt"}})

    def test_valid_blocks_accepted(self):
        pubmed_tool.validate_recall_blocks([{"label": "pop", "query": '"care home"[tiab] OR nursing home*[tiab]'}])
        pubmed_tool.validate_recall_blocks({"setting": '"care home"[tiab]'})  # {label: query} map form

    def test_cli_bad_block_fails_fast_without_network(self):
        calls = []

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            calls.append(query)
            uids = set(re.findall(r"(\d+)\[uid\]", query))
            return {"count": len(uids), "retmax": retmax, "pmids": sorted(uids), "query_translation_hook": {"issues": []}}

        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch
        buffer = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                blocks = Path(tmp) / "blocks.json"
                blocks.write_text(json.dumps([{"label": "pop", "query": {"Name": "f.txt", "LastWriteTime": "x"}}]), encoding="utf-8")
                with contextlib.redirect_stdout(buffer):
                    rc = pubmed_tool.main(["recall", "STRATEGY", "--benchmark-pmids", "1", "--blocks-file", str(blocks)])
        finally:
            pubmed_tool.esearch = original
        payload = json.loads(buffer.getvalue())
        self.assertEqual(rc, 1)
        self.assertIn("pop", payload["error"])
        self.assertEqual(calls, [])  # failed before any esearch was issued

    def test_cli_benchmark_json_non_numeric_fails_fast(self):
        calls = []

        def fake_esearch(client, query, retmax=0, retstart=0, sort=None):
            calls.append(query)
            return {"count": 0, "retmax": retmax, "pmids": [], "query_translation_hook": {"issues": []}}

        original = pubmed_tool.esearch
        pubmed_tool.esearch = fake_esearch
        buffer = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                benchmark = Path(tmp) / "benchmark.json"
                benchmark.write_text(json.dumps(["foo.txt", "Mode -a---"]), encoding="utf-8")  # metadata, not PMIDs
                with contextlib.redirect_stdout(buffer):
                    rc = pubmed_tool.main(["recall", "STRATEGY", "--benchmark-json", str(benchmark)])
        finally:
            pubmed_tool.esearch = original
        payload = json.loads(buffer.getvalue())
        self.assertEqual(rc, 1)
        self.assertIn("non-numeric", payload["error"])
        self.assertEqual(calls, [])  # failed before any esearch was issued


if __name__ == "__main__":
    unittest.main()
