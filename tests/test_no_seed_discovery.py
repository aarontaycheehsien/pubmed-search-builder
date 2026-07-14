import importlib.util
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("no_seed_discovery_test", ROOT / "scripts" / "no_seed_discovery.py")
no_seed = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(no_seed)


class FakeClient:
    def metadata(self):
        return {"tool": "test"}


def pilots():
    return [{"type": pilot_type, "query": f"{index}[tiab]", "expand_links": False} for index, pilot_type in enumerate(sorted(no_seed.PILOT_TYPES), start=1)]


class NoSeedDiscoveryTests(unittest.TestCase):
    def test_candidate_template_supplies_protocol_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = Path(tmp) / "candidate_ledger_template_v1.json"
            template.write_text(
                json.dumps(
                    {
                        "artifact_type": "candidate-ledger-template",
                        "artifact_version": 1,
                        "protocol_id": "demo",
                        "scope_version": 1,
                        "dsl_version": 1,
                        "generated_from": {"path": "review_protocol_v1.json", "sha256": "abc"},
                        "ledger_status": "template",
                        "records": [],
                    }
                ),
                encoding="utf-8",
            )
            binding = no_seed.resolve_protocol_binding(None, str(template), 1)
        self.assertEqual(
            binding,
            {
                "protocol_id": "demo",
                "protocol_sha256": "abc",
                "dsl_version": 1,
                "protocol_path": "review_protocol_v1.json",
            },
        )

    def test_adjudicate_rejects_bound_inputs_without_binding_authority(self):
        with self.assertRaisesRegex(no_seed.NoSeedDiscoveryError, "require --protocol-file or --candidate-ledger-template"):
            no_seed.adjudicate(
                {
                    "operation": "orthogonal-pilot-screening",
                    "scope_version": 1,
                    "round": 1,
                    "provenance_blinded": True,
                    "protocol_id": "demo",
                    "records": [],
                },
                {
                    "operation": "orthogonal-pilot-provenance",
                    "scope_version": 1,
                    "round": 1,
                    "protocol_id": "demo",
                    "records": [],
                },
                previous_state=None,
                scope_version=1,
                required_saturated_rounds=2,
                allocation_seed="test",
            )

    def test_discovery_merges_pilots_and_blinds_per_record_provenance(self):
        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            pmid = str(int(query.split("[")[0]) % 2 + 1)
            return {"count": 1, "pmids": [pmid]}

        records = [
            {"pmid": "1", "title": "One", "abstract": "", "year": "2020", "mesh_headings": [], "keywords": []},
            {"pmid": "2", "title": "Two", "abstract": "", "year": "2021", "mesh_headings": [], "keywords": []},
        ]
        with (
            mock.patch.object(no_seed.pubmed_tool, "esearch", side_effect=fake_search),
            mock.patch.object(no_seed.pubmed_tool, "efetch", return_value={"records": records}),
        ):
            screening, provenance = no_seed.discover(
                FakeClient(), pilots(), scope_version=1, round_number=1, previous_state=None, safety_cap_per_pilot=50
            )
        self.assertTrue(screening["provenance_blinded"])
        self.assertEqual(len(screening["records"]), 2)
        self.assertNotIn("pilot_types", screening["records"][0])
        self.assertEqual(set(provenance["pilot_types"]), no_seed.PILOT_TYPES)
        self.assertTrue(all(item["pilot_types"] for item in provenance["records"]))

    def test_saturation_requires_repeated_zero_study_and_vocabulary_novelty_then_freezes_ledger(self):
        candidate_id = no_seed.blind_id(1, "1")
        screening = {
            "operation": "orthogonal-pilot-screening",
            "scope_version": 1,
            "round": 1,
            "provenance_blinded": True,
            "records": [
                {
                    "candidate_id": candidate_id,
                    "pmid": "1",
                    "title": "Novel allocation method",
                    "abstract": "Operational description",
                    "year": "2020",
                    "mesh_headings": [{"name": "Random Allocation"}],
                    "keywords": ["allocation"],
                    "decision": "include",
                    "title_abstract_reviewed": True,
                    "eligibility_reason": "Matches locked scope",
                }
            ],
        }
        provenance = {
            "operation": "orthogonal-pilot-provenance",
            "scope_version": 1,
            "round": 1,
            "pilot_types": sorted(no_seed.PILOT_TYPES),
            "safety_cap_reached": False,
            "records": [{"candidate_id": candidate_id, "pmid": "1", "pilot_types": ["mesh-led"], "pilot_labels": ["mesh"]}],
        }
        state1, ledger1 = no_seed.adjudicate(
            screening, provenance, previous_state=None, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertFalse(state1["saturation_reached"])
        self.assertIsNone(ledger1)
        empty_screening = {**screening, "round": 2, "records": []}
        empty_provenance = {**provenance, "round": 2, "records": []}
        state2, ledger2 = no_seed.adjudicate(
            empty_screening, empty_provenance, previous_state=state1, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertFalse(state2["saturation_reached"])
        self.assertIsNone(ledger2)
        state3, ledger3 = no_seed.adjudicate(
            {**empty_screening, "round": 3}, {**empty_provenance, "round": 3}, previous_state=state2, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertTrue(state3["saturation_reached"])
        self.assertTrue(state3["ledger_frozen"])
        self.assertIsNotNone(ledger3)
        self.assertEqual(ledger3["records"][0]["use"], "both")

    def test_reached_safety_cap_blocks_false_saturation(self):
        state, ledger = no_seed.adjudicate(
            {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 2, "provenance_blinded": True, "records": []},
            {"operation": "orthogonal-pilot-provenance", "scope_version": 1, "round": 2, "records": [], "safety_cap_reached": True},
            previous_state={"operation": "orthogonal-pilot-adjudication", "ok": True, "scope_version": 1, "round": 1, "consecutive_saturated_rounds": 1, "seen_pmids": [], "included_pmids": [], "vocabulary_terms": [], "adjudicated_records": []},
            scope_version=1,
            required_saturated_rounds=2,
            allocation_seed="test",
        )
        self.assertFalse(state["saturation_reached"])
        self.assertTrue(state["safety_cap_reached_any"])
        self.assertIsNone(ledger)


def _empty_saturating_round():
    """A round that reaches novelty saturation with an empty screened-in set."""
    screening = {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 2, "provenance_blinded": True, "records": []}
    provenance = {"operation": "orthogonal-pilot-provenance", "scope_version": 1, "round": 2, "records": [], "safety_cap_reached": False}
    previous = {
        "operation": "orthogonal-pilot-adjudication",
        "ok": True,
        "scope_version": 1,
        "round": 1,
        "consecutive_saturated_rounds": 1,
        "seen_pmids": [],
        "included_pmids": [],
        "vocabulary_terms": [],
        "adjudicated_records": [],
    }
    return screening, provenance, previous


class VolumeDiscriminationGateTests(unittest.TestCase):
    def test_classify_topic_volume_boundaries(self):
        self.assertEqual(no_seed.classify_topic_volume(500, sparse_ceiling=500, bottleneck_floor=1000), "genuinely-sparse")
        self.assertEqual(no_seed.classify_topic_volume(750, sparse_ceiling=500, bottleneck_floor=1000), "indeterminate")
        self.assertEqual(no_seed.classify_topic_volume(1000, sparse_ceiling=500, bottleneck_floor=1000), "discovery-bottleneck")

    def test_empty_saturation_without_discrimination_is_blocked(self):
        screening, provenance, previous = _empty_saturating_round()
        state, ledger = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertTrue(state["novelty_saturation_reached"])
        self.assertFalse(state["saturation_reached"])
        self.assertEqual(state["saturation_gate"]["verdict"], "pending-discrimination")
        self.assertIsNone(ledger)

    def test_empty_saturation_with_bottleneck_verdict_is_blocked(self):
        screening, provenance, previous = _empty_saturating_round()
        discrimination = {"operation": "orthogonal-pilot-discrimination", "ok": True, "scope_version": 1, "discriminating_volume": 5000, "discriminating_basis": "topic-core"}
        state, ledger = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2,
            allocation_seed="test", discrimination=discrimination,
        )
        self.assertFalse(state["saturation_reached"])
        self.assertEqual(state["saturation_gate"]["verdict"], "discovery-bottleneck")
        self.assertIn("required_action", state["saturation_gate"])
        self.assertIsNone(ledger)

    def test_gate_downgrades_proxy_bottleneck_to_indeterminate(self):
        # The binding gate must respect basis too: a large single-concept proxy blocks
        # saturation as indeterminate, not as an over-confident discovery-bottleneck.
        screening, provenance, previous = _empty_saturating_round()
        discrimination = {"operation": "orthogonal-pilot-discrimination", "ok": True, "scope_version": 1, "discriminating_volume": 5000, "discriminating_basis": "single-concept-proxy"}
        state, ledger = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2,
            allocation_seed="test", discrimination=discrimination,
        )
        self.assertFalse(state["saturation_reached"])
        self.assertEqual(state["saturation_gate"]["verdict"], "indeterminate")
        self.assertEqual(state["saturation_gate"]["user_decision"]["verdict"], "indeterminate")
        self.assertIsNone(ledger)

    def test_empty_saturation_with_sparse_verdict_is_accepted(self):
        screening, provenance, previous = _empty_saturating_round()
        discrimination = {"operation": "orthogonal-pilot-discrimination", "ok": True, "scope_version": 1, "discriminating_volume": 80, "discriminating_basis": "topic-core"}
        state, ledger = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2,
            allocation_seed="test", discrimination=discrimination,
        )
        self.assertTrue(state["saturation_reached"])
        self.assertEqual(state["saturation_gate"]["verdict"], "genuinely-sparse")
        self.assertIn("genuinely-sparse", state["stop_reason"])
        self.assertIsNone(ledger)

    def test_discrimination_scope_version_mismatch_raises(self):
        screening, provenance, previous = _empty_saturating_round()
        discrimination = {"scope_version": 2, "discriminating_volume": 80}
        with self.assertRaises(no_seed.NoSeedDiscoveryError):
            no_seed.adjudicate(
                screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2,
                allocation_seed="test", discrimination=discrimination,
            )

    def test_single_included_record_still_freezes_without_discrimination(self):
        # A non-empty screened-in set is below neither the default floor nor the gate;
        # the small-set (role "both") freeze path is preserved unchanged.
        candidate_id = no_seed.blind_id(1, "1")
        record = {
            "candidate_id": candidate_id, "pmid": "1", "title": "One", "abstract": "",
            "year": "2020", "mesh_headings": [], "keywords": [],
            "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "scope",
        }
        screening = {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 3, "provenance_blinded": True, "records": [record]}
        provenance = {"operation": "orthogonal-pilot-provenance", "scope_version": 1, "round": 3, "records": [{"candidate_id": candidate_id, "pmid": "1", "pilot_types": ["mesh-led"], "pilot_labels": ["mesh"]}], "safety_cap_reached": False}
        previous = {"operation": "orthogonal-pilot-adjudication", "ok": True, "scope_version": 1, "round": 2, "consecutive_saturated_rounds": 2, "seen_pmids": ["1"], "included_pmids": ["1"], "vocabulary_terms": [], "adjudicated_records": []}
        state, ledger = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertTrue(state["saturation_reached"])
        self.assertTrue(state["ledger_frozen"])
        self.assertEqual(state["saturation_gate"]["verdict"], "not-applicable")
        self.assertIsNotNone(ledger)


