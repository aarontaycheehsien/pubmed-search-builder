"""Wildcard rules PubMed applies silently, checked against the behaviour observed live."""

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_wildcard_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


wildcard_rules = load("wildcard_rules")
hooks_tool = load("hooks_tool")
pubmed_tool = load("pubmed_tool")

# Query -> PubMed's translation, as returned by live ESearch.
LIVE_TRANSLATIONS = {
    "cat*[tiab]": '"cat"[Title/Abstract]',
    "il6*[tiab]": '"il6"[Title/Abstract]',
    "tb*": '"tb"[All Fields]',
    "hip*[ti]": '"hip"[Title]',
    '"cat* scratch"[tiab]': '"cat scratch"[Title/Abstract]',
    '"scratch cat*"[tiab]': '"scratch cat*"[Title/Abstract]',
    "colo*[tiab]": '"colo*"[Title/Abstract]',
    "ca*t[tiab]": '"ca*t"[Title/Abstract]',
    '"colo* cancer*"[tiab]': '"colo* cancer*"[Title/Abstract]',
}
TRUNCATION_DROPPED_LIVE = {"cat*[tiab]", "il6*[tiab]", "tb*", "hip*[ti]", '"cat* scratch"[tiab]'}


class RuleTests(unittest.TestCase):
    def test_short_truncation_matches_what_pubmed_actually_dropped(self):
        for query in LIVE_TRANSLATIONS:
            with self.subTest(query=query):
                self.assertEqual(bool(wildcard_rules.short_truncations(query)), query in TRUNCATION_DROPPED_LIVE)

    def test_dropped_truncation_is_read_from_the_translation(self):
        for query, translation in LIVE_TRANSLATIONS.items():
            with self.subTest(query=query):
                dropped = wildcard_rules.dropped_truncations(query, translation)
                self.assertEqual(bool(dropped), query in TRUNCATION_DROPPED_LIVE, dropped)
        self.assertEqual(wildcard_rules.dropped_truncations("cat*[tiab]", ""), [])

    def test_field_tags_are_not_read_as_terms(self):
        self.assertEqual(wildcard_rules.short_truncations('"heart attack*"[tiab:~2] OR asthma[mh]'), [])

    def test_wildcards_are_counted_per_asterisk(self):
        self.assertEqual(wildcard_rules.wildcard_count('"colo* cancer*"[tiab] OR neoplas*[tiab]'), 3)


class FinalQaTests(unittest.TestCase):
    def codes(self, strategy):
        return {issue["code"]: issue["severity"] for issue in hooks_tool.final_qa(strategy)["issues"]}

    def test_a_stem_pubmed_will_not_truncate_is_an_error_not_a_waivable_warning(self):
        result = hooks_tool.final_qa("(cat*[tiab] OR feline*[tiab]) AND asthma[tiab]")
        self.assertFalse(result["ok"])
        codes = {issue["code"]: issue["severity"] for issue in result["issues"]}
        self.assertEqual(codes.get("truncation_ignored_short_stem"), "error")
        self.assertNotIn("cat*", [issue.get("evidence") for issue in result["issues"] if issue["code"] == "short_wildcard"])

    def test_a_four_character_stem_remains_a_noise_warning(self):
        codes = self.codes("colo*[tiab] AND asthma[tiab]")
        self.assertNotIn("truncation_ignored_short_stem", codes)
        self.assertEqual(codes.get("short_wildcard"), "warning")

    def test_a_phrase_supplying_four_leading_characters_is_accepted(self):
        self.assertNotIn("truncation_ignored_short_stem", self.codes('"scratch cat*"[tiab] AND fever[tiab]'))

    def test_more_than_256_wildcards_is_an_error(self):
        strategy = " OR ".join(f"term{i:04d}*[tiab]" for i in range(257))
        self.assertEqual(self.codes(strategy).get("too_many_wildcards"), "error")
        self.assertNotIn("too_many_wildcards", self.codes(" OR ".join(f"term{i:04d}*[tiab]" for i in range(256))))


class PubMedToolTests(unittest.TestCase):
    def test_every_search_reports_a_truncation_pubmed_dropped(self):
        result = pubmed_tool.query_translation_drift_hook("cat*[tiab] OR asthma[tiab]", '"cat"[Title/Abstract] OR "asthma"[Title/Abstract]', [], {}, {})
        issue = next(item for item in result["issues"] if item["code"] == "truncation_dropped")
        self.assertIn("cat*", issue["evidence"])
        kept = pubmed_tool.query_translation_drift_hook("colo*[tiab]", '"colo*"[Title/Abstract]', [], {}, {})
        self.assertNotIn("truncation_dropped", [item["code"] for item in kept["issues"]])

    def test_a_query_over_the_wildcard_limit_is_blocked_before_it_is_sent(self):
        args = argparse.Namespace(command="search", retmax=0, query=None, query_file="strategy.txt", query_stdin=False)
        client = argparse.Namespace(api_key="")
        query = " OR ".join(f"term{i:04d}*[tiab]" for i in range(257))
        with mock.patch.object(sys, "argv", ["pubmed_tool.py", "search"]):
            blocked = pubmed_tool.pre_command_hook(client, args, query=query)
            allowed = pubmed_tool.pre_command_hook(client, args, query="asthma*[tiab]")
        self.assertFalse(blocked["ok"])
        self.assertIn("too_many_wildcards", [issue["code"] for issue in blocked["issues"]])
        self.assertTrue(allowed["ok"])


if __name__ == "__main__":
    unittest.main()
