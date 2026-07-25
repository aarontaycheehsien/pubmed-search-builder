import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


generate = load_module("eval_generate_test", ROOT / "evals" / "generate.py")
run_eval = load_module("eval_run_eval_test", ROOT / "evals" / "run_eval.py")


class EvalHarnessTests(unittest.TestCase):
    def test_bundled_fixtures_use_structured_review_protocol(self):
        for path in sorted((ROOT / "evals" / "datasets").glob("**/*.json")):
            if path.name.endswith(".blocks.json"):
                continue
            fixture = json.loads(path.read_text(encoding="utf-8-sig"))
            with self.subTest(path=path):
                self.assertNotIn("protocol", fixture)
                protocol = fixture["review_protocol"]
                self.assertEqual(protocol["dsl_version"], 1)
                self.assertEqual(protocol["review"]["question"], fixture["question"])

    def test_isolated_workspace_excludes_answer_keys_and_uses_opaque_prompt_path(self):
        with tempfile.TemporaryDirectory() as td:
            skill_dir, run_dir = generate.isolated_run_workspace(ROOT, Path(td))
            self.assertTrue((skill_dir / "SKILL.md").is_file())
            self.assertTrue((skill_dir / "scripts" / "strategy_analysis.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "no_seed_discovery.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "vocabulary_learning.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "screening_burden.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "protocol_tool.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "revision_guard.py").is_file())
            self.assertTrue((skill_dir / "schemas" / "review-protocol.schema.json").is_file())
            self.assertFalse((skill_dir / "evals").exists())
            self.assertFalse((skill_dir / "tests").exists())
            self.assertNotIn("SECRET-FIXTURE", str(run_dir))
            fixture = {
                "id": "SECRET-FIXTURE",
                "question": "Does X improve Y?",
                "review_protocol": {
                    "dsl_version": 1,
                    "protocol_id": "opaque-protocol",
                    "seeds": {"records": []},
                    "priorities": {"recall": {"policy": "recall first"}},
                },
                "evaluation_gold_pmids": [11111111],
            }
            prompt = generate.build_prompt(fixture, run_dir)
            self.assertNotIn("SECRET-FIXTURE", prompt)
            self.assertNotIn("11111111", prompt)
            self.assertIn(run_dir.as_posix(), prompt)
            self.assertIn("REVIEW PROTOCOL DSL", prompt)
            saved_protocol = json.loads((run_dir / "review_protocol.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_protocol["protocol_id"], "opaque-protocol")

    def test_legacy_protocol_still_loads_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = {
                "question": "Does X improve Y?",
                "protocol": {"framework": "PICO", "seeds": "none"},
            }
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                prompt = generate.build_prompt(fixture, Path(td))
            self.assertTrue(any("deprecated" in str(item.message) for item in caught))
            self.assertIn("PICO", prompt)

    def test_candidate_evidence_pmids_separates_reviewed_from_mined(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "candidate_ledger.json").write_text(
                json.dumps(
                    {
                        "records": [
                            {"pmid": "1", "title_abstract_reviewed": True, "decision": "include", "use": "discovery"},
                            {"pmid": "2", "title_abstract_reviewed": True, "decision": "include", "use": "holdout"},
                            {"pmid": "3", "title_abstract_reviewed": False, "decision": "exclude", "use": "neither"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            reviewed, mined = generate.candidate_evidence_pmids(run_dir)
            self.assertEqual(reviewed, {"1", "2"})
            self.assertEqual(mined, {"1"})

    def test_score_reports_never_reviewed_recall(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fixture = base / "fixture.json"
            fixture.write_text(
                json.dumps(
                    {
                        "id": "opaque",
                        "suite": "test",
                        "question": "Question",
                        "evaluation_gold_pmids": [1, 2, 3],
                    }
                ),
                encoding="utf-8",
            )
            strategy = base / "strategy.txt"
            strategy.write_text("x[tiab]", encoding="utf-8")
            recall = {
                "retrieved_pmids": ["1", "2"],
                "missed_pmids": ["3"],
                "block_recall": [],
                "miss_diagnosis": [],
            }
            with (
                mock.patch.object(run_eval, "resolve_in_pubmed", return_value={"1", "2", "3"}),
                mock.patch.object(run_eval, "run_recall", return_value=recall),
                mock.patch.object(run_eval, "strategy_total_count", return_value=100),
            ):
                card = run_eval.score(
                    fixture,
                    ROOT / "scripts" / "pubmed_tool.py",
                    strategy_override=strategy,
                    seen_pmids={"1"},
                    mined_pmids={"1"},
                )
            self.assertEqual(card["gold_field"], "evaluation_gold_pmids")
            self.assertEqual(card["seen_evaluation"]["recall_percent"], 100.0)
            self.assertEqual(card["unseen_evaluation"]["recall_percent"], 50.0)
            self.assertEqual(card["unseen_evaluation"]["missed_pmids"], ["3"])

    def test_first_critic_strategy_resolves_snapshot_for_ablation(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            snapshot = run_dir / "strategy_v1.txt"
            snapshot.write_text("old[tiab]", encoding="utf-8")
            critic = run_dir / "critic_round_1.json"
            critic.write_text(json.dumps({"strategy_file": snapshot.name}), encoding="utf-8")
            (run_dir / "run_manifest.json").write_text(
                json.dumps({"build_state": {"critic_rounds": [{"artifact": critic.name}]}}),
                encoding="utf-8",
            )
            self.assertEqual(generate.first_critic_strategy(run_dir), snapshot)

    def test_first_critic_strategy_ignores_same_named_files_in_the_working_directory(self):
        """A leftover build in the CWD must not be scored as this run's pre-critic strategy."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cwd:
            decoy_dir = Path(cwd)
            (decoy_dir / "main_strategy.txt").write_text("unrelated[tiab]", encoding="utf-8")
            (decoy_dir / "critic_round_1.json").write_text(
                json.dumps({"strategy_file": "main_strategy.txt"}), encoding="utf-8"
            )
            run_dir = Path(td)
            (run_dir / "run_manifest.json").write_text(
                json.dumps({"build_state": {"critic_rounds": [{"artifact": "critic_round_1.json"}]}}),
                encoding="utf-8",
            )
            previous = os.getcwd()
            os.chdir(cwd)
            try:
                self.assertIsNone(generate.first_critic_strategy(run_dir))
            finally:
                os.chdir(previous)

    def test_candidate_evidence_ignores_a_ledger_outside_the_run(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
            stray = Path(other) / "candidate_ledger.json"
            stray.write_text(
                json.dumps({"records": [{"pmid": "999", "title_abstract_reviewed": True}]}),
                encoding="utf-8",
            )
            run_dir = Path(td)
            (run_dir / "run_manifest.json").write_text(
                json.dumps({"build_state": {"candidate_screening": {"artifact": str(stray)}}}),
                encoding="utf-8",
            )
            self.assertEqual(generate.candidate_evidence_pmids(run_dir), (set(), set()))

    def _score(self, base: Path, retrieved: list[str], strategy_text: str = "x[tiab]") -> dict:
        fixture = base / "fixture.json"
        fixture.write_text(
            json.dumps(
                {"id": "opaque", "suite": "test", "question": "Question", "evaluation_gold_pmids": [1, 2, 3]}
            ),
            encoding="utf-8",
        )
        strategy = base / "strategy.txt"
        strategy.write_text(strategy_text, encoding="utf-8")
        recall = {
            "retrieved_pmids": retrieved,
            "missed_pmids": [p for p in ("1", "2", "3") if p not in retrieved],
            "block_recall": [],
            "miss_diagnosis": [],
        }
        with (
            mock.patch.object(run_eval, "resolve_in_pubmed", return_value={"1", "2", "3"}),
            mock.patch.object(run_eval, "run_recall", return_value=recall),
            mock.patch.object(run_eval, "strategy_total_count", return_value=100),
        ):
            return run_eval.score(fixture, ROOT / "scripts" / "pubmed_tool.py", strategy_override=strategy)

    def test_scorecard_embeds_the_scored_query_and_its_hash(self):
        with tempfile.TemporaryDirectory() as td:
            card = self._score(Path(td), ["1", "2"], strategy_text="asthma[tiab]")
            self.assertEqual(card["strategy_query"], "asthma[tiab]")
            self.assertEqual(
                card["strategy_sha256"],
                hashlib.sha256("asthma[tiab]".encode("utf-8")).hexdigest(),
            )
            self.assertFalse(card["sanity"]["zero_recall"])

    def test_zero_recall_is_flagged_as_suspect(self):
        with tempfile.TemporaryDirectory() as td:
            card = self._score(Path(td), [])
            self.assertTrue(card["sanity"]["zero_recall"])
            self.assertTrue(card["sanity"]["warnings"])

    def test_zero_recall_scorecard_is_not_persisted_without_the_override(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            card = self._score(base, [])
            out = base / "scorecard.json"
            with mock.patch.object(run_eval, "score", return_value=card):
                code = run_eval.main([str(base / "fixture.json"), "--output", str(out)])
            self.assertEqual(code, 4)
            self.assertFalse(out.exists())

            with mock.patch.object(run_eval, "score", return_value=card):
                code = run_eval.main([str(base / "fixture.json"), "--output", str(out), "--allow-zero-recall"])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
