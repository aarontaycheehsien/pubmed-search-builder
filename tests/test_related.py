import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "pubmed_tool.py"
SPEC = importlib.util.spec_from_file_location("pubmed_tool", MODULE_PATH)
pubmed_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pubmed_tool)


def elink_payload(seed, linkname, links):
    """Build an eLink-shaped JSON response. links is a list of ids or (id, score)."""
    rows = []
    for link in links:
        if isinstance(link, tuple):
            rows.append({"id": link[0], "score": link[1]})
        else:
            rows.append(link)
    return {
        "linksets": [
            {
                "dbfrom": "pubmed",
                "ids": [seed],
                "linksetdbs": [{"linkname": linkname, "links": rows}],
            }
        ]
    }


class FakeClient:
    """Fake NcbiClient whose request() returns canned eLink JSON keyed by (id, linkname)."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, endpoint, params, *, method="GET"):
        self.calls.append((endpoint, params.get("id"), params.get("linkname"), params.get("cmd")))
        seed = params["id"]
        linkname = params["linkname"]
        links = self.responses.get((seed, linkname), [])
        return json.dumps(elink_payload(seed, linkname, links)).encode("utf-8")

    def metadata(self):
        return {"tool": "test"}


class RelatedTests(unittest.TestCase):
    def test_dedup_provenance_and_overlap_ranking(self):
        # PMID 100 is a neighbor of both seeds (overlap 2); 200 only of seed 1.
        responses = {
            ("1", "pubmed_pubmed"): [("100", 50), ("200", 80)],
            ("2", "pubmed_pubmed"): [("100", 30)],
        }
        client = FakeClient(responses)
        result = pubmed_tool.related_pmids(
            client, ["1", "2"], links=["similar"], max_per_seed=20, max_total=200
        )

        self.assertEqual(result["operation"], "related")
        self.assertEqual(result["seed_pmids"], ["1", "2"])
        self.assertEqual(result["link_counts"], {"similar": 3})

        candidates = result["candidate_pmids"]
        # Highest seed overlap first.
        self.assertEqual(candidates[0]["pmid"], "100")
        self.assertEqual(candidates[0]["seed_overlap_count"], 2)
        self.assertEqual(sorted(candidates[0]["seed_sources"]), ["1", "2"])
        self.assertEqual(candidates[0]["via"], ["similar"])
        # Max similarity score retained across seeds.
        self.assertEqual(candidates[0]["similarity_score"], 50)

        self.assertEqual(candidates[1]["pmid"], "200")
        self.assertEqual(candidates[1]["seed_overlap_count"], 1)

    def test_seeds_excluded_from_candidates(self):
        responses = {("1", "pubmed_pubmed"): ["1", "2", "300"]}
        client = FakeClient(responses)
        result = pubmed_tool.related_pmids(
            client, ["1", "2"], links=["similar"], max_per_seed=20, max_total=200
        )
        pmids = [row["pmid"] for row in result["candidate_pmids"]]
        self.assertNotIn("1", pmids)
        self.assertNotIn("2", pmids)
        self.assertIn("300", pmids)

    def test_multiple_links_merge_via_provenance(self):
        responses = {
            ("1", "pubmed_pubmed"): [("400", 10)],
            ("1", "pubmed_pubmed_citedin"): ["400", "500"],
        }
        client = FakeClient(responses)
        result = pubmed_tool.related_pmids(
            client, ["1"], links=["similar", "citedin"], max_per_seed=20, max_total=200
        )
        by_pmid = {row["pmid"]: row for row in result["candidate_pmids"]}
        self.assertEqual(sorted(by_pmid["400"]["via"]), ["citedin", "similar"])
        self.assertEqual(by_pmid["500"]["via"], ["citedin"])
        self.assertEqual(result["link_counts"], {"similar": 1, "citedin": 2})

    def test_max_per_seed_caps_neighbors(self):
        responses = {("1", "pubmed_pubmed"): ["10", "11", "12", "13"]}
        client = FakeClient(responses)
        result = pubmed_tool.related_pmids(
            client, ["1"], links=["similar"], max_per_seed=2, max_total=200
        )
        self.assertEqual(result["link_counts"]["similar"], 2)
        self.assertEqual(result["candidate_count"], 2)

    def test_max_total_caps_candidate_set(self):
        responses = {("1", "pubmed_pubmed"): ["10", "11", "12", "13", "14"]}
        client = FakeClient(responses)
        result = pubmed_tool.related_pmids(
            client, ["1"], links=["similar"], max_per_seed=20, max_total=3
        )
        self.assertEqual(result["candidate_count_before_cap"], 5)
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(len(result["candidate_pmids"]), 3)

    def test_similarity_score_requested_only_for_similar(self):
        responses = {
            ("1", "pubmed_pubmed"): [("10", 99)],
            ("1", "pubmed_pubmed_refs"): ["20"],
        }
        client = FakeClient(responses)
        pubmed_tool.related_pmids(client, ["1"], links=["similar", "refs"], max_per_seed=20, max_total=200)
        cmds = {(linkname): cmd for _, _, linkname, cmd in client.calls}
        self.assertEqual(cmds["pubmed_pubmed"], "neighbor_score")
        self.assertIsNone(cmds["pubmed_pubmed_refs"])

    def test_no_neighbors_returns_empty_candidates(self):
        client = FakeClient({})
        result = pubmed_tool.related_pmids(
            client, ["99999999999"], links=["similar"], max_per_seed=20, max_total=200
        )
        self.assertEqual(result["candidate_pmids"], [])
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["link_counts"], {"similar": 0})


if __name__ == "__main__":
    unittest.main()
