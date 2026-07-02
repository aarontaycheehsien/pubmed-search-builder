"""Tests for the per-block evidence coverage gate (Phase 1).

`state register-blocks`/`register-block` declare the essential concept blocks; each block must,
before final handoff, have a MeSH sweep and a block count recorded against it (or a reasoned
waiver). This turns the workflow's "aggressive sweep + count-test per concept" prose into a
machine-checked precondition. The gate is opt-in here via `show --require-coverage` / the
read-only `state coverage`; folding it into `--require-ready` is deferred to Phase 2.
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "manifest_tool.py"
SPEC = importlib.util.spec_from_file_location("manifest_tool", MODULE_PATH)
manifest_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifest_tool)


class ManifestCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.manifest = str(self.dir / "run_manifest.json")

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = manifest_tool.main(args)
        text = out.getvalue().strip()
        return rc, (json.loads(text) if text else None)

    def load(self):
        return json.loads(Path(self.manifest).read_text(encoding="utf-8"))

    def state(self, *args):
        return self.run_cli(["state", *args, "--manifest", self.manifest])

    def add(self, **kw):
        args = ["add", "--manifest", self.manifest, "--kind", kw.pop("kind"), "--command", kw.pop("command", "cmd")]
        for flag, value in kw.items():
            args += [f"--{flag}", str(value)]
        return self.run_cli(args)

    def write_blocks_file(self, payload):
        path = self.dir / "blocks.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    # --- registration ---------------------------------------------------------------------

    def test_register_blocks_from_list_file(self):
        bf = self.write_blocks_file([{"label": "malaria", "query": "x"}, {"label": "rdt", "query": "y"}])
        rc, _ = self.state("register-blocks", "--blocks-file", bf)
        self.assertEqual(rc, 0)
        blocks = self.load()["build_state"]["blocks"]
        self.assertEqual(set(blocks), {"malaria", "rdt"})
        self.assertEqual(blocks["malaria"], {"waivers": {}})

    def test_register_blocks_from_map_file_and_is_idempotent(self):
        bf = self.write_blocks_file({"malaria": "x", "rdt": "y"})
        self.state("register-blocks", "--blocks-file", bf)
        # Re-registering must not clobber a waiver already recorded.
        self.state("waive-requirement", "malaria", "mesh_sweep", "SCR-only concept")
        self.state("register-blocks", "--blocks-file", bf)
        blocks = self.load()["build_state"]["blocks"]
        self.assertEqual(blocks["malaria"]["waivers"], {"mesh_sweep": "SCR-only concept"})

    def test_register_block_single(self):
        rc, _ = self.state("register-block", "malaria")
        self.assertEqual(rc, 0)
        self.assertIn("malaria", self.load()["build_state"]["blocks"])

    def test_empty_blocks_file_rejected(self):
        bf = self.write_blocks_file([])
        rc, _ = self.state("register-blocks", "--blocks-file", bf)
        self.assertEqual(rc, 1)

    # --- evidence matching ----------------------------------------------------------------

    def test_explicit_block_tag_satisfies_both_requirements(self):
        self.state("register-block", "malaria")
        self.add(kind="mesh", block="malaria", command="mesh_tool.py sweep --concept malaria --output s.json")
        self.add(kind="search", block="malaria", command="pubmed_tool.py search --query-file m.txt --retmax 0", count="5")
        rc, receipt = self.state("coverage")
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        cov = receipt["coverage"]["malaria"]
        self.assertEqual(cov["mesh_sweep"]["status"], "satisfied")
        self.assertEqual(cov["block_count"]["status"], "satisfied")

    def test_label_fallback_matches_when_block_tag_absent(self):
        self.state("register-block", "malaria")
        # No --block; the free-text label contains the block key.
        self.add(kind="mesh", label="malaria block", command="mesh_tool.py sweep --concept malaria --output s.json")
        self.add(kind="batch", label="malaria counts", command="pubmed_tool.py batch q.json")
        rc, receipt = self.state("coverage")
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])

    def test_mesh_sweep_satisfied_by_command_regex_without_mesh_kind(self):
        self.state("register-block", "malaria")
        # kind is 'other' but the command is clearly a mesh sweep.
        self.add(kind="other", block="malaria", command="python scripts/mesh_tool.py sweep --concept malaria --output s.json")
        cov = manifest_tool.derive_block_coverage(self.load()["build_state"], self.load()["entries"])
        self.assertEqual(cov["malaria"]["mesh_sweep"]["status"], "satisfied")

    def test_non_matching_entries_leave_requirements_pending(self):
        self.state("register-block", "malaria")
        self.add(kind="search", block="some-other-block", command="pubmed_tool.py search --retmax 0")
        rc, receipt = self.state("coverage")
        self.assertEqual(rc, 1)
        self.assertFalse(receipt["ok"])
        self.assertTrue(any("malaria" in i and "block_count" in i for i in receipt["issues"]))

    # --- waivers --------------------------------------------------------------------------

    def test_waiver_with_reason_clears_requirement(self):
        self.state("register-block", "rdt")
        self.add(kind="mesh", block="rdt", command="mesh_tool.py sweep --concept rdt --output s.json")
        self.state("waive-requirement", "rdt", "block_count", "text-word only by design")
        rc, receipt = self.state("coverage")
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["coverage"]["rdt"]["block_count"], {"status": "waived", "reason": "text-word only by design"})

    def test_empty_reason_rejected_without_writing(self):
        self.state("register-block", "rdt")
        rc, _ = self.state("waive-requirement", "rdt", "block_count", "   ")
        self.assertEqual(rc, 1)
        self.assertEqual(self.load()["build_state"]["blocks"]["rdt"]["waivers"], {})

    def test_unknown_requirement_rejected(self):
        self.state("register-block", "rdt")
        rc, _ = self.state("waive-requirement", "rdt", "not_a_requirement", "x")
        self.assertEqual(rc, 1)

    def test_waive_unregistered_block_rejected(self):
        rc, _ = self.state("waive-requirement", "ghost", "mesh_sweep", "x")
        self.assertEqual(rc, 1)

    # --- the show --require-coverage gate -------------------------------------------------

    def test_require_coverage_gate_blocks_then_passes(self):
        self.state("register-block", "malaria")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-coverage"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("coverage gap" in i for i in receipt["issues"]))

        self.add(kind="mesh", block="malaria", command="mesh_tool.py sweep --output s.json")
        self.state("waive-requirement", "malaria", "block_count", "single-concept pilot")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-coverage", "--validate"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["issues"], [])

    def test_require_coverage_fails_when_no_blocks_registered(self):
        self.run_cli(["init", "--manifest", self.manifest])
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-coverage"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("build_state not initialized" in i for i in receipt["issues"]))

    def test_require_ready_unchanged_ignores_coverage(self):
        # Phase 1: --require-ready must NOT enforce coverage. A build with pending block evidence
        # but a resolved concept gate and no pending question still passes --require-ready.
        self.state("register-block", "malaria")  # pending coverage
        self.state("resolve-gate", "concept", "resolved")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-ready"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])

    # --- backward compatibility -----------------------------------------------------------

    def test_add_only_entry_has_empty_block_field_and_no_build_state(self):
        self.add(kind="search", command="cmd", count="1")
        data = self.load()
        self.assertNotIn("build_state", data)
        self.assertEqual(data["entries"][0]["block"], "")

    def test_ensure_build_state_backfills_blocks_on_legacy_state(self):
        legacy = manifest_tool.new_manifest("demo", "1.0.0")
        legacy["build_state"] = {"current_stage": "validation"}  # pre-coverage state, no 'blocks'
        state = manifest_tool.ensure_build_state(legacy)
        self.assertEqual(state["blocks"], {})

    def test_report_includes_block_coverage(self):
        self.state("register-block", "malaria")
        self.add(kind="mesh", block="malaria", command="mesh_tool.py sweep --output s.json")
        rc, receipt = self.run_cli(["report", "--manifest", self.manifest])
        self.assertEqual(rc, 0)
        self.assertIn("block_coverage", receipt)
        self.assertEqual(receipt["block_coverage"]["malaria"]["mesh_sweep"]["status"], "satisfied")

    def test_low_count_review_gate_passes_when_final_count_is_not_low(self):
        self.add(
            kind="search",
            command="pubmed_tool.py search --query-file final_strategy.txt --retmax 0",
            count="501",
            label="Final selected PubMed strategy count",
        )

        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-low-count-review"])

        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])

    def test_low_count_review_gate_blocks_then_passes(self):
        self.add(
            kind="search",
            command="pubmed_tool.py search --query-file final_strategy.txt --retmax 0",
            count="39",
            label="Final selected PubMed strategy count",
        )
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-low-count-review"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("low-count review" in issue for issue in receipt["issues"]))

        review = self.dir / "low_count_review.json"
        review.write_text(
            json.dumps(
                {
                    "hook": "low_count_plausibility_review",
                    "status": "pass",
                    "ok": True,
                    "final_count": 39,
                }
            ),
            encoding="utf-8",
        )
        self.add(
            kind="qa",
            command="python scripts/hooks_tool.py low-count-review --strategy-file final_strategy.txt --final-count 39 --output low_count_review.json",
            output=str(review),
            label="Low-count plausibility review",
        )

        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-low-count-review"])

        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])


class BramerGapCoverageTests(unittest.TestCase):
    """Conditional Bramer reciprocal gap analysis: tracked per block, gated by the separate opt-in
    `--require-gap-analysis`, never by `--require-coverage`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.manifest = str(self.dir / "run_manifest.json")

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = manifest_tool.main(args)
        text = out.getvalue().strip()
        return rc, (json.loads(text) if text else None)

    def state(self, *args):
        return self.run_cli(["state", *args, "--manifest", self.manifest])

    def add(self, **kw):
        args = ["add", "--manifest", self.manifest, "--kind", kw.pop("kind"), "--command", kw.pop("command", "cmd")]
        for flag, value in kw.items():
            args += [f"--{flag}", str(value)]
        return self.run_cli(args)

    def _gap(self, block, command, kind="sample"):
        self.add(kind=kind, block=block, command=command)
        data = json.loads(Path(self.manifest).read_text(encoding="utf-8"))
        cov = manifest_tool.derive_block_coverage(
            data["build_state"], data["entries"], requirements=manifest_tool.GAP_BLOCK_REQUIREMENTS
        )
        return cov[block]["bramer_gap"]["status"]

    def test_term_diff_command_satisfies_gap(self):
        self.state("register-block", "malaria")
        status = self._gap("malaria", "python scripts/pubmed_tool.py term-diff --mesh-query-file m.txt --tiab-query-file t.txt --output d.json")
        self.assertEqual(status, "satisfied")

    def test_manual_gap_query_filename_satisfies_gap(self):
        self.state("register-block", "malaria")
        status = self._gap("malaria", "pubmed_tool.py sample --query-file concept_mesh_not_text.txt --output g.json")
        self.assertEqual(status, "satisfied")

    def test_inline_not_gap_query_satisfies_gap(self):
        self.state("register-block", "malaria")
        status = self._gap("malaria", 'pubmed_tool.py search --query-file f.txt --retmax 0  # (mesh) NOT (tiab)')
        self.assertEqual(status, "satisfied")

    def test_plain_block_count_does_not_satisfy_gap(self):
        self.state("register-block", "malaria")
        status = self._gap("malaria", "pubmed_tool.py search --query-file malaria_block.txt --retmax 0")
        self.assertEqual(status, "pending")

    def test_bramer_gap_is_waivable(self):
        self.state("register-block", "rdt")
        rc, _ = self.state("waive-requirement", "rdt", "bramer_gap", "simple concept, stable MeSH")
        self.assertEqual(rc, 0)
        self.assertEqual(self.load_waivers("rdt"), {"bramer_gap": "simple concept, stable MeSH"})

    def load_waivers(self, block):
        data = json.loads(Path(self.manifest).read_text(encoding="utf-8"))
        return data["build_state"]["blocks"][block]["waivers"]

    def test_require_gap_analysis_blocks_then_passes(self):
        self.state("register-block", "malaria")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-gap-analysis"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("gap-analysis gap" in i for i in receipt["issues"]))

        self.add(kind="sample", block="malaria", command="pubmed_tool.py term-diff --mesh-query-file m.txt --tiab-query-file t.txt --output d.json")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--require-gap-analysis"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])

    def test_require_coverage_does_not_demand_gap(self):
        # Separation: mesh_sweep + block_count satisfied, gap pending -> --require-coverage passes,
        # but --require-gap-analysis fails. Proves the gap gate is independent.
        self.state("register-block", "malaria")
        self.add(kind="mesh", block="malaria", command="mesh_tool.py sweep --output s.json")
        self.add(kind="search", block="malaria", command="pubmed_tool.py search --query-file m.txt --retmax 0", count="5")
        rc, _ = self.run_cli(["show", "--manifest", self.manifest, "--require-coverage"])
        self.assertEqual(rc, 0)
        rc, _ = self.run_cli(["show", "--manifest", self.manifest, "--require-gap-analysis"])
        self.assertEqual(rc, 1)

    def test_state_coverage_surfaces_gap_separately(self):
        self.state("register-block", "malaria")
        rc, receipt = self.state("coverage")
        self.assertIn("gap_coverage", receipt)
        self.assertEqual(receipt["gap_coverage"]["malaria"]["bramer_gap"]["status"], "pending")
        # Mandatory coverage 'ok' is unaffected by the (informational) gap status.
        self.assertIn("coverage", receipt)


if __name__ == "__main__":
    unittest.main()
