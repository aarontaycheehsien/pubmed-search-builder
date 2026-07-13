import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "mesh_tool.py"
SPEC = importlib.util.spec_from_file_location("mesh_tool", MODULE_PATH)
mesh_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mesh_tool)


SUMMARY_XML = b"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE eSummaryResult PUBLIC "-//NLM//DTD esummary mesh 20250219//EN" "">
<eSummaryResult>
  <DocumentSummarySet status="OK">
    <DocumentSummary uid="2023512">
      <DS_YearIntroduced>2023</DS_YearIntroduced>
      <DS_ScopeNote>The use of immersive virtual environments.</DS_ScopeNote>
      <DS_MeshTerms><string>Virtual Reality</string><string>Virtual Environments</string></DS_MeshTerms>
      <DS_Subheading><string>methods</string></DS_Subheading>
      <DS_SeeRelated><string>Augmented Reality</string></DS_SeeRelated>
      <DS_IdxLinks><LinksType><TreeNum>L01.224.230.110.500</TreeNum></LinksType></DS_IdxLinks>
      <DS_RecordType>TopicalDescriptor</DS_RecordType>
      <DS_MeSHUI>D000076142</DS_MeSHUI>
    </DocumentSummary>
  </DocumentSummarySet>
</eSummaryResult>"""


def eutils_record():
    return {
        "descriptor": "D000076142",
        "resource": "http://id.nlm.nih.gov/mesh/D000076142",
        "label": "Virtual Reality",
        "terms": ["Virtual Reality", "Virtual Environments"],
        "qualifiers": ["methods"],
        "tree_numbers": ["L01.224.230.110.500"],
        "scope_note": "The use of immersive virtual environments.",
        "previous_indexing": [],
        "see_related": ["Augmented Reality"],
        "mapped_to": [],
        "record_type": "TopicalDescriptor",
        "year_introduced": "2023",
    }


class MeshEutilsTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            name: getattr(mesh_tool, name)
            for name in (
                "rdf_lookup",
                "eutils_lookup",
                "eutils_search_uids",
                "eutils_summary_records",
                "lookup",
                "terms",
                "term_descriptor_candidates",
            )
        }
        mesh_tool.reset_runtime_backend_state()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(mesh_tool, name, value)
        mesh_tool.reset_runtime_backend_state()

    def test_esummary_v2_xml_is_normalized_to_mesh_records(self):
        records = mesh_tool.parse_eutils_summary(SUMMARY_XML)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["descriptor"], "D000076142")
        self.assertEqual(records[0]["label"], "Virtual Reality")
        self.assertEqual(records[0]["terms"], ["Virtual Reality", "Virtual Environments"])
        self.assertEqual(records[0]["qualifiers"], ["methods"])
        self.assertEqual(records[0]["tree_numbers"], ["L01.224.230.110.500"])

    def test_eutils_exact_lookup_verifies_the_preferred_heading(self):
        calls = []

        def fake_search(label, match, limit, *, field):
            calls.append((label, match, limit, field))
            return ["2023512"]

        mesh_tool.eutils_search_uids = fake_search
        near_match = dict(eutils_record())
        near_match.update(
            {
                "descriptor": "D063367",
                "resource": mesh_tool.mesh_resource("D063367"),
                "label": "Virtual Reality Exposure Therapy",
            }
        )
        mesh_tool.eutils_summary_records = lambda _uids: [eutils_record(), near_match]

        result = mesh_tool.lookup("Virtual Reality", "exact", 10, backend="eutils")

        self.assertEqual(calls[0][3], "MESH")
        self.assertEqual(result["results"][0]["resource"], eutils_record()["resource"])
        self.assertEqual(result["results"][0]["fidelity"], "full")
        self.assertEqual(result["results"][0]["provenance"]["backend"], "eutils")
        self.assertEqual(len(result["results"]), 1)

    def test_eutils_term_results_carry_the_parent_descriptor_directly(self):
        mesh_tool.eutils_search_uids = lambda *_args, **_kwargs: ["2023512"]
        mesh_tool.eutils_summary_records = lambda _uids: [eutils_record()]

        result = mesh_tool.terms("virtual", "contains", 10, backend="eutils")

        self.assertTrue(result["results"])
        self.assertEqual(result["results"][0]["descriptor"], "D000076142")
        self.assertEqual(result["results"][0]["fidelity"], "reduced")

    def test_eutils_details_preserves_the_supported_summary_metadata(self):
        mesh_tool.eutils_search_uids = lambda *_args, **_kwargs: ["2023512"]
        mesh_tool.eutils_summary_records = lambda _uids: [eutils_record()]

        result = mesh_tool.details("D000076142", "terms,seealso,qualifiers", backend="eutils")

        self.assertEqual(result["details"]["terms"][0]["label"], "Virtual Reality")
        self.assertTrue(result["details"]["terms"][0]["preferred"])
        self.assertEqual(result["details"]["qualifiers"][0]["label"], "methods")
        self.assertEqual(result["provenance"]["fidelity"], "reduced")

    def test_eutils_rate_limit_follows_ncbi_api_key_presence(self):
        with patch.object(mesh_tool, "read_env", lambda name, default="": "" if name == "NCBI_API_KEY" else default):
            self.assertEqual(mesh_tool.eutils_rate_limit(), 3.0)
        with patch.object(mesh_tool, "read_env", lambda name, default="": "private-key" if name == "NCBI_API_KEY" else default):
            self.assertEqual(mesh_tool.eutils_rate_limit(), 10.0)

    def test_eutils_api_key_is_sent_to_ncbi_but_never_written_into_the_cache_key_or_payload(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"esearchresult": {"idlist": []}}'

        captured = []

        def fake_urlopen(request, timeout):
            captured.append(request.full_url)
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "MESH_CACHE": "on",
                "MESH_CACHE_DIR": tmp,
                "NCBI_API_KEY": "private-key",
                "NCBI_TOOL": "mesh-eutils-test",
            },
            clear=False,
        ), patch.object(mesh_tool.urllib.request, "urlopen", fake_urlopen):
            mesh_tool.REQUEST_CACHE.clear()
            params = {"db": "mesh", "term": "virtual reality", "retmode": "json"}
            mesh_tool.request_json(f"{mesh_tool.EUTILS_BASE}/esearch.fcgi", params, backend="eutils")

            self.assertIn("api_key=private-key", captured[0])
            cache_payload = mesh_tool.cache_entry_path(
                f"{mesh_tool.EUTILS_BASE}/esearch.fcgi", params
            ).read_text(encoding="utf-8")
            self.assertNotIn("private-key", cache_payload)

    def test_auto_falls_back_once_then_latches_to_eutils_for_this_process(self):
        calls = []

        def failing_rdf(_label, _match, _limit, _reason=None):
            calls.append("rdf")
            raise mesh_tool.MeshRequestError(
                "RDF request failed", classification=mesh_tool.ERROR_TRANSIENT, host="id.nlm.nih.gov", attempts=4
            )

        def fallback_eutils(label, match, limit, reason=None):
            calls.append(reason or "eutils")
            return {"operation": "lookup", "label": label, "match": match, "results": []}

        mesh_tool.rdf_lookup = failing_rdf
        mesh_tool.eutils_lookup = fallback_eutils

        mesh_tool.lookup("one", "exact", 10, backend="auto")
        mesh_tool.lookup("two", "exact", 10, backend="auto")

        self.assertEqual(calls, ["rdf", "rdf_transient", "rdf_degraded_for_run"])

    def test_auto_does_not_fallback_after_a_hard_rdf_error(self):
        def hard_rdf(_label, _match, _limit, _reason=None):
            raise mesh_tool.MeshRequestError(
                "invalid request", classification=mesh_tool.ERROR_HARD, host="id.nlm.nih.gov", attempts=1
            )

        mesh_tool.rdf_lookup = hard_rdf
        mesh_tool.eutils_lookup = lambda *_args, **_kwargs: self.fail("hard RDF errors must not use EUtils")

        with self.assertRaises(mesh_tool.MeshRequestError):
            mesh_tool.lookup("one", "exact", 10, backend="auto")

    def test_sweep_accepts_eutils_direct_term_to_descriptor_hits_without_sparql(self):
        descriptor = "D000076142"
        mesh_tool.lookup = lambda *_args, **_kwargs: {"operation": "lookup", "results": []}
        mesh_tool.terms = lambda _label, match, _limit, **_kwargs: {
            "operation": "terms",
            "results": (
                [
                    {
                        "resource": "",
                        "label": "Virtual Reality",
                        "descriptor": descriptor,
                        "descriptor_resource": mesh_tool.mesh_resource(descriptor),
                        "descriptor_label": "Virtual Reality",
                        "provenance": {"backend": "eutils", "fidelity": "reduced", "method": "fixture"},
                    }
                ]
                if match == "exact"
                else []
            ),
        }
        mesh_tool.term_descriptor_candidates = lambda *_args, **_kwargs: self.fail(
            "direct EUtils descriptor association should skip RDF SPARQL"
        )

        result = mesh_tool.sweep("virtual reality", [], 10, False, 0, 0, backend="eutils")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["candidates"][0]["descriptor"], descriptor)
        self.assertEqual(result["backend_provenance"][0]["fidelity"], "reduced")
        self.assertIn("reduced-fidelity", result["review_required"][0])

    def test_cli_exposes_backend_and_rejects_eutils_tree(self):
        parser = mesh_tool.build_parser()
        self.assertEqual(parser.parse_args(["lookup", "--label", "x", "--backend", "eutils"]).backend, "eutils")

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = mesh_tool.main(["tree", "--descriptor", "D003668", "--backend", "eutils"])
        self.assertEqual(exit_code, 1)
        self.assertIn("RDF-only", output.getvalue())


if __name__ == "__main__":
    unittest.main()
