"""The offline robustness selftest must pass, and cover the hardened invariants."""
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pubmed_tool", ROOT / "scripts" / "pubmed_tool.py")
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


class SelfTestTests(unittest.TestCase):
    def test_offline_selftest_passes(self):
        report = pubmed_tool.run_selftest()
        self.assertTrue(report["ok"], report)
        self.assertFalse(report["network"])
        self.assertEqual(report["passed"], report["total"])

    def test_selftest_covers_hardening_invariants(self):
        names = {c["name"] for c in pubmed_tool.run_selftest()["checks"]}
        for expected in (
            "tolerated_summary_parse",
            "record_output_required",
            "tolerated_summary_receipt",
            "query_encoding_tolerance",
            "ncbi_retry_visibility",
        ):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
