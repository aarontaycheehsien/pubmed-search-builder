import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


pubmed_tool = _load("pubmed_tool")
audit_markdown = _load("audit_markdown")


def manifest(entries, **kw):
    base = {
        "manifest_version": "1.0",
        "skill": "pubmed-search-builder",
        "topic_slug": "demo",
        "created_utc": "2026-05-30T10:00:00Z",
        "updated_utc": "2026-05-31T12:00:00Z",
        "working_dir": ".",
        "entries": entries,
        "superseded": [],
    }
    base.update(kw)
    return base


class BuildScaffoldTests(unittest.TestCase):
    """Direct, network-free tests of the build_audit_scaffold projection."""

    def build(self, **kw):
        defaults = dict(
            topic_slug="",
            manifest_data=None,
            date_searched=None,
            final_search_data=None,
            strategy_text=None,
            validate_data=None,
            variants_data=None,
            seed_fetch_data=None,
            seed_mine_data=None,
            related_data=None,
            recall_data=None,
            seed_status="unknown",
            audit_workbook=None,
            sources={},
        )
        defaults.update(kw)
        return pubmed_tool.build_audit_scaffold(**defaults)

    def test_result_count_from_final_search(self):
        audit, _ = self.build(final_search_data={"count": 369, "query_translation": "x"})
        self.assertEqual(audit["result_count"], 369)

    def test_result_count_placeholder_when_no_final_search(self):
        audit, _ = self.build()
        self.assertTrue(str(audit["result_count"]).startswith("["))
        self.assertIn("count", str(audit["result_count"]))  # trigger word -> render refuses

    def test_date_from_manifest_search_entry_not_now(self):
        m = manifest([{"seq": 1, "kind": "search", "label": "main", "timestamp_utc": "2020-01-02T09:00:00Z", "output_path": None, "count": 5}])
        audit, _ = self.build(manifest_data=m)
        self.assertEqual(audit["date_searched"], "2020-01-02")

    def test_date_override_wins_over_manifest_search_entry(self):
        m = manifest([{"seq": 1, "kind": "search", "label": "main", "timestamp_utc": "2020-01-02T09:00:00Z", "output_path": None, "count": 5}])
        audit, _ = self.build(manifest_data=m, date_searched="2026-06-02")
        self.assertEqual(audit["date_searched"], "2026-06-02")

    def test_manifest_path_populates_reporting_notes(self):
        audit, _ = self.build(sources={"manifest": "run_manifest.json"})
        self.assertEqual(audit["reporting_notes"]["run_manifest"], "run_manifest.json")

    def test_count_authority_file_wins_over_manifest_count(self):
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / "final.json"
            fp.write_text(json.dumps({"count": 369}), encoding="utf-8")
            m = manifest([{"seq": 1, "kind": "search", "label": "main strategy", "timestamp_utc": "2026-05-31T11:00:00Z", "output_path": str(fp), "count": 999}])
            audit, _ = self.build(manifest_data=m)
            self.assertEqual(audit["pubmed_cli_checks"]["main strategy"], 369)

    def test_seed_validation_fills_and_miss_forces_reason(self):
        audit, _ = self.build(validate_data={"provided_pmids": ["1", "2"], "retrieved_pmids": ["1"], "missed_pmids": ["2"]})
        self.assertEqual(audit["seed_validation"]["retrieved"], ["1"])
        self.assertEqual(audit["seed_validation"]["missed"], ["2"])
        self.assertIn("reason", str(audit["seed_validation"]["reason_for_misses"]))  # forced placeholder

    def test_seed_validation_no_miss_sets_none(self):
        audit, _ = self.build(validate_data={"provided_pmids": ["1"], "retrieved_pmids": ["1"], "missed_pmids": []})
        self.assertEqual(audit["seed_validation"]["reason_for_misses"], "none")

    def test_seed_status_unknown_emits_placeholder_not_a_no_seed_guess(self):
        audit, _ = self.build(seed_status="unknown")
        self.assertIn("seed_pmids", audit)
        self.assertIn("pmid", str(audit["seed_pmids"][0]).lower())

    def test_seed_status_no_omits_seed_block(self):
        audit, _ = self.build(seed_status="no")
        self.assertNotIn("seed_pmids", audit)
        self.assertNotIn("seed_validation", audit)

    def test_never_fabricates_seed_derived_mesh(self):
        audit, _ = self.build(validate_data={"provided_pmids": ["1"], "retrieved_pmids": ["1"], "missed_pmids": []})
        self.assertNotIn("mesh_derived_from_seed_records", audit)

    def test_record_content_cites_path_never_attests_review(self):
        m = manifest([{"seq": 1, "kind": "fetch", "label": "seed fetch", "timestamp_utc": "2026-05-31T11:00:00Z", "output_path": "seeds.json", "count": None}])
        audit, _ = self.build(manifest_data=m)
        row = audit["record_content_evidence"][0]
        self.assertEqual(row["evidence_file_reviewed"], "seeds.json")
        self.assertEqual(row["receipt_only_stdout_used_as_decision_evidence"], "no")
        self.assertIn("record", str(row["record_content_reviewed"]).lower())  # placeholder, not "yes"
        self.assertIn("decision", str(row["decision_supported"]).lower())  # placeholder, not "yes"

    def test_judgment_fields_are_placeholders(self):
        audit, _ = self.build()
        self.assertIn("decision", str(audit["decision_ledger"][0]["decision_point"]).lower())
        self.assertTrue(all(str(v).startswith("[") for v in audit["rationale"].values()))
        self.assertTrue(str(audit["peer_review_attention_points"][0]).startswith("["))

    def test_variant_choice_from_decision_status_and_role(self):
        v = {"results": [
            {"label": "main", "count": 369, "decision_status": "selected", "role": "sensitive"},
            {"label": "focused", "count": 200, "role": "focused"},
        ]}
        audit, _ = self.build(variants_data=v)
        self.assertIn("main", audit["main_variant_chosen"])
        self.assertIn("focused", audit["focused_variant_count"])

    def test_degradation_missing_output_file_falls_back_no_crash(self):
        m = manifest([{"seq": 1, "kind": "search", "label": "main", "timestamp_utc": "2026-05-31T11:00:00Z", "output_path": "/no/such/file.json", "count": 42}])
        audit, _ = self.build(manifest_data=m)  # must not raise
        self.assertEqual(audit["pubmed_cli_checks"]["main"], 42)


    def test_zero_hit_phrases_aggregated_into_tiab(self):
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / "s.json"
            sp.write_text(
                json.dumps({"count": 3, "errors": {"phrasesnotfound": ['"robocat"']}, "warnings": {"quotedphrasesnotfound": ['"teleseal"']}}),
                encoding="utf-8",
            )
            m = manifest([{"seq": 1, "kind": "search", "label": "blk", "timestamp_utc": "2026-06-01T10:00:00Z", "output_path": str(sp), "count": 3}])
            audit, _ = self.build(manifest_data=m)
            removed = str(audit["tiab_expansion"]["zero_hit_terms_removed"])
            self.assertIn("robocat", removed)  # errorlist phrase
            self.assertIn("teleseal", removed)  # warninglist phrase
            self.assertIn("decision", removed)  # forced placeholder: blocks render until authored

    def test_tiab_zero_hit_placeholder_when_none_found(self):
        audit, _ = self.build()
        self.assertIn("tiab_expansion", audit)
        self.assertTrue(str(audit["tiab_expansion"]["zero_hit_terms_removed"]).startswith("["))

    def test_tiab_morphology_review_placeholder_is_scaffolded(self):
        audit, _ = self.build()
        review = audit["tiab_expansion"]["morphology_review"][0]

        self.assertIn("phrase_family", review)
        self.assertIn("decision", str(review["decision"]).lower())
        self.assertIn("wildcard", str(review["wildcard_candidate"]).lower())
        self.assertIn("phrase-anchored/concept-specific", str(review["wildcard_candidate"]).lower())

    def test_tiab_proximity_review_placeholders_are_scaffolded(self):
        audit, _ = self.build()
        expansion = audit["tiab_expansion"]

        self.assertIn("proximity_candidates_tested", expansion)
        self.assertIn("proximity_expressions_added", expansion)
        self.assertIn("proximity_expressions_tested_but_rejected", expansion)
        self.assertIn("proximity_not_applicable_rationale", expansion)
        self.assertIn("decision", str(expansion["proximity_candidates_tested"]).lower())

    def test_seed_fetch_populates_pre_gate_seed_triage_without_attesting_review(self):
        fetch_data = {
            "operation": "fetch",
            "requested_pmids": ["1", "2"],
            "found_pmids": ["1"],
            "missing_pmids": ["2"],
            "records": [
                {
                    "pmid": "1",
                    "title": "Robot pets in care homes",
                    "year": "2024",
                    "publication_types": ["Journal Article"],
                    "abstract": "Abstract text.",
                }
            ],
        }
        audit, _ = self.build(seed_fetch_data=fetch_data, sources={"seed_fetch": "seed_fetch.json"})
        triage = audit["pre_gate_seed_triage"]
        self.assertEqual(triage["requested_seed_entries"], ["1", "2"])
        self.assertEqual(triage["missing_not_found_pmids_excluded"], ["2"])
        self.assertEqual(triage["evidence_file_reviewed"], "seed_fetch.json")
        self.assertEqual(triage["fetched_seed_records"][0]["title"], "Robot pets in care homes")
        self.assertIn("record", str(triage["record_content_reviewed"]).lower())
        self.assertIn("decision", str(triage["likely_out_of_scope_seeds"]).lower())

    def test_related_json_populates_seed_set_expansion_with_use_placeholder(self):
        related = {
            "operation": "related",
            "links_used": ["similar", "citedin"],
            "max_per_seed": 10,
            "max_total": 50,
            "link_counts": {"similar": 20, "citedin": 4},
            "candidate_count": 12,
            "candidate_count_before_cap": 14,
            "candidate_pmids": [
                {"pmid": "999", "via": ["similar"], "seed_overlap_count": 2},
                {"pmid": "888", "via": ["citedin"], "seed_overlap_count": 1},
            ],
        }
        audit, _ = self.build(related_data=related)
        expansion = audit["seed_set_expansion"]
        self.assertEqual(expansion["links_used"], ["similar", "citedin"])
        self.assertEqual(expansion["candidate_count"], 12)
        self.assertEqual(expansion["high_overlap_candidate_pmids"], ["999 (seed_overlap_count=2; via=similar)"])
        self.assertIn("decision", str(expansion["how_related_set_evidence_was_used"]).lower())

    def test_recall_json_populates_relative_recall_mechanically(self):
        recall = {
            "operation": "recall",
            "benchmark_source": "benchmark-json: related",
            "benchmark_size": 10,
            "retrieved_count": 9,
            "missed_count": 1,
            "relative_recall_percent": 90.0,
            "retrieved_pmids": ["1", "2"],
            "missed_pmids": ["3"],
            "block_recall": [
                {"label": "robot pet block", "retrieved_count": 8, "recall_percent": 80.0, "bottleneck": True}
            ],
            "miss_diagnosis": [{"pmid": "3", "culprit_blocks": ["robot pet block"], "and_interaction": False}],
            "note": "relative, not absolute sensitivity",
        }
        audit, _ = self.build(recall_data=recall)
        rel = audit["relative_recall"]
        self.assertEqual(rel["relative_recall_percent"], 90.0)
        self.assertEqual(rel["bottleneck_block"], "robot pet block")
        self.assertEqual(rel["miss_diagnosis"][0]["pmid"], "3")


class ScaffoldCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def run_main(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = pubmed_tool.main(args)
        text = out.getvalue().strip()
        return rc, (json.loads(text) if text else None)

    def render(self, audit_path, md_path):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = audit_markdown.main([str(audit_path), "--output", str(md_path)])
        return rc

    def test_scaffold_then_render_blocks_until_judgment_filled(self):
        ap = self.dir / "audit.json"
        rc, receipt = self.run_main(["audit-scaffold", "--output", str(ap), "--topic-slug", "demo", "--seed-status", "no"])
        self.assertEqual(rc, 0)
        self.assertEqual(receipt["operation"], "audit-scaffold")
        self.assertTrue(ap.exists())

        # Mechanical fields filled, judgment placeholders present -> renderer must refuse.
        self.assertEqual(self.render(ap, self.dir / "blocked.md"), 1)

        # Author the judgment + the (no-source) mechanical placeholders, then render succeeds.
        a = json.loads(ap.read_text(encoding="utf-8"))
        a["result_count"] = 369
        a["final_strategy"] = "(a) AND (b)"
        a["date_searched"] = "2026-05-31"
        a["search_structure"] = {
            "framework": "PICO effectiveness",
            "concept_gate_status": "completed",
            "and_block_admission_summary": "two essential blocks",
            "methodological_filters_or_limits": "none",
        }
        a["decision_ledger"] = [{
            "decision_point": "Seed handling", "options_considered": "use/drop",
            "evidence_or_test_used": "fetch", "decision_made": "drop one",
            "rationale_or_recall_risk_note": "off-topic", "reflected_in_strategy_or_report": "seed validation",
        }]
        a["rationale"] = {k: "authored" for k in a["rationale"]}
        a["peer_review_attention_points"] = ["confirm scope"]
        a["reporting_notes"]["remaining_caveats"] = "single-database PubMed only"
        a["tiab_expansion"] = {"zero_hit_terms_removed": "none", "zero_hit_terms_kept": "none"}
        ap.write_text(json.dumps(a), encoding="utf-8")
        self.assertEqual(self.render(ap, self.dir / "ok.md"), 0)

    def test_if_exists_fail_protects_existing_then_suffix(self):
        ap = self.dir / "audit.json"
        rc1, _ = self.run_main(["audit-scaffold", "--output", str(ap), "--topic-slug", "demo", "--seed-status", "no"])
        self.assertEqual(rc1, 0)
        rc2, _ = self.run_main(["audit-scaffold", "--output", str(ap), "--topic-slug", "demo", "--seed-status", "no"])
        self.assertEqual(rc2, 1)  # default --if-exists fail does not clobber
        rc3, receipt3 = self.run_main(["audit-scaffold", "--output", str(ap), "--topic-slug", "demo", "--seed-status", "no", "--if-exists", "suffix"])
        self.assertEqual(rc3, 0)
        self.assertTrue(receipt3["output"].endswith("audit_2.json"))

    def test_scaffold_cli_accepts_date_override(self):
        ap = self.dir / "audit.json"
        rc, _ = self.run_main(
            ["audit-scaffold", "--output", str(ap), "--topic-slug", "demo", "--seed-status", "no", "--date-searched", "2026-06-02"]
        )
        self.assertEqual(rc, 0)
        audit = json.loads(ap.read_text(encoding="utf-8"))
        self.assertEqual(audit["date_searched"], "2026-06-02")

    def test_scaffold_cli_accepts_seed_related_and_recall_sources(self):
        fetch_path = self.dir / "seed_fetch.json"
        related_path = self.dir / "related.json"
        recall_path = self.dir / "recall.json"
        fetch_path.write_text(
            json.dumps(
                {
                    "operation": "fetch",
                    "requested_pmids": ["1"],
                    "found_pmids": ["1"],
                    "missing_pmids": [],
                    "records": [{"pmid": "1", "title": "Seed title", "year": "2024", "publication_types": ["Journal Article"]}],
                }
            ),
            encoding="utf-8",
        )
        related_path.write_text(
            json.dumps(
                {
                    "operation": "related",
                    "links_used": ["similar"],
                    "max_per_seed": 5,
                    "max_total": 20,
                    "link_counts": {"similar": 5},
                    "candidate_count": 2,
                    "candidate_count_before_cap": 2,
                    "candidate_pmids": [{"pmid": "9", "via": ["similar"], "seed_overlap_count": 2}],
                }
            ),
            encoding="utf-8",
        )
        recall_path.write_text(
            json.dumps(
                {
                    "operation": "recall",
                    "benchmark_source": "benchmark-json: related",
                    "benchmark_size": 2,
                    "retrieved_count": 1,
                    "missed_count": 1,
                    "relative_recall_percent": 50.0,
                    "retrieved_pmids": ["9"],
                    "missed_pmids": ["10"],
                }
            ),
            encoding="utf-8",
        )

        ap = self.dir / "audit.json"
        rc, receipt = self.run_main(
            [
                "audit-scaffold",
                "--output", str(ap),
                "--topic-slug", "demo",
                "--seed-fetch-json", str(fetch_path),
                "--related-json", str(related_path),
                "--recall-json", str(recall_path),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(receipt["sources_used"]["seed_fetch"], str(fetch_path))
        self.assertEqual(receipt["sources_used"]["related"], str(related_path))
        self.assertEqual(receipt["sources_used"]["recall"], str(recall_path))
        audit = json.loads(ap.read_text(encoding="utf-8"))
        self.assertIn("pre_gate_seed_triage", audit)
        self.assertIn("seed_set_expansion", audit)
        self.assertIn("relative_recall", audit)


class ZeroHitRenderTests(unittest.TestCase):
    def test_renderer_emits_zero_hit_rows(self):
        md = audit_markdown.render_audit_markdown(
            {"tiab_expansion": {"zero_hit_terms_removed": "robocat (removed, recall-neutral)", "zero_hit_terms_kept": "none"}}
        )
        self.assertIn("Zero-hit terms removed (documented):** robocat (removed, recall-neutral)", md)
        self.assertIn("Zero-hit terms kept after user choice:** none", md)


class ScaffoldConceptBlocksTests(unittest.TestCase):
    """concept_blocks population for the numbered line set (Phase #4)."""

    def build(self, **kw):
        defaults = dict(
            topic_slug="", manifest_data=None, date_searched=None, final_search_data=None,
            strategy_text=None, validate_data=None, variants_data=None, seed_fetch_data=None,
            seed_mine_data=None, related_data=None, recall_data=None, seed_status="unknown",
            audit_workbook=None, sources={},
        )
        defaults.update(kw)
        return pubmed_tool.build_audit_scaffold(**defaults)

    def test_blocks_populate_with_counts_matched_by_manifest_label(self):
        m = manifest([
            {"seq": 1, "kind": "search", "label": "Diabetes", "timestamp_utc": "2026-06-02T09:00:00Z", "output_path": None, "count": 612000},
            {"seq": 2, "kind": "search", "label": "Telehealth", "timestamp_utc": "2026-06-02T09:01:00Z", "output_path": None, "count": 410000},
        ])
        blocks = [
            {"label": "Diabetes", "query": '("Diabetes Mellitus, Type 2"[Mesh] OR diabet*[tiab])'},
            {"label": "Telehealth", "query": '("Telemedicine"[Mesh] OR telehealth[tiab])'},
        ]
        audit, _ = self.build(manifest_data=m, blocks_data=blocks)
        self.assertEqual(len(audit["concept_blocks"]), 2)
        self.assertEqual(audit["concept_blocks"][0]["count"], 612000)  # matched by label
        self.assertEqual(audit["concept_blocks"][1]["count"], 410000)
        self.assertEqual(audit["combination"], "1 AND 2")

    def test_block_without_manifest_match_has_no_count(self):
        blocks = [{"label": "Orphan", "query": "orphan[tiab]"}]
        audit, _ = self.build(blocks_data=blocks)
        self.assertNotIn("count", audit["concept_blocks"][0])

    def test_no_blocks_file_leaves_concept_blocks_absent(self):
        audit, _ = self.build()
        self.assertNotIn("concept_blocks", audit)

    def test_scaffolded_blocks_render_a_line_set(self):
        m = manifest([{"seq": 1, "kind": "search", "label": "A", "timestamp_utc": "2026-06-02T09:00:00Z", "output_path": None, "count": 100}])
        audit, _ = self.build(manifest_data=m, blocks_data=[{"label": "A", "query": "a[tiab]"}])
        md = audit_markdown.render_audit_markdown(audit, Path("audit.md"))
        self.assertIn("## Search strategy (numbered line set)", md)
        self.assertIn("a[tiab]", md)
        self.assertIn("100", md)


class NoSeedRecallScaffoldTests(unittest.TestCase):
    """The relative-recall scaffold block reflects the no-seed heuristic offer outcome."""

    def build(self, **kw):
        defaults = dict(
            topic_slug="", manifest_data=None, date_searched=None, final_search_data=None,
            strategy_text=None, validate_data=None, variants_data=None, seed_fetch_data=None,
            seed_mine_data=None, related_data=None, recall_data=None, seed_status="unknown",
            audit_workbook=None, sources={},
        )
        defaults.update(kw)
        return pubmed_tool.build_audit_scaffold(**defaults)

    def _recall(self):
        return {
            "benchmark_source": "benchmark-json",
            "benchmark_size": 40,
            "relative_recall_percent": 88.0,
            "retrieved_count": 35,
            "missed_count": 5,
            "block_recall": [{"label": "A", "recall_percent": 70, "bottleneck": True}],
            "note": "heuristic note",
        }

    def test_no_seed_done_labels_benchmark_as_heuristic(self):
        m = manifest([], build_state={"recall_offer": "done"})
        audit, _ = self.build(recall_data=self._recall(), seed_status="no", manifest_data=m)
        rr = audit["relative_recall"]
        self.assertEqual(rr["check_run"], "Yes (no-seed heuristic)")
        self.assertIn("no-seed pilot-expansion heuristic", rr["benchmark_source"])
        self.assertEqual(rr["bottleneck_block"], "A")

    def test_no_seed_declined_renders_as_deliberate_choice(self):
        m = manifest([], build_state={"recall_offer": "declined"})
        audit, _ = self.build(recall_data=None, seed_status="no", manifest_data=m)
        self.assertEqual(audit["relative_recall"]["check_run"], "Offered; declined by user")

    def test_no_seed_not_applicable(self):
        m = manifest([], build_state={"recall_offer": "not-applicable"})
        audit, _ = self.build(recall_data=None, seed_status="no", manifest_data=m)
        self.assertIn("Not applicable", audit["relative_recall"]["check_run"])

    def test_no_seed_pending_leaves_no_block(self):
        m = manifest([], build_state={"recall_offer": "pending"})
        audit, _ = self.build(recall_data=None, seed_status="no", manifest_data=m)
        self.assertNotIn("relative_recall", audit)

    def test_seeded_build_unaffected(self):
        audit, _ = self.build(recall_data=self._recall(), seed_status="yes")
        rr = audit["relative_recall"]
        self.assertEqual(rr["check_run"], "Yes")
        self.assertEqual(rr["benchmark_source"], "benchmark-json")


if __name__ == "__main__":
    unittest.main()
