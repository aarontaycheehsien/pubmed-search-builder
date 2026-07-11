import importlib.util
import json
import tempfile
import unittest
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
    def test_isolated_workspace_excludes_answer_keys_and_uses_opaque_prompt_path(self):
        with tempfile.TemporaryDirectory() as td:
            skill_dir, run_dir = generate.isolated_run_workspace(ROOT, Path(td))
            self.assertTrue((skill_dir / "SKILL.md").is_file())
            self.assertTrue((skill_dir / "scripts" / "strategy_analysis.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "no_seed_discovery.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "vocabulary_learning.py").is_file())
            self.assertTrue((skill_dir / "scripts" / "screening_burden.py").is_file())
            self.assertFalse((skill_dir / "evals").exists())
            self.assertFalse((skill_dir / "tests").exists())
            self.assertNotIn("SECRET-FIXTURE", str(run_dir))
            fixture = {
                "id": "SECRET-FIXTURE",
                "question": "Does X improve Y?",
                "protocol": {},
                "evaluation_gold_pmids": [11111111],
            }
            prompt = generate.build_prompt(fixture, run_dir)
            self.assertNotIn("SECRET-FIXTURE", prompt)
            self.assertNotIn("11111111", prompt)
            self.assertIn(run_dir.as_posix(), prompt)

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


if __name__ == "__main__":
    unittest.main()
