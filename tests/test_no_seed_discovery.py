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


if __name__ == "__main__":
    unittest.main()
