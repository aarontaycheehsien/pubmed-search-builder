import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_doc(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def markdown_docs() -> list[Path]:
    return [path for path in ROOT.rglob("*.md") if "__pycache__" not in path.parts]


class ConceptAnalysisDocsTests(unittest.TestCase):
    def test_skill_requires_stage_reporting_contract(self):
        skill = read_doc("SKILL.md").lower()
        contract = skill.split("## stage reporting contract", 1)[1].split("## required input", 1)[0]

        self.assertIn("stage banner", contract)
        for field in [
            "`stage`",
            "`reference(s) in force`",
            "`doing now`",
            "`allowed now`",
            "`not doing yet`",
            "`user decision needed`",
        ]:
            self.assertIn(field, contract)

        for reference in [
            "references/workflow.md",
            "references/framework-selection.md",
            "references/concept-analysis-and-gating.md",
            "references/mesh-and-pubmed-tools.md",
            "references/seed-pmid-validation.md",
            "references/audit-template.md",
        ]:
            self.assertIn(reference, contract)

        self.assertIn("optional secondary blocks", contract)
        self.assertIn("filters", contract)
        self.assertIn("focused variants", contract)

    def test_workflow_contains_numbered_stage_map_and_banner_requirements(self):
        workflow = read_doc("references/workflow.md").lower()
        stage_map = workflow.split("## stage map and banner requirement", 1)[1].split("high-sensitivity pubmed strategies", 1)[0]

        for stage in [
            "1. **question intake**",
            "2. **seed intake**",
            "4. **concept gate**",
            "6. **mesh/pubmed exploration**",
            "8. **block testing**",
            "9. **validation**",
            "11. **final qa**",
            "12. **audit output**",
        ]:
            self.assertIn(stage, stage_map)

        # Tiered reporting: full banners only at decision gates, one-line markers elsewhere.
        self.assertGreaterEqual(stage_map.count("`full banner required`"), 3)
        self.assertIn("`stage marker`", stage_map)
        self.assertIn("exact reference files in force", stage_map)
        self.assertIn("user/protocol decision needed", stage_map)
        self.assertIn("before concept-block counts", workflow)
        self.assertIn("before final parse checks", workflow)
        self.assertIn("before rendering or saving the audit markdown file", workflow)

    def test_framework_selection_states_when_user_question_is_needed(self):
        doc = read_doc("references/framework-selection.md").lower()

        self.assertIn("state the framework choice and reason", doc)
        self.assertIn("state whether a framework question is needed", doc)
        self.assertIn("no framework question is needed", doc)
        self.assertIn("ask only that question and stop", doc)
        self.assertIn("whether a framework question was needed, and why or why not", doc)

    def test_concept_gate_asks_before_testing_optional_secondary_blocks(self):
        doc = read_doc("references/concept-analysis-and-gating.md").lower()

        self.assertIn("pre-mesh gate summary", doc)
        self.assertIn("ask the user at the concept gate by default", doc)
        self.assertIn("optional secondary `and` block", doc)
        self.assertIn("outcome block", doc)
        self.assertIn("safety block", doc)
        self.assertIn("filter/limit", doc)
        self.assertIn("focused variant", doc)
        self.assertIn("unless the protocol already decides it", doc)
        self.assertIn("pause and ask before testing or promoting", doc)
        self.assertIn("do not use it to test unauthorized optional secondary blocks", doc)

    def test_reference_documents_required_seed_branches(self):
        doc = read_doc("references/concept-analysis-and-gating.md")
        normalized = doc.lower()
        workflow = read_doc("references/workflow.md").lower()

        self.assertIn("formal concept analysis and concept gate", workflow)
        self.assertLess(workflow.index("plain-language research/review question"), workflow.index("seed pmid decision"))
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
        self.assertIn("`/goal` with no plain-language research question", normalized)
        self.assertIn("`/goal` with a confirmed research question and no seed status", normalized)
        self.assertIn("`/goal` with seeds and a dangerous optional concept", normalized)
        self.assertIn("ask only for the research/review question", normalized)

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
            "`framework_slot`",
            "`seed_evidence`",
            "`pre_gate_no_seed_evidence`",
            "`post_gate_validation_evidence`",
            "`recall_risk`",
            "`and_block_admission`",
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
        self.assertIn("pre-gate no-seed evidence", normalized)
        self.assertIn("post-gate validation/audit evidence", normalized)
        phase_1_no_seed = normalized.split("when no seed pmids are supplied", 1)[1].split("## gate output contract", 1)[0]
        for forbidden in [
            "do not use mesh sweeps",
            "pubmed atm/query translations",
            "sample-record patterns",
            "concept-block counts",
            "final qa",
        ]:
            self.assertIn(forbidden, phase_1_no_seed)
        self.assertIn("do not report true seed-derived mesh", normalized)
        self.assertIn("known-item recall", normalized)
        self.assertIn("sample-record mesh patterns are not seed-derived evidence", normalized)
        self.assertIn("and-block admission test", normalized)
        self.assertIn("acceptance checks", normalized)
        self.assertIn("concept-gate pilot-test protocol", normalized)
        self.assertIn("phase 1 - pre-mesh admission check", normalized)
        self.assertIn("phase 2 - post-block pilot checks", normalized)
        self.assertIn("gate output contract", normalized)
        self.assertIn("default if uncertain", normalized)
        self.assertIn("do not use pasted boolean syntax", normalized)
        self.assertNotIn("supplied boolean context", normalized)

    def test_first_response_precedes_reference_navigation(self):
        skill = read_doc("SKILL.md").lower()

        self.assertLess(skill.index("## core goal"), skill.index("## first response"))
        self.assertLess(skill.index("## first response"), skill.index("## required input"))
        self.assertLess(skill.index("## first response"), skill.index("## canonical workflow"))
        self.assertNotIn("## request router", skill)
        self.assertNotIn("## build sequence", skill)
        self.assertNotIn("## bundled tools and detailed workflow", skill)

    def test_skill_requires_research_question_before_seed_intake(self):
        skill = read_doc("SKILL.md").lower()
        first_response = skill.split("## first response", 1)[1].split("## required input", 1)[0]

        self.assertIn("first require an independently stated plain-language research/review question", first_response)
        self.assertIn("ask only for the research/review question and stop", first_response)
        self.assertLess(first_response.index("plain-language research/review question"), first_response.index("seed pmids"))
        self.assertIn("after the plain-language research/review question is confirmed", first_response)

    def test_pre_gate_seed_triage_policy_is_documented(self):
        skill = read_doc("SKILL.md").lower()
        first_response = skill.split("## first response", 1)[1].split("## required input", 1)[0]
        workflow = read_doc("references/workflow.md").lower()
        seed_doc = read_doc("references/seed-pmid-validation.md").lower()
        concept_doc = read_doc("references/concept-analysis-and-gating.md").lower()
        audit = read_doc("references/audit-template.md").lower()

        for phrase in [
            "normalize and deduplicate numeric pmids",
            "malformed entries",
            "not-found pmids",
            "limited pre-gate seed fetch/mining",
            "retracted",
            "materially out of scope",
            "exclude it, replace it, or retain it as a special validation seed",
            "do not run broader pubmed exploration",
        ]:
            self.assertIn(phrase, first_response)

        seed_section = workflow.split("## 2. ask once for seed pmids", 1)[1].split("## 3. run formal concept analysis", 1)[0]
        for phrase in [
            "malformed entries",
            "missing or not-found pmids",
            "exclude them from seed evidence",
            "limited pre-gate seed fetch/mining",
            "pause before the concept gate only when a fetched seed is retracted or appears materially out of scope",
            "ordinary uncertainty is recorded",
            "broader pubmed exploration",
            "block testing",
            "final qa",
        ]:
            self.assertIn(phrase, seed_section)

        for phrase in [
            "pre-gate seed triage",
            "`pubmed_tool.py mine --pmids ... --output",
            "`requested_pmids`",
            "`found_pmids`",
            "`missing_pmids`",
            "titles",
            "abstract text",
            "publication types",
            "mesh headings",
            "keywords",
            "missing or not-found pmids",
            "retain it as a special validation seed",
            "do not use malformed, missing, excluded, or unresolved seed records as term evidence",
        ]:
            self.assertIn(phrase, seed_doc)

        for phrase in [
            "pre-gate seed triage",
            "document malformed and missing/not-found pmids",
            "pause before the concept gate only for fetched seeds that are retracted or clearly out of scope",
        ]:
            self.assertIn(phrase, concept_doc)

        for phrase in [
            "pre-gate seed triage",
            "malformed pmids",
            "missing/not-found pmids",
            "fetched seed records",
            "retracted seeds",
            "likely out-of-scope seeds",
            "user/protocol decision when paused",
        ]:
            self.assertIn(phrase, audit)

    def test_frontmatter_has_strong_triggers_and_no_release_metadata(self):
        skill = read_doc("SKILL.md")
        frontmatter = skill.split("---", 2)[1].lower()
        agent_metadata = read_doc("agents/openai.yaml").lower()

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

        self.assertNotIn("license:", frontmatter)
        self.assertNotIn("metadata:", frontmatter)
        self.assertNotIn("\nversion:", frontmatter)
        self.assertIn("plain-language research/review question", agent_metadata)
        self.assertLess(agent_metadata.index("plain-language research/review question"), agent_metadata.index("seed pmids"))
        self.assertNotIn("ask for optional seed pmids first", agent_metadata)

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
        self.assertIn("ask only for the topic or review question in plain language", required_input)
        self.assertIn("do not ask for seed pmids in the same response", required_input)
        self.assertIn("ignore the pasted syntax", required_input)
        self.assertIn("restate or confirm the topic/review question in plain language before asking for seed pmids", required_input)
        self.assertIn("never use pasted boolean terms, operators, filters, line numbers, field tags, or line structure", required_input)
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
            "plain-language research/review question",
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

    def test_tool_sequence_runs_concept_gate_before_exploration(self):
        tools_doc = read_doc("references/mesh-and-pubmed-tools.md").lower()
        # The duplicated 20-step "Suggested Operational Sequence" was collapsed in Phase 1;
        # workflow.md owns the canonical order and the tools doc keeps only a tool-to-stage map.
        self.assertNotIn("## suggested operational sequence", tools_doc)
        self.assertIn("## tool-to-stage quick map", tools_doc)
        sequence = tools_doc.split("## tool-to-stage quick map", 1)[1].split("## do not fabricate", 1)[0]

        self.assertIn("workflow.md", sequence)
        self.assertIn("owns the canonical build sequence", sequence)
        # The concept gate still precedes MeSH/PubMed exploration in the map.
        self.assertLess(sequence.index("concept gate"), sequence.index("mesh/pubmed exploration"))

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

    def test_no_seed_objective_term_path_is_documented(self):
        concept_doc = read_doc("references/concept-analysis-and-gating.md").lower()
        tiab = read_doc("references/tiab-expansion.md").lower()
        workflow = read_doc("references/workflow.md").lower()
        tools_doc = read_doc("references/mesh-and-pubmed-tools.md").lower()

        # The no-seed branch (post-gate) must route to objective term ranking,
        # not leave term selection to LLM eyeballing.
        no_seed_branch = concept_doc.split("## with no seed pmids", 1)[1]
        self.assertIn("--relevant-query-file", no_seed_branch)
        self.assertIn("pilot relevant-set query", no_seed_branch)
        self.assertIn("not validated recall", no_seed_branch)

        # tiab-expansion owns the how-to for building a no-seed pilot relevant set.
        self.assertIn("--relevant-query-file", tiab)
        self.assertIn("pilot relevant-set query", tiab)
        self.assertIn("high-precision", tiab)

        # workflow step 5 and the tools reference both expose the no-seed route.
        self.assertIn("--relevant-query-file", workflow)
        self.assertIn("--relevant-query-file", tools_doc)
        self.assertIn("term-rank --relevant-query-file pilot.txt", tools_doc)

    def test_zero_hit_term_decision_is_documented(self):
        workflow = read_doc("references/workflow.md").lower()
        tools_doc = read_doc("references/mesh-and-pubmed-tools.md").lower()
        audit = read_doc("references/audit-template.md").lower()

        # Final hygiene removes genuinely zero-hit terms and documents them by default,
        # while still offering the user the option to keep any.
        self.assertIn("phrases_not_found", workflow)
        self.assertIn("remove and document", workflow)
        self.assertIn("option to keep any as an intentional zero-hit term", workflow)
        self.assertIn("duplicate_term", workflow)

        # The tools reference documents the new hook issues and the duplicate check.
        self.assertIn("phrases_not_found", tools_doc)
        self.assertIn("fields_not_found", tools_doc)
        self.assertIn("duplicate_term", tools_doc)

        # The audit ledger captures the zero-hit/duplicate decision.
        self.assertIn("zero-hit", audit)

    def test_final_validation_cleanup_step_is_documented(self):
        workflow = read_doc("references/workflow.md").lower()

        # An explicit, required closing gate that tests, reports, and offers remediation.
        self.assertIn("final validation and cleanup offer", workflow)
        self.assertIn("required closing gate", workflow)
        self.assertIn("apply the offered cleanups", workflow)
        # Recall-first guardrail: recall-reducing items (not zero-hit terms) stay offer-only and default to keep.
        self.assertIn("offer-only and default to keep", workflow)
        # Approved cleanups are applied, then the count is re-confirmed.
        self.assertIn("confirm the delivered count", workflow)
        # It is also a stop condition.
        self.assertIn("final validation and cleanup offer has been presented", workflow)

    def test_run_manifest_is_canonical_output(self):
        skill = read_doc("SKILL.md").lower()
        workflow = read_doc("references/workflow.md").lower()
        tools_doc = read_doc("references/mesh-and-pubmed-tools.md").lower()
        audit = read_doc("references/audit-template.md").lower()

        # SKILL.md Output Format names the canonical run manifest and the five recorded facts.
        output_format = skill.split("## output format", 1)[1]
        self.assertIn("run_manifest.json", output_format)
        for field in ["command", "output path", "date", "count", "superseded"]:
            self.assertIn(field, output_format)

        # workflow.md saves the manifest at audit output: after the audit Markdown, before PRESS handoff.
        self.assertIn("run_manifest.json", workflow)
        self.assertLess(
            workflow.index("save audit markdown file with decision ledger"),
            workflow.index("run_manifest.json"),
        )
        self.assertLess(
            workflow.index("run_manifest.json"),
            workflow.index("documented draft strategy for human press peer review"),
        )

        # The tools reference documents the helper script and the manifest file.
        self.assertIn("manifest_tool.py", tools_doc)
        self.assertIn("run_manifest.json", tools_doc)

        # The audit template Reporting notes point to the manifest.
        self.assertIn("run manifest", audit)
        self.assertIn("run_manifest.json", audit)

    def test_record_content_command_docs_require_saved_json(self):
        for path in markdown_docs():
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if "pubmed_tool.py fetch --pmids" in stripped:
                    self.assertIn("--output", stripped, msg=str(path))
                if stripped.startswith("python ") and "pubmed_tool.py mine --pmids" in stripped:
                    self.assertIn("--output", stripped, msg=str(path))
                    self.assertNotIn("--summary", stripped, msg=str(path))
                if stripped.startswith("python ") and "pubmed_tool.py sample" in stripped:
                    self.assertIn("--output", stripped, msg=str(path))
                    self.assertNotIn("--summary", stripped, msg=str(path))

        skill = read_doc("SKILL.md").lower()
        mesh_tools = read_doc("references/mesh-and-pubmed-tools.md").lower()
        workflow = read_doc("references/workflow.md").lower()
        audit_template = read_doc("references/audit-template.md").lower()
        for doc in (skill, mesh_tools):
            self.assertIn("fetch", doc)
            self.assertIn("mine", doc)
            self.assertIn("sample", doc)
            self.assertIn("record-content commands", doc)
            self.assertIn("do not support `--summary`", doc)
            self.assertIn("inspect the saved json", doc)
        self.assertIn("no reviewed json, no decision", workflow)
        self.assertIn("receipt-only stdout from `fetch`, `mine`, or `sample` cannot support", workflow)
        self.assertIn("record-content evidence reviewed", audit_template)
        self.assertIn("receipt-only stdout used as decision evidence", audit_template)


if __name__ == "__main__":
    unittest.main()