class UserDecisionTests(unittest.TestCase):
    def test_bottleneck_recommends_repair_and_flags_accept(self):
        decision = no_seed.build_user_decision(
            verdict="discovery-bottleneck", screened_in_count=0, discriminating_volume=193628,
            discriminating_basis="topic-core", consecutive_rounds=2,
        )
        self.assertEqual(decision["recommended_option"], "repair-pilots")
        by_id = {opt["id"]: opt for opt in decision["options"]}
        self.assertTrue(by_id["repair-pilots"]["recommended"])
        self.assertFalse(by_id["accept-unvalidated"]["recommended"])
        self.assertIn("not_recommended_reason", by_id["accept-unvalidated"])
        # Every verdict must always offer the seed and adjacent-review routes.
        self.assertIn("supply-seeds", by_id)
        self.assertIn("name-adjacent-reviews", by_id)

    def test_sparse_recommends_accepting_unvalidated(self):
        decision = no_seed.build_user_decision(
            verdict="genuinely-sparse", screened_in_count=0, discriminating_volume=80,
            discriminating_basis="topic-core", consecutive_rounds=2,
        )
        self.assertEqual(decision["recommended_option"], "accept-unvalidated")
        by_id = {opt["id"]: opt for opt in decision["options"]}
        self.assertTrue(by_id["accept-unvalidated"]["recommended"])

    def test_pending_recommends_measuring_volume(self):
        decision = no_seed.build_user_decision(
            verdict="pending-discrimination", screened_in_count=0, discriminating_volume=None,
            discriminating_basis=None, consecutive_rounds=2,
        )
        self.assertEqual(decision["recommended_option"], "measure-volume")
        text = no_seed.render_user_decision_text(decision)
        self.assertIn("unmeasured", text)
        self.assertIn("[recommended]", text)

    def test_adjudicate_attaches_user_decision_on_empty_saturation(self):
        screening, provenance, previous = _empty_saturating_round()
        state, _ = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        gate = state["saturation_gate"]
        self.assertIn("user_decision", gate)
        self.assertIn("user_decision_text", gate)
        self.assertEqual(gate["user_decision"]["verdict"], "pending-discrimination")

    def test_single_included_record_has_no_user_decision(self):
        candidate_id = no_seed.blind_id(1, "1")
        record = {
            "candidate_id": candidate_id, "pmid": "1", "title": "One", "abstract": "",
            "year": "2020", "mesh_headings": [], "keywords": [],
            "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "scope",
        }
        screening = {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 3, "provenance_blinded": True, "records": [record]}
        provenance = {"operation": "orthogonal-pilot-provenance", "scope_version": 1, "round": 3, "records": [{"candidate_id": candidate_id, "pmid": "1", "pilot_types": ["mesh-led"], "pilot_labels": ["mesh"]}], "safety_cap_reached": False}
        previous = {"operation": "orthogonal-pilot-adjudication", "ok": True, "scope_version": 1, "round": 2, "consecutive_saturated_rounds": 2, "seen_pmids": ["1"], "included_pmids": ["1"], "vocabulary_terms": [], "adjudicated_records": []}
        state, _ = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertNotIn("user_decision", state["saturation_gate"])


