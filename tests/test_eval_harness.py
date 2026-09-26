import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
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


def write_critic_round(run_dir: Path, *, reviewed: str, absolute: bool = False) -> None:
    """Lay out critic round 1 the way critic_tool.py and manifest_tool.py record it."""
    strategy = run_dir / "strategy.txt"
    strategy.write_text(reviewed, encoding="utf-8")
    bundle = run_dir / "critic_bundle_r1.json"
    bundle.write_text(
        json.dumps(
            {
                "bundle_version": 1,
                "artifacts": [
                    {"role": "strategy", "path": str(strategy), "sha256": hashlib.sha256(reviewed.encode("utf-8")).hexdigest()}
                ],
            }
        ),
        encoding="utf-8",
    )
    critic = run_dir / "critic_round_1.json"
    critic.write_text(json.dumps({"strategy_file": "strategy.txt", "evidence_bundle": bundle.name}), encoding="utf-8")
    artifact = str(critic) if absolute else critic.name
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"build_state": {"critic_rounds": [{"artifact": artifact}]}}), encoding="utf-8"
    )


def record_final_search(run_dir: Path, searched: str) -> None:
    """Add the final topic-only search entry the completion gate binds, unless one is recorded."""
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    entries = manifest.setdefault("entries", [])
    if any(generate.manifest_tool.looks_like_final_topic_search(entry) for entry in entries):
        return
    digest = hashlib.sha256((run_dir / searched).read_bytes()).hexdigest()
    entries.append(
        {"seq": len(entries) + 1, "kind": "search", "label": "Final topic-only strategy", "count": 10,
         "command": f"pubmed_tool.py search --query-file {searched}", "input_sha256": {searched: digest}}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


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

    def test_pmids_given_to_the_skill_never_count_as_unseen(self):
        """A development or protocol-seed PMID in gold was shown to the skill by construction."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fixture = base / "fixture.json"
            fixture.write_text(
                json.dumps(
                    {
                        "id": "opaque",
                        "suite": "test",
                        "question": "Question",
                        "evaluation_gold_pmids": [1, 2, 3, 4],
                        "development_pmids_given_to_skill": [1],
                        "review_protocol": {"seeds": {"records": [{"pmid": "2", "role": "discovery-candidate"}]}},
                    }
                ),
                encoding="utf-8",
            )
            strategy = base / "strategy.txt"
            strategy.write_text("x[tiab]", encoding="utf-8")
            recall = {"retrieved_pmids": ["1", "2", "3"], "missed_pmids": ["4"], "block_recall": [], "miss_diagnosis": []}
            with (
                mock.patch.object(run_eval, "resolve_in_pubmed", return_value={"1", "2", "3", "4"}),
                mock.patch.object(run_eval, "run_recall", return_value=recall),
                mock.patch.object(run_eval, "strategy_total_count", return_value=100),
            ):
                card = run_eval.score(fixture, ROOT / "scripts" / "pubmed_tool.py", strategy_override=strategy, seen_pmids=set())
            self.assertEqual(card["unseen_evaluation"]["gold_in_pubmed"], 2)
            self.assertEqual(card["unseen_evaluation"]["recall_percent"], 50.0)
            self.assertEqual(card["seen_evaluation"]["gold_in_pubmed"], 2)

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

    def test_first_critic_strategy_rejects_a_snapshot_revised_after_the_critic(self):
        """The ablation's "before" must be the content the critic reviewed, not the file's later state."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            write_critic_round(run_dir, reviewed="old[tiab]")
            self.assertEqual(generate.first_critic_strategy(run_dir), run_dir / "strategy.txt")
            (run_dir / "strategy.txt").write_text("revised[tiab]", encoding="utf-8")
            self.assertIsNone(generate.first_critic_strategy(run_dir))

    def _generate(self, run_dir: Path, agent_files, *, cards: dict | None = None, argv: list[str] | None = None):
        """Drive generate.main() with a fake Codex run that writes ``agent_files(agent_run_dir)``."""
        fixture = run_dir.parent / "fixture.json"
        fixture.write_text(
            json.dumps({"id": "opaque", "question": "Q", "review_protocol": {"dsl_version": 1}, "evaluation_gold_pmids": [1]}),
            encoding="utf-8",
        )

        def fake_run_skill(prompt, *, run_dir, **kwargs):
            self.run_skill_kwargs = kwargs
            agent_files(run_dir)
            if not (run_dir / "events.jsonl").exists():
                (run_dir / "events.jsonl").write_text("", encoding="utf-8")
            if (run_dir / "final_strategy.txt").exists():
                record_final_search(run_dir, "final_strategy.txt")
            return {"returncode": 0, "last_message": "", "stderr": ""}

        scored: list[str] = []
        self.score_kwargs: list[dict] = []

        def fake_score(_fixture, _tool, *, strategy_override, **kwargs):
            text = Path(strategy_override).read_text(encoding="utf-8")
            scored.append(text)
            self.score_kwargs.append(kwargs)
            return (cards or {}).get(text) or {
                "unseen_evaluation": {"recall_percent": 50.0}, "strategy_total_hits": 10, "sanity": {"zero_recall": False},
            }

        with (
            mock.patch.object(generate.codex, "run_skill", side_effect=fake_run_skill),
            mock.patch.object(generate, "completion_gate", return_value=(True, {"ok": True})),
            mock.patch.object(generate.run_eval, "score", side_effect=fake_score),
            mock.patch.object(generate.run_eval, "render", return_value=""),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = generate.main([str(fixture), "--run-dir", str(run_dir), *(argv or [])])
        return code, scored

    def test_a_reused_run_dir_is_refused_so_stale_artifacts_are_not_scored(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            run_dir.mkdir()
            (run_dir / "final_strategy.txt").write_text("stale[tiab]", encoding="utf-8")
            with self.assertRaises(SystemExit):
                self._generate(run_dir, lambda agent_dir: None)

    def test_ablation_delta_is_undefined_when_no_gold_went_unreviewed(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"

            def agent_files(agent_dir: Path) -> None:
                write_critic_round(agent_dir, reviewed="old[tiab]")
                (agent_dir / "final_strategy.txt").write_text("new[tiab]", encoding="utf-8")

            no_unseen = {"unseen_evaluation": {"recall_percent": None}, "strategy_total_hits": 10, "sanity": {"zero_recall": False}}
            code, scored = self._generate(run_dir, agent_files, cards={"old[tiab]": no_unseen, "new[tiab]": no_unseen})
            self.assertEqual(code, 0)
            self.assertEqual(scored, ["new[tiab]", "old[tiab]"])
            ablation = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))["critic_ablation"]
            self.assertTrue(ablation["available"])
            self.assertIsNone(ablation["unseen_recall_delta"])

    def test_ablation_survives_absolute_paths_into_the_deleted_agent_workspace(self):
        """Agents record absolute paths in the temporary workspace, which is gone by scoring time."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"

            def agent_files(agent_dir: Path) -> None:
                write_critic_round(agent_dir, reviewed="old[tiab]", absolute=True)
                (agent_dir / "final_strategy.txt").write_text("new[tiab]", encoding="utf-8")

            code, scored = self._generate(run_dir, agent_files)
            self.assertEqual(code, 0)
            self.assertEqual(scored, ["new[tiab]", "old[tiab]"])
            ablation = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))["critic_ablation"]
            self.assertTrue(ablation["available"])
            self.assertEqual(Path(ablation["before_strategy"]), run_dir / "strategy.txt")

    def test_seen_pmids_come_from_the_manifest_ledger_even_when_its_path_is_absolute(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"

            def agent_files(agent_dir: Path) -> None:
                ledger = agent_dir / "candidate_ledger_v1.json"
                ledger.write_text(
                    json.dumps({"scope_version": 1, "records": [{"pmid": "1", "title_abstract_reviewed": True}]}),
                    encoding="utf-8",
                )
                # A second same-scope ledger (an earlier draft) is only disambiguated by the manifest.
                (agent_dir / "candidate_ledger_draft.json").write_text(
                    json.dumps({"scope_version": 1, "records": [{"pmid": "9", "title_abstract_reviewed": True}]}),
                    encoding="utf-8",
                )
                (agent_dir / "run_manifest.json").write_text(
                    json.dumps({"build_state": {"candidate_screening": {"artifact": str(ledger)}}}), encoding="utf-8"
                )
                (agent_dir / "final_strategy.txt").write_text("new[tiab]", encoding="utf-8")

            code, _scored = self._generate(run_dir, agent_files)
            self.assertEqual(code, 0)
            self.assertEqual(self.score_kwargs[0]["seen_pmids"], {"1"})

    def test_a_driver_timeout_is_a_failed_run_not_a_crash(self):
        """Seen in the audit's E2E run: TimeoutExpired escaped and the workspace was discarded."""
        with tempfile.TemporaryDirectory() as td:
            timeout = subprocess.TimeoutExpired(["codex"], 5, stderr=b"partial")
            with mock.patch.object(generate.codex.subprocess, "run", side_effect=timeout) as run:
                result = generate.codex.run_skill("p", skill_dir=Path(td), run_dir=Path(td), codex_bin="codex", timeout=5)
            self.assertEqual(run.call_count, 1)  # never relaunched
            self.assertTrue(result["timed_out"])
            self.assertNotEqual(result["returncode"], 0)
            self.assertIn("timed out", result["stderr"])

            run_dir = Path(td) / "run"
            fixture = Path(td) / "fixture.json"
            fixture.write_text(json.dumps({"id": "opaque", "question": "Q", "review_protocol": {"dsl_version": 1}}), encoding="utf-8")

            def timed_out_run(prompt, *, run_dir, **_kwargs):
                (run_dir / "final_strategy.txt").write_text("partial[tiab]", encoding="utf-8")
                return {"returncode": 124, "timed_out": True, "last_message": "", "stderr": "timed out"}

            with (
                mock.patch.object(generate.codex, "run_skill", side_effect=timed_out_run),
                mock.patch.object(generate.run_eval, "score") as score,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = generate.main([str(fixture), "--run-dir", str(run_dir)])
            self.assertEqual(code, 2)
            score.assert_not_called()
            self.assertTrue((run_dir / "final_strategy.txt").is_file())  # partial artifacts kept for diagnosis

    @unittest.skipUnless(os.name == "nt", "Windows ACL behaviour")
    def test_agent_workspace_grants_the_harness_user_access(self):
        """Seen in the audit's E2E run: an owner-only mkdtemp ACL left sandbox-written files unreadable."""
        user = os.environ.get("USERNAME", "")
        with generate.agent_temp_root() as root:
            acl = subprocess.run(["icacls", str(root)], capture_output=True, text=True).stdout
            self.assertIn(f"\\{user}:".casefold(), acl.casefold())
        self.assertFalse(root.exists())

    def test_a_final_strategy_file_other_than_the_gated_search_is_not_scored(self):
        """The gate binds the searched strategy; the harness scores final_strategy.txt. They must agree."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"

            def agent_files(agent_dir: Path) -> None:
                (agent_dir / "strategy_v3.txt").write_text("revised[tiab]", encoding="utf-8")
                record_final_search(agent_dir, "strategy_v3.txt")
                (agent_dir / "final_strategy.txt").write_text("earlier[tiab]", encoding="utf-8")

            code, scored = self._generate(run_dir, agent_files)
            self.assertEqual(code, 3)
            self.assertEqual(scored, [])

    def test_the_same_strategy_saved_under_another_name_is_scored(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"

            def agent_files(agent_dir: Path) -> None:
                (agent_dir / "strategy_v3.txt").write_text("revised[tiab]\n", encoding="utf-8")
                record_final_search(agent_dir, "strategy_v3.txt")
                (agent_dir / "final_strategy.txt").write_text("revised[tiab]", encoding="utf-8")

            code, scored = self._generate(run_dir, agent_files)
            self.assertEqual(code, 0)
            self.assertEqual(scored, ["revised[tiab]"])

    def _transcript(self, path: Path, items: list[dict]) -> Path:
        path.write_text(
            "\n".join(json.dumps({"type": "item.completed", "item": item}) for item in items), encoding="utf-8"
        )
        return path

    def test_leakage_scan_flags_reaching_the_answer_key(self):
        fixture = {"id": "CD000001", "evaluation_gold_pmids": [12345678, 23456789], "development_pmids_given_to_skill": [23456789]}
        with tempfile.TemporaryDirectory() as td:
            events = self._transcript(
                Path(td) / "events.jsonl",
                [
                    {"type": "command_execution", "command": "Get-Content ..\\evals\\datasets\\x\\CD000001.json", "aggregated_output": ""},
                    {"type": "command_execution", "command": "pubmed_tool.py fetch --pmids 12345678", "aggregated_output": ""},
                    {"type": "command_execution", "command": "pubmed_tool.py fetch --pmids 23456789", "aggregated_output": ""},
                ],
            )
            scan = generate.leakage_scan(events, fixture, Path(td) / "CD000001.json")
        self.assertFalse(scan["clean"])
        self.assertTrue(any("evals\\datasets" in ref for ref in scan["repository_references"]))
        # A PMID given to the skill is not leakage; an unseen gold PMID typed from nowhere is.
        self.assertEqual([item["pmid"] for item in scan["gold_used_before_discovery"]], ["12345678"])

    def test_leakage_scan_accepts_gold_the_agent_discovered(self):
        fixture = {"id": "CD000001", "evaluation_gold_pmids": [12345678]}
        with tempfile.TemporaryDirectory() as td:
            events = self._transcript(
                Path(td) / "events.jsonl",
                [
                    {"type": "command_execution", "command": "pubmed_tool.py search --query-file q.txt", "aggregated_output": '{"pmids": ["112345678", "12345678"]}'},
                    {"type": "command_execution", "command": "pubmed_tool.py fetch --pmids 12345678", "aggregated_output": ""},
                ],
            )
            scan = generate.leakage_scan(events, fixture, Path(td) / "CD000001.json")
        self.assertTrue(scan["clean"], scan)
        self.assertEqual(scan["actions_scanned"], 2)

    def test_a_leaking_run_writes_its_scorecard_but_is_not_a_measurement(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"

            def agent_files(agent_dir: Path) -> None:
                (agent_dir / "final_strategy.txt").write_text("x[tiab]", encoding="utf-8")
                self._transcript(
                    agent_dir / "events.jsonl",
                    [{"type": "command_execution", "command": "type evals/datasets/fixture.json", "aggregated_output": ""}],
                )

            code, _scored = self._generate(run_dir, agent_files)
            self.assertEqual(code, 5)
            card = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))
            self.assertFalse(card["leakage_scan"]["clean"])

    def test_a_relaunch_starts_from_the_staged_files_only(self):
        """A transient failure late in a build leaves a partial manifest; attempt 2 must not inherit it."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "prompt.txt").write_text("p", encoding="utf-8")
            seen_on_relaunch = {}
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                if len(calls) == 1:
                    (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
                    (run_dir / "protocol_v1").mkdir()
                    (run_dir / "protocol_v1" / "compiled.json").write_text("{}", encoding="utf-8")
                    return subprocess.CompletedProcess(cmd, 1, stdout=None, stderr="windows sandbox: timed out connecting runner pipe-in")
                seen_on_relaunch["files"] = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*"))
                return subprocess.CompletedProcess(cmd, 0, stdout=None, stderr="")

            with mock.patch.object(generate.codex.subprocess, "run", side_effect=fake_run):
                result = generate.codex.run_skill("p", skill_dir=run_dir, run_dir=run_dir, codex_bin="codex")
            self.assertEqual(result["attempts"], 2)
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(seen_on_relaunch["files"], ["events.jsonl", "prompt.txt"])

    def test_generation_defaults_to_a_two_hour_budget_and_records_elapsed_time(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            code, _scored = self._generate(
                run_dir, lambda agent_dir: (agent_dir / "final_strategy.txt").write_text("x[tiab]", encoding="utf-8")
            )
            self.assertEqual(code, 0)
            self.assertEqual(self.run_skill_kwargs["timeout"], 7200)
            card = json.loads((run_dir / "scorecard.json").read_text(encoding="utf-8"))
            self.assertIsInstance(card["elapsed_seconds"], int)

    def test_a_codex_failure_records_the_reason_codex_gave(self):
        """Seen in the Phase 3 build: codex exec exited 1 with no final message and empty stderr; the
        reason (a usage limit) was only in the event stream."""
        limit = "You've hit your usage limit. Try again at 4:58 AM."
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            fixture = Path(td) / "fixture.json"
            fixture.write_text(json.dumps({"id": "opaque", "question": "Q", "review_protocol": {"dsl_version": 1}}), encoding="utf-8")

            def failed_run(prompt, *, run_dir, **_kwargs):
                self._transcript(
                    run_dir / "events.jsonl",
                    [{"type": "command_execution", "command": "python scripts/critic_tool.py --run-independent", "aggregated_output": ""}],
                )
                with (run_dir / "events.jsonl").open("a", encoding="utf-8") as events:
                    events.write("\n" + json.dumps({"type": "error", "message": "Reconnecting... 1/5"}))
                    events.write("\n" + json.dumps({"type": "turn.failed", "error": {"message": limit}}))
                return {"returncode": 1, "last_message": "", "stderr": ""}

            out = io.StringIO()
            with (
                mock.patch.object(generate.codex, "run_skill", side_effect=failed_run),
                mock.patch.object(generate.run_eval, "score") as score,
                contextlib.redirect_stdout(out),
            ):
                code = generate.main([str(fixture), "--run-dir", str(run_dir)])
            self.assertEqual(code, 2)
            score.assert_not_called()
            failure = json.loads((run_dir / "failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["codex_error"], limit)
            self.assertIn(limit, out.getvalue())

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
