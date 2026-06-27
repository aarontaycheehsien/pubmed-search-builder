"""Regression tests: record-content commands tolerate a stray --summary.

Reproduces the observed failure where `pubmed_tool.py mine ... --summary` aborted
a build with argparse `unrecognized arguments: --summary`. fetch/mine/sample are
receipt-only by design, but a stray --summary must degrade to a no-op note, not a
hard error. Network-free.
"""
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

OK_PRECMD = {"name": "pre_pubmed_command", "ok": True, "issues": []}


class ToleratedSummaryFlagTests(unittest.TestCase):
    def test_record_parsers_accept_summary_without_error(self):
        """argparse must accept --summary on fetch/mine/sample (the regression)."""
        parser = pubmed_tool.build_parser()
        for cmd in ("fetch", "mine", "sample"):
            with tempfile.TemporaryDirectory() as d:
                out = str(Path(d) / "o.json")
                if cmd == "sample":
                    args = parser.parse_args([cmd, "asthma[tiab]", "--output", out, "--summary"])
                else:
                    args = parser.parse_args([cmd, "--pmids", "1", "2", "--output", out, "--summary"])
                self.assertTrue(args.summary, f"{cmd} should accept --summary")
                self.assertEqual(args.output, out)

    def test_receipt_notes_tolerated_summary_and_still_writes_full_json(self):
        result = {
            "requested_pmids": ["1", "2"],
            "found_pmids": ["1", "2"],
            "missing_pmids": [],
            "records": [{"pmid": "1"}, {"pmid": "2"}],
            "pre_command_hook": OK_PRECMD,
        }
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "fetch.json"
            args = argparse.Namespace(output=str(out), summary=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pubmed_tool.emit_record_content_receipt("fetch", result, args)
            receipt = json.loads(buf.getvalue())
            # stdout stays a receipt with a note; the contract is preserved.
            self.assertIn("tolerated_flag", receipt)
            self.assertIn("--summary ignored", receipt["tolerated_flag"])
            self.assertEqual(receipt["stdout_role"], "receipt_only")
            self.assertTrue(receipt["full_json_review_required"])
            # full record-content JSON still written to --output.
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(saved["found_pmids"], ["1", "2"])

    def test_no_note_when_summary_absent(self):
        result = {
            "requested_pmids": ["1"], "found_pmids": ["1"], "missing_pmids": [],
            "records": [{"pmid": "1"}], "pre_command_hook": OK_PRECMD,
        }
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "fetch.json"
            args = argparse.Namespace(output=str(out), summary=False)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pubmed_tool.emit_record_content_receipt("fetch", result, args)
            receipt = json.loads(buf.getvalue())
            self.assertNotIn("tolerated_flag", receipt)


if __name__ == "__main__":
    unittest.main()
