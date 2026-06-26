import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pubmed_tool", ROOT / "scripts" / "pubmed_tool.py")
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


class PlainQueryGuardTests(unittest.TestCase):
    """assert_plain_query rejects PowerShell-serialized object/metadata query values, and the
    variants/batch JSON parsers route through it (the ConvertTo-Json footgun)."""

    def test_assert_plain_query_object_metadata_empty_and_valid(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.assert_plain_query("x", {"Length": 1, "Name": "f.txt"})  # serialized object
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.assert_plain_query("x", "@{LastWriteTime=6/1/2026; Name=q.txt}")  # metadata string
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.assert_plain_query("x", "   ")  # empty
        pubmed_tool.assert_plain_query("x", 'asthma[tiab] OR "care home"[tiab]')  # valid -> no raise

    def test_variants_json_object_query_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.parse_variant_queries(json.dumps([{"label": "main", "query": {"Name": "f.txt", "LastWriteTime": "x"}}]))

    def test_variants_json_metadata_string_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.parse_variant_queries(json.dumps([{"label": "main", "query": "@{Mode=-a---; DirectoryName=C:/x}"}]))

    def test_batch_json_dict_object_value_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.parse_batch_queries(json.dumps({"blk": {"Length": 1, "Name": "f.txt"}}))

    def test_batch_json_list_object_query_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.parse_batch_queries(json.dumps([{"label": "blk", "query": {"PSChildName": "f.txt"}}]))

    def test_valid_variants_and_batch_accepted(self):
        variants, _ = pubmed_tool.parse_variant_queries(json.dumps([{"label": "main", "query": "asthma[tiab]"}]))
        self.assertEqual(variants[0]["query"], "asthma[tiab]")
        batch = pubmed_tool.parse_batch_queries(json.dumps({"a": "asthma[tiab]", "b": "child[tiab]"}))
        self.assertEqual({row["label"] for row in batch}, {"a", "b"})


class NumericPmidGuardTests(unittest.TestCase):
    def test_non_numeric_pmids_rejected(self):
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.assert_numeric_pmids(["123", "foo.txt", "456"], source="--benchmark-json b.json")

    def test_numeric_and_empty_accepted(self):
        pubmed_tool.assert_numeric_pmids(["123", "456"], source="x")  # all numeric
        pubmed_tool.assert_numeric_pmids([], source="x")  # empty -> the empty-benchmark error handles it

    def test_metadata_benchmark_list_is_caught(self):
        pmids = pubmed_tool.extract_benchmark_pmids(["foo.txt", "Mode -a---"], min_seed_overlap=0)
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.assert_numeric_pmids(pmids, source="--benchmark-json b.json")


if __name__ == "__main__":
    unittest.main()
