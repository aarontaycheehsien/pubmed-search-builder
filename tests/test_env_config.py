"""Trusted env-file selection and precedence."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pubmed_search_builder.infrastructure import env as env_config


class EnvConfigTests(unittest.TestCase):
    def tearDown(self):
        env_config.configure_env_file(None)
        env_config.reset_env_file_cache()

    def test_current_working_directory_env_is_not_loaded_implicitly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env").write_text("NCBI_TOOL=planted-workspace-value\n", encoding="utf-8")
            missing_default = root / "trusted" / ".env"
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(env_config, "DEFAULT_ENV_FILE", missing_default):
                    env_config.reset_env_file_cache()
                    self.assertEqual(env_config.env_file_values(), {})
            finally:
                os.chdir(previous)

    def test_explicit_env_file_is_loaded_and_quotes_are_removed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pubmed.env"
            path.write_text('NCBI_TOOL="explicit-tool"\n', encoding="utf-8")
            self.assertEqual(env_config.configure_env_file(path), path.resolve())
            with patch.dict(os.environ, {"NCBI_TOOL": ""}):
                self.assertEqual(env_config.read_env("NCBI_TOOL"), "explicit-tool")

    def test_process_environment_wins_over_file_values(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pubmed.env"
            path.write_text("NCBI_TOOL=file-tool\n", encoding="utf-8")
            env_config.configure_env_file(path)
            with patch.dict(os.environ, {"NCBI_TOOL": "process-tool"}):
                self.assertEqual(env_config.read_env("NCBI_TOOL"), "process-tool")

    def test_env_file_ignores_non_allowlisted_process_settings(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pubmed.env"
            path.write_text("CODEX_HOME=C:/untrusted\nNCBI_EMAIL=person@example.org\n", encoding="utf-8")
            env_config.configure_env_file(path)
            self.assertEqual(env_config.env_file_values(), {"NCBI_EMAIL": "person@example.org"})

    def test_missing_explicit_env_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "does not exist"):
                env_config.configure_env_file(Path(td) / "missing.env")


if __name__ == "__main__":
    unittest.main()
