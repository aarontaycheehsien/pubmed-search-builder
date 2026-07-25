"""Screening validates evidence, not form."""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SPEC = importlib.util.spec_from_file_location("screening_tool_test", ROOT / "scripts" / "screening_tool.py")
screening = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(screening)

import candidate_ledger  # noqa: E402

PROTOCOL = {
    "dsl_version": 1,
    "scope_version": 1,
    "protocol_id": "demo-review",
    "eligibility": {
        "inclusion": [
            {"id": "inc_population", "label": "Nursing students", "description": "Population is nursing students."},
            {"id": "inc_intervention", "label": "VR teaching", "description": "Intervention is VR-based teaching."},
        ],
        "exclusion": [
            {"id": "exc_design", "label": "Ineligible type", "description": "Conference abstract or editorial."},
        ],
    },
}

RECORD = {
    "pmid": "12345678",
    "title": "Virtual reality simulation for nursing students",
    "abstract": "Undergraduate nursing students trained with an immersive virtual reality module.",
    "keywords": ["virtual reality", "nursing education"],
    "mesh_headings": [{"name": "Students, Nursing"}],
}


def rubric_for(protocol=PROTOCOL):
    return screening.compile_rubric(protocol, scope_version=1, protocol_path="review_protocol_v1.json")


def worksheet_for(records=(RECORD,), rubric=None):
    return screening.prepare_worksheet(
        rubric or rubric_for(), list(records), scope_version=1, round_number=1, records_path="records.json"
    )


def set_row(row, verdicts, evidence, decision, decided_by="model", adjudicated_by="", reason="reasoned"):
    for assessment in row["assessments"]:
        criterion = assessment["criterion_id"]
        assessment["verdict"] = verdicts.get(criterion, "not_reported")
        assessment["evidence"] = evidence.get(criterion, [])
    row["decision"] = decision
    row["decided_by"] = decided_by
    row["adjudicated_by"] = adjudicated_by
    row["eligibility_reason"] = reason
    return row


TITLE_QUOTE = [{"field": "title", "quote": "nursing students"}]
ABSTRACT_QUOTE = [{"field": "abstract", "quote": "immersive virtual reality module"}]
INCLUDE_EVIDENCE = {"inc_population": TITLE_QUOTE, "inc_intervention": ABSTRACT_QUOTE}
INCLUDE_VERDICTS = {"inc_population": "yes", "inc_intervention": "yes", "exc_design": "no"}


def validate(worksheet, records=(RECORD,), rubric=None):
    return screening.validate_worksheet(worksheet, rubric or rubric_for(), list(records))


class RubricTests(unittest.TestCase):
    def test_criteria_are_compiled_with_roles_from_the_protocol(self):
        rubric = rubric_for()
        roles = {item["id"]: item["role"] for item in rubric["criteria"]}
        self.assertEqual(roles["inc_population"], screening.REQUIRED_INCLUSION)
        self.assertEqual(roles["exc_design"], screening.DECISIVE_EXCLUSION)
        self.assertEqual(sorted(rubric["verdicts"]), ["no", "not_reported", "unclear", "yes"])

    def test_scope_version_mismatch_is_refused(self):
        with self.assertRaises(screening.ScreeningError):
            screening.compile_rubric(PROTOCOL, scope_version=2, protocol_path="p.json")

    def test_protocol_without_eligibility_cannot_produce_a_rubric(self):
        with self.assertRaises(screening.ScreeningError):
            screening.compile_rubric({"scope_version": 1}, scope_version=1, protocol_path="p.json")

    def test_a_tampered_rubric_is_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rubric.json"
            rubric = rubric_for()
            rubric["criteria"][0]["role"] = screening.DECISIVE_EXCLUSION
            path.write_text(json.dumps(rubric), encoding="utf-8")
            with self.assertRaises(screening.ScreeningError):
                screening.load_rubric(path, scope_version=1)


class WorksheetTests(unittest.TestCase):
    def test_every_record_gets_one_pending_assessment_per_criterion(self):
        worksheet = worksheet_for()
        row = worksheet["records"][0]
        self.assertEqual(len(row["assessments"]), 3)
        self.assertTrue(all(item["verdict"] == "pending" for item in row["assessments"]))
        self.assertEqual(row["decision"], "pending")

    def test_a_pending_worksheet_does_not_validate(self):
        issues, _summary = validate(worksheet_for())
        self.assertTrue(issues)

    def test_a_worksheet_screened_against_another_rubric_is_rejected(self):
        worksheet = worksheet_for()
        worksheet["rubric_sha256"] = "0" * 64
        issues, _summary = validate(worksheet)
        self.assertTrue(any("not screened against this rubric" in issue for issue in issues))


