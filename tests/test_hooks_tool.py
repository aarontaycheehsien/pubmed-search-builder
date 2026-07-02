import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "hooks_tool.py"
SPEC = importlib.util.spec_from_file_location("hooks_tool", MODULE_PATH)
hooks_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(hooks_tool)


def issue_codes(result):
    return [issue["code"] for issue in result["issues"]]


def duplicate_evidence(result):
    return {issue["evidence"] for issue in result["issues"] if issue["code"] == "duplicate_term"}


def wildcard_review_evidence(result):
    return {
        issue["evidence"]
        for issue in result["issues"]
        if issue["code"] == "singular_plural_wildcard_review"
    }


class SplitTopLevelOrTests(unittest.TestCase):
    def test_splits_on_top_level_or_only(self):
        parts = hooks_tool.split_top_level_or("a[tiab] OR b[tiab] OR (c[tiab] OR d[tiab])")
        self.assertEqual(parts, ["a[tiab]", "b[tiab]", "(c[tiab] OR d[tiab])"])

    def test_does_not_split_inside_quotes(self):
        parts = hooks_tool.split_top_level_or('"word or phrase"[tiab] OR b[tiab]')
        self.assertEqual(parts, ['"word or phrase"[tiab]', "b[tiab]"])


class ExtractLeafAtomsTests(unittest.TestCase):
    def test_recurses_into_nested_and_or_groups(self):
        query = '(PARO[tiab] OR ("Pets"[Mesh] AND (robot*[tiab] OR PARO[tiab])))'
        atoms = hooks_tool.extract_leaf_atoms(query)
        self.assertEqual(atoms.count("PARO[tiab]"), 2)
        self.assertIn('"Pets"[Mesh]', atoms)
        self.assertIn("robot*[tiab]", atoms)


class DuplicateTermTests(unittest.TestCase):
    # Same shape as the real robopets strategy: brand names standalone AND inside
    # two "MeSH AND (...)" sub-clauses, which is what produced "NeCoRo, JustoCat x3".
    ROBO = (
        "(\n"
        '  "social robot"[tiab]\n'
        "  OR PARO[tiab]\n"
        "  OR NeCoRo[tiab]\n"
        "  OR JustoCat[tiab]\n"
        '  OR ("Pets"[Mesh] AND (robot*[tiab] OR PARO[tiab] OR NeCoRo[tiab] OR JustoCat[tiab]))\n'
        '  OR ("Play and Playthings"[Mesh] AND (robot*[tiab] OR PARO[tiab] OR NeCoRo[tiab] OR JustoCat[tiab]))\n'
        ")\n"
        "AND\n"
        "(\n"
        '  "long-term care"[tiab]\n'
        '  OR "long term care"[tiab]\n'
        ")"
    )

    def test_duplicate_atoms_flagged_with_counts(self):
        result = hooks_tool.final_qa(self.ROBO)
        evidence = duplicate_evidence(result)
        self.assertIn("NeCoRo[tiab] (3x)", evidence)
        self.assertIn("JustoCat[tiab] (3x)", evidence)
        self.assertIn("PARO[tiab] (3x)", evidence)
        self.assertIn("robot*[tiab] (2x)", evidence)

    def test_hyphenation_variants_not_flagged_as_duplicates(self):
        result = hooks_tool.final_qa(self.ROBO)
        evidence = " ".join(duplicate_evidence(result))
        self.assertNotIn("long-term care", evidence)
        self.assertNotIn("long term care", evidence)

    def test_no_duplicate_term_when_all_unique(self):
        result = hooks_tool.final_qa('("a"[tiab] OR "b"[tiab]) AND ("c"[tiab] OR "d"[tiab])')
        self.assertNotIn("duplicate_term", issue_codes(result))

    def test_duplicate_followup_marks_cleanup_as_recall_neutral(self):
        # When duplicates exist, the follow-up distinguishes recall-neutral cleanup
        # from recall-reducing warnings that need justification.
        followups = " ".join(hooks_tool.final_qa(self.ROBO)["required_followups"]).lower()
        self.assertIn("recall-neutral cleanup", followups)
        self.assertIn("duplicate_term", followups)

    def test_no_duplicate_followup_when_all_unique(self):
        followups = " ".join(
            hooks_tool.final_qa('("a"[tiab] OR "b"[tiab]) AND ("c"[tiab] OR "d"[tiab])')["required_followups"]
        ).lower()
        self.assertNotIn("duplicate_term", followups)


class SingularPluralWildcardReviewTests(unittest.TestCase):
    def test_flags_quoted_tiab_singular_plural_phrase_pair(self):
        result = hooks_tool.final_qa(
            '("immune checkpoint inhibitor"[tiab] OR "immune checkpoint inhibitors"[tiab])'
        )

        self.assertIn("singular_plural_wildcard_review", issue_codes(result))
        evidence = " ".join(wildcard_review_evidence(result))
        self.assertIn('"immune checkpoint inhibitor*"[tiab]', evidence)

    def test_does_not_flag_when_equivalent_wildcard_is_present(self):
        result = hooks_tool.final_qa(
            '("immune checkpoint inhibitor"[tiab] OR "immune checkpoint inhibitors"[tiab] '
            'OR "immune checkpoint inhibitor*"[tiab])'
        )

        self.assertNotIn("singular_plural_wildcard_review", issue_codes(result))

    def test_does_not_flag_hyphenation_only_variants(self):
        result = hooks_tool.final_qa('("long-term care"[tiab] OR "long term care"[tiab])')

        self.assertNotIn("singular_plural_wildcard_review", issue_codes(result))

    def test_does_not_flag_single_token_drug_names_or_acronyms(self):
        result = hooks_tool.final_qa(
            '(pembrolizumab[tiab] OR pembrolizumabs[tiab] OR ICI[tiab] OR ICIs[tiab])'
        )

        self.assertNotIn("singular_plural_wildcard_review", issue_codes(result))

    def test_followup_explains_review_not_auto_replacement(self):
        followups = " ".join(
            hooks_tool.final_qa(
                '("checkpoint inhibitor"[tiab] OR "checkpoint inhibitors"[tiab])'
            )["required_followups"]
        ).lower()

        self.assertIn("test the phrase-final, phrase-anchored/concept-specific wildcard candidate", followups)
        self.assertIn("document why explicit singular/plural forms were retained", followups)


class LowCountReviewTests(unittest.TestCase):
    STRATEGY = '("large language model*"[tiab]) AND ("search strategy"[tiab])'

    def test_blocks_low_count_without_rationale_or_variant_evidence(self):
        result = hooks_tool.low_count_review(
            self.STRATEGY,
            final_count=39,
            threshold=500,
            decision="low-count-plausible",
            rationale=None,
            relaxed_variant_tested=False,
            relaxed_variant_count=None,
            no_relaxed_variant_reason=None,
            blocks_file=None,
            seed_status=None,
            recall_offer_status=None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_low_count_rationale", issue_codes(result))
        self.assertIn("missing_relaxed_variant_evidence", issue_codes(result))

    def test_passes_documented_low_count_review(self):
        result = hooks_tool.low_count_review(
            self.STRATEGY,
            final_count=39,
            threshold=500,
            decision="relaxed-variant-rejected",
            rationale="Relaxed variant retrieved mostly off-scope records.",
            relaxed_variant_tested=True,
            relaxed_variant_count=982,
            no_relaxed_variant_reason=None,
            blocks_file=None,
            seed_status="none",
            recall_offer_status="done",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["low_count_review_required"])


if __name__ == "__main__":
    unittest.main()
