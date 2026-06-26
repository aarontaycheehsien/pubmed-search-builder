import contextlib
import importlib.util
import io
import json
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "mesh_tool.py"
SPEC = importlib.util.spec_from_file_location("mesh_tool", MODULE_PATH)
mesh_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mesh_tool)

PRESSURE_ULCER = "http://id.nlm.nih.gov/mesh/D003668"


class FakeClock:
    """Deterministic monotonic() for the time-budget test: returns each queued value once, then
    repeats the final value forever (so trailing elapsed() calls stay stable)."""

    def __init__(self, values):
        self._values = list(values)

    def monotonic(self):
        if len(self._values) > 1:
            return self._values.pop(0)
        return self._values[0]


class MeshSweepTests(unittest.TestCase):
    def setUp(self):
        self._orig = {
            name: getattr(mesh_tool, name)
            for name in ("lookup", "terms", "term_descriptor_candidates", "details", "time")
        }

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(mesh_tool, name, value)

    def install_fakes(self, *, failing_labels=()):
        def fake_lookup(label, match, limit):
            if label in failing_labels:
                raise mesh_tool.MeshError(f"network down for {label!r}")
            results = [{"resource": PRESSURE_ULCER, "label": "Pressure Ulcer"}] if match == "exact" else []
            return {"operation": "lookup", "label": label, "match": match, "results": results}

        def fake_terms(label, match, limit):
            return {"operation": "terms", "label": label, "match": match, "results": []}

        def fake_term_descriptor_candidates(term_resource, limit):
            return []

        def fake_details(descriptor, include):
            return {
                "operation": "details",
                "descriptor": descriptor,
                "include": include,
                "details": {
                    "descriptor": descriptor,
                    "terms": [{"resource": "T1", "label": "synonym", "preferred": False}],
                },
            }

        mesh_tool.lookup = fake_lookup
        mesh_tool.terms = fake_terms
        mesh_tool.term_descriptor_candidates = fake_term_descriptor_candidates
        mesh_tool.details = fake_details

    def test_complete_run_reports_complete_status_and_candidates(self):
        self.install_fakes()
        result = mesh_tool.sweep("pressure ulcer", ["bed sore"], 20, True, 40, 30, max_seconds=0.0)

        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["stop_reason"])
        self.assertEqual(result["pending"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["coverage"]["units_total"], 6)  # 3 matches x 2 labels
        self.assertEqual(result["coverage"]["units_processed"], 6)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["descriptor"], "D003668")
        # --details enrichment is attached on a complete run (recall payload intact).
        self.assertIn("details", result["candidates"][0])

    def test_request_error_yields_partial_without_aborting(self):
        self.install_fakes(failing_labels={"boom"})
        result = mesh_tool.sweep("pressure ulcer", ["boom"], 20, False, 40, 30, max_seconds=0.0)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["stop_reason"], "request_errors")
        # The healthy label still produced its candidate; one failing label does not abort the run.
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["descriptor"], "D003668")
        # All units were attempted, so nothing is "pending", but the failures are recorded.
        self.assertEqual(result["pending"], [])
        self.assertIn("boom", {error["label"] for error in result["errors"]})
        self.assertTrue(all(error["source"] == "descriptor" for error in result["errors"]))

    def test_time_budget_stops_early_and_lists_pending(self):
        self.install_fakes()
        # start=0.0, first-unit budget check=0.0 (under), second-unit check=5.0 (over budget).
        mesh_tool.time = FakeClock([0.0, 0.0, 5.0])
        result = mesh_tool.sweep("pressure ulcer", ["a", "b"], 20, False, 40, 30, max_seconds=1.0)

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["stop_reason"], "time_budget")
        self.assertEqual(result["coverage"]["units_total"], 9)  # 3 matches x 3 labels
        self.assertEqual(result["coverage"]["units_processed"], 1)
        self.assertEqual(result["coverage"]["units_pending"], 8)
        self.assertEqual(len(result["pending"]), 8)
        self.assertEqual(set(result["pending"][0]), {"match", "label"})

    def test_pending_output_writes_rerunnable_variant_labels(self):
        self.install_fakes()
        mesh_tool.time = FakeClock([0.0, 0.0, 5.0])
        result = mesh_tool.sweep("pressure ulcer", ["a", "b"], 20, False, 40, 30, max_seconds=1.0)

        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / "pending_variants.txt"
            args = types.SimpleNamespace(output=None, summary=True, pending_output=str(pending))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                mesh_tool.emit_sweep(result, args)

            receipt = json.loads(buffer.getvalue())
            self.assertEqual(receipt["pending_output"], str(pending))
            lines = [line for line in pending.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
            self.assertEqual(lines, ["a", "b"])

    def test_output_checkpoints_to_file_and_compact_stdout_drops_raw(self):
        self.install_fakes()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sweep.json"
            result = mesh_tool.sweep(
                "pressure ulcer", ["bed sore"], 20, False, 40, 30, max_seconds=0.0, output_path=str(out)
            )

            # A killed process would still find the full JSON on disk.
            self.assertTrue(out.exists())
            on_disk = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("raw_searches", on_disk)
            self.assertEqual(on_disk["status"], "complete")

            # With --output, stdout is the compact summary (no raw_searches) and names the file.
            args = types.SimpleNamespace(output=str(out), summary=False)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                mesh_tool.emit_sweep(result, args)
            stdout = json.loads(buffer.getvalue())

            self.assertNotIn("raw_searches", stdout)
            self.assertEqual(stdout["output"], str(out))
            self.assertEqual(stdout["candidate_count"], 1)
            self.assertNotIn("details", stdout["candidates"][0])

    def test_no_flags_emit_keeps_full_output(self):
        self.install_fakes()
        result = mesh_tool.sweep("pressure ulcer", [], 20, False, 40, 30, max_seconds=0.0)
        args = types.SimpleNamespace(output=None, summary=False)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            mesh_tool.emit_sweep(result, args)
        stdout = json.loads(buffer.getvalue())

        self.assertIn("raw_searches", stdout)
        self.assertEqual(stdout["status"], "complete")


if __name__ == "__main__":
    unittest.main()
