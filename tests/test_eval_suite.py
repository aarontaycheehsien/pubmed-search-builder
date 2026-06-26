import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "evals" / "run_suite.py"
SPEC = importlib.util.spec_from_file_location("run_suite", MODULE_PATH)
run_suite = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(run_suite)


class EvalSuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.fixture = self.dir / "TOPIC1.json"
        self.strategy = self.dir / "TOPIC1.strategy.txt"
        self.blocks = self.dir / "TOPIC1.blocks.json"
        self.cache = self.dir / "cache"
        self.tool = ROOT / "scripts" / "pubmed_tool.py"
        self.strategy.write_text('("Asthma"[Mesh] OR asthma[tiab])', encoding="utf-8")
        self.blocks.write_text(json.dumps([{"label": "Asthma", "query": "asthma[tiab]"}]), encoding="utf-8")
        self.fixture.write_text(
            json.dumps(
                {
                    "id": "TOPIC1",
                    "suite": "unit",
                    "question": "Asthma in children",
                    "strategy_file": self.strategy.name,
                    "blocks_file": self.blocks.name,
                    "gold_relevant_pmids": ["1", "2"],
                }
            ),
            encoding="utf-8",
        )

    def write_cached_scorecard(self):
        key = run_suite.cache_key(self.fixture, self.strategy, self.blocks, self.tool)
        self.cache.mkdir(parents=True, exist_ok=True)
        path = self.cache / f"{key}.json"
        card = {
            "id": "TOPIC1",
            "suite": "unit",
            "fixture": str(self.fixture),
            "status": "scored",
            "recall_reachable_percent": 75.0,
            "strategy_total_hits": 40,
            "nnr_proxy": 20,
        }
        path.write_text(json.dumps(card), encoding="utf-8")
        return path

    def test_cached_only_reports_miss_without_network_call(self):
        card = run_suite.score_or_cache(
            self.fixture,
            self.tool,
            self.cache,
            refresh=False,
            cached_only=True,
        )

        self.assertEqual(card["status"], "skipped")
        self.assertIn("cache miss", card["reason"])

    def test_cached_scorecard_hit_feeds_aggregate(self):
        cache_path = self.write_cached_scorecard()

        card = run_suite.score_or_cache(
            self.fixture,
            self.tool,
            self.cache,
            refresh=False,
            cached_only=True,
        )
        summary = run_suite.aggregate([card])

        self.assertEqual(card["cache"]["status"], "hit")
        self.assertEqual(card["cache"]["path"], str(cache_path))
        self.assertEqual(summary["scored_count"], 1)
        self.assertEqual(summary["mean_recall_reachable_percent"], 75.0)
        self.assertEqual(summary["mean_nnr_proxy"], 20.0)

    def test_cli_cached_only_outputs_json(self):
        self.write_cached_scorecard()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = run_suite.main(
                [
                    "--topic",
                    str(self.fixture),
                    "--pubmed-tool",
                    str(self.tool),
                    "--cache-dir",
                    str(self.cache),
                    "--cached-only",
                    "--json",
                ]
            )

        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["summary"]["fixture_count"], 1)
        self.assertEqual(result["summary"]["scored_count"], 1)


if __name__ == "__main__":
    unittest.main()
