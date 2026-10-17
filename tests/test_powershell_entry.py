"""Exercise the public Windows entry point without credentials or paid calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import run_qmean


class PowerShellEntryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows launcher integration test')
    def test_launcher_applies_final_intervention_and_explicit_safety_stock(self):
        shell = shutil.which('powershell') or shutil.which('pwsh')
        if not shell:
            self.skipTest('PowerShell is not installed')
        project = Path(__file__).resolve().parents[1]
        script = str(project / 'Run-Experiment.ps1').replace("'", "''")
        environment = dict(os.environ)
        environment.pop('OPENROUTER_API_KEY', None)
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        with tempfile.TemporaryDirectory() as temporary:
            output = str(Path(temporary) / 'final mock').replace("'", "''")
            command = (f"& '{script}' -Conditions @('A','C0M0T2') -Seeds 201 "
                       f"-Backend mock -SafetyStock 10 -EvaluationPeriods 1 -Output '{output}'")
            completed = subprocess.run(
                [shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command],
                cwd=project, env=environment, capture_output=True, text=True,
                errors='replace', timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            folder = Path(temporary) / 'final mock'
            manifest = json.loads((folder / 'batch_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['simulation']['safety_stock'], 10)
            self.assertEqual(manifest['simulation']['evaluation_periods'], 1)
            self.assertEqual(manifest['simulation']['initial_inventory'], 0)
            self.assertEqual(manifest['variant']['implementation_revision'], 4)
            for episode in (folder / 'episodes').iterdir():
                condition = episode.name.split('__')[0]
                events = json.loads((episode / 'mock_calls.json').read_text(encoding='utf-8'))
                for event in events:
                    if event['task'] == 'order':
                        self.assertEqual(run_qmean.QMEAN in event['instructions'], condition == 'C0M0T2')
            self.assertFalse(list(folder.glob('episodes/*/api_calls.jsonl')))


if __name__ == '__main__':
    unittest.main()