class EvidenceTests(unittest.TestCase):
    """The central fix: a quotation must exist in the record it claims to come from."""

    def test_an_evidence_backed_include_validates(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include")
        issues, summary = validate(worksheet)
        self.assertEqual(issues, [])
        self.assertEqual(summary["verified_evidence_spans"], 2)

    def test_a_fabricated_quotation_is_rejected(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            INCLUDE_VERDICTS,
            {**INCLUDE_EVIDENCE, "inc_intervention": [{"field": "abstract", "quote": "a randomised crossover trial"}]},
            "include",
        )
        issues, _summary = validate(worksheet)
        self.assertTrue(any("quotes text absent from abstract" in issue for issue in issues))

    def test_a_quotation_attributed_to_the_wrong_field_is_rejected(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            INCLUDE_VERDICTS,
            {**INCLUDE_EVIDENCE, "inc_population": [{"field": "abstract", "quote": "Virtual reality simulation for"}]},
            "include",
        )
        issues, _summary = validate(worksheet)
        self.assertTrue(any("quotes text absent from abstract" in issue for issue in issues))

    def test_quotations_tolerate_whitespace_and_case_but_not_invention(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            INCLUDE_VERDICTS,
            {**INCLUDE_EVIDENCE, "inc_population": [{"field": "title", "quote": "  NURSING\n  students "}]},
            "include",
        )
        issues, _summary = validate(worksheet)
        self.assertEqual(issues, [])

    def test_evidence_may_be_drawn_from_keywords_and_mesh_headings(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            INCLUDE_VERDICTS,
            {
                "inc_population": [{"field": "mesh_headings", "quote": "Students, Nursing"}],
                "inc_intervention": [{"field": "keywords", "quote": "virtual reality"}],
            },
            "include",
        )
        issues, _summary = validate(worksheet)
        self.assertEqual(issues, [])

    def test_screening_a_record_that_has_since_changed_is_rejected(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include")
        changed = {**RECORD, "abstract": "A completely different abstract."}
        issues, _summary = validate(worksheet, records=(changed,))
        self.assertTrue(any("record content changed after screening" in issue for issue in issues))


class EvidenceQualityTests(unittest.TestCase):
    """Existing in the record is necessary but not sufficient to function as evidence."""

    def _with_quote(self, field, quote):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            {"inc_population": "yes", "inc_intervention": "no", "exc_design": "no"},
            {"inc_intervention": [{"field": field, "quote": quote}]},
            "exclude",
        )
        return validate(worksheet)[0]

    def test_a_contentless_quotation_is_rejected(self):
        issues = self._with_quote("abstract", "with an")
        self.assertTrue(any("cites no substantive content" in issue for issue in issues), issues)

    def test_a_whole_field_dump_is_rejected(self):
        long_record = {**RECORD, "abstract": " ".join(f"word{index}" for index in range(200))}
        worksheet = screening.prepare_worksheet(
            rubric_for(), [long_record], scope_version=1, round_number=1, records_path="r.json"
        )
        set_row(
            worksheet["records"][0],
            {"inc_population": "yes", "inc_intervention": "no", "exc_design": "no"},
            {"inc_intervention": [{"field": "abstract", "quote": " ".join(f"word{index}" for index in range(70))}]},
            "exclude",
        )
        issues, _summary = validate(worksheet, records=(long_record,))
        self.assertTrue(any("points at nothing in particular" in issue for issue in issues), issues)

    def test_a_substantive_quotation_is_accepted(self):
        self.assertEqual(self._with_quote("title", "Virtual reality simulation"), [])

    def test_a_span_reused_across_every_criterion_is_reported(self):
        worksheet = worksheet_for()
        shared = [{"field": "abstract", "quote": "Undergraduate nursing students trained with an immersive virtual reality module"}]
        set_row(
            worksheet["records"][0],
            INCLUDE_VERDICTS,
            {"inc_population": shared, "inc_intervention": shared, "exc_design": shared},
            "include",
        )
        issues, summary = validate(worksheet)
        self.assertEqual(issues, [])
        # Not rejected -- a dense sentence can settle several criteria -- but visible.
        self.assertEqual(summary["single_span_records"], ["12345678"])
        self.assertEqual(summary["distinct_evidence_spans"], 1)
        self.assertEqual(summary["verified_evidence_spans"], 3)

    def test_distinct_spans_are_counted_separately_from_total_spans(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include")
        _issues, summary = validate(worksheet)
        self.assertEqual(summary["distinct_evidence_spans"], 2)
        self.assertEqual(summary["single_span_records"], [])


class DecisionRuleTests(unittest.TestCase):
    def test_include_requires_affirmative_evidence_on_every_required_criterion(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, {"inc_population": TITLE_QUOTE}, "include")
        issues, _summary = validate(worksheet)
        self.assertTrue(any("without supporting evidence for required criteria" in issue for issue in issues))

    def test_exclude_needs_evidence_for_only_the_decisive_failure(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            {"inc_population": "yes", "inc_intervention": "no", "exc_design": "no"},
            {"inc_intervention": [{"field": "title", "quote": "Virtual reality simulation"}]},
            "exclude",
        )
        issues, _summary = validate(worksheet)
        self.assertEqual(issues, [])

    def test_exclude_without_any_evidenced_failure_is_rejected(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            {"inc_population": "yes", "inc_intervention": "no", "exc_design": "no"},
            {},
            "exclude",
        )
        issues, _summary = validate(worksheet)
        self.assertTrue(any("without supporting evidence for any decisive failure" in issue for issue in issues))

    def test_a_decisive_exclusion_alone_supports_an_exclude(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            {"inc_population": "not_reported", "inc_intervention": "not_reported", "exc_design": "yes"},
            {"exc_design": [{"field": "title", "quote": "Virtual reality simulation"}]},
            "exclude",
        )
        issues, _summary = validate(worksheet)
        self.assertEqual(issues, [])

    def test_missing_information_becomes_uncertain_never_exclude(self):
        for verdict in ("unclear", "not_reported"):
            with self.subTest(verdict=verdict):
                worksheet = worksheet_for()
                set_row(
                    worksheet["records"][0],
                    {"inc_population": "yes", "inc_intervention": verdict, "exc_design": "no"},
                    {"inc_population": TITLE_QUOTE},
                    "uncertain",
                )
                self.assertEqual(validate(worksheet)[0], [])

    def test_an_unresolved_required_criterion_cannot_be_recorded_as_exclude(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0],
            {"inc_population": "yes", "inc_intervention": "unclear", "exc_design": "no"},
            {"inc_population": TITLE_QUOTE},
            "exclude",
        )
        issues, _summary = validate(worksheet)
        self.assertTrue(any("entail 'uncertain'" in issue for issue in issues))

    def test_a_decision_contradicting_its_verdicts_is_rejected(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "exclude")
        issues, _summary = validate(worksheet)
        self.assertTrue(any("entail 'include'" in issue for issue in issues))

    def test_an_unassessed_criterion_is_rejected(self):
        worksheet = worksheet_for()
        row = set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include")
        row["assessments"] = [item for item in row["assessments"] if item["criterion_id"] != "exc_design"]
        issues, _summary = validate(worksheet)
        self.assertTrue(any("leaves criteria unassessed: exc_design" in issue for issue in issues))

    def test_every_decision_still_requires_a_reason(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include", reason="")
        issues, _summary = validate(worksheet)
        self.assertTrue(any("requires an eligibility_reason" in issue for issue in issues))


class DecisionProvenanceTests(unittest.TestCase):
    def test_decided_by_must_name_a_known_method(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include", decided_by="vibes")
        issues, _summary = validate(worksheet)
        self.assertTrue(any("decided_by must be one of" in issue for issue in issues))

    def test_all_four_decision_methods_are_accepted(self):
        for method in ("human", "model", "rule", "human_verified_model"):
            with self.subTest(method=method):
                worksheet = worksheet_for()
                set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include", decided_by=method)
                self.assertEqual(validate(worksheet)[0], [])

    def test_rule_only_decisions_are_reported(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include", decided_by="rule")
        _issues, summary = validate(worksheet)
        self.assertEqual(summary["rule_only_pmids"], ["12345678"])

    def test_an_adjudicated_rule_decision_is_not_rule_only(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include",
            decided_by="rule", adjudicated_by="human",
        )
        issues, summary = validate(worksheet)
        self.assertEqual(issues, [])
        self.assertEqual(summary["rule_only_pmids"], [])


class LedgerTests(unittest.TestCase):
    """A rule may triage; it may not be the final authority for evidence-bearing records."""

    def _ledger(self, decided_by, adjudicated_by=""):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include",
            decided_by=decided_by, adjudicated_by=adjudicated_by,
        )
        return screening.to_ledger(worksheet, rubric_for(), [RECORD])

    def test_a_reviewed_include_can_carry_evidence_roles(self):
        ledger = self._ledger("model")
        self.assertEqual(ledger["records"][0]["use"], "both")
        self.assertFalse(ledger["records"][0]["screening"]["rule_only"])
        self.assertEqual(candidate_ledger.validate_ledger(ledger)[0], [])

    def test_a_rule_only_include_is_demoted_to_heuristic(self):
        ledger = self._ledger("rule")
        self.assertEqual(ledger["records"][0]["use"], "heuristic")
        self.assertTrue(ledger["records"][0]["screening"]["rule_only"])
        self.assertEqual(candidate_ledger.validate_ledger(ledger)[0], [])

    def test_an_adjudicated_rule_include_regains_evidence_roles(self):
        ledger = self._ledger("rule", adjudicated_by="human")
        self.assertEqual(ledger["records"][0]["use"], "both")

    def test_forcing_a_rule_only_record_into_discovery_is_refused(self):
        ledger = self._ledger("rule")
        ledger["records"][0]["use"] = "discovery"
        issues, _summary = candidate_ledger.validate_ledger(ledger)
        self.assertTrue(any("decided by rule alone and cannot take discovery use" in issue for issue in issues))

    def test_evidence_roles_require_rubric_and_record_binding(self):
        ledger = self._ledger("model")
        ledger["records"][0]["screening"]["record_sha256"] = ""
        issues, _summary = candidate_ledger.validate_ledger(ledger)
        self.assertTrue(any("requires screening.record_sha256" in issue for issue in issues))

    def _agreement_artifact(self, flagged, rubric_sha=None):
        return {
            "operation": "screening-agreement",
            "rubric_sha256": rubric_sha or rubric_for()["rubric_sha256"],
            "compared_records": 4,
            "raw_agreement": 0.75,
            "cohen_kappa": 0.5,
            "confusion_matrix": {},
            "disagreements": [],
            "evidence_divergence": [],
            "adjudication_pmids": flagged,
        }

    def test_a_flagged_record_must_be_adjudicated_before_it_reaches_the_ledger(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include", decided_by="model")
        with self.assertRaises(screening.ScreeningError) as ctx:
            screening.to_ledger(
                worksheet, rubric_for(), [RECORD],
                agreement_artifact=self._agreement_artifact(["12345678"]),
            )
        self.assertIn("does not adjudicate", str(ctx.exception))

    def test_an_adjudicated_flagged_record_passes(self):
        worksheet = worksheet_for()
        set_row(
            worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include",
            decided_by="model", adjudicated_by="human",
        )
        ledger = screening.to_ledger(
            worksheet, rubric_for(), [RECORD],
            agreement_artifact=self._agreement_artifact(["12345678"]),
        )
        agreement = ledger["screening_provenance"]["agreement"]
        self.assertEqual(agreement["adjudicated_pmids"], ["12345678"])
        self.assertEqual(agreement["unresolved_adjudications"], [])
        self.assertEqual(agreement["coverage"], 4.0)

    def test_an_agreement_artifact_from_another_rubric_is_refused(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, INCLUDE_EVIDENCE, "include")
        with self.assertRaises(screening.ScreeningError):
            screening.to_ledger(
                worksheet, rubric_for(), [RECORD],
                agreement_artifact=self._agreement_artifact([], rubric_sha="0" * 64),
            )

    def test_an_invalid_worksheet_cannot_become_a_ledger(self):
        worksheet = worksheet_for()
        set_row(worksheet["records"][0], INCLUDE_VERDICTS, {}, "include")
        with self.assertRaises(screening.ScreeningError):
            screening.to_ledger(worksheet, rubric_for(), [RECORD])

    def test_ledgers_without_screening_provenance_still_validate(self):
        legacy = {
            "scope_version": 1,
            "records": [
                {
                    "pmid": "12345678", "provenance": "user-seed", "decision": "include", "use": "discovery",
                    "title_abstract_reviewed": True, "eligibility_reason": "in scope",
                }
            ],
        }
        issues, summary = candidate_ledger.validate_ledger(legacy)
        self.assertEqual(issues, [])
        # ...but the gap is reported rather than passing silently.
        provenance = summary["screening_provenance"]
        self.assertEqual(provenance["evidence_roles_without_screening_provenance"], ["12345678"])
        self.assertFalse(provenance["all_evidence_roles_screened_with_evidence"])


class AgreementTests(unittest.TestCase):
    def _screened(self, decisions):
        worksheet = worksheet_for()
        rows = []
        for index, decision in enumerate(decisions):
            row = copy.deepcopy(worksheet["records"][0])
            row["pmid"] = str(100000 + index)
            row["decision"] = decision
            rows.append(row)
        worksheet["records"] = rows
        return worksheet

    def test_the_sample_is_stratified_so_rare_decisions_are_checked(self):
        worksheet = self._screened(["exclude"] * 32 + ["include"] * 5 + ["uncertain"] * 3)
        sample = screening.stratified_sample(worksheet, fraction=0.15, seed="test")
        self.assertEqual(sample["stratum_totals"], {"exclude": 32, "include": 5, "uncertain": 3})
        # A simple random 15% of this set is very likely all excludes.
        for decision in ("include", "exclude", "uncertain"):
            self.assertTrue(sample["selected_by_decision"][decision], decision)

    def test_the_sample_is_deterministic(self):
        worksheet = self._screened(["exclude"] * 10 + ["include"] * 4)
        first = screening.stratified_sample(worksheet, fraction=0.5, seed="test")
        second = screening.stratified_sample(worksheet, fraction=0.5, seed="test")
        self.assertEqual(first["pmids"], second["pmids"])

    def test_agreement_reports_a_confusion_matrix_alongside_kappa(self):
        original = self._screened(["exclude"] * 8 + ["include"] * 2)
        replicate = self._screened(["exclude"] * 7 + ["include"] * 3)
        result = screening.agreement(original, replicate)
        self.assertEqual(result["compared_records"], 10)
        self.assertEqual(result["raw_agreement"], 0.9)
        self.assertIsNotNone(result["cohen_kappa"])
        self.assertEqual(result["confusion_matrix"]["exclude"]["include"], 1)
        self.assertTrue(result["adjudication_required"])
        self.assertEqual([item["pmid"] for item in result["disagreements"]], ["100007"])

    def test_perfect_agreement_needs_no_adjudication(self):
        worksheet = self._screened(["exclude"] * 5 + ["include"] * 5)
        result = screening.agreement(worksheet, copy.deepcopy(worksheet))
        self.assertEqual(result["raw_agreement"], 1.0)
        self.assertEqual(result["cohen_kappa"], 1.0)
        self.assertFalse(result["adjudication_required"])

    def test_agreement_on_the_decision_with_unrelated_evidence_is_flagged(self):
        """The gap verbatim checking cannot close: a real but irrelevant quotation."""
        def screened(field, quote):
            worksheet = worksheet_for()
            set_row(
                worksheet["records"][0],
                {"inc_population": "yes", "inc_intervention": "no", "exc_design": "no"},
                {"inc_intervention": [{"field": field, "quote": quote}]},
                "exclude",
            )
            return worksheet

        reader_a = screened("title", "Virtual reality simulation")
        reader_b = screened("abstract", "Undergraduate nursing students trained")
        # Each is individually valid: both quotations really are in the record.
        self.assertEqual(validate(reader_a)[0], [])
        self.assertEqual(validate(reader_b)[0], [])

        result = screening.agreement(reader_a, reader_b)
        self.assertEqual(result["raw_agreement"], 1.0)  # decision-level comparison sees nothing
        self.assertEqual(result["evidence_divergence"], [{"pmid": "12345678", "criteria": ["inc_intervention"]}])
        self.assertTrue(result["adjudication_required"])
        self.assertEqual(result["adjudication_pmids"], ["12345678"])

    def test_shared_evidence_is_not_flagged_as_divergent(self):
        def screened(quote):
            worksheet = worksheet_for()
            set_row(
                worksheet["records"][0],
                {"inc_population": "yes", "inc_intervention": "no", "exc_design": "no"},
                {"inc_intervention": [{"field": "abstract", "quote": quote}]},
                "exclude",
            )
            return worksheet

        result = screening.agreement(
            screened("immersive virtual reality module"), screened("an immersive virtual reality")
        )
        self.assertEqual(result["evidence_divergence"], [])
        self.assertFalse(result["adjudication_required"])

    def test_agreement_across_rubric_versions_is_refused(self):
        original = self._screened(["exclude"])
        replicate = self._screened(["exclude"])
        replicate["rubric_sha256"] = "0" * 64
        with self.assertRaises(screening.ScreeningError):
            screening.agreement(original, replicate)


if __name__ == "__main__":
    unittest.main()
