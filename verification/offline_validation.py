"""Release validation, with real network access blocked and credentials absent."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--tests-only', action='store_true')
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ('OPENROUTER_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY', 'OPENAI_API_KEY'):
        os.environ.pop(name, None)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(project))
    os.chdir(project)
    with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden in offline validation')):
        with (output / 'tests.log').open('w', encoding='utf-8') as log:
            with redirect_stdout(log), redirect_stderr(log):
                suite = unittest.defaultTestLoader.discover(str(project / 'tests'))
                result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        summary = {'tests_run': result.testsRun, 'failures': len(result.failures),
                   'errors': len(result.errors), 'skipped': len(result.skipped),
                   'successful': result.wasSuccessful(), 'network_blocked': True,
                   'credentials_removed': True, 'python': sys.version}
        (output / 'tests_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps(summary))
        if not result.wasSuccessful():
            raise SystemExit(1)
        if not args.tests_only:
            import run_final
            # The JSON registry is the public selection list used by collaborators.
            conditions = [row['id'] for row in json.loads((project / 'configs/registered_conditions.json').read_text(encoding='utf-8'))]
            with (output / 'all105_mock.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
                run_final.main(['--conditions', *conditions, '--seeds', '201', '--safety-stock', '10',
                                '--backend', 'mock', '--evaluation-periods', '2', '--workers', '8',
                                '--output', str(output / 'all105_mock')])
            rows = json.loads((output / 'all105_mock/results.json').read_text(encoding='utf-8'))
            check = {'expected': len(conditions), 'completed': sum(row['complete'] for row in rows),
                     'common_warmup_hashes': len({row['warmup_hash'] for row in rows}),
                     'common_demand_hashes': len({row['demand_hash'] for row in rows}),
                     'agent_rows': sum(len(json.loads(p.read_text(encoding='utf-8')))
                                       for p in (output / 'all105_mock').glob('episodes/*/periods.json'))}
            assert check == {'expected': 105, 'completed': 105, 'common_warmup_hashes': 1,
                             'common_demand_hashes': 1, 'agent_rows': 840}, check
            (output / 'all105_mock_summary.json').write_text(json.dumps(check, indent=2), encoding='utf-8')
            print(json.dumps(check))


if __name__ == '__main__':
    main()
