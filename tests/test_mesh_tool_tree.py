import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "mesh_tool.py"
SPEC = importlib.util.spec_from_file_location("mesh_tool", MODULE_PATH)
mesh_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mesh_tool)


def literal(value):
    return {"type": "literal", "value": value}


def uri(value):
    return {"type": "uri", "value": value}


def sparql_result(bindings):
    return {"operation": "sparql", "results": {"results": {"bindings": bindings}}}


class MeshTreeTests(unittest.TestCase):
    def setUp(self):
        self.original_details = mesh_tool.details
        self.original_sparql = mesh_tool.sparql

    def tearDown(self):
        mesh_tool.details = self.original_details
        mesh_tool.sparql = self.original_sparql

    def install_fakes(
        self,
        descriptor="D003668",
        label="Pressure Ulcer",
        resource_type="TopicalDescriptor",
        descendants=None,
        mapping=None,
    ):
        descendants = descendants or []
        mapping = mapping or []

        def fake_details(requested_descriptor, include):
            self.assertEqual(requested_descriptor, descriptor)
            self.assertEqual(include, "terms,seealso,qualifiers")
            return {
                "operation": "details",
                "descriptor": requested_descriptor,
                "include": include,
                "details": {
                    "descriptor": f"http://id.nlm.nih.gov/mesh/{descriptor}",
                    "terms": [
                        {
                            "resource": "http://id.nlm.nih.gov/mesh/T010680",
                            "label": label,
                            "preferred": True,
                        },
                        {
                            "resource": "http://id.nlm.nih.gov/mesh/T010681",
                            "label": "Bed Sores",
                            "preferred": False,
                        },
                        {
                            "resource": "http://id.nlm.nih.gov/mesh/T010681",
                            "label": "Bed Sores",
                            "preferred": False,
                        },
                    ],
                    "qualifiers": [],
                    "seealso": [],
                },
            }

        def fake_sparql(query, limit, offset, inference):
            if "SELECT ?label ?type ?scopeNote ?annotation ?historyNote ?publicMeSHNote" in query:
                return sparql_result(
                    [
                        {
                            "label": literal(label),
                            "type": uri(f"http://id.nlm.nih.gov/mesh/vocab#{resource_type}"),
                            "scopeNote": literal("A scope note."),
                            "annotation": literal("An annotation."),
                            "historyNote": literal("2006 (1963)"),
                            "publicMeSHNote": literal("2006; see older heading"),
                        }
                    ]
                )
            if "SELECT ?treeNumber WHERE" in query:
                return sparql_result(
                    [
                        {"treeNumber": uri("http://id.nlm.nih.gov/mesh/C17.800.893.665")},
                    ]
                )
            if "SELECT ?broader ?broaderLabel ?tree" in query:
                return sparql_result(
                    [
                        {
                            "broader": uri("http://id.nlm.nih.gov/mesh/D012883"),
                            "broaderLabel": literal("Skin Ulcer"),
                            "tree": uri("http://id.nlm.nih.gov/mesh/C17.800.893"),
                        },
                    ]
                )
            if "SELECT ?narrower ?narrowerLabel ?tree" in query:
                return sparql_result([])
            if "SELECT ?descendant ?descendantLabel ?tree" in query:
                return sparql_result(descendants)
            if "SELECT ?parent ?parentLabel ?sibling ?siblingLabel ?tree" in query:
                return sparql_result(
                    [
                        {
                            "parent": uri("http://id.nlm.nih.gov/mesh/D012883"),
                            "parentLabel": literal("Skin Ulcer"),
                            "sibling": uri("http://id.nlm.nih.gov/mesh/D054312"),
                            "siblingLabel": literal("Buruli Ulcer"),
                            "tree": uri("http://id.nlm.nih.gov/mesh/C17.800.893.295"),
                        },
                        {
                            "parent": uri("http://id.nlm.nih.gov/mesh/D012883"),
                            "parentLabel": literal("Skin Ulcer"),
                            "sibling": uri("http://id.nlm.nih.gov/mesh/D054312"),
                            "siblingLabel": literal("Buruli Ulcer"),
                            "tree": uri("http://id.nlm.nih.gov/mesh/C01.150.252.410.040.552.475.247"),
                        },
                    ]
                )
            if "SELECT ?mapped ?mappedLabel" in query:
                return sparql_result(mapping)
            if "SELECT ?label WHERE" in query and "mesh:D000983" in query:
                return sparql_result([{"label": literal("Antipyrine")}])
            if "SELECT ?label WHERE" in query and "mesh:Q000031" in query:
                return sparql_result([{"label": literal("analysis")}])
            raise AssertionError(f"Unexpected SPARQL query: {query}")

        mesh_tool.details = fake_details
        mesh_tool.sparql = fake_sparql

    def test_descriptor_tree_report_fields_and_dedupes(self):
        self.install_fakes()

        result = mesh_tool.tree("D003668", max_descendants=100, max_siblings=100)

        self.assertEqual(result["operation"], "tree")
        self.assertEqual(result["descriptor"], "D003668")
        self.assertEqual(result["preferred_label"], "Pressure Ulcer")
        self.assertEqual(result["scope_note"], "A scope note.")
        self.assertEqual(result["annotation"], "An annotation.")
        self.assertEqual(result["history_note"], "2006 (1963)")
        self.assertEqual(result["public_mesh_note"], "2006; see older heading")
        self.assertEqual(result["entry_terms"], [{"term": "T010681", "resource": "http://id.nlm.nih.gov/mesh/T010681", "label": "Bed Sores", "preferred": False}])
        self.assertEqual(result["tree_numbers"], ["C17.800.893.665"])
        self.assertEqual(result["broader_descriptors"][0]["descriptor"], "D012883")
        self.assertEqual(result["sibling_descriptors"][0]["siblings"][0]["tree_numbers"], ["C01.150.252.410.040.552.475.247", "C17.800.893.295"])
        self.assertEqual(result["scr_mapping"], {"status": "not_applicable"})
        self.assertFalse(result["descendants"])
        self.assertTrue(any("No descendants were returned" in prompt for prompt in result["explosion_review_prompts"]))

    def test_descendants_are_truncated_and_prompted(self):
        self.install_fakes(
            descendants=[
                {
                    "descendant": uri("http://id.nlm.nih.gov/mesh/D000001"),
                    "descendantLabel": literal("First Child"),
                    "tree": uri("http://id.nlm.nih.gov/mesh/C17.800.893.665.100"),
                },
                {
                    "descendant": uri("http://id.nlm.nih.gov/mesh/D000002"),
                    "descendantLabel": literal("Second Child"),
                    "tree": uri("http://id.nlm.nih.gov/mesh/C17.800.893.665.200"),
                },
            ]
        )

        result = mesh_tool.tree("D003668", max_descendants=1, max_siblings=100)

        self.assertEqual(len(result["descendants"]), 1)
        self.assertTrue(result["descendants_truncated"])
        self.assertTrue(any("truncated" in prompt for prompt in result["explosion_review_prompts"]))

    def test_scr_preferred_mapped_to_mapping_is_normalized(self):
        self.install_fakes(
            descriptor="C123456",
            label="Example SCR",
            resource_type="SCR_Chemical",
            mapping=[
                {
                    "mapped": uri("http://id.nlm.nih.gov/mesh/D000983Q000031"),
                }
            ],
        )

        result = mesh_tool.tree("C123456", max_descendants=100, max_siblings=100)

        self.assertEqual(result["resource_type"], "SCR_Chemical")
        self.assertEqual(result["scr_mapping"]["status"], "mapped")
        mapping = result["scr_mapping"]["mappings"][0]
        self.assertEqual(mapping["mapped_to"], "D000983Q000031")
        self.assertEqual(mapping["descriptor"]["descriptor"], "D000983")
        self.assertEqual(mapping["descriptor"]["label"], "Antipyrine")
        self.assertEqual(mapping["qualifier"]["qualifier"], "Q000031")
        self.assertEqual(mapping["qualifier"]["label"], "analysis")
        self.assertTrue(any("Supplementary Concept Record" in prompt for prompt in result["explosion_review_prompts"]))


if __name__ == "__main__":
    unittest.main()
