import importlib.util
import sys
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
            "scope_version": 1,
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
        empty_provenance = {**provenance, "records": []}
        state2, ledger2 = no_seed.adjudicate(
            empty_screening, empty_provenance, previous_state=state1, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertFalse(state2["saturation_reached"])
        self.assertIsNone(ledger2)
        state3, ledger3 = no_seed.adjudicate(
            {**empty_screening, "round": 3}, empty_provenance, previous_state=state2, scope_version=1, required_saturated_rounds=2, allocation_seed="test"
        )
        self.assertTrue(state3["saturation_reached"])
        self.assertTrue(state3["ledger_frozen"])
        self.assertIsNotNone(ledger3)
        self.assertEqual(ledger3["records"][0]["use"], "both")

    def test_reached_safety_cap_blocks_false_saturation(self):
        state, ledger = no_seed.adjudicate(
            {"operation": "orthogonal-pilot-screening", "scope_version": 1, "round": 2, "provenance_blinded": True, "records": []},
            {"scope_version": 1, "records": [], "safety_cap_reached": True},
            previous_state={"consecutive_saturated_rounds": 1, "seen_pmids": [], "included_pmids": [], "vocabulary_terms": [], "adjudicated_records": []},
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
    provenance = {"scope_version": 1, "records": [], "safety_cap_reached": False}
    previous = {
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
        discrimination = {"scope_version": 1, "discriminating_volume": 5000, "discriminating_basis": "topic-core"}
        state, ledger = no_seed.adjudicate(
            screening, provenance, previous_state=previous, scope_version=1, required_saturated_rounds=2,
            allocation_seed="test", discrimination=discrimination,
        )
        self.assertFalse(state["saturation_reached"])
        self.assertEqual(state["saturation_gate"]["verdict"], "discovery-bottleneck")
        self.assertIn("required_action", state["saturation_gate"])
        self.assertIsNone(ledger)

    def test_empty_saturation_with_sparse_verdict_is_accepted(self):
        screening, provenance, previous = _empty_saturating_round()
        discrimination = {"scope_version": 1, "discriminating_volume": 80, "discriminating_basis": "topic-core"}
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
        provenance = {"scope_version": 1, "records": [{"candidate_id": candidate_id, "pmid": "1", "pilot_types": ["mesh-led"], "pilot_labels": ["mesh"]}], "safety_cap_reached": False}
        previous = {"consecutive_saturated_rounds": 2, "seen_pmids": ["1"], "included_pmids": ["1"], "vocabulary_terms": [], "adjudicated_records": []}
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
        provenance = {"scope_version": 1, "records": [{"candidate_id": candidate_id, "pmid": "1", "pilot_types": ["mesh-led"], "pilot_labels": ["mesh"]}], "safety_cap_reached": False}
        previous = {"consecutive_saturated_rounds": 2, "seen_pmids": ["1"], "included_pmids": ["1"], "vocabulary_terms": [], "adjudicated_records": []}
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

    def test_essential_only_probes_are_low_confidence_proxy(self):
        def fake_search(client, query, retmax=0, retstart=0, sort=None):
            return {"count": 40, "pmids": []}

        probes = [{"label": "c", "role": "essential-concept", "query": "c[tiab]"}]
        with mock.patch.object(no_seed.pubmed_tool, "esearch", side_effect=fake_search):
            artifact = no_seed.discriminate(FakeClient(), probes, scope_version=1, sparse_ceiling=500, bottleneck_floor=1000)
        self.assertEqual(artifact["discriminating_basis"], "single-concept-proxy")
        self.assertEqual(artifact["provisional_verdict"], "genuinely-sparse")
        self.assertEqual(artifact["verdict_confidence"], "low")


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


class RecaptureCompletenessTests(unittest.TestCase):
    def test_worked_example_matches_chao1_math(self):
        # 10 singletons, 5 doubletons, 5 triples -> S_obs=20, f1=10, f2=5.
        provenance, included = _provenance([(10, 1), (5, 2), (5, 3)])
        result = no_seed.estimate_completeness(included, provenance)
        self.assertEqual(result["screened_in_observed"], 20)
        self.assertEqual((result["f1_singletons"], result["f2_doubletons"]), (10, 5))
        self.assertEqual(result["estimated_total_relevant"], 30.0)
        self.assertAlmostEqual(result["completeness"], 0.6667, places=3)
        self.assertEqual(result["chao1_estimate"]["variance"], 70.0)
        self.assertEqual(result["chao1_estimate"]["ci95"], [22.4, 61.69])

    def test_low_overlap_is_undersaturated_leak_signal(self):
        # 18 singletons + 2 doubletons -> N_hat huge, completeness far below 0.60.
        provenance, included = _provenance([(18, 1), (2, 2)])
        result = no_seed.estimate_completeness(included, provenance)
        self.assertEqual(result["verdict"], "undersaturated")
        self.assertLess(result["completeness"], 0.60)
        self.assertIn("leak signal", result["interpretation"])

    def test_high_overlap_is_converged_weak_positive(self):
        # 2 singletons, 10 doubletons, 8 triples -> completeness ~0.99.
        provenance, included = _provenance([(2, 1), (10, 2), (8, 3)])
        result = no_seed.estimate_completeness(included, provenance)
        self.assertEqual(result["verdict"], "converged")
        self.assertGreaterEqual(result["completeness"], 0.85)
        self.assertIn("weak positive", result["interpretation"])

    def test_too_few_screened_in_stays_indeterminate_without_estimate(self):
        provenance, included = _provenance([(2, 1), (1, 2)])  # S_obs=3 < 5
        result = no_seed.estimate_completeness(included, provenance)
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["reason"], "too-few-screened-in")
        self.assertIsNone(result["completeness"])
        self.assertIsNone(result["estimated_total_relevant"])

    def test_no_doubletons_gives_indicative_point_estimate_without_ci(self):
        # 8 records, all singletons -> f2=0: bias-corrected point estimate, no CI, no firm verdict.
        provenance, included = _provenance([(8, 1)])
        result = no_seed.estimate_completeness(included, provenance)
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["reason"], "no-recaptures")
        self.assertEqual(result["estimated_total_relevant"], 8 + 8 * 7 / 2)  # bias-corrected Chao1
        self.assertIsNone(result["chao1_estimate"]["ci95"])
        self.assertIsNone(result["completeness"])

    def test_indicative_confidence_below_firm_verdict_floor(self):
        # S_obs between 5 and 15 -> completeness computed but flagged indicative.
        provenance, included = _provenance([(2, 1), (5, 2)])  # S_obs=7
        result = no_seed.estimate_completeness(included, provenance)
        self.assertEqual(result["confidence"], "indicative")
        self.assertEqual(result["reason"], "below-firm-verdict-floor")

    def test_jaccard_and_per_family_counts_populated(self):
        provenance, included = _provenance([(4, 1), (6, 2)])
        result = no_seed.estimate_completeness(included, provenance)
        self.assertTrue(result["per_family_capture_counts"])
        self.assertTrue(result["pairwise_jaccard"])
        self.assertIsNotNone(result["mean_pairwise_jaccard"])

    def test_adjudicate_attaches_estimate_and_recall_risk(self):
        provenance, included = _provenance([(18, 1), (2, 2)])  # undersaturated
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
        prov = {"scope_version": 1, "pilot_types": sorted(no_seed.PILOT_TYPES),
                "safety_cap_reached": False, "records": prov_records}
        state, _ = no_seed.adjudicate(
            screening, prov, previous_state=None, scope_version=1,
            required_saturated_rounds=2, allocation_seed="test",
        )
        self.assertIn("completeness_estimate", state)
        self.assertEqual(state["completeness_estimate"]["verdict"], "undersaturated")
        self.assertTrue(state["recall_risk"]["critic_must_clear"])

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
            self.assertEqual(artifact["operation"], "orthogonal-pilot-recapture")
            self.assertEqual(artifact["estimated_total_relevant"], 30.0)


if __name__ == "__main__":
    unittest.main()
