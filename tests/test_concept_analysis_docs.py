"""Documentation-contract tests for the scope-first conceptual/objective/critic workflow."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read_doc(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def skill_docs() -> list[Path]:
    return [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]


class CrossReferenceIntegrityTests(unittest.TestCase):
    """Mechanical guards against reference drift, not phrasing contracts."""

    def test_every_reference_doc_is_routed_from_skill_md(self):
        routing = read_doc("SKILL.md").split("## Reference Routing")[1]
        listed = set(re.findall(r"`references/([a-z0-9._-]+\.md)`", routing))
        actual = {path.name for path in (ROOT / "references").glob("*.md")}
        self.assertEqual(
            actual - listed, set(), "reference docs missing from SKILL.md Reference Routing"
        )
        self.assertEqual(listed - actual, set(), "SKILL.md routes a reference that does not exist")

    def test_workflow_section_pointers_resolve_to_real_sections(self):
        workflow = read_doc("references/workflow.md")
        headings = dict(re.findall(r"^## (\d+)\. (.+)$", workflow, re.M))
        pointer = re.compile(r"workflow\.md`?[\s,]*(?:§|section )\s*(\d+)`?[\s,]*(?:\(([^)]*)\))?")
        found = 0
        for doc in skill_docs():
            for number, label in pointer.findall(doc.read_text(encoding="utf-8")):
                found += 1
                heading = headings.get(number)
                self.assertIsNotNone(heading, f"{doc.name}: workflow.md has no section {number}")
                if not label:
                    continue
                # A parenthetical label must describe the section it points at.
                words = {w for w in re.findall(r"[a-z]{4,}", label.lower())}
                target = heading.lower()
                self.assertTrue(
                    any(w in target for w in words) or not words,
                    f"{doc.name}: '§{number} ({label})' does not describe section {number!r} ({heading!r})",
                )
        self.assertGreater(found, 3, "pointer scan found too little to be meaningful")


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

    def test_intake_stops_for_the_seed_decision_rather_than_assuming_none(self):
        skill = read_doc("SKILL.md").lower()
        self.assertIn("ask once for optional known-relevant seed pmids and stop for the answer", skill)
        self.assertIn('"no seeds" must still be the user\'s stated choice rather than an assumption', skill)
        # The generic stop rule must not read as forbidding the intake stop.
        self.assertIn("stop at intake for the plain-language question and for the seed decision", skill)
        workflow = read_doc("references/workflow.md").lower()
        self.assertIn("ask once whether known-relevant seed pmids exist and stop for the answer", workflow)
        seeds = read_doc("references/seed-pmid-validation.md").lower()
        self.assertIn("do not treat silence, or your own inference that none exist", seeds)
        # The two legitimate skips stay available.
        for doc in (skill, workflow):
            self.assertIn("valid locked protocol", doc)

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
            "no-harm-revisions.md",
            "press-critic.md",
            "mesh-and-pubmed-tools.md",
            "tiab-expansion.md",
            "seed-pmid-validation.md",
            "no-seed-recall-estimation.md",
            "audit-template.md",
            "goal-tracking.md",
        ):
            self.assertIn(reference, skill)


class ConceptGateAskingPolicyTests(unittest.TestCase):
    """Recording an offer and blocking the gate on it are different acts."""

    def test_gate_blocks_only_on_decisions_evidence_cannot_settle(self):
        gate = read_doc("references/concept-analysis-and-gating.md").lower()
        self.assertIn("which offers block the gate", gate)
        self.assertIn("recording an offer and blocking on it are different acts", gate)
        for blocking in (
            "changes which concepts are in scope, or what the review question means",
            "changes the eligibility interpretation",
            "resolves a `high`-impact framework-slot or scope-breadth ambiguity",
        ):
            self.assertIn(blocking, gate)
        self.assertIn("defer to phase 2, offer recorded", gate)
        # Requiring an in-scope concept as a block is measurable, so it must not block the gate.
        self.assertIn("is a retrieval-structure question, not a scope question", gate)
        self.assertIn("only the question of whether the concept is in scope at all belongs at the gate", gate)
        self.assertIn("ask one question at a time, in the precedence order above", gate)
        self.assertIn("several qualifying offers do not become several questions", gate)

    def test_asking_policy_matches_the_top_level_stop_rule(self):
        skill = read_doc("SKILL.md").lower()
        gate = read_doc("references/concept-analysis-and-gating.md").lower()
        self.assertIn("present their evidence before asking the user to adopt a narrowing design", skill)
        self.assertIn("present the evidence before asking the user to adopt a narrowing design", gate)
        # decision_needed must not be read as "this blocks the gate".
        self.assertIn("does not by itself mean the question blocks the concept gate", gate)


class MethodsEvaluationFrameworkTests(unittest.TestCase):
    def test_profile_is_routed_from_skill_selection_and_concept_gate(self):
        skill = read_doc("SKILL.md").lower()
        self.assertIn("methods-evaluation-framework.md", skill)
        self.assertIn("profile_id", skill)
        selection = read_doc("references/framework-selection.md").lower()
        self.assertIn("methods-evaluation-framework.md", selection)
        self.assertIn("how well does [method/tool] perform [task]", selection)
        gate = read_doc("references/concept-analysis-and-gating.md").lower()
        self.assertIn("methods-evaluation-framework.md", gate)

    def test_framework_tracks_question_type_and_evidence_target_carries_report_type(self):
        selection = read_doc("references/framework-selection.md").lower()
        self.assertIn("the framework tracks the **question type**", selection)
        self.assertIn("carried separately by `evidence_target`", selection)
        self.assertIn("do not invent an \"umbrella\" framework", selection)
        self.assertIn("currently only `methods-evaluation`", selection)

    def test_canonical_slots_and_search_defaults_are_documented(self):
        doc = read_doc("references/methods-evaluation-framework.md").lower()
        for slot in (
            "technology_method",
            "task_function",
            "application_context",
            "comparator",
            "performance_outcome",
        ):
            self.assertIn(slot, doc)
        self.assertIn("screening-only by default", doc)
        self.assertIn("essential only when definitional", doc)
        self.assertIn("all five slots must be named in the protocol", doc)
        # A slot is an analytic role, not a required block: it may carry several elements.
        self.assertIn("a slot may carry more than one element", doc)
        self.assertIn("is an eligibility property, not searchable context", doc)
        self.assertIn("when the method and the task are the same artifact", doc)
        self.assertIn("the five slots are analytic roles, not a required block count", doc)

    def test_definitional_context_and_fragility_scope_have_concrete_tests(self):
        doc = read_doc("references/methods-evaluation-framework.md").lower()
        self.assertIn("would a record about the same method performing the same task in a different domain be out of scope", doc)
        self.assertIn("within-block tethering family", doc)
        # The rubric's hard red flags must not evict the paper's own subject from the search.
        self.assertIn("applies to the paper's subject, not its study properties", doc)
        self.assertIn("what the paper is *about*", doc)
        self.assertIn("a stage named in the plain-language question is not by itself the protocol narrowing the review", doc)

    def test_mandatory_ambiguity_check_separates_role_stage_and_evidence_type(self):
        doc = read_doc("references/methods-evaluation-framework.md").lower()
        self.assertIn("mandatory ambiguity check", doc)
        self.assertIn("performing the task, or being evaluated at it", doc)
        self.assertIn("which workflow stage is in scope", doc)
        self.assertIn("application context or the eligible report type", doc)
        self.assertIn("pause and ask the user before mesh lookup", doc)

    def test_application_context_never_switches_the_evidence_target(self):
        doc = read_doc("references/methods-evaluation-framework.md").lower()
        self.assertIn("includes primary methodological evaluations", doc)
        self.assertIn("the application context never triggers this mode on its own", doc)
        self.assertIn("evidence-synthesis-retrieval.md", doc)

    def test_narrow_task_language_stays_a_variant_not_the_main_block(self):
        doc = read_doc("references/methods-evaluation-framework.md").lower()
        self.assertIn("within-block term family or a focused variant", doc)
        self.assertIn("do not let a single brittle expression carry the block", doc)
        self.assertIn("two-block recall-first main strategy", doc)

    def test_profile_id_and_compiled_qa_are_documented_in_the_dsl(self):
        dsl = read_doc("references/protocol-dsl.md").lower()
        self.assertIn("profile_id", dsl)
        self.assertIn("methods-evaluation", dsl)
        self.assertIn("no dsl version bump", dsl)
        self.assertIn("methods-evaluation-role-safety", dsl)
        doc = read_doc("references/methods-evaluation-framework.md").lower()
        self.assertIn("methods-evaluation-role-safety", doc)
        audit = read_doc("references/audit-template.md").lower()
        self.assertIn("## methods-evaluation framework decisions (conditional)", audit)


class WorkflowContractTests(unittest.TestCase):
    def test_every_revision_has_an_executable_no_harm_gate(self):
        workflow = read_doc("references/workflow.md").lower()
        guard = read_doc("references/no-harm-revisions.md").lower()
        self.assertIn("revision_guard.py", workflow)
        for phrase in (
            "named defect fixed",
            "held-out retrieval preserved",
            "no unjustified required block",
            "syntax and translation stable",
            "scope unchanged or explicitly versioned",
            "workload effect recorded",
            "revert-to-baseline",
            "experimental-only",
        ):
            self.assertIn(phrase, guard)

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

    def test_screening_decisions_require_verifiable_evidence(self):
        doc = read_doc("references/candidate-screening.md").lower()
        for phrase in (
            "scripts/screening_tool.py",
            "quotation appears verbatim in that field of the hash-bound record",
            "`yes`, `no`, `unclear`, or `not_reported`",
        ):
            self.assertIn(phrase, doc)
        # Absent information must never become a silent exclusion.
        self.assertIn("forces `uncertain`", doc)

    def test_rule_only_screening_cannot_supply_evidence_roles(self):
        doc = read_doc("references/candidate-screening.md").lower()
        for phrase in (
            "`human`, `model`, `rule`, or `human_verified_model`",
            "cannot take `discovery`, `holdout`, or `both`",
            "a rule alone cannot finalise the records the evidence base is built from",
        ):
            self.assertIn(phrase, doc)

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
