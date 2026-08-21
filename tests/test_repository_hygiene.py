"""Repository hygiene policy remains enforceable in local tests and CI."""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "repository_hygiene.py"
SPEC = importlib.util.spec_from_file_location("repository_hygiene", MODULE_PATH)
repository_hygiene = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(repository_hygiene)


class RepositoryHygieneTests(unittest.TestCase):
    def test_repository_has_no_published_run_state_or_personal_paths(self):
        self.assertEqual(repository_hygiene.assess_repository(ROOT), [])

    def test_personal_path_patterns_cover_windows_unix_and_encoded_forms(self):
        samples = (
            "C:" + "/Users/" + "person/Downloads/private.txt",
            "C:" + "\\Users\\" + r"person\private.txt",
            "/" + "home/" + "person/private.txt",
            "/" + "Users/" + "person/private.txt",
            "C--" + "Users-" + "person--workspace",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(any(pattern.search(sample) for pattern in repository_hygiene.PERSONAL_PATH_PATTERNS))


if __name__ == "__main__":
    unittest.main()
