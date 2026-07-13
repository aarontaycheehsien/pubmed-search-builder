"""Offline contract tests for the canonical MeSH provenance summary."""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "mesh_evidence.py"
SPEC = importlib.util.spec_from_file_location("mesh_evidence", MODULE_PATH)
mesh_evidence = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mesh_evidence)


RDF = {"backend": "rdf", "fidelity": "full", "method": "rdf_sparql"}
EUTILS = {
    "backend": "eutils",
    "fidelity": "reduced",
    "method": "eutils_batch_esearch_esummary",
    "fallback_reason": "rdf_transient",
}


class MeshEvidenceTests(unittest.TestCase):
    def test_zero_candidate_eutils_sweep_still_requires_rdf_confirmation(self):
        payload = {
            "operation": "sweep",
            "status": "complete",
            "candidates": [],
            "backend_provenance": [EUTILS],
            "raw_searches": [
                {"label": "rare phrase", "match": "exact", "results": [], "provenance": EUTILS}
            ],
        }

        summary = mesh_evidence.build_mesh_evidence(payload)

        self.assertEqual(summary["overall_fidelity"], "reduced")
        self.assertTrue(summary["reduced_fidelity_present"])
        self.assertEqual(summary["records"]["total"], 0)
        self.assertIn("eutils_batch_esearch_esummary", summary["methods"])
        self.assertIn("Confirm preferred headings", summary["review_required"][0])
        self.assertTrue(mesh_evidence.complete_sweep_evidence(summary))

    def test_mixed_candidate_provenance_is_counted_without_hiding_reduced_rows(self):
        payload = {
            "operation": "sweep",
            "status": "complete",
            "candidates": [
                {"descriptor": "D1", "provenance": RDF},
                {"descriptor": "D2", "provenance": EUTILS},
            ],
            "backend_provenance": [RDF, EUTILS],
        }

        summary = mesh_evidence.build_mesh_evidence(payload)

        self.assertEqual(summary["overall_fidelity"], "mixed")
        self.assertEqual(summary["records"], {
            "total": 2, "full_only": 1, "reduced_only": 1, "mixed": 0, "unclassified": 0,
        })
        self.assertTrue(summary["reduced_fidelity_present"])

    def test_partial_sweep_cannot_supply_complete_coverage(self):
        summary = mesh_evidence.build_mesh_evidence(
            {"operation": "sweep", "status": "partial", "backend_provenance": [RDF]}
        )

        self.assertFalse(mesh_evidence.complete_sweep_evidence(summary))
        self.assertIn("partial", summary["review_required"][0])

    def test_eutils_tree_limitations_and_truncation_are_disclosed(self):
        summary = mesh_evidence.build_mesh_evidence(
            {
                "operation": "tree",
                "status": "complete",
                "provenance": {
                    "backend": "eutils",
                    "fidelity": "reduced",
                    "method": "eutils_tree_esearch_esummary",
                },
                "tree_search": {"truncated": True},
            }
        )

        limitations = " ".join(summary["limitations"])
        self.assertIn("RDF-only annotations", limitations)
        self.assertIn("truncated", limitations)

    def test_embedded_summary_must_match_provenance_fields(self):
        payload = {
            "operation": "lookup",
            "status": "complete",
            "provenance": RDF,
            "results": [],
            "mesh_evidence": {"operation": "lookup", "overall_fidelity": "reduced"},
        }

        self.assertEqual(
            mesh_evidence.mesh_evidence_issues(payload),
            ["mesh_evidence does not match the artifact provenance fields"],
        )


if __name__ == "__main__":
    unittest.main()
