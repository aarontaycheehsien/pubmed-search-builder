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

    def test_zero_hit_terms_have_stable_cleanup_code(self):
        result = hooks_tool.final_qa(
            '("Asthma"[Mesh] OR asthma[tiab])',
            zero_hit_terms=['"robocat"', "teleseal"],
        )
        codes = issue_codes(result)
        self.assertEqual(codes.count("zero_hit_cleanup_candidate"), 2)
        followups = " ".join(result["required_followups"])
        self.assertIn("zero_hit_cleanup_candidate", followups)


if __name__ == "__main__":
    unittest.main()
