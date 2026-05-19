import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_doc(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class ConceptAnalysisDocsTests(unittest.TestCase):
    def test_reference_documents_required_seed_branches(self):
        doc = read_doc("references/concept-analysis-and-gating.md")
        normalized = doc.lower()
        workflow = read_doc("references/workflow.md").lower()

        self.assertIn("formal concept analysis and concept gate", workflow)
        self.assertLess(workflow.index("seed pmid decision"), workflow.index("formal concept analysis and concept gate"))
        self.assertLess(workflow.index("formal concept analysis and concept gate"), workflow.index("pre-mesh vocabulary/domain brainstorm"))
        self.assertLess(workflow.index("pre-mesh vocabulary/domain brainstorm"), workflow.index("mesh/pubmed exploration"))
        self.assertLess(workflow.index("formal concept analysis and concept gate"), workflow.index("mesh/pubmed exploration"))

        self.assertIn("with seed pmids", normalized)
        self.assertIn("with no seed pmids", normalized)
        self.assertIn("limited seed fetch/mining", normalized)
        self.assertLess(workflow.index("seed pmid decision"), workflow.index("limited seed fetch/mining"))
        self.assertLess(workflow.index("limited seed fetch/mining"), workflow.index("formal concept analysis and concept gate"))
        self.assertIn("not available - no seed pmids supplied", normalized)
        self.assertIn("do not report true seed-derived mesh", normalized)
        self.assertIn("known-item recall", normalized)

        self.assertIn("goal-tracked concept gates", normalized)
        self.assertIn("goal-tracking.md", normalized)
        self.assertIn("social-science, psychosocial, behavioral, qualitative, health-services", normalized)
        self.assertIn("ask one concise user-facing domain-framing question", normalized)
        self.assertIn("minority stress", normalized)
        self.assertIn("disclosure/concealment", normalized)

    def test_goal_tracking_reference_owns_goal_rules(self):
        doc = read_doc("references/goal-tracking.md")
        normalized = doc.lower()
        skill = read_doc("SKILL.md").lower()

        for state in [
            "goal_requested_intake_pending",
            "goal_active_autonomous",
            "goal_active_blocked",
            "goal_completion_audit",
        ]:
            self.assertIn(state, doc)

        self.assertIn("do not call `create_goal`", normalized)
        self.assertIn("ask only whether the user has known relevant seed pmids", normalized)
        self.assertIn("limited seed fetch/mining", normalized)
        self.assertIn("concept-gate/filter decisions", normalized)
        self.assertIn("token budgets", normalized)
        self.assertIn("completion audit", normalized)
        self.assertIn("suggested objective wording", normalized)
        self.assertIn("`/goal` with no seed status", normalized)
        self.assertIn("`/goal` with seeds and a dangerous optional concept", normalized)

        self.assertIn("references/goal-tracking.md", skill)
        self.assertIn("pre-goal intake rules", skill)
        self.assertNotIn("goal_requested_intake_pending", skill)
        self.assertNotIn("treat `/goal` as", skill)
        self.assertNotIn("do not call `create_goal` yet", skill)

    def test_reference_defines_ledger_roles_and_seed_behaviors(self):
        doc = read_doc("references/concept-analysis-and-gating.md")
        normalized = doc.lower()

        for role in [
            "essential `and` block",
            "within-block synonym/term only",
            "sensitivity-dangerous optional `and` block",
            "methodological/filter concept",
            "omitted concept",
        ]:
            self.assertIn(role, normalized)

        for field in [
            "`candidate_concept`",
            "`seed_evidence`",
            "`no_seed_evidence`",
            "`recall_risk`",
            "`final_handling`",
        ]:
            self.assertIn(field, doc)

        self.assertIn("with seed pmids", normalized)
        self.assertIn("do not ask for seeds again", normalized)
        self.assertIn("treat seed status as resolved", normalized)
        self.assertIn("use limited seed fetch/mining before the concept gate", normalized)
        self.assertIn("validate the final topic-only strategy against in-scope seeds", normalized)
        self.assertIn("do not overfit", normalized)

        self.assertIn("with no seed pmids", normalized)
        self.assertIn("not available - no seed pmids supplied", normalized)
        self.assertIn("do not report true seed-derived mesh", normalized)
        self.assertIn("known-item recall", normalized)
        self.assertIn("sample-record mesh patterns are not seed-derived evidence", normalized)
        self.assertNotIn("pilot test protocol", normalized)
        self.assertNotIn("acceptance checks", normalized)
        self.assertNotIn("pilot 1", normalized)
        self.assertNotIn("pilot 2", normalized)
        self.assertNotIn("pilot 3", normalized)

    def test_first_response_precedes_reference_navigation(self):
        skill = read_doc("SKILL.md").lower()

        self.assertLess(skill.index("## core goal"), skill.index("## first response"))
        self.assertLess(skill.index("## first response"), skill.index("## required input"))
        self.assertLess(skill.index("## first response"), skill.index("## canonical workflow"))
        self.assertNotIn("## request router", skill)
        self.assertNotIn("## build sequence", skill)
        self.assertNotIn("## bundled tools and detailed workflow", skill)

    def test_frontmatter_has_strong_triggers_and_metadata(self):
        skill = read_doc("SKILL.md")
        frontmatter = skill.split("---", 2)[1].lower()

        for trigger in [
            "pubmed/medline",
            "systematic reviews",
            "scoping reviews",
            "rapid reviews",
            "evidence maps",
            "narrative/evidence syntheses",
            "mesh",
            "seed pmid",
            "press",
            "prisma-s",
        ]:
            self.assertIn(trigger, frontmatter)

        self.assertIn("license: mit", frontmatter)
        self.assertIn("metadata:", frontmatter)
        self.assertIn('  version: "1.0.0"', frontmatter)
        self.assertNotIn("\nversion:", frontmatter)

    def test_required_input_rejects_existing_boolean_context(self):
        skill = read_doc("SKILL.md")
        normalized = skill.lower()
        required_input = normalized.split("## required input", 1)[1].split("## goal tracking", 1)[0]

        self.assertNotIn("use one mode only", required_input)
        self.assertNotIn("**build mode**", required_input)
        self.assertIn("independently stated topic, review question, or protocol-style question", required_input)
        self.assertIn("seed pmids or seed papers", required_input)
        self.assertIn("no-seed workflow", required_input)
        self.assertIn("boolean syntax", required_input)
        self.assertIn("pubmed line set", required_input)
        self.assertIn("strategy fragment", required_input)
        self.assertIn("ask for the topic or review question in plain language", required_input)
        self.assertIn("provide or confirm the topic/review question without using the pasted strategy", required_input)
        self.assertIn("do not use pasted boolean terms, operators, filters, or line structure", required_input)
        self.assertNotIn("optional build context", normalized)
        self.assertNotIn("source of candidate terms", normalized)
        self.assertNotIn("reuse", required_input)
        self.assertNotIn("strategy review mode", required_input)
        self.assertNotIn("syntax/logic review", required_input)
        self.assertNotIn("build mode", normalized)
        self.assertNotIn("existing boolean or syntax provided", normalized)
        self.assertNotIn("review-existing-strategy.md", normalized)

    def test_workflow_owns_canonical_sequence_and_mental_model(self):
        workflow = read_doc("references/workflow.md").lower()

        sequence_items = [
            "question",
            "seed pmid decision",
            "limited seed fetch/mining, if supplied, only to inform concept analysis",
            "formal concept analysis and concept gate",
            "pre-mesh vocabulary/domain brainstorm for weak-mesh or social-science concepts",
            "mesh/pubmed exploration",
            "text-word, proximity, and wildcard candidate generation",
            "concept-block construction and testing",
            "seed pmid validation, if seeds were provided",
            "revision",
            "final query hygiene and qa",
            "save audit markdown file with decision ledger",
            "documented draft strategy for human press peer review",
        ]

        for item in sequence_items:
            self.assertIn(item, workflow)
        for before, after in zip(sequence_items, sequence_items[1:]):
            self.assertLess(workflow.index(before), workflow.index(after))

        self.assertIn("(mesh layer or title/abstract layer or proximity/wildcard layer)", workflow)
        self.assertIn("mesh does not replace free text", workflow)
        self.assertIn("free text does not replace mesh", workflow)
        self.assertIn("proximity and wildcards do not replace either", workflow)
        self.assertIn("do not overwrite it silently", workflow)
        self.assertIn("report the saved audit markdown path", workflow)
        self.assertIn("not performed", workflow)
        self.assertIn("not available", workflow)
        self.assertIn("not applicable", workflow)
        self.assertIn("draft pending human peer review (press", workflow)

    def test_workflow_links_specialist_references_at_relevant_steps(self):
        workflow = read_doc("references/workflow.md").lower()

        for reference in [
            "concept-analysis-and-gating.md",
            "goal-tracking.md",
            "tiab-expansion.md",
            "mesh-and-pubmed-tools.md",
            "wildcard-and-truncation.md",
            "validated-methodological-filters-and-hedges.md",
            "seed-pmid-validation.md",
            "audit-template.md",
            "prisma-s-reporting.md",
        ]:
            self.assertIn(reference, workflow)

        self.assertLess(workflow.index("mesh-and-pubmed-tools.md"), workflow.index("mesh_tool.py sweep"))
        self.assertLess(workflow.index("wildcard-and-truncation.md"), workflow.index("truncat*[tiab]"))
        self.assertLess(workflow.index("seed-pmid-validation.md"), workflow.index("## 7a. record search design alternatives"))
        self.assertLess(workflow.index("prisma-s-reporting.md"), workflow.index("record:"))

    def test_noncanonical_docs_reference_workflow_without_full_duplication(self):
        skill = read_doc("SKILL.md").lower()
        readme = read_doc("README.md").lower()
        concept_doc = read_doc("references/concept-analysis-and-gating.md").lower()

        for doc in [skill, readme, concept_doc]:
            self.assertIn("workflow.md", doc)
            self.assertNotIn("-> seed pmid", doc)
            self.assertNotIn("-> formal concept analysis", doc)
            self.assertNotIn("(mesh layer or title/abstract layer or proximity/wildcard layer)", doc)
            self.assertNotIn("mesh does not replace free text", doc)

    def test_primary_docs_link_to_formal_concept_analysis(self):
        skill = read_doc("SKILL.md").lower()
        workflow = read_doc("references/workflow.md").lower()
        tiab = read_doc("references/tiab-expansion.md").lower()

        self.assertIn("references/concept-analysis-and-gating.md", skill)
        self.assertIn("references/goal-tracking.md", skill)
        self.assertFalse((ROOT / "references/review-existing-strategy.md").exists())
        self.assertIn("references/workflow.md", skill)
        self.assertIn("canonical build sequence", skill)
        self.assertIn("high-sensitivity mental model", skill)
        self.assertIn("seed/no-seed branches", skill)
        self.assertIn("pre-goal intake rules", skill)

        self.assertIn("concept-analysis-and-gating.md", workflow)
        self.assertIn("goal-tracking.md", workflow)
        self.assertIn("formal concept analysis and concept gate", workflow)
        self.assertIn("pre-mesh vocabulary/domain brainstorm", workflow)
        self.assertIn("before mesh lookup", workflow)
        self.assertIn("do not call `create_goal` while seed status", workflow)
        self.assertLess(workflow.index("formal concept analysis and concept gate"), workflow.index("pre-mesh vocabulary/domain brainstorm"))
        self.assertLess(workflow.index("pre-mesh vocabulary/domain brainstorm"), workflow.index("mesh/pubmed exploration"))

        self.assertIn("pre-mesh vocabulary/domain brainstorm", tiab)
        self.assertIn("minority-stress", tiab)
        self.assertIn("disclosure", tiab)
        self.assertIn("unmet need", tiab)


if __name__ == "__main__":
    unittest.main()
