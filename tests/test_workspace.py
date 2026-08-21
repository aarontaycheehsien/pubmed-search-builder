"""Run-workspace anchoring: resolution stays inside the run, build state stays out of the install."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pubmed_search_builder.core.workspace import (  # noqa: E402
    ALLOW_SKILL_ROOT_ENV,
    WorkspaceError,
    guard_run_workspace,
    is_within,
    prepare_workspace,
    resolve_within,
    skill_root,
)


class ResolveWithinTests(unittest.TestCase):
    def test_relative_reference_resolves_against_the_run_root(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            target = run / "critic_round_1.json"
            target.write_text("{}", encoding="utf-8")
            self.assertEqual(resolve_within(run, "critic_round_1.json"), target.resolve())

    def test_absolute_reference_inside_the_run_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            target = run / "nested" / "strategy.txt"
            target.parent.mkdir()
            target.write_text("q", encoding="utf-8")
            self.assertEqual(resolve_within(run, str(target)), target.resolve())

    def test_absolute_reference_outside_the_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
            stray = Path(other) / "strategy.txt"
            stray.write_text("q", encoding="utf-8")
            self.assertIsNone(resolve_within(Path(td), str(stray)))

    def test_bare_filename_never_falls_back_to_the_working_directory(self):
        """The regression: a same-named leftover in the CWD must not resolve as run evidence."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cwd:
            decoy = Path(cwd) / "critic_round_1.json"
            decoy.write_text("{}", encoding="utf-8")
            previous = os.getcwd()
            os.chdir(cwd)
            try:
                self.assertIsNone(resolve_within(Path(td), "critic_round_1.json"))
            finally:
                os.chdir(previous)

    def test_missing_reference_is_searched_within_the_run_tree(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            nested = run / "a" / "b"
            nested.mkdir(parents=True)
            target = nested / "strategy_v1.txt"
            target.write_text("q", encoding="utf-8")
            self.assertEqual(resolve_within(run, "strategy_v1.txt"), target.resolve())

    def test_tree_search_is_deterministic_across_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            for folder in ("b", "a"):
                (run / folder).mkdir()
                (run / folder / "strategy.txt").write_text(folder, encoding="utf-8")
            first = resolve_within(run, "strategy.txt")
            self.assertEqual(first, resolve_within(run, "strategy.txt"))
            self.assertEqual(first.read_text(encoding="utf-8"), "a")

    def test_search_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            (run / "a").mkdir()
            (run / "a" / "strategy.txt").write_text("q", encoding="utf-8")
            self.assertIsNone(resolve_within(run, "strategy.txt", search=False))

    def test_must_exist_false_returns_a_planned_path_inside_the_run(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            planned = resolve_within(run, "not_written_yet.json", must_exist=False)
            self.assertEqual(planned, (run / "not_written_yet.json").resolve())

    def test_parent_traversal_cannot_escape_the_run(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            run.mkdir()
            (Path(td) / "outside.txt").write_text("q", encoding="utf-8")
            self.assertIsNone(resolve_within(run, "../outside.txt", search=False))

    def test_tree_search_rejects_a_file_symlink_that_escapes_the_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = root / "run"
            run.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            link = run / "nested" / "outside.txt"
            link.parent.mkdir()
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")
            self.assertIsNone(resolve_within(run, "outside.txt"))


class IsWithinTests(unittest.TestCase):
    def test_root_itself_and_descendants_are_within(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertTrue(is_within(root, root))
            self.assertTrue(is_within(root / "a" / "b", root))

    def test_sibling_is_not_within(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            root.mkdir()
            self.assertFalse(is_within(Path(td) / "other", root))


class GuardRunWorkspaceTests(unittest.TestCase):
    def test_build_state_in_the_skill_install_is_refused(self):
        with self.assertRaises(WorkspaceError) as ctx:
            guard_run_workspace(skill_root() / "run_manifest.json", what="a run manifest")
        self.assertIn("run workspace", str(ctx.exception))

    def test_a_run_workspace_under_the_install_is_allowed(self):
        resolved = guard_run_workspace(skill_root() / "runs" / "demo" / "run_manifest.json")
        self.assertEqual(resolved, (skill_root() / "runs" / "demo" / "run_manifest.json").resolve())

    def test_paths_outside_the_install_are_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "run_manifest.json"
            self.assertEqual(guard_run_workspace(target), target.resolve())

    def test_explicit_override_permits_the_install_directory(self):
        target = skill_root() / "run_manifest.json"
        self.assertEqual(guard_run_workspace(target, allow_skill_root=True), target.resolve())

    def test_environment_override_permits_the_install_directory(self):
        target = skill_root() / "run_manifest.json"
        previous = os.environ.get(ALLOW_SKILL_ROOT_ENV)
        os.environ[ALLOW_SKILL_ROOT_ENV] = "1"
        try:
            self.assertEqual(guard_run_workspace(target), target.resolve())
        finally:
            if previous is None:
                os.environ.pop(ALLOW_SKILL_ROOT_ENV, None)
            else:
                os.environ[ALLOW_SKILL_ROOT_ENV] = previous


class PrepareWorkspaceTests(unittest.TestCase):
    def test_no_workspace_leaves_the_target_unchanged(self):
        self.assertEqual(prepare_workspace(None, "run_manifest.json"), Path("run_manifest.json"))

    def test_workspace_is_created_and_the_target_resolves_inside_it(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "runs" / "demo"
            resolved = prepare_workspace(workspace, "run_manifest.json")
            self.assertTrue(workspace.is_dir())
            self.assertEqual(resolved, workspace / "run_manifest.json")

    def test_absolute_target_outside_the_workspace_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td) / "runs" / "demo"
            with self.assertRaises(WorkspaceError):
                prepare_workspace(workspace, Path(td) / "elsewhere.json")


if __name__ == "__main__":
    unittest.main()