class DiscriminateTests(unittest.TestCase):
    def test_topic_core_probe_drives_high_confidence_verdict(self):
        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 12000 if "core" in query else 999999, "pmids": []}

        probes = [
            {"label": "core", "role": "topic-core", "query": "core[tiab]"},
            {"label": "broad", "role": "essential-concept", "query": "broad[tiab]"},
        ]
        with mock.patch.object(no_seed.pubmed_tool, "esearch", side_effect=fake_search):
            artifact = no_seed.discriminate(FakeClient(), probes, scope_version=1, sparse_ceiling=500, bottleneck_floor=1000)
        self.assertEqual(artifact["discriminating_basis"], "topic-core")
        self.assertEqual(artifact["discriminating_volume"], 12000)
        self.assertEqual(artifact["provisional_verdict"], "discovery-bottleneck")
        self.assertEqual(artifact["verdict_confidence"], "high")

    def test_disagreeing_topic_core_renderings_take_the_generous_max(self):
        # Two vocabulary renderings of the same essential-AND disagree: a narrow one
        # returns 150, a broader one 2200. min() would read 150 -> genuinely-sparse
        # and accept an empty screened-in set; max() reads 2200 -> discovery-bottleneck
        # and blocks, so one narrow rendering cannot force the risky accept.
        counts = {"narrow[tiab]": 150, "broad[tiab]": 2200}

        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            return {"count": counts[query], "pmids": []}

        probes = [
            {"label": "narrow", "role": "topic-core", "query": "narrow[tiab]"},
            {"label": "broad", "role": "topic-core", "query": "broad[tiab]"},
        ]
        with mock.patch.object(no_seed.pubmed_tool, "esearch", side_effect=fake_search):
            artifact = no_seed.discriminate(FakeClient(), probes, scope_version=1, sparse_ceiling=500, bottleneck_floor=1000)
        self.assertEqual(artifact["discriminating_volume"], 2200)
        self.assertEqual(artifact["provisional_verdict"], "discovery-bottleneck")
        self.assertEqual(artifact["topic_core_volume_range"], {"min": 150, "max": 2200})
        self.assertEqual(artifact["verdict_confidence"], "high")

    def test_all_small_topic_core_renderings_stay_genuinely_sparse(self):
        # When even the most generous rendering is below the ceiling, the sparse
        # verdict is still reachable -- the fix does not just always block.
        counts = {"a[tiab]": 150, "b[tiab]": 300}

        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            return {"count": counts[query], "pmids": []}

        probes = [
            {"label": "a", "role": "topic-core", "query": "a[tiab]"},
            {"label": "b", "role": "topic-core", "query": "b[tiab]"},
        ]
        with mock.patch.object(no_seed.pubmed_tool, "esearch", side_effect=fake_search):
            artifact = no_seed.discriminate(FakeClient(), probes, scope_version=1, sparse_ceiling=500, bottleneck_floor=1000)
        self.assertEqual(artifact["discriminating_volume"], 300)
        self.assertEqual(artifact["provisional_verdict"], "genuinely-sparse")

    def test_essential_only_probes_are_low_confidence_proxy(self):
        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 40, "pmids": []}

        probes = [{"label": "c", "role": "essential-concept", "query": "c[tiab]"}]
        with mock.patch.object(no_seed.pubmed_tool, "esearch", side_effect=fake_search):
            artifact = no_seed.discriminate(FakeClient(), probes, scope_version=1, sparse_ceiling=500, bottleneck_floor=1000)
        self.assertEqual(artifact["discriminating_basis"], "single-concept-proxy")
        self.assertEqual(artifact["provisional_verdict"], "genuinely-sparse")
        self.assertEqual(artifact["verdict_confidence"], "low")

    def test_essential_proxy_above_floor_is_indeterminate_not_bottleneck(self):
        # A single large essential concept is an upper bound on the AND core, which
        # could still be tiny; the proxy must not confirm a bottleneck on its own.
        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 50000, "pmids": []}

        probes = [{"label": "c", "role": "essential-concept", "query": "c[tiab]"}]
        with mock.patch.object(no_seed.pubmed_tool, "esearch", side_effect=fake_search):
            artifact = no_seed.discriminate(FakeClient(), probes, scope_version=1, sparse_ceiling=500, bottleneck_floor=1000)
        self.assertEqual(artifact["discriminating_basis"], "single-concept-proxy")
        self.assertEqual(artifact["provisional_verdict"], "indeterminate")

    def test_classify_discrimination_verdict_caps_proxy_bottleneck(self):
        # topic-core keeps all three verdicts; proxy above the floor is capped.
        self.assertEqual(
            no_seed.classify_discrimination_verdict(5000, "topic-core", sparse_ceiling=500, bottleneck_floor=1000),
            "discovery-bottleneck",
        )
        self.assertEqual(
            no_seed.classify_discrimination_verdict(5000, "single-concept-proxy", sparse_ceiling=500, bottleneck_floor=1000),
            "indeterminate",
        )
        self.assertEqual(
            no_seed.classify_discrimination_verdict(80, "single-concept-proxy", sparse_ceiling=500, bottleneck_floor=1000),
            "genuinely-sparse",
        )


