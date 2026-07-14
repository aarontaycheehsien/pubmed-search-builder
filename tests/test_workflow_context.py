import unittest

from pubmed_search_builder.domain.protocol import workflow_context
from pubmed_search_builder.workflow.gates import PREDICATES
from pubmed_search_builder.workflow.stages import completion_diagnostics


class WorkflowContextTests(unittest.TestCase):
    def test_handoff_predicates_are_registered_with_stable_names(self):
        self.assertEqual(
            [predicate.id for predicate in PREDICATES],
            ["question-resolved", "no-pending-decisions", "required-stage-outputs", "conditional-outputs", "no-stale-artifacts"],
        )

    def test_locked_protocol_enables_only_applicable_branches(self):
        context = workflow_context(
            {
                "information_source_mode": "pubmed-plus-external-validation",
                "external_validation": {"status": "enabled"},
                "seeds": {"records": []},
                "searchable_scope": {"concepts": [{"role": "essential", "provisional_fragility": "fragile"}]},
            }
        )
        self.assertEqual(
            context,
            {"information_source_mode": "pubmed-plus-external-validation", "external_validation_enabled": True, "no_seed_build": True, "fragile_topic": True},
        )
        diagnostics = completion_diagnostics({"decisions": {"question": {"status": "resolved"}}, "artifacts": {}, "workflow_context": context})
        codes = [item.code for item in diagnostics]
        self.assertGreaterEqual(codes.count("workflow.conditional_output_missing"), 4)

    def test_missing_legacy_fields_do_not_activate_branches(self):
        self.assertEqual(workflow_context({}), {})

    def test_explicit_evidence_target_activates_review_branch(self):
        context = workflow_context(
            {
                "evidence_target": {
                    "mode": "evidence-syntheses",
                    "eligible_types": ["meta-analysis", "systematic-review"],
                    "protocols": "screen",
                    "narrative_reviews": "screen",
                    "methods_papers": "screen",
                }
            }
        )
        self.assertEqual(
            context,
            {"evidence_synthesis_targeted": True, "eligible_evidence_synthesis_types": ["meta-analysis", "systematic-review"]},
        )
        diagnostics = completion_diagnostics(
            {"decisions": {"question": {"status": "resolved"}}, "artifacts": {}, "workflow_context": context}
        )
        self.assertEqual(
            sum(item.code == "workflow.conditional_output_missing" for item in diagnostics),
            4,
        )


if __name__ == "__main__":
    unittest.main()
