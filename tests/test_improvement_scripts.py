"""Regression checks for intervention isolation; all transport is mocked."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_qmean
import run_variant
import run_final
from scm import prompts, runner
from scm.config import SimulationConfig
from variant_support import runtime_intervention


class ImprovementScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network = patch('scm.provider.urlopen', side_effect=AssertionError('No paid calls in tests'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.capture = redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def args(self, folder, *extra):
        return ['--conditions', 'A', 'C0M0T2', 'D_cost', 'D_bullwhip',
                '--seeds', '7', '--backend', 'mock', '--evaluation-periods', '1',
                '--output', str(folder), *extra]

    @staticmethod
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))

    def test_sentence_only_changes_CMT_order_prompt_and_is_restored(self):
        original = prompts.order_instructions
        source_hash = runner.source_fingerprint()
        folder = self.root / 'qmean'
        run_qmean.main(self.args(folder))
        for episode in (folder / 'episodes').iterdir():
            events = self.read(episode / 'mock_calls.json')
            condition = episode.name.split('__')[0]
            for event in events:
                expected = condition == 'C0M0T2' and event['task'] == 'order'
                self.assertEqual(run_qmean.QMEAN in event['instructions'], expected)
        self.assertIs(prompts.order_instructions, original)
        self.assertEqual(runner.source_fingerprint(), source_hash)
        self.assertFalse(list(folder.glob('episodes/*/api_calls.jsonl')))

    def test_resume_keeps_signature_and_blocks_cross_treatment_both_directions(self):
        folder = self.root / 'qmean'
        args = self.args(folder)
        run_qmean.main(args)
        first = (folder / 'results.json').read_bytes()
        run_qmean.main([*args, '--resume'])
        self.assertEqual((folder / 'results.json').read_bytes(), first)
        with self.assertRaisesRegex(ValueError, 'Different intervention'):
            run_variant.main([*args, '--resume'])
        with self.assertRaisesRegex(ValueError, 'another frozen batch'):
            runner.run_batch(['A', 'C0M0T2', 'D_cost', 'D_bullwhip'], [7], folder,
                             backend='mock', config=SimulationConfig(evaluation_periods=1), resume=True)
        baseline = self.root / 'ordinary'
        runner.run_batch(['A'], [7], baseline, config=SimulationConfig(evaluation_periods=1))
        with self.assertRaisesRegex(ValueError, 'lacks this intervention manifest'):
            run_qmean.main(self.args(baseline, '--resume'))

    def test_safety_stock_changes_warmup_but_not_demand(self):
        folders = [self.root / f'ss{ss}' for ss in (0, 10)]
        for folder, ss in zip(folders, (0, 10)):
            run_variant.main(self.args(folder, '--safety-stock', str(ss)))
            summaries = self.read(folder / 'results.json')
            self.assertEqual(len({row['warmup_hash'] for row in summaries}), 1)
            manifest = self.read(folder / 'batch_manifest.json')
            self.assertEqual(manifest['simulation']['safety_stock'], ss)
            self.assertEqual(manifest['simulation']['initial_inventory'], 0)
        warmups = [self.read(folder / 'warmup' / 'seed-7.json') for folder in folders]
        self.assertEqual(warmups[0]['demand_hash'], warmups[1]['demand_hash'])
        self.assertNotEqual(warmups[0]['snapshot_hash'], warmups[1]['snapshot_hash'])

    def test_dry_run_creates_nothing_and_validates_objective(self):
        folder = self.root / 'dry'
        run_qmean.main(self.args(folder, '--dry-run'))
        self.assertFalse(folder.exists())
        with self.assertRaisesRegex(ValueError, 'fixed'):
            run_qmean.main(self.args(folder, '--dry-run', '--objective', 'bullwhip'))

    def test_prompt_and_fingerprint_restored_on_failure(self):
        original_prompt = prompts.order_instructions
        original_fingerprint = runner.source_fingerprint
        with self.assertRaisesRegex(RuntimeError, 'deliberate'):
            with runtime_intervention('diagnostic-hash', run_qmean.QMEAN):
                self.assertEqual(runner.source_fingerprint(), 'diagnostic-hash')
                raise RuntimeError('deliberate')
        self.assertIs(prompts.order_instructions, original_prompt)
        self.assertIs(runner.source_fingerprint, original_fingerprint)

    def test_final_entry_requires_safety_stock_and_records_combined_identity(self):
        folder = self.root / 'final'
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            run_final.main(self.args(folder))
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(folder.exists())
        run_final.main(self.args(folder, '--safety-stock', '10'))
        manifest = self.read(folder / 'batch_manifest.json')
        self.assertEqual(manifest['simulation']['safety_stock'], 10)
        self.assertEqual(manifest['variant']['id'], 'FINAL_V1_V2_OWNERSHIP_M2_N0')
        intervention = self.read(folder / 'intervention_manifest.json')['signature']['intervention']
        self.assertEqual(intervention['name'], 'final_v1_v2_ownership_qmean')
        self.assertEqual(intervention['q_base_meaning_sentence'], run_qmean.QMEAN)
        for episode in (folder / 'episodes').iterdir():
            condition = episode.name.split('__')[0]
            for event in self.read(episode / 'mock_calls.json'):
                self.assertIn('information_sources', event['payload'])
                self.assertEqual(run_qmean.QMEAN in event['instructions'],
                                 condition == 'C0M0T2' and event['task'] == 'order')


if __name__ == '__main__':
    unittest.main()
