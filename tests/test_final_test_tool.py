import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import final_test_tool as tool
import candidate_ledger
import pubmed_tool
import critic_tool
import audit_markdown
from test_protocol_tool import valid_protocol
import protocol_tool


class FinalTestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.protocol = self.root / 'protocol.json'
        self.save(self.protocol, valid_protocol())
        self.strategy = self.root / 'strategy.txt'
        self.strategy.write_text('allocation[tiab]')
        self.development = self.root / 'development.json'
        self.test_ledger = self.root / 'private_candidates.json'
        self.save(self.development, self.ledger(['1', '2']))
        self.save(self.test_ledger, self.ledger(['3', '4']))
        self.sealed = self.root / 'custodian' / 'sealed.json'
        self.receipt = self.root / 'receipt.json'
        self.frozen = self.root / 'frozen.json'
        self.result = self.root / 'result.json'
        self.manifest = self.root / 'manifest.json'
        inputs = {str(self.strategy): tool.digest(self.strategy)}
        self.save(self.manifest, {
            'build_state': {'candidate_screening': {'artifact': str(self.development)}},
            'entries': [{'kind': 'search', 'input_sha256': inputs},
                        {'kind': 'qa', 'command': 'hooks_tool.py final-qa', 'input_sha256': inputs}],
        })

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def ledger(self, pmids):
        protocol = tool.read(self.protocol)
        return {
            'artifact_type': 'candidate-ledger', 'artifact_version': 1, 'dsl_version': 1,
            'protocol_id': protocol['protocol_id'], 'scope_version': 1,
            'generated_from': {'sha256': protocol_tool.canonical_sha256(protocol)},
            'records': [{'pmid': p, 'provenance': 'prior-review', 'decision': 'include',
                         'use': 'development-validation', 'eligibility_reason': 'eligible',
                         'title_abstract_reviewed': True,
                         'screening': {'decided_by': 'human', 'rubric_sha256': 'rubric', 'record_sha256': p}}
                        for p in pmids],
        }

    def seal_and_freeze(self):
        public = tool.seal(self.test_ledger, self.protocol, self.sealed, self.receipt,
                           custodian='independent-reviewer', unseen_by_builder=True)
        with patch('manifest_tool.complete_loop_readiness', return_value=[]):
            tool.freeze(self.strategy, self.protocol, self.development, self.receipt, self.manifest, self.frozen)
        return public

    @staticmethod
    def search(client, query, retmax, retstart, sort):
        return {'pmids': ['3'] if 'allocation[tiab]' in query else ['3', '4'], 'warnings': {}, 'errors': {}}

    def test_aggregate_one_time_result_and_audit(self):
        public = self.seal_and_freeze()
        self.assertNotIn('records', public)
        self.assertNotIn('pmids', public)
        with patch.object(pubmed_tool, 'esearch', side_effect=self.search):
            result = tool.evaluate(self.sealed, self.frozen, self.result, client=object())
        self.assertEqual(result['recall'], .5)
        self.assertEqual(result['missed_records'], 1)
        self.assertNotIn('missed_pmids', result)
        self.assertTrue(tool.verify(self.result)['ok'])
        report = audit_markdown.render_audit_markdown({'final_test_result_file': str(self.result)})
        self.assertIn('1 / 2', report)
        with self.assertRaisesRegex(tool.FinalTestError, 'consumed'):
            tool.evaluate(self.sealed, self.frozen, self.root / 'rerun.json', client=object())

    def test_strategy_change_before_evaluation_rejected_without_request(self):
        self.seal_and_freeze()
        self.strategy.write_text('changed[tiab]')
        with patch.object(pubmed_tool, 'esearch') as search:
            with self.assertRaisesRegex(tool.FinalTestError, 'changed'):
                tool.evaluate(self.sealed, self.frozen, self.result, client=object())
            search.assert_not_called()

    def test_result_invalid_after_revision_even_if_only_or_added(self):
        self.seal_and_freeze()
        with patch.object(pubmed_tool, 'esearch', side_effect=self.search):
            tool.evaluate(self.sealed, self.frozen, self.result, client=object())
        self.strategy.write_text('allocation[tiab] OR random[tiab]')
        with self.assertRaises(tool.FinalTestError):
            tool.verify(self.result)
        with self.assertRaises(audit_markdown.AuditMarkdownError):
            audit_markdown.render_final_test({'final_test_result_file': str(self.result)})

    def test_overlap_including_excluded_development_record_rejected(self):
        development = tool.read(self.development)
        row = copy.deepcopy(development['records'][0])
        row.update(pmid='3', decision='exclude', use='neither')
        development['records'].append(row)
        self.save(self.development, development)
        self.seal_and_freeze()
        with self.assertRaisesRegex(tool.FinalTestError, 'overlap'):
            tool.evaluate(self.sealed, self.frozen, self.result, client=object())

    def test_companion_reports_rejected(self):
        for path in (self.development, self.test_ledger):
            ledger = tool.read(path)
            ledger['records'][0]['study_family_id'] = 'trial-1'
            self.save(path, ledger)
        self.seal_and_freeze()
        with self.assertRaisesRegex(tool.FinalTestError, 'family'):
            tool.evaluate(self.sealed, self.frozen, self.result, client=object())

    def test_failed_network_attempt_consumes_set(self):
        self.seal_and_freeze()
        with patch.object(pubmed_tool, 'esearch', side_effect=pubmed_tool.PubMedError('offline')):
            with self.assertRaises(pubmed_tool.PubMedError):
                tool.evaluate(self.sealed, self.frozen, self.result, client=object())
        with self.assertRaisesRegex(tool.FinalTestError, 'consumed'):
            tool.evaluate(self.sealed, self.frozen, self.result, client=object())

    def test_empty_reachable_denominator_not_perfect_recall(self):
        self.seal_and_freeze()
        with patch.object(pubmed_tool, 'esearch', return_value={'pmids': [], 'warnings': {}, 'errors': {}}):
            result = tool.evaluate(self.sealed, self.frozen, self.result, client=object())
        self.assertIsNone(result['recall'])
        self.assertEqual(result['unreachable_records'], 2)

    def test_sealed_data_cannot_enter_development_consumers(self):
        self.seal_and_freeze()
        for purpose in ('discovery', 'validation'):
            with self.assertRaises(pubmed_tool.PubMedError):
                pubmed_tool.candidate_ledger_pmids(str(self.sealed), purpose)
        with self.assertRaises(pubmed_tool.PubMedError):
            pubmed_tool.extract_benchmark_pmids(tool.read(self.sealed), min_seed_overlap=0)
        with self.assertRaises(critic_tool.CriticArtifactError):
            critic_tool.build_evidence_bundle([f'strategy={self.strategy}', f'test={self.sealed}'], self.root / 'bundle.json')

    def test_new_and_legacy_development_roles_resolve_without_independence_claim(self):
        ledger = tool.read(self.development)
        ledger['records'][1]['use'] = 'holdout'
        self.save(self.development, ledger)
        ids, meta = pubmed_tool.candidate_ledger_pmids(str(self.development), 'validation')
        self.assertEqual(ids, ['1', '2'])
        self.assertFalse(meta['independent'])
        self.assertTrue(meta['disjoint_from_discovery'])

    def test_freeze_requires_development_completion(self):
        tool.seal(self.test_ledger, self.protocol, self.sealed, self.receipt,
                  custodian='reviewer', unseen_by_builder=True)
        with patch('manifest_tool.complete_loop_readiness', return_value=['critic incomplete']):
            with self.assertRaisesRegex(tool.FinalTestError, 'critic incomplete'):
                tool.freeze(self.strategy, self.protocol, self.development, self.receipt, self.manifest, self.frozen)

    def test_seal_requires_nonexposure_attestation(self):
        with self.assertRaises(tool.FinalTestError):
            tool.seal(self.test_ledger, self.protocol, self.sealed, self.receipt,
                      custodian='reviewer', unseen_by_builder=False)

    def test_no_final_set_reports_not_performed(self):
        self.assertIn('Not performed', '\n'.join(audit_markdown.render_final_test({})))


if __name__ == '__main__':
    unittest.main()
