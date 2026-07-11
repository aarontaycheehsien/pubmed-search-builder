"""Documentation-contract tests for the scope-first conceptual/objective/critic workflow."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read_doc(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class SkillContractTests(unittest.TestCase):
    def test_frontmatter_uses_only_name_and_description_with_strong_triggers(self):
        skill = read_doc("SKILL.md")
        frontmatter = skill.split("---", 2)[1]
        keys = [line.split(":", 1)[0].strip() for line in frontmatter.splitlines() if ":" in line]
        self.assertEqual(keys, ["name", "description"])
        lower = frontmatter.lower()
        for trigger in (
            "pubmed/medline",
            "systematic reviews",
            "scoping reviews",
            "mesh",
            "prescreen",
            "held-out",
            "press-informed",
            "prisma-s",
        ):
            self.assertIn(trigger, lower)

    def test_ui_metadata_matches_the_loop(self):
        metadata = read_doc("agents/openai.yaml")
        self.assertIn("$pubmed-search-builder", metadata)
        self.assertIn("empirically", metadata.lower())
        self.assertIn("critic loop", metadata.lower())

    def test_plain_language_question_precedes_seed_intake_and_strategy_review(self):
        skill = read_doc("SKILL.md").lower()
        question = skill.index("require an independently stated plain-language")
        seed = skill.index("ask once for optional known-relevant seed pmids")
        review = skill.index("before inspecting the supplied strategy")
        self.assertLess(question, seed)
        self.assertIn("review objects, never as scope evidence", skill[review:])
        self.assertIn("do not search pubmed or the web to answer", skill)

    def test_only_four_user_facing_markers_and_probes_before_adoption(self):
        skill = read_doc("SKILL.md").lower()
        for marker in ("`intake`", "`scope lock`", "`empirical build and critic loop`", "`handoff`"):
            self.assertIn(marker, skill)
        self.assertIn("read-only pubmed probes", skill)
        self.assertIn("before asking the user to adopt", skill)

    def test_top_level_routes_to_specialist_references(self):
        skill = read_doc("SKILL.md").lower()
        for reference in (
            "workflow.md",
            "framework-selection.md",
            "concept-analysis-and-gating.md",
            "candidate-screening.md",
            "press-critic.md",
            "mesh-and-pubmed-tools.md",
            "tiab-expansion.md",
            "seed-pmid-validation.md",
            "no-seed-recall-estimation.md",
            "audit-template.md",
            "goal-tracking.md",
        ):
            self.assertIn(reference, skill)


class WorkflowContractTests(unittest.TestCase):
    def test_scope_lock_precedes_candidate_and_objective_evidence(self):
        workflow = read_doc("references/workflow.md").lower()
        sequence = [
            "`scope-lock`",
            "`candidate-discovery`",
            "`candidate-screening`",
            "`objective-evidence`",
            "`block-testing`",
            "`validation`",
            "`critic-review`",
            "`revision`",
            "`final-qa`",
            "`audit-output`",
        ]
        positions = [workflow.index(item) for item in sequence]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("save `review_protocol_v1.json`", workflow)
        self.assertIn("state lock-protocol", workflow)
        self.assertIn("before any pubmed record fetch", workflow)

    def test_workflow_defines_a_repeating_empirical_critic_loop(self):
        workflow = read_doc("references/workflow.md").lower()
        self.assertIn("stages 5-9 form a loop", workflow)
        self.assertIn("state reopen-scope", workflow)
        self.assertIn("save a new scope version", workflow)
        self.assertIn("repeat objective evidence, testing, validation, and critic review", workflow)
        self.assertIn("no open must-fix or should-fix finding", workflow)

    def test_workflow_preserves_high_sensitivity_layer_model(self):
        workflow = read_doc("references/workflow.md").lower()
        self.assertIn("mesh/scr layer or title/abstract layer", workflow)
        self.assertIn("prefer fewer required `and` blocks", workflow)
        self.assertIn("mesh does not replace free text", workflow)
        self.assertIn("free text does not replace mesh", workflow)

    def test_read_only_variants_are_tested_before_narrowing_adoption(self):
        workflow = read_doc("references/workflow.md").lower()
        self.assertIn("run reversible, read-only diagnostic comparisons", workflow)
        self.assertIn("may be adopted only after the user/protocol accepts", workflow)
        self.assertIn("gather the comparison evidence before asking", workflow)

    def test_final_handoff_uses_combined_gate_and_human_press(self):
        workflow = read_doc("references/workflow.md").lower()
        self.assertIn("--require-complete-loop", workflow)
        self.assertIn("draft pending human press peer review", workflow)
        self.assertIn("every critic round", workflow)
        self.assertIn("revision-cycle ledger", workflow)


class CandidateEvidenceTests(unittest.TestCase):
    def test_candidate_screening_schema_and_role_constraints_are_documented(self):
        doc = read_doc("references/candidate-screening.md").lower()
        for phrase in (
            "user seed",
            "discovery record",
            "held-out validation record",
            "heuristic neighbor",
            "include`, `exclude`, or `uncertain`",
            "`discovery`, `holdout`, `both`, `heuristic`, or `neither`",
            "scripts/candidate_ledger.py",
        ):
            self.assertIn(phrase, doc)
        self.assertIn("do not feed a related-record set directly to `term-rank`", doc)

    def test_seed_evidence_cannot_precede_scope_lock(self):
        doc = read_doc("references/seed-pmid-validation.md").lower()
        self.assertIn("use them only after retrieval scope version 1 is locked", doc)
        self.assertIn("do not fetch, mine, inspect, expand", doc)
        self.assertIn("screen each found record against the locked scope", doc)
        self.assertIn("non-independent reused seed", doc)

    def test_objective_term_ranking_uses_screened_discovery_records(self):
        doc = read_doc("references/tiab-expansion.md").lower()
        self.assertIn("validated candidate ledger", doc)
        self.assertIn("pass only pmids assigned `discovery` or `both`", doc)
        self.assertIn("high overlap and similarity prioritize screening", doc)

    def test_no_seed_heuristic_requires_screened_anchors(self):
        doc = read_doc("references/no-seed-recall-estimation.md").lower()
        self.assertIn("candidate anchors are screened", doc)
        self.assertIn("candidate_ledger.py", doc)
        self.assertIn("convenience one-liner", doc)
        self.assertIn("does not satisfy candidate-screening integrity", doc)


class CriticAndAuditTests(unittest.TestCase):
    def test_critic_schema_routing_and_press_distinction_are_documented(self):
        doc = read_doc("references/press-critic.md").lower()
        for phrase in (
            "fresh context",
            "reviewed_domains",
            "must-fix",
            "should-fix",
            "lexical",
            "structural",
            "scope",
            "filter",
            "syntax",
            "scripts/critic_tool.py",
            "does not constitute press peer review",
        ):
            self.assertIn(phrase, doc)

    def test_audit_template_contains_scope_candidate_critic_and_revision_sections(self):
        audit = read_doc("references/audit-template.md").lower()
        for heading in (
            "## retrieval-scope versions",
            "## candidate evidence screening",
            "## press-informed internal critic rounds",
            "## revision-cycle ledger",
            "## press 2015 element coverage",
            "## peer review status",
        ):
            self.assertIn(heading, audit)
        self.assertIn("automated internal qa, not press peer review", audit)

    def test_prisma_s_does_not_mislabel_internal_critic_as_peer_review(self):
        doc = read_doc("references/prisma-s-reporting.md").lower()
        self.assertIn("press-informed internal critic", doc)
        self.assertIn("do not satisfy item 14", doc)


class SupportingGuardrailTests(unittest.TestCase):
    def test_record_content_requires_saved_json(self):
        tools = read_doc("references/mesh-and-pubmed-tools.md").lower()
        self.assertIn("record-content commands", tools)
        self.assertIn("inspect the saved json", tools)
        self.assertIn("--output", tools)

    def test_bramer_and_filter_references_remain_routed(self):
        skill = read_doc("SKILL.md").lower()
        workflow = read_doc("references/workflow.md").lower()
        self.assertIn("gap-analysis", skill)
        self.assertIn("bramer-reciprocal-gap-analysis.md", workflow)
        self.assertIn("validated pubmed filter", workflow)
        self.assertIn("validated-methodological-filters-and-hedges.md", read_doc("references/prisma-s-reporting.md").lower())

    def test_goal_completion_uses_complete_loop_gate(self):
        goal = read_doc("references/goal-tracking.md").lower()
        self.assertIn("goal_requested_intake_pending", goal)
        self.assertIn("do not call `create_goal`", goal)
        self.assertIn("--require-complete-loop", goal)


if __name__ == "__main__":
    unittest.main()