FAMILY_POOL = sorted(no_seed.PILOT_TYPES)


def _provenance(spec):
    """Build a provenance map from a list of (num_records, num_families) groups.

    Each record in a group is captured by ``num_families`` distinct pilot families
    (rotated through the pool so doubletons/triples use different family pairs).
    """
    records = []
    pmid = 1
    for group_index, (count, families) in enumerate(spec):
        for _ in range(count):
            fams = [FAMILY_POOL[(group_index + offset) % len(FAMILY_POOL)] for offset in range(families)]
            records.append({"pmid": str(pmid), "candidate_id": f"c{pmid}", "pilot_types": fams})
            pmid += 1
    included = [str(index) for index in range(1, pmid)]
    return {"scope_version": 1, "records": records, "safety_cap_reached": False}, included


class InternalConvergenceTests(unittest.TestCase):
    def test_reports_overlap_without_population_estimate(self):
        provenance, included = _provenance([(10, 1), (5, 2), (5, 3)])
        result = no_seed.internal_convergence_diagnostic(included, provenance)
        self.assertEqual(result["screened_in_observed"], 20)
        self.assertEqual((result["f1_singletons"], result["f2_doubletons"]), (10, 5))
        self.assertEqual(result["diagnostic_type"], "internal-convergence-not-capture-recapture")
        self.assertFalse(result["independence_assumption_met"])
        self.assertIsNone(result["formal_population_estimate"])
        self.assertEqual(result["unique_family_yield"], 0.5)
        self.assertEqual(result["convergence_score"], 0.5)
        self.assertNotIn("completeness", result)
        self.assertEqual(result["decision_thresholds"], {
            "min_screened_in_for_estimate": 5,
            "min_screened_in_for_firm_verdict": 15,
            "converged_convergence_score_at_or_above": 0.85,
            "recall_risk_convergence_score_below": 0.60,
        })

    def test_custom_overlap_threshold_changes_verdict_and_is_recorded(self):
        provenance, included = _provenance([(10, 1), (5, 2), (5, 3)])
        result = no_seed.internal_convergence_diagnostic(
            included,
            provenance,
            undersaturated_completeness=0.40,
        )
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["decision_thresholds"]["recall_risk_convergence_score_below"], 0.40)

    def test_adjudicate_parser_exposes_convergence_thresholds(self):
        args = no_seed.build_parser().parse_args([
            "adjudicate",
            "--screening-file", "screening.json",
            "--provenance-file", "provenance.json",
            "--scope-version", "1",
            "--state-output", "state.json",
            "--ledger-output", "ledger.json",
            "--min-screened-in-for-estimate", "7",
            "--min-screened-in-for-firm-verdict", "21",
            "--converged-completeness", "0.9",
            "--undersaturated-completeness", "0.5",
        ])
        self.assertEqual(args.min_screened_in_for_estimate, 7)
        self.assertEqual(args.min_screened_in_for_firm_verdict, 21)
        self.assertEqual(args.converged_completeness, 0.9)
        self.assertEqual(args.undersaturated_completeness, 0.5)

    def test_cli_adjudicate_applies_and_records_custom_convergence_thresholds(self):
        import json
        import tempfile

        provenance, included = _provenance([(10, 1), (5, 2), (5, 3)])
        screening_records = []
        provenance_records = []
        for pmid in included:
            candidate_id = no_seed.blind_id(1, pmid)
            screening_records.append({
                "candidate_id": candidate_id,
                "pmid": pmid,
                "title": "t",
                "abstract": "",
                "year": "2020",
                "mesh_headings": [],
                "keywords": [],
                "decision": "include",
                "title_abstract_reviewed": True,
                "eligibility_reason": "in scope",
            })
            families = next(row["pilot_types"] for row in provenance["records"] if row["pmid"] == pmid)
            provenance_records.append({
                "candidate_id": candidate_id,
                "pmid": pmid,
                "pilot_types": families,
                "pilot_labels": families,
            })
        screening = {
            "operation": "orthogonal-pilot-screening",
            "scope_version": 1,
            "round": 1,
            "provenance_blinded": True,
            "records": screening_records,
        }
        provenance_artifact = {
            "operation": "orthogonal-pilot-provenance",
            "scope_version": 1,
            "round": 1,
            "safety_cap_reached": False,
            "records": provenance_records,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screening_path = root / "screening.json"
            provenance_path = root / "provenance.json"
            state_path = root / "state.json"
            ledger_path = root / "ledger.json"
            screening_path.write_text(json.dumps(screening), encoding="utf-8")
            provenance_path.write_text(json.dumps(provenance_artifact), encoding="utf-8")
            code = no_seed.main([
                "adjudicate",
                "--screening-file", str(screening_path),
                "--provenance-file", str(provenance_path),
                "--scope-version", "1",
                "--state-output", str(state_path),
                "--ledger-output", str(ledger_path),
                "--undersaturated-completeness", "0.4",
            ])

            self.assertEqual(code, 0)
            diagnostic = json.loads(state_path.read_text(encoding="utf-8"))["internal_convergence_diagnostic"]
            self.assertEqual(diagnostic["verdict"], "indeterminate")
            self.assertEqual(diagnostic["decision_thresholds"]["recall_risk_convergence_score_below"], 0.4)

    def test_low_overlap_is_recall_risk_signal(self):
        provenance, included = _provenance([(18, 1), (2, 2)])
        result = no_seed.internal_convergence_diagnostic(included, provenance)
        self.assertEqual(result["verdict"], "recall-risk")
        self.assertLess(result["convergence_score"], 0.60)
        self.assertIn("recall-risk signal", result["interpretation"])

    def test_high_overlap_is_converged_weak_positive(self):
        provenance, included = _provenance([(2, 1), (10, 2), (8, 3)])
        result = no_seed.internal_convergence_diagnostic(included, provenance)
        self.assertEqual(result["verdict"], "converged")
        self.assertGreaterEqual(result["convergence_score"], 0.85)
        self.assertIn("weak", result["interpretation"])

    def test_too_few_screened_in_stays_indeterminate_without_estimate(self):
        provenance, included = _provenance([(2, 1), (1, 2)])
        result = no_seed.internal_convergence_diagnostic(included, provenance)
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["reason"], "too-few-screened-in")
        self.assertIsNone(result["formal_population_estimate"])

    def test_no_recaptures_is_recall_risk_without_estimate(self):
        provenance, included = _provenance([(8, 1)])
        result = no_seed.internal_convergence_diagnostic(included, provenance)
        self.assertEqual(result["verdict"], "recall-risk")
        self.assertEqual(result["reason"], "no-recaptures")
        self.assertIsNone(result["formal_population_estimate"])
        self.assertEqual(result["unique_family_yield"], 1.0)

    def test_indicative_confidence_below_firm_verdict_floor(self):
        provenance, included = _provenance([(2, 1), (5, 2)])
        result = no_seed.internal_convergence_diagnostic(included, provenance)
        self.assertEqual(result["confidence"], "indicative")
        self.assertEqual(result["reason"], "below-firm-verdict-floor")

    def test_jaccard_and_per_family_counts_populated(self):
        provenance, included = _provenance([(4, 1), (6, 2)])
        result = no_seed.internal_convergence_diagnostic(included, provenance)
        self.assertTrue(result["per_family_capture_counts"])
        self.assertTrue(result["pairwise_jaccard"])
        self.assertIsNotNone(result["mean_pairwise_jaccard"])

    def test_adjudicate_attaches_diagnostic_and_recall_risk(self):
        provenance, included = _provenance([(18, 1), (2, 2)])
        # Build a screening/provenance pair that adjudicates these as included.
        screening_records = []
        prov_records = []
        for pmid in included:
            cid = no_seed.blind_id(1, pmid)
            screening_records.append({
                "candidate_id": cid, "pmid": pmid, "title": "t", "abstract": "", "year": "2020",
                "mesh_headings": [], "keywords": [], "decision": "include",
                "title_abstract_reviewed": True, "eligibility_reason": "in scope",
            })
            fams = next(r["pilot_types"] for r in provenance["records"] if r["pmid"] == pmid)
            prov_records.append({"candidate_id": cid, "pmid": pmid, "pilot_types": fams, "pilot_labels": fams})
        screening = {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 1,
                     "provenance_blinded": True, "records": screening_records}
        prov = {"operation": "orthogonal-pilot-provenance", "scope_version": 1, "round": 1, "pilot_types": sorted(no_seed.PILOT_TYPES),
                "safety_cap_reached": False, "records": prov_records}
        state, _ = no_seed.adjudicate(
            screening, prov, previous_state=None, scope_version=1,
            required_saturated_rounds=2, allocation_seed="test",
        )
        self.assertIn("internal_convergence_diagnostic", state)
        self.assertEqual(state["internal_convergence_diagnostic"]["verdict"], "recall-risk")
        self.assertTrue(state["recall_risk"]["critic_must_clear"])

    def _adjudicate_round_one(self, spec):
        """Adjudicate a single round that screens in every record in ``spec``."""
        provenance, included = _provenance(spec)
        screening_records, prov_records = [], []
        for pmid in included:
            cid = no_seed.blind_id(1, pmid)
            screening_records.append({
                "candidate_id": cid, "pmid": pmid, "title": "t", "abstract": "", "year": "2020",
                "mesh_headings": [], "keywords": [], "decision": "include",
                "title_abstract_reviewed": True, "eligibility_reason": "in scope",
            })
            fams = next(r["pilot_types"] for r in provenance["records"] if r["pmid"] == pmid)
            prov_records.append({"candidate_id": cid, "pmid": pmid, "pilot_types": fams, "pilot_labels": fams})
        screening = {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 1,
                     "provenance_blinded": True, "records": screening_records}
        prov = {"operation": "orthogonal-pilot-provenance", "scope_version": 1, "round": 1, "safety_cap_reached": False, "records": prov_records}
        return no_seed.adjudicate(
            screening, prov, previous_state=None, scope_version=1,
            required_saturated_rounds=2, allocation_seed="test",
        )

    def test_convergence_diagnostic_survives_empty_saturation_round(self):
        # Round 1 screens in 20 records (18 singletons, 2 doubletons -> recall-risk).
        state1, _ = self._adjudicate_round_one([(18, 1), (2, 2)])
        self.assertEqual(state1["internal_convergence_diagnostic"]["screened_in_observed"], 20)

        # Round 2 discovers nothing new, so its provenance file is empty. Before the
        # accumulated-provenance fix the diagnostic collapsed to zero observations
        # here (the exact round whose state freezes the ledger). It must still see
        # all 20 accumulated screened-in records and keep the recall-risk signal.
        empty_screening = {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 2,
                           "provenance_blinded": True, "records": []}
        empty_prov = {"operation": "orthogonal-pilot-provenance", "scope_version": 1, "round": 2, "safety_cap_reached": False, "records": []}
        state2, _ = no_seed.adjudicate(
            empty_screening, empty_prov, previous_state=state1, scope_version=1,
            required_saturated_rounds=2, allocation_seed="test",
        )
        diagnostic = state2["internal_convergence_diagnostic"]
        self.assertEqual(diagnostic["screened_in_observed"], 20)
        self.assertEqual(diagnostic["verdict"], "recall-risk")
        self.assertTrue(state2["recall_risk"]["critic_must_clear"])

    def test_cli_recapture_round_trip(self):
        import json
        import tempfile

        provenance, included = _provenance([(10, 1), (5, 2), (5, 3)])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prov_path = root / "prov.json"
            state_path = root / "state.json"
            out_path = root / "recapture.json"
            prov_path.write_text(json.dumps(provenance), encoding="utf-8")
            state_path.write_text(json.dumps({"scope_version": 1, "included_pmids": included}), encoding="utf-8")
            code = no_seed.main([
                "recapture", "--provenance-file", str(prov_path), "--state-file", str(state_path),
                "--scope-version", "1", "--output", str(out_path),
            ])
            self.assertEqual(code, 0)
            artifact = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["operation"], "internal-convergence-diagnostic")
            self.assertIsNone(artifact["formal_population_estimate"])
            self.assertNotIn("completeness", artifact)


