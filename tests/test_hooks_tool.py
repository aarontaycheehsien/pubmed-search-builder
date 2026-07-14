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


def proximity_review_evidence(result):
    return {
        issue["evidence"]
        for issue in result["issues"]
        if issue["code"] == "proximity_review_needed"
    }


class SplitTopLevelOrTests(unittest.TestCase):
    def test_splits_on_top_level_or_only(self):
        parts = hooks_tool.split_top_level_or("a[tiab] OR b[tiab] OR (c[tiab] OR d[tiab])")
        self.assertEqual(parts, ["a[tiab]", "b[tiab]", "(c[tiab] OR d[tiab])"])

    def test_does_not_split_inside_quotes(self):
        parts = hooks_tool.split_top_level_or('"word or phrase"[tiab] OR b[tiab]')
        self.assertEqual(parts, ['"word or phrase"[tiab]', "b[tiab]"])

    def test_rejects_misordered_parentheses(self):
        self.assertIsNotNone(hooks_tool.parenthesis_nesting_issue(")("))


class WarningDispositionTests(unittest.TestCase):
    def test_warning_requires_authored_disposition(self):
        strategy = '("Asthma"[Mesh]) NOT animals[Mesh]'
        unresolved = hooks_tool.final_qa(strategy)
        self.assertFalse(unresolved["ok"])
        self.assertIn("not_operator", unresolved["unresolved_warning_codes"])
        resolved = hooks_tool.final_qa(strategy, {"not_operator": "Protocol-authorized exclusion, tested against holdout."})
        self.assertNotIn("not_operator", resolved["unresolved_warning_codes"])


class EvidenceSynthesisFilterTests(unittest.TestCase):
    def test_systematic_subset_is_detected_as_a_filter(self):
        result = hooks_tool.filter_check(
            "topic AND systematic[sb]",
            filter_decision="used",
            no_filter_reason=None,
            filter_source=None,
            topic_only_count=None,
            topic_plus_filter_count=None,
            seed_impact=None,
            seed_pmids=[],
        )
        self.assertTrue(result["requires_methodological_filter_review"])
        self.assertIn("systematic[sb]", result["detected_filter_fragments"])
        self.assertFalse(result["ok"])
        self.assertIn("missing_validated_filter_source", issue_codes(result))

    def test_selected_filter_fails_closed_without_comparison_evidence(self):
        result = hooks_tool.filter_check(
            "topic AND \"meta analysis\"[pt]",
            filter_decision="used",
            no_filter_reason=None,
            filter_source="NLM publication type",
            topic_only_count=None,
            topic_plus_filter_count=None,
            seed_impact=None,
            seed_pmids=["123"],
        )
        self.assertFalse(result["ok"])
        self.assertIn("missing_topic_only_count", issue_codes(result))
        self.assertIn("missing_topic_plus_filter_count", issue_codes(result))
        self.assertIn("missing_seed_filter_impact", issue_codes(result))

    def test_documented_topical_review_language_can_use_no_filter(self):
        result = hooks_tool.filter_check(
            "methods for systematic reviews",
            filter_decision="none",
            no_filter_reason="Review terminology is the topic, not a retrieval restriction.",
            filter_source=None,
            topic_only_count=None,
            topic_plus_filter_count=None,
            seed_impact=None,
            seed_pmids=[],
        )
        self.assertTrue(result["ok"])

    def test_final_qa_requires_disposition_for_systematic_subset(self):
        result = hooks_tool.final_qa("topic[tiab] AND systematic[sb]")
        self.assertIn("review_subset_filter", issue_codes(result))
        self.assertFalse(result["ok"])


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


class ProximityReviewTests(unittest.TestCase):
    def test_flags_reordered_phrase_family_without_proximity(self):
        result = hooks_tool.final_qa(
            '("patient physician relationship"[tiab] OR "physician patient relationship"[tiab])'
        )

        self.assertIn("proximity_review_needed", issue_codes(result))
        evidence = " ".join(proximity_review_evidence(result))
        self.assertIn("patient physician relationship", evidence)
        self.assertIn("physician patient relationship", evidence)

    def test_flags_variable_phrase_family_without_proximity(self):
        result = hooks_tool.final_qa('("hip pain"[tiab] OR "hip joint pain"[tiab])')

        self.assertIn("proximity_review_needed", issue_codes(result))

    def test_flags_same_field_and_pair_inside_concept_block(self):
        result = hooks_tool.final_qa('((patient[tiab] AND physician[tiab]) OR "doctor patient relationship"[tiab])')

        self.assertIn("proximity_review_needed", issue_codes(result))
        evidence = " ".join(proximity_review_evidence(result))
        self.assertIn("patient[tiab] AND physician[tiab]", evidence)

    def test_does_not_flag_when_matching_proximity_is_present(self):
        result = hooks_tool.final_qa(
            '("patient physician relationship"[tiab] OR "physician patient relationship"[tiab] '
            'OR "patient physician relationship"[tiab:~0])'
        )

        self.assertNotIn("proximity_review_needed", issue_codes(result))

    def test_does_not_flag_hyphenation_only_phrase_variants(self):
        result = hooks_tool.final_qa('("patient-reported outcome"[tiab] OR "patient reported outcome"[tiab])')

        self.assertNotIn("proximity_review_needed", issue_codes(result))

    def test_does_not_flag_singular_plural_only_phrase_variants(self):
        result = hooks_tool.final_qa(
            '("immune checkpoint inhibitor"[tiab] OR "immune checkpoint inhibitors"[tiab])'
        )

        self.assertNotIn("proximity_review_needed", issue_codes(result))
        self.assertIn("singular_plural_wildcard_review", issue_codes(result))

    def test_does_not_flag_wildcarded_phrases(self):
        result = hooks_tool.final_qa('("checkpoint inhibitor*"[tiab] OR "immune checkpoint inhibitor*"[tiab])')

        self.assertNotIn("proximity_review_needed", issue_codes(result))

    def test_does_not_flag_single_stable_named_phrase(self):
        result = hooks_tool.final_qa(
            '("Patient Reported Outcomes Measurement Information System"[tiab] OR PROMIS[tiab])'
        )

        self.assertNotIn("proximity_review_needed", issue_codes(result))

    def test_followup_explains_test_or_document_not_auto_insertion(self):
        followups = " ".join(
            hooks_tool.final_qa(
                '("patient physician relationship"[tiab] OR "physician patient relationship"[tiab])'
            )["required_followups"]
        ).lower()

        self.assertIn("compare exact phrases, boolean and, and pubmed proximity widths", followups)
        self.assertIn("document why it was rejected/not applicable", followups)


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
