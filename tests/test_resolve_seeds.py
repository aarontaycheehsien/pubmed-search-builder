"""Seed resolution verifies identifiers and never auto-accepts a citation match."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("resolve_seeds_test", ROOT / "scripts" / "resolve_seeds.py")
resolve_seeds = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(resolve_seeds)
pubmed_tool = resolve_seeds.pubmed_tool

PRISMA_TITLE = "The PRISMA 2020 statement: an updated guideline for reporting systematic reviews."
RECORDS = {
    "33782057": {"pmid": "33782057", "title": PRISMA_TITLE, "journal": "BMJ", "year": "2021", "doi": "10.1136/bmj.n71", "pmcid": "PMC8005924"},
    "33781348": {"pmid": "33781348", "title": PRISMA_TITLE, "journal": "Syst Rev", "year": "2021", "doi": "10.1186/s13643-021-01626-4", "pmcid": ""},
    "11111111": {"pmid": "11111111", "title": "Unrelated", "journal": "J", "year": "2001", "doi": "10.1000/other", "pmcid": "PMC1"},
}


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


def fake_esearch(client, query, retmax, retstart, sort):
    if "[doi]" in query:
        # PubMed's DOI field is a Publisher ID match: return a near miss alongside the real record.
        return {"pmids": ["11111111", "33782057"] if "bmj.n71" in query else ["11111111"]}
    if query.startswith("PMC"):
        return {"pmids": ["11111111", "33782057"] if query == "PMC8005924" else []}
    if "[ti]" in query:
        return {"pmids": ["33781348", "33782057"] if "PRISMA[ti]" in query else []}
    return {"pmids": []}


def fake_efetch(client, pmids):
    return {"records": [RECORDS[p] for p in pmids if p in RECORDS]}


def run(lines):
    with mock.patch.object(pubmed_tool, "esearch", side_effect=fake_esearch), mock.patch.object(pubmed_tool, "efetch", side_effect=fake_efetch):
        return resolve_seeds.resolve(FakeClient(), lines)


class ClassificationTests(unittest.TestCase):
    def test_lines_are_classified_by_identifier_type(self):
        cases = {
            "33782057": ("pmid", "33782057"),
            "PMID: 33782057": ("pmid", "33782057"),
            "https://doi.org/10.1136/bmj.n71.": ("doi", "10.1136/bmj.n71"),
            "pmc8005924": ("pmcid", "PMC8005924"),
            "Page MJ. The PRISMA 2020 statement. BMJ. 2021": ("citation", "Page MJ. The PRISMA 2020 statement. BMJ. 2021"),
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(resolve_seeds.classify(line), expected)

    def test_the_title_is_taken_from_vancouver_and_apa_citations_not_the_author_list(self):
        vancouver = "Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. BMJ. 2021;372:n71."
        apa = "Rethlefsen, M. L., Kirtley, S., et al. (2021). PRISMA-S: an extension to the PRISMA statement for reporting literature searches. Syst Rev, 10, 39."
        self.assertEqual(resolve_seeds.title_words(vancouver)[:3], ["PRISMA", "2020", "statement"])
        self.assertEqual(resolve_seeds.title_words(apa)[:3], ["PRISMA", "extension", "PRISMA"])


class ResolutionTests(unittest.TestCase):
    def test_identifiers_resolve_only_to_the_record_that_carries_them(self):
        result = run(["10.1136/bmj.n71", "PMC8005924", "33782057"])
        self.assertEqual([item["status"] for item in result["items"]], ["resolved"] * 3)
        self.assertEqual([item["pmid"] for item in result["items"]], ["33782057"] * 3)
        self.assertEqual(result["resolved_pmids"], ["33782057"])

    def test_an_unknown_identifier_is_not_found_with_a_reason(self):
        result = run(["10.9999/missing", "PMC0000000", "99999999"])
        self.assertEqual([item["status"] for item in result["items"]], ["not-found"] * 3)
        self.assertTrue(all(item.get("reason") for item in result["items"]))
        self.assertEqual(result["resolved_pmids"], [])

    def test_a_citation_only_ever_returns_candidates_for_the_user_to_confirm(self):
        citation = "Page MJ, et al. The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. BMJ. 2021."
        result = run([citation])
        item = result["items"][0]
        self.assertEqual(item["status"], "needs-confirmation")
        self.assertEqual({candidate["pmid"] for candidate in item["candidates"]}, {"33781348", "33782057"})
        self.assertEqual(result["resolved_pmids"], [])
        self.assertEqual(result["needs_user_confirmation"], [citation])
        table = resolve_seeds.render_table(result)
        self.assertIn("BMJ (2021)", table)
        self.assertIn("Syst Rev (2021)", table)

    def test_pre_lock_mode_verifies_identifiers_without_exposing_content(self):
        citation = "Page MJ, et al. The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. BMJ. 2021."
        with mock.patch.object(pubmed_tool, "esearch", side_effect=fake_esearch) as search, mock.patch.object(
            pubmed_tool, "efetch", side_effect=fake_efetch
        ):
            result = resolve_seeds.resolve(FakeClient(), ["10.1136/bmj.n71", citation], identifiers_only=True)
        self.assertEqual(result["resolved_pmids"], ["33782057"])
        self.assertEqual(result["items"][0]["record"], {"pmid": "33782057", "doi": "10.1136/bmj.n71", "pmcid": "PMC8005924"})
        self.assertEqual(result["items"][1]["status"], "deferred")
        self.assertEqual(result["deferred"], [citation])
        self.assertFalse(any("[ti]" in call.args[1] for call in search.call_args_list))
        self.assertNotIn("PRISMA 2020 statement: an updated", resolve_seeds.render_table(result).split("\n", 3)[2])

    def test_comments_and_blank_lines_are_skipped_and_vague_lines_explained(self):
        result = run(["# my seeds", "", "Smith 2020"])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["status"], "not-found")
        self.assertIn("supply the DOI or PMID", result["items"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
