import contextlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "manifest_tool.py"
SPEC = importlib.util.spec_from_file_location("manifest_tool", MODULE_PATH)
manifest_tool = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifest_tool)


class ManifestToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.manifest = str(self.dir / "run_manifest.json")

    def run_cli(self, args):
        """Invoke main() with stdout/stderr captured; return (rc, parsed_receipt_or_None)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = manifest_tool.main(args)
        text = out.getvalue().strip()
        return rc, (json.loads(text) if text else None)

    def load(self):
        return json.loads(Path(self.manifest).read_text(encoding="utf-8"))

    def test_add_auto_inits_manifest_with_full_schema(self):
        rc, receipt = self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "search",
             "--command", "pubmed_tool.py search --query-file q.txt --retmax 0", "--count", "1234"]
        )
        self.assertEqual(rc, 0)
        self.assertTrue(Path(self.manifest).exists())
        self.assertEqual(receipt["operation"], "manifest-add")
        self.assertEqual(receipt["added_seq"], 1)
        self.assertEqual(receipt["entry_count"], 1)

        data = self.load()
        for key in manifest_tool.TOP_LEVEL_KEYS:
            self.assertIn(key, data)
        self.assertEqual(data["skill"], "pubmed-search-builder")
        self.assertEqual(data["manifest_version"], "1.0")

        entry = data["entries"][0]
        self.assertEqual(entry["seq"], 1)
        self.assertEqual(entry["kind"], "search")
        self.assertEqual(entry["count"], 1234)
        self.assertIsInstance(entry["count"], int)
        self.assertIsNone(entry["output_path"])
        self.assertTrue(entry["timestamp_utc"].endswith("Z"))

    def test_seq_increments_and_updated_advances(self):
        for i in range(3):
            self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", f"cmd {i}"])
        data = self.load()
        self.assertEqual([e["seq"] for e in data["entries"]], [1, 2, 3])
        # updated_utc is refreshed on each add and is always >= created_utc (lexicographic on ISO-Z).
        self.assertGreaterEqual(data["updated_utc"], data["created_utc"])

    def test_supersedes_updates_superseded_index_and_entry(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "artifact",
                      "--command", "render audit", "--output", "audit_demo.md"])
        rc, _ = self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "artifact", "--command", "re-render audit",
             "--output", "audit_demo_2.md", "--supersedes", "audit_demo.md", "--note", "cleanup"]
        )
        self.assertEqual(rc, 0)
        data = self.load()
        self.assertEqual(data["entries"][-1]["supersedes"], "audit_demo.md")
        self.assertEqual(len(data["superseded"]), 1)
        sup = data["superseded"][0]
        self.assertEqual(sup["path"], "audit_demo.md")
        self.assertEqual(sup["superseded_by"], "audit_demo_2.md")
        self.assertEqual(sup["reason"], "cleanup")

    def test_supersede_path_not_previously_present_is_recorded(self):
        rc, _ = self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "artifact", "--command", "rename",
             "--output", "new.txt", "--supersedes", "never_seen.txt"]
        )
        self.assertEqual(rc, 0)
        data = self.load()
        self.assertEqual(data["superseded"][0]["path"], "never_seen.txt")

    def test_init_sets_metadata_and_refuses_to_clobber(self):
        rc1, _ = self.run_cli(["init", "--manifest", self.manifest, "--topic-slug", "demo", "--skill-version", "1.0.0"])
        self.assertEqual(rc1, 0)
        self.assertEqual(self.load()["topic_slug"], "demo")

        rc2, receipt2 = self.run_cli(["init", "--manifest", self.manifest])
        self.assertEqual(rc2, 1)  # default --if-exists fail
        self.assertIsNone(receipt2)  # error went to stderr, no receipt on stdout

    def test_init_if_exists_suffix_creates_sibling_file(self):
        self.run_cli(["init", "--manifest", self.manifest])
        rc, receipt = self.run_cli(["init", "--manifest", self.manifest, "--if-exists", "suffix"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.dir / "run_manifest_2.json").exists())
        self.assertTrue(receipt["manifest_path"].endswith("run_manifest_2.json"))

    def test_non_integer_count_rejected_without_creating_file(self):
        rc, _ = self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "lots"]
        )
        self.assertEqual(rc, 1)
        self.assertFalse(Path(self.manifest).exists())

    def test_unknown_kind_rejected(self):
        rc, _ = self.run_cli(["add", "--manifest", self.manifest, "--kind", "frobnicate", "--command", "cmd"])
        self.assertEqual(rc, 1)
        self.assertFalse(Path(self.manifest).exists())

    def test_show_validate_passes_for_clean_manifest(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "5"])
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["issues"], [])

    def test_show_validate_flags_non_int_count(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "cmd", "--count", "5"])
        data = self.load()
        data["entries"][0]["count"] = "lots"  # corrupt the manifest by hand
        Path(self.manifest).write_text(json.dumps(data), encoding="utf-8")
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 1)
        self.assertFalse(receipt["ok"])
        self.assertTrue(any("count is not an integer" in issue for issue in receipt["issues"]))

    def test_show_validate_check_files_flags_missing_outputs(self):
        existing = self.dir / "search.json"
        existing.write_text("{}", encoding="utf-8")
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "search", "--command", "ok", "--output", existing.name]
        )
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "search", "--command", "missing", "--output", "missing.json"]
        )

        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate", "--check-files"])

        self.assertEqual(rc, 1)
        issues = "\n".join(receipt["issues"])
        self.assertIn("output_path does not exist: missing.json", issues)
        self.assertNotIn(f"output_path does not exist: {existing.name}", issues)

    def test_add_stores_label_and_open_decision(self):
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "search", "--command", "search main",
             "--count", "100", "--label", "main strategy", "--open-decision"]
        )
        entry = self.load()["entries"][0]
        self.assertEqual(entry["label"], "main strategy")
        self.assertTrue(entry["open_decision"])

    def test_validate_kind_is_accepted(self):
        rc, _ = self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "validate", "--command", "validate seeds",
             "--output", "validate.json"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self.load()["entries"][0]["kind"], "validate")

    def test_sample_kind_is_first_class_record_content(self):
        rc, _ = self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "sample",
             "--command", "python scripts/pubmed_tool.py sample --query-file q.txt --output sample.json",
             "--output", "sample.json", "--label", "draft sample"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(self.load()["entries"][0]["kind"], "sample")

        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])

        rc, receipt = self.run_cli(["report", "--manifest", self.manifest])
        self.assertEqual(rc, 0)
        self.assertEqual(receipt["kind_counts"]["sample"], 1)
        self.assertEqual(receipt["entries_by_kind"]["sample"][0]["output_path"], "sample.json")

    def test_record_content_entries_require_output_path(self):
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "fetch",
             "--command", "python scripts/pubmed_tool.py fetch --pmids 1 --output fetch.json"]
        )
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 1)
        self.assertFalse(receipt["ok"])
        self.assertTrue(any("without an output_path" in issue for issue in receipt["issues"]))

    def test_record_content_command_history_rejects_summary_and_missing_output_option(self):
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "other",
             "--command", "python scripts/pubmed_tool.py mine --pmids 1 --summary --output mine.json",
             "--output", "mine.json"]
        )
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "other",
             "--command", "python scripts/pubmed_tool.py sample --query-file q.txt",
             "--output", "sample.json"]
        )
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 1)
        issues = "\n".join(receipt["issues"])
        self.assertIn("unsupported --summary", issues)
        self.assertIn("missing required --output", issues)

    def test_record_content_command_history_detects_absolute_paths_with_hyphens(self):
        command = (
            'python "C:\\Users\\aaron\\.codex\\skills\\pubmed-search-builder\\scripts\\pubmed_tool.py" '
            "fetch --pmids 1"
        )
        self.run_cli(
            ["add", "--manifest", self.manifest, "--kind", "other",
             "--command", command, "--output", "fetch.json"]
        )
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 1)
        self.assertTrue(any("missing required --output" in issue for issue in receipt["issues"]))

    def test_record_content_manifest_validation_accepts_saved_outputs(self):
        commands = {
            "fetch": "python scripts/pubmed_tool.py fetch --pmids 1 --output fetch.json",
            "mine": "python scripts/pubmed_tool.py mine --pmids 1 --output mine.json",
            "sample": "python scripts/pubmed_tool.py sample --query-file q.txt --output sample.json",
        }
        for kind, command in commands.items():
            self.run_cli(
                ["add", "--manifest", self.manifest, "--kind", kind,
                 "--command", command,
                 "--output", f"{kind}.json"]
            )
        rc, receipt = self.run_cli(["show", "--manifest", self.manifest, "--validate"])
        self.assertEqual(rc, 0)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["issues"], [])

    def test_report_groups_by_kind_and_surfaces_dashboard(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "main", "--count", "1200", "--label", "main strategy"])
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "block1", "--count", "500", "--label", "robopet block"])
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "recall", "--command", "recall", "--label", "relative recall", "--output", "recall.json"])
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "qa", "--command", "final-qa", "--label", "final qa", "--open-decision", "--note", "keep zero-hit term?"])
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "artifact", "--command", "render", "--output", "audit_demo.md"])
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "artifact", "--command", "re-render", "--output", "audit_demo_2.md", "--supersedes", "audit_demo.md"])

        rc, receipt = self.run_cli(["report", "--manifest", self.manifest])
        self.assertEqual(rc, 0)
        self.assertEqual(receipt["operation"], "manifest-report")
        self.assertEqual(receipt["kind_counts"]["search"], 2)
        self.assertEqual(receipt["kind_counts"]["artifact"], 2)
        labels = [e["label"] for e in receipt["entries_by_kind"]["search"]]
        self.assertIn("main strategy", labels)
        self.assertIn("robopet block", labels)
        self.assertEqual(receipt["audit_path"], "audit_demo_2.md")  # latest .md artifact is the current audit
        self.assertEqual(len(receipt["open_decisions"]), 1)
        self.assertEqual(receipt["open_decisions"][0]["kind"], "qa")
        self.assertEqual(receipt["superseded"][0]["path"], "audit_demo.md")
        self.assertEqual(receipt["superseded"][0]["superseded_by"], "audit_demo_2.md")

    def test_report_is_read_only(self):
        self.run_cli(["add", "--manifest", self.manifest, "--kind", "search", "--command", "x", "--count", "5"])
        before = Path(self.manifest).read_text(encoding="utf-8")
        rc, _ = self.run_cli(["report", "--manifest", self.manifest])
        self.assertEqual(rc, 0)
        self.assertEqual(Path(self.manifest).read_text(encoding="utf-8"), before)  # no reruns, no mutation


class ManifestConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.manifest = str(self.dir / "run_manifest.json")
        # write_json prints a receipt to stdout; silence it thread-safely
        # (contextlib.redirect_stdout patches global sys.stdout and is NOT thread-safe).
        original = manifest_tool.write_json
        manifest_tool.write_json = lambda data: None
        self.addCleanup(lambda: setattr(manifest_tool, "write_json", original))

    def test_parallel_adds_get_unique_sequential_seqs(self):
        n = 25
        barrier = threading.Barrier(n)
        errors = []

        def worker(i):
            barrier.wait()  # release all threads together to maximize contention
            try:
                self.assertEqual(
                    manifest_tool.main(
                        ["add", "--manifest", self.manifest, "--kind", "search", "--command", f"c{i}", "--count", str(i)]
                    ),
                    0,
                )
            except BaseException as exc:  # record; assert on the main thread after join
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        data = json.loads(Path(self.manifest).read_text(encoding="utf-8"))  # raises if the file was corrupted
        seqs = sorted(e["seq"] for e in data["entries"])
        self.assertEqual(len(data["entries"]), n)  # no lost entries
        self.assertEqual(seqs, list(range(1, n + 1)))  # unique + contiguous: no duplicate/colliding seq

    def test_atomic_write_failure_preserves_original_and_leaves_no_temp(self):
        manifest_tool.save_manifest(Path(self.manifest), manifest_tool.new_manifest("demo", "1.0.0"))
        before = Path(self.manifest).read_text(encoding="utf-8")
        with mock.patch.object(manifest_tool.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                manifest_tool.save_manifest(Path(self.manifest), manifest_tool.new_manifest("other", "9.9.9"))
        self.assertEqual(Path(self.manifest).read_text(encoding="utf-8"), before)  # original intact, not torn
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])  # temp cleaned up

    def test_lock_times_out_when_held(self):
        lock = Path(self.manifest + ".lock")
        lock.write_text("held", encoding="utf-8")  # a fresh (non-stale) lock
        with self.assertRaises(manifest_tool.ManifestError):
            with manifest_tool.manifest_lock(Path(self.manifest), timeout=0.2, stale=60.0):
                pass

    def test_lock_steals_stale_lock(self):
        lock = Path(self.manifest + ".lock")
        lock.write_text("held", encoding="utf-8")
        old = time.time() - 10_000
        os.utime(lock, (old, old))  # make the lock look abandoned by a crashed writer
        with manifest_tool.manifest_lock(Path(self.manifest), timeout=0.5, stale=1.0):
            pass  # steals the stale lock without raising
        self.assertFalse(lock.exists())  # released on exit


if __name__ == "__main__":
    unittest.main()
