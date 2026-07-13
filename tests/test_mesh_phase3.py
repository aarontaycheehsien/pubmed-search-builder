import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "mesh_tool.py"
SPEC = importlib.util.spec_from_file_location("mesh_tool", MODULE_PATH)
mesh_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mesh_tool)


def uri(value):
    return {"type": "uri", "value": value}


def literal(value):
    return {"type": "literal", "value": value}


def record(descriptor, label, trees):
    return {
        "descriptor": descriptor,
        "resource": mesh_tool.mesh_resource(descriptor),
        "label": label,
        "terms": [label],
        "qualifiers": [],
        "tree_numbers": trees,
        "scope_note": "",
        "previous_indexing": [],
        "see_related": [],
        "mapped_to": [],
        "record_type": "Descriptor",
        "year_introduced": "",
    }


class MeshPhase3Tests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            name: getattr(mesh_tool, name)
            for name in (
                "sparql",
                "lookup",
                "terms",
                "term_descriptor_candidates_batch",
                "eutils_search_uids",
                "eutils_search",
                "eutils_summary_records",
                "rdf_tree",
                "eutils_tree",
            )
        }
        mesh_tool.reset_runtime_backend_state()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(mesh_tool, name, value)
        mesh_tool.reset_runtime_backend_state()

    def test_rdf_term_mappings_are_resolved_with_one_values_query(self):
        first = mesh_tool.mesh_resource("T000001")
        second = mesh_tool.mesh_resource("T000002")
        calls = []

        def fake_sparql(query, limit, offset, inference):
            calls.append((query, limit, offset, inference))
            return {
                "operation": "sparql",
                "results": {
                    "results": {
                        "bindings": [
                            {
                                "term": uri(first),
                                "descriptor": uri(mesh_tool.mesh_resource("D000001")),
                                "descriptorLabel": literal("First descriptor"),
                                "concept": uri("http://example.test/concept/1"),
                                "conceptLabel": literal("First concept"),
                            },
                        ]
                    }
                },
            }

        mesh_tool.sparql = fake_sparql
        result = mesh_tool.rdf_term_descriptor_candidates_batch([second, first], 10)

        self.assertEqual(len(calls), 1)
        self.assertIn(f"<{first}>", calls[0][0])
        self.assertIn(f"<{second}>", calls[0][0])
        self.assertEqual(calls[0][1], 20)
        self.assertEqual(result[first][0]["descriptor"], "D000001")
        self.assertEqual(result[first][0]["provenance"]["method"], "rdf_term_to_concept_batch")
        self.assertEqual(result[second], [])

    def test_sweep_batches_unique_term_resources_and_reports_the_savings(self):
        first = mesh_tool.mesh_resource("T000001")
        second = mesh_tool.mesh_resource("T000002")
        calls = []
        term_records = {
            "alpha": {"resource": first, "label": "alpha"},
            "beta": {"resource": second, "label": "beta"},
        }
        mesh_tool.lookup = lambda *_args, **_kwargs: {"operation": "lookup", "results": []}
        mesh_tool.terms = lambda label, match, *_args, **_kwargs: {
            "operation": "terms",
            "results": [term_records[label]] if match == "exact" else [],
        }

        def fake_batch(labels, limit, *, backend=None, provenance_out=None):
            calls.append((dict(labels), limit, backend))
            if provenance_out is not None:
                provenance_out["provenance"] = {"backend": "rdf", "fidelity": "full", "method": "fixture"}
            return {
                resource: [
                    {
                        "descriptor": "D000001" if resource == first else "D000002",
                        "resource": mesh_tool.mesh_resource("D000001" if resource == first else "D000002"),
                        "label": "First" if resource == first else "Second",
                        "provenance": {"backend": "rdf", "fidelity": "full", "method": "fixture"},
                    }
                ]
                for resource in labels
            }

        mesh_tool.term_descriptor_candidates_batch = fake_batch
        result = mesh_tool.sweep("alpha", ["beta"], 10, False, 2, 0, term_mapping_batch_size=2)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0][0]), {first, second})
        self.assertEqual(result["network_budget"]["term_mapping_batches"], 1)
        self.assertEqual(result["network_budget"]["estimated_term_mapping_requests_avoided"], 1)
        self.assertEqual({item["descriptor"] for item in result["candidates"]}, {"D000001", "D000002"})

    def test_sweep_keeps_unresolved_batch_mappings_visible(self):
        resource = mesh_tool.mesh_resource("T000001")
        mesh_tool.lookup = lambda *_args, **_kwargs: {"operation": "lookup", "results": []}
        mesh_tool.terms = lambda _label, match, *_args, **_kwargs: {
            "operation": "terms",
            "results": [{"resource": resource, "label": "alpha"}] if match == "exact" else [],
        }
        mesh_tool.term_descriptor_candidates_batch = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            mesh_tool.MeshError("batch unavailable")
        )

        result = mesh_tool.sweep("alpha", [], 10, False, 1, 0)

        self.assertEqual(result["status"], "partial")
        self.assertIn("term_descriptor_mapping_pending", result["stop_reason"])
        self.assertEqual(result["pending_term_descriptor_lookups"][0]["term_resource"], resource)
        self.assertEqual(result["errors"][0]["source"], "term_descriptor_batch")

    def test_eutils_batch_uses_original_term_label_when_building_exact_search(self):
        resource = mesh_tool.mesh_resource("T000001")
        queries = []
        mesh_tool.eutils_search = lambda query, limit, *, field=None: (
            queries.append((query, limit, field)) or {"count": "1", "ids": ["1"], "query_translation": query}
        )
        mesh_tool.eutils_summary_records = lambda _uids: [record("D000001", "Alpha beta", ["A01.100"])]

        result = mesh_tool.eutils_term_descriptor_candidates_batch({resource: "Alpha-beta"}, 10, "rdf_transient")

        self.assertIn('"Alpha-beta"[WORD]', queries[0][0])
        self.assertEqual(result[resource][0]["descriptor"], "D000001")
        self.assertEqual(result[resource][0]["provenance"]["fallback_reason"], "rdf_transient")

    def test_batch_result_safeguards_do_not_silently_report_truncated_mappings_complete(self):
        resource = mesh_tool.mesh_resource("T000001")
        mesh_tool.sparql = lambda *_args, **_kwargs: {
            "operation": "sparql",
            "results": {"results": {"bindings": [{"term": uri(resource), "descriptor": uri(mesh_tool.mesh_resource("D000001"))}]}},
        }
        with self.assertRaisesRegex(mesh_tool.MeshError, "result safeguard"):
            mesh_tool.rdf_term_descriptor_candidates_batch([resource], 1)

        mesh_tool.eutils_search = lambda *_args, **_kwargs: {"count": "2", "ids": ["1"], "query_translation": "fixture"}
        with self.assertRaisesRegex(mesh_tool.MeshError, "candidate pool"):
            mesh_tool.eutils_term_descriptor_candidates_batch({resource: "Alpha"}, 1, "rdf_transient")

    def test_eutils_tree_reconstructs_bounded_context_from_tree_numbers(self):
        primary = record("D000100", "Root", ["A01.100"])
        parent = record("D000001", "Parent", ["A01"])
        child = record("D000101", "Child", ["A01.100.001"])
        grandchild = record("D000102", "Grandchild", ["A01.100.001.001"])
        sibling = record("D000103", "Sibling", ["A01.200"])
        mesh_tool.eutils_search_uids = lambda *_args, **_kwargs: ["primary"]
        mesh_tool.eutils_search = lambda *_args, **_kwargs: {
            "count": "5",
            "ids": ["parent", "child", "grandchild", "sibling", "primary"],
            "query_translation": "fixture",
        }
        mesh_tool.eutils_summary_records = lambda uids: [primary] if uids == ["primary"] else [parent, child, grandchild, sibling, primary]

        result = mesh_tool.tree("D000100", 10, 10, backend="eutils")

        self.assertEqual(result["provenance"]["fidelity"], "reduced")
        self.assertEqual(result["broader_descriptors"][0]["descriptor"], "D000001")
        self.assertEqual([item["descriptor"] for item in result["narrower_descriptors"]], ["D000101"])
        self.assertEqual([item["descriptor"] for item in result["descendants"]], ["D000101", "D000102"])
        self.assertEqual(result["sibling_descriptors"][0]["siblings"][0]["descriptor"], "D000103")
        self.assertTrue(any("reduced fidelity" in prompt for prompt in result["explosion_review_prompts"]))

    def test_tree_auto_falls_back_to_eutils_and_scrs_remain_rdf_only(self):
        calls = []

        def failing_rdf(*_args, **_kwargs):
            raise mesh_tool.MeshRequestError(
                "RDF unavailable", classification=mesh_tool.ERROR_TRANSIENT, host="id.nlm.nih.gov", attempts=1
            )

        def fallback_eutils(*_args, fallback_reason=None, **_kwargs):
            calls.append(fallback_reason)
            return {"operation": "tree", "provenance": {"backend": "eutils", "fallback_reason": fallback_reason}}

        mesh_tool.rdf_tree = failing_rdf
        mesh_tool.eutils_tree = fallback_eutils

        result = mesh_tool.tree("D000001", 10, 10, backend="auto")

        self.assertEqual(result["provenance"]["backend"], "eutils")
        self.assertEqual(calls, ["rdf_transient"])
        with self.assertRaisesRegex(mesh_tool.MeshError, "Supplementary Concept Record"):
            self.originals["eutils_tree"]("C000001", 10, 10)


if __name__ == "__main__":
    unittest.main()
