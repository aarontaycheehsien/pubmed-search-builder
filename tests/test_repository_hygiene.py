import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "repository_hygiene.py"


class RepositoryHygieneTests(unittest.TestCase):
    def test_current_tracked_repository_is_clean(self):
        result = subprocess.run(
            [sys.executable, str(TOOL)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["issues"], [])


if __name__ == "__main__":
    unittest.main()
