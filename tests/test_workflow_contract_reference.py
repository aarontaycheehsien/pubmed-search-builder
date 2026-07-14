import unittest
from pathlib import Path

from pubmed_search_builder.workflow.stages import render_contract_reference


class WorkflowContractReferenceTests(unittest.TestCase):
    def test_committed_reference_matches_executable_stage_registry(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            (root / "references" / "workflow-contracts.md").read_text(encoding="utf-8"),
            render_contract_reference(),
        )


if __name__ == "__main__":
    unittest.main()