class PriorReviewBenchmarkTests(unittest.TestCase):
    def test_harvest_merges_sources_excludes_reviews_and_blinds(self):
        def fake_related(client, seeds, links, max_per_seed, max_total):
            # Review 100 cites 3, 4, and (spuriously) itself.
            return {"candidate_pmids": [{"pmid": "3"}, {"pmid": "4"}, {"pmid": "100"}], "candidate_count_before_cap": 3}

        records = [{"pmid": p, "title": f"t{p}", "abstract": "", "year": "2020", "mesh_headings": [], "keywords": []} for p in ["1", "2", "3", "4"]]
        with (
            mock.patch.object(no_seed.pubmed_tool, "related_pmids", side_effect=fake_related),
            mock.patch.object(no_seed.pubmed_tool, "efetch", return_value={"records": records}),
        ):
            screening, provenance = no_seed.harvest_benchmark(
                FakeClient(), review_pmids=["100"], included_pmids=["1", "2"],
                scope_version=1, safety_cap=500, max_per_review=200,
            )
        pmids = [r["pmid"] for r in screening["records"]]
        self.assertEqual(pmids, ["1", "2", "3", "4"])  # review 100 excluded
        self.assertNotIn("100", pmids)
        self.assertNotIn("pilot_types", screening["records"][0])
        self.assertTrue(all(r["title_abstract_reviewed"] is False for r in screening["records"]))
        by_pmid = {r["pmid"]: r["benchmark_sources"] for r in provenance["records"]}
        self.assertEqual(by_pmid["1"], ["included-study-list"])
        self.assertEqual(by_pmid["3"], ["prior-review-refs"])

    def _screened(self):
        return {
            "operation": "prior-review-benchmark-screening",
            "scope_version": 1,
            "source_reviews": ["100"],
            "records": [
                {"pmid": "1", "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
                {"pmid": "2", "decision": "exclude", "title_abstract_reviewed": True, "eligibility_reason": "wrong population"},
                {"pmid": "3", "decision": "include", "title_abstract_reviewed": True, "eligibility_reason": "in scope"},
            ],
        }

    def test_freeze_screened_keeps_only_included_and_labels_semi_independent(self):
        artifact = no_seed.freeze_benchmark(self._screened(), scope_version=1, screened=True)
        self.assertEqual(artifact["pmids"], ["1", "3"])
        self.assertEqual(artifact["benchmark_status"], "screened")
        self.assertEqual(artifact["confidence"], "semi-independent")
        self.assertEqual(artifact["benchmark_source_label"], "prior-review-semi-independent")
        self.assertEqual(artifact["benchmark_size"], 2)

    def test_freeze_preserves_benchmark_source_quality_tiers(self):
        provenance = {
            "records": [
                {"pmid": "1", "source_evidence": [{"source": "included-study-list", "source_tier": "declared-included-study-list"}]},
                {"pmid": "3", "source_evidence": [{"source": "prior-review-refs", "source_tier": "screened-cited-reference"}]},
            ]
        }
        artifact = no_seed.freeze_benchmark(self._screened(), scope_version=1, screened=True, provenance=provenance)
        self.assertEqual(artifact["benchmark_kind"], "screened-citation-benchmark")
        self.assertEqual(artifact["source_tier_counts"], {"declared-included-study-list": 1, "screened-cited-reference": 1})
        self.assertEqual(artifact["source_evidence"]["1"][0]["source_tier"], "declared-included-study-list")

    def test_freeze_screened_rejects_unreviewed_record(self):
        screening = self._screened()
        screening["records"][0]["title_abstract_reviewed"] = False
        with self.assertRaises(no_seed.NoSeedDiscoveryError):
            no_seed.freeze_benchmark(screening, scope_version=1, screened=True)

    def test_freeze_unscreened_keeps_all_as_indicative(self):
        screening = self._screened()
        for record in screening["records"]:  # unscreened path ignores decisions
            record["decision"] = ""
            record["title_abstract_reviewed"] = False
        artifact = no_seed.freeze_benchmark(screening, scope_version=1, screened=False)
        self.assertEqual(artifact["pmids"], ["1", "2", "3"])
        self.assertEqual(artifact["confidence"], "indicative")
        self.assertEqual(artifact["benchmark_status"], "unscreened")

    def test_freeze_scope_mismatch_raises(self):
        with self.assertRaises(no_seed.NoSeedDiscoveryError):
            no_seed.freeze_benchmark(self._screened(), scope_version=2, screened=True)

    def test_frozen_artifact_feeds_extract_benchmark_pmids(self):
        artifact = no_seed.freeze_benchmark(self._screened(), scope_version=1, screened=True)
        pmids = no_seed.pubmed_tool.extract_benchmark_pmids(artifact, min_seed_overlap=0)
        self.assertEqual(pmids, ["1", "3"])

    def test_cli_freeze_round_trip_and_harvest_requires_a_source(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screening_path = root / "bench_screening.json"
            out_path = root / "benchmark.json"
            screening_path.write_text(json.dumps(self._screened()), encoding="utf-8")
            code = no_seed.main([
                "benchmark-freeze", "--screening-file", str(screening_path),
                "--scope-version", "1", "--output", str(out_path),
            ])
            self.assertEqual(code, 0)
            artifact = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["pmids"], ["1", "3"])
            # harvest with neither source is rejected before any network call.
            code = no_seed.main([
                "benchmark-harvest", "--scope-version", "1",
                "--screening-output", str(root / "s.json"), "--provenance-output", str(root / "p.json"),
            ])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
