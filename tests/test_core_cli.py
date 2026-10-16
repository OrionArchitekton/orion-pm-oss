import json
import fcntl
import importlib.util
import os
from pathlib import Path
import subprocess
import select
import tarfile
import zipfile
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
BIN = os.environ.get('PM_TEST_BIN', str(ROOT / '.venv/bin/orion-pm'))


class CoreCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'state'
        self.config = Path(self.tmp.name) / 'projects.json'
        self.config.write_text(json.dumps({'schema_version': 1, 'projects': [{'id': 'sample'}]}))

    def call(self, *args, code=0):
        command = [BIN, '--json', '--home', str(self.home), *map(str, args)]
        try:
            p = subprocess.run(command, capture_output=True, text=True, timeout=10,
                               cwd=self.tmp.name, env={**os.environ, 'PYTHONPATH': '', 'PYTHONDONTWRITEBYTECODE': '1'})
        except FileNotFoundError:
            self.fail('Installed standalone entry point does not exist yet')
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        reply = json.loads(p.stdout)
        self.assertEqual(reply['ok'], code == 0)
        self.assertEqual(reply['api_version'], 1)
        return reply

    def init(self):
        return self.call('init', '--projects', self.config)['data']

    def add(self, task='one', *options):
        return self.call('add', '--id', task, '--title', task, '--project', 'sample', *options)['data']

    def compete(self, commands):
        # Both real installed entry-point processes wait behind an externally
        # held mutation lock before competing. This prevents startup timing from
        # turning the race into two sequential command tests.
        fd = os.open(self.home / 'arcs', os.O_RDONLY)
        processes = []
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            for command in commands:
                program = ('import sys\nfrom orion_pm.cli import main\n'
                           + 'sys.argv=' + repr(command) + '\n'
                           + "print('READY',flush=True)\nsys.stdin.read(1)\nraise SystemExit(main())\n")
                p = subprocess.Popen([str(Path(BIN).with_name('python')), '-c', program],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    cwd=self.tmp.name, env={**os.environ, 'PYTHONPATH': '', 'PYTHONDONTWRITEBYTECODE': '1'})
                processes.append(p)
            for p in processes:
                self.assertTrue(select.select([p.stdout], [], [], 5)[0])
                self.assertEqual(p.stdout.readline().strip(), 'READY')
                p.stdin.write('G'); p.stdin.flush()
            time.sleep(0.05)
            self.assertTrue(all(p.poll() is None for p in processes))
        finally:
            os.close(fd)
        results = []
        try:
            for command, p in zip(commands, processes):
                out, err = p.communicate(timeout=10)
                results.append(subprocess.CompletedProcess(command, p.returncode, out, err))
        finally:
            for p in processes:
                if p.poll() is None:
                    p.kill(); p.communicate()
        return results

    def test_S01_installed_isolated_lifecycle(self):
        version = self.call('version')['data']
        self.assertIn('tasks.v1', version['capabilities'])
        self.assertFalse(self.home.exists())
        init = self.init()
        self.assertEqual(len(init['store_id']), 32)
        self.assertEqual(self.call('init', '--projects', self.config)['outcome'], 'no_change')
        created = self.add()
        observed = self.call('show', 'one')['data']
        self.assertEqual(created, observed)
        self.assertEqual(observed['task']['status'], 'backlog')
        self.assertEqual(observed['task']['owner'], 'unassigned')
        self.assertEqual(observed['claim']['state'], 'absent')
        self.assertEqual(len(observed['task']['revision']), 64)

    def test_S02_projects_coverage_and_unknown(self):
        init = self.init()
        other = Path(self.tmp.name) / 'other.json'
        other.write_text(json.dumps({'id': 'other', 'group': 'team'}))
        self.call('projects', 'add', '--input', other, '--expect-config-revision', init['config_revision'])
        self.add('alpha', '--status', 'todo', '--priority', '7')
        self.add('closed', '--status', 'done')
        listed = self.call('list')['data']
        self.assertEqual([x['id'] for x in listed['tasks']], ['alpha', 'closed'])
        self.assertEqual(self.call('probe', 'alpha')['data']['coverage'], 'matches')
        self.assertEqual(self.call('probe', 'unmatched')['data']['coverage'], 'clear')
        self.assertEqual(self.call('rollup')['data']['by_status']['todo'], 1)
        (self.home / 'arcs/bad.json').write_text('{')
        self.assertEqual(self.call('probe', 'unmatched')['data']['coverage'], 'unknown')
        self.assertEqual(self.call('list')['data']['completeness'], 'partial')

    def test_S02_invalid_create_preserves_store(self):
        self.init()
        created = self.add()
        for flags in [('--id', '../escape'), ('--project', 'missing'), ('--priority', 'nan'),
                      ('--status', 'in_progress'), ('--owner', ''), ('--description', 'x' * 17000)]:
            self.call('add', '--id', 'different', '--title', 'x', '--project', 'sample', *flags, code=2)
        self.call('add', '--id', 'one', '--title', 'changed', '--project', 'sample', code=3)
        self.assertEqual(self.call('show', 'one')['data'], created)

    def test_S01_missing_and_legacy_are_not_empty(self):
        self.call('list', code=6)
        self.assertFalse(self.home.exists())
        self.home.mkdir(mode=0o700)
        (self.home / 'legacy.json').write_text('{}')
        self.call('init', '--projects', self.config, code=5)
        self.call('show', 'one', code=5)

    def test_S03_competing_processes_and_queue(self):
        self.init()
        for index in range(5):
            task_id = f'race-{index}'
            self.add(task_id, '--status', 'todo')
            command = [BIN, '--json', '--home', str(self.home), 'claim', task_id, '--holder', 'same-holder']
            results = self.compete([command, command])
            self.assertEqual(sorted(p.returncode for p in results), [0, 3], [p.stdout for p in results])
            winner = json.loads(next(p.stdout for p in results if p.returncode == 0))['data']
            self.assertEqual(winner['task']['status'], 'in_progress')
            self.assertEqual(winner['claim']['holder'], 'same-holder')
            self.assertEqual(self.call('show', task_id)['data'], winner)
        self.add('low', '--priority', '1')
        self.add('high', '--priority', '9')
        selected = self.call('claim-next', '--holder', 'picker')['data']
        self.assertEqual(selected['task']['id'], 'high')
        self.call('claim', 'high', '--holder', 'other', code=3)
        self.add('finished', '--status', 'done')
        self.call('claim', 'finished', '--holder', 'other', code=3)

    def test_S04_lifecycle_evidence_and_same_holder_ABA(self):
        self.init(); self.add()
        first = self.call('claim', 'one', '--holder', 'worker')['data']
        generation = first['claim']['generation']
        renewed = self.call('renew', 'one', '--holder', 'worker', '--generation', generation)['data']
        self.assertEqual(renewed['task']['revision'], first['task']['revision'])
        evidence = Path(self.tmp.name) / 'evidence.json'
        evidence.write_text(json.dumps({'id': 'read-1', 'source': 'example', 'artifact': 'sha256:' + 'a' * 64,
            'observed_at': '2026-10-15T00:00:00Z', 'scope': 'Synthetic observation only', 'ref': 'artifact:example'}))
        flags = ['--holder', 'worker', '--generation', generation, '--expect-revision', first['task']['revision']]
        attached = self.call('evidence', 'attach', 'one', '--input', evidence, *flags)['data']
        self.assertEqual(len(attached['task']['evidence']), 1)
        self.call('transition', 'one', 'done', *flags, code=3)
        flags[-1] = attached['task']['revision']
        self.assertEqual(self.call('evidence', 'attach', 'one', '--input', evidence, *flags)['outcome'], 'no_change')
        self.call('release', 'one', *flags)
        second = self.call('claim', 'one', '--holder', 'worker')['data']
        self.assertNotEqual(generation, second['claim']['generation'])
        flags[-1] = second['task']['revision']
        for command in (['renew', 'one', '--holder', 'worker', '--generation', generation],
                        ['release', 'one', *flags], ['transition', 'one', 'done', *flags],
                        ['evidence', 'attach', 'one', '--input', evidence, *flags]):
            self.call(*command, code=3)
            self.assertEqual(self.call('show', 'one')['data'], second)
        flags[3] = second['claim']['generation']
        result = self.call('transition', 'one', 'done', *flags)['data']
        self.assertEqual(result['claim']['state'], 'absent')
        self.assertEqual(result['task']['status'], 'done')
        self.assertEqual(len(self.call('evidence', 'list', 'one')['data']['evidence']), 1)

    def expire(self, task_id):
        p = self.home / 'claims' / (task_id + '.lock')
        rec = json.loads(p.read_text())
        rec['acquired_at'], rec['expires_at'] = '2000-01-01T00:00:00Z', '2000-01-01T04:00:00Z'
        p.write_text(json.dumps(rec))
        return rec

    def test_S05_expiry_takeover_orphan_and_default_triage(self):
        self.init(); self.add()
        first = self.call('claim', 'one', '--holder', 'worker')['data']
        expired = self.expire('one')
        flags = ['--holder', 'worker', '--generation', first['claim']['generation']]
        self.call('renew', 'one', *flags, code=3)
        self.assertEqual(self.call('triage', 'one')['data']['disposition'], 'surface')
        self.assertEqual(len(self.call('overdue')['data']['items']), 1)
        self.call('triage', 'one', '--git-evidence', code=2)
        takeover = ['takeover', 'one', '--holder', 'new', '--expect-generation', expired['generation'],
                    '--expect-expires-at', expired['expires_at'], '--expect-revision', first['task']['revision'], '--reason', 'Resume synthetic work']
        second = self.call(*takeover)['data']
        self.assertNotEqual(second['claim']['generation'], expired['generation'])
        self.call(*takeover, code=3)
        (self.home / 'claims/one.lock').unlink()
        self.assertEqual(self.call('triage', 'one')['data']['disposition'], 'orphan')
        recovered = self.call('recover', 'one', '--expect-revision', second['task']['revision'], '--reason', 'Synthetic interruption')['data']
        self.assertEqual(recovered['task']['status'], 'todo')
        self.assertEqual(recovered['claim']['state'], 'absent')

    def test_S06_maintenance_race_drain_and_replacement(self):
        self.init(); self.add()
        worker = self.call('claim', 'one', '--holder', 'worker')['data']
        lease = self.call('claim-admission', 'acquire', '--holder', 'maint', '--reason', 'do-not-echo')['data']['admission']
        self.assertNotIn('do-not-echo', json.dumps(lease))
        self.add('waiting')
        self.call('claim', 'waiting', '--holder', 'other', code=3)
        self.call('claim-next', '--holder', 'other', code=3)
        self.call('renew', 'one', '--holder', 'worker', '--generation', worker['claim']['generation'])
        self.call('release', 'one', '--holder', 'worker', '--generation', worker['claim']['generation'], '--expect-revision', worker['task']['revision'])
        self.call('claim-admission', 'release', '--holder', 'maint', '--lease-id', lease['lease_id'])
        replacement = self.call('claim-admission', 'acquire', '--holder', 'maint', '--reason', 'replacement')['data']['admission']
        self.call('claim-admission', 'release', '--holder', 'maint', '--lease-id', lease['lease_id'], code=3)
        self.call('claim-admission', 'release', '--holder', 'maint', '--lease-id', replacement['lease_id'])
        prefix = [BIN, '--json', '--home', str(self.home)]
        commands = [prefix + ['claim', 'waiting', '--holder', 'racer'],
                    prefix + ['claim-admission', 'acquire', '--holder', 'maint', '--reason', 'race']]
        results = self.compete(commands)
        self.assertEqual(results[1].returncode, 0, results[1].stdout)
        self.assertIn(results[0].returncode, (0, 3), results[0].stdout)
        if results[0].returncode == 0:
            self.assertEqual(self.call('show', 'waiting')['data']['claim']['holder'], 'racer')
        else:
            self.assertEqual(self.call('show', 'waiting')['data']['claim']['state'], 'absent')
        self.call('claim', 'one', '--holder', 'late', code=3)

    def test_S06_unknown_admission_denies_even_empty_queue(self):
        self.init()
        d = self.home / 'claims/.claim-admission'
        d.mkdir(mode=0o700)
        (d / 'unexpected.json').write_text('{}')
        state = self.call('claim-admission', 'status')['data']['admission']
        self.assertEqual(state, {'state': 'unknown', 'claims_admitted': False})
        self.call('claim-next', '--holder', 'worker', code=5)

    def snapshot(self):
        return {str(p.relative_to(self.home)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.home.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_S08_truthful_bounded_projection_and_readonly(self):
        self.init(); self.add('high', '--priority', '9'); self.add('low', '--priority', '1')
        self.call('claim', 'high', '--holder', 'worker')
        self.expire('high')
        orphan = self.home / 'claims/ghost.lock'
        orphan.write_text('{}')
        before = self.snapshot()
        surface = self.call('surface')['data']
        self.assertEqual([x['id'] for x in surface['queue']], ['low'])
        self.assertEqual(surface['inflight'], [])
        self.assertEqual(len(surface['stale']), 1)
        self.assertTrue(any(f['code'] == 'orphan_claim' for f in surface['claim_issues']))
        self.assertEqual(surface, self.call('surface')['data'])
        for args in [('audit',), ('events',), ('show', 'high'), ('list',), ('rollup',),
                     ('probe', 'high'), ('projects', 'list'), ('overdue',), ('triage', 'high'),
                     ('claim-admission', 'status'), ('evidence', 'list', 'high')]:
            self.call(*args)
        self.assertEqual(before, self.snapshot())
        (self.home / 'claims/low.lock').write_text('{')
        self.assertEqual(self.call('probe', 'low')['data']['coverage'], 'unknown')
        self.call('claim-next', '--holder', 'worker', code=5)

    def injected(self, args, patch):
        program = ('import sys\nfrom unittest import mock\nfrom orion_pm import cli,store,claim,events\n'
                   + 'sys.argv=' + repr(['orion-pm', '--json', '--home', str(self.home), *args]) + '\n'
                   + patch + '\n')
        return subprocess.run([str(Path(BIN).with_name('python')), '-c', program],
                              capture_output=True, text=True, timeout=10, cwd=self.tmp.name,
                              env={**os.environ, 'PYTHONPATH': '', 'PYTHONDONTWRITEBYTECODE': '1'})

    def test_S07_events_are_best_effort_and_bounded(self):
        self.init(); self.add()
        observed = self.call('events')['data']
        self.assertTrue(observed['events'])
        self.assertFalse(observed['history_complete'])
        log = self.home / 'events.jsonl'
        log.unlink(); log.mkdir()
        task = self.call('claim', 'one', '--holder', 'worker')['data']
        self.assertEqual(task['task']['status'], 'in_progress')
        events = self.call('events')
        self.assertEqual(events['data']['read_state'], 'unknown')
        self.assertTrue(events['warnings'])

    def test_S07_short_write_and_replacement_failure_are_visible(self):
        self.init(); self.add()
        args = ['claim', 'one', '--holder', 'worker']
        p = self.injected(args, "with mock.patch.object(claim.os, 'write', return_value=0):\n    raise SystemExit(cli.main())")
        self.assertEqual(p.returncode, 7, p.stdout + p.stderr)
        self.assertEqual(self.call('show', 'one')['data']['claim']['state'], 'absent')
        p = self.injected(args, "with mock.patch.object(store.os, 'replace', side_effect=OSError()):\n    raise SystemExit(cli.main())")
        self.assertEqual(p.returncode, 7, p.stdout + p.stderr)
        self.assertTrue(any(x['code'] == 'provisional_claim' for x in self.call('audit')['data']['findings']))

    def test_S07_killed_acquisition_has_no_fabricated_completion(self):
        self.init(); self.add()
        script = ('import sys,time\nfrom unittest import mock\nfrom orion_pm import cli,store\n'
                  + 'sys.argv=' + repr(['orion-pm', '--json', '--home', str(self.home), 'claim', 'one', '--holder', 'worker']) + '\n'
                  + "def pause(*a,**k):\n    print('READY',flush=True)\n    time.sleep(30)\n"
                  + "with mock.patch.object(store,'write_json',side_effect=pause):\n    cli.main()\n")
        process = subprocess.Popen([str(Path(BIN).with_name('python')), '-c', script],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.tmp.name)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            self.assertEqual(process.stdout.readline().strip(), 'READY')
            process.kill(); out, err = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(out, '')
            result = self.call('show', 'one')['data']
            self.assertEqual(result['task']['status'], 'backlog')
            self.assertEqual(result['claim']['state'], 'live')
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_S07_lock_timeout_and_status_exit_residue(self):
        self.init(); self.add()
        claimed = self.call('claim', 'one', '--holder', 'worker')['data']
        fd = os.open(self.home / 'arcs', os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.call('show', 'one', code=6)
        finally:
            os.close(fd)
        args = ['transition', 'one', 'done', '--holder', 'worker', '--generation', claimed['claim']['generation'],
                '--expect-revision', claimed['task']['revision']]
        p = self.injected(args, "with mock.patch.object(claim, 'unlink', side_effect=store.PMError('mutation_unknown','Injected cleanup failure',7)):\n    raise SystemExit(cli.main())")
        self.assertEqual(p.returncode, 7, p.stdout + p.stderr)
        self.assertTrue(any(x['code'] == 'status_exit_residue' for x in self.call('audit')['data']['findings']))

    def test_S08_strict_state_and_orphan_authority(self):
        self.init(); self.add()
        config = self.home / 'projects.json'
        original = config.read_bytes()
        damaged = json.loads(original); damaged['schema_version'] = True
        config.write_text(json.dumps(damaged))
        self.call('list', code=5)
        config.write_bytes(original)
        task = self.home / 'arcs/one.json'
        original_task = task.read_bytes()
        damaged = json.loads(original_task); damaged['project'] = 'missing'
        task.write_text(json.dumps(damaged))
        self.call('show', 'one', code=5)
        task.write_bytes(original_task)
        (self.home / 'claims/ghost.lock').write_text('{}')
        self.call('add', '--id', 'ghost', '--title', 'ghost', '--project', 'sample', code=5)

    def test_S08_linked_special_and_large_records(self):
        self.init(); self.add()
        p = self.home / 'claims/one.lock'
        target = Path(self.tmp.name) / 'unrelated'
        target.write_text('preserve this')
        p.symlink_to(target)
        self.assertEqual(self.call('show', 'one')['data']['claim']['state'], 'unknown')
        p.unlink(); os.mkfifo(p)
        self.assertEqual(self.call('show', 'one')['data']['claim']['state'], 'unknown')
        p.unlink(); p.write_bytes(b'x' * 65537)
        self.call('claim', 'one', '--holder', 'worker', code=5)
        self.assertEqual(target.read_text(), 'preserve this')
        p.unlink()
        task = self.home / 'arcs/one.json'
        task.write_bytes(b'x' * (4 * 1024 * 1024 + 1))
        self.call('show', 'one', code=5)
        self.assertEqual(self.call('probe', 'missing')['data']['coverage'], 'unknown')

    def test_S08_parent_symlink_and_request_echo_are_bounded(self):
        alias = Path(self.tmp.name) / 'alias'
        alias.symlink_to(self.tmp.name, target_is_directory=True)
        self.home = alias / 'state'
        self.call('init', '--projects', self.config, code=5)
        result = self.call('--request-id', 'x' * 300, 'version', code=2)
        self.assertIsNone(result['request_id'])

    def test_S07_event_tail_exposes_torn_and_unsafe_records(self):
        self.init()
        rec = {'task_id': 'one', 'event': 'claimed', 'ts': '2026-10-15T00:00:00Z', 'appended_at': '2026-10-15T00:00:01Z'}
        log = self.home / 'events.jsonl'
        with log.open('wb') as out:
            out.write(b'z' * (1024 * 1024 + 100) + b'\n')
            out.write(json.dumps({**rec, 'bad': float('nan')}).encode() + b'\n')
            out.write(json.dumps(rec).encode() + b'\n' + b'{torn')
        result = self.call('events')['data']
        self.assertEqual(result['events'], [rec])
        self.assertTrue(result['truncated'])
        self.assertGreaterEqual(result['skipped_lines'], 2)
        self.assertLessEqual(result['scanned_bytes'], 1024 * 1024)

    def test_S08_output_and_claim_scan_limits_never_read_as_clear(self):
        self.init()
        for index in range(5):
            self.add(f'task-{index}')
        result = self.injected(['list'], "with mock.patch.object(cli,'MAX_OUTPUT_BYTES',1024,create=True):\n    raise SystemExit(cli.main())")
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        # A small injected bound exercises the same cumulative-claim cutoff without
        # creating a production-sized corpus or adding user-visible test switches.
        for index in range(5):
            (self.home / f'claims/task-{index}.lock').write_bytes(b'x' * 200)
        result = self.injected(['surface'], "with mock.patch.object(claim,'MAX_CORPUS_BYTES',300,create=True):\n    raise SystemExit(cli.main())")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)['data']
        self.assertTrue(any(f['code'] == 'limit_exceeded' for f in data['claim_issues']))
        self.assertEqual(data['queue'], [])

    def test_review_overdue_preserves_claim_scan_uncertainty(self):
        self.init()
        for index in range(3):
            self.add(f'task-{index}')
            self.call('claim', f'task-{index}', '--holder', 'worker')
        before = self.snapshot()
        result = self.injected(['overdue'], "with mock.patch.object(claim,'MAX_CORPUS_BYTES',1):\n    raise SystemExit(cli.main())")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)['data']
        self.assertEqual(data['completeness'], 'partial')
        self.assertTrue(any(issue['code'] == 'limit_exceeded' for issue in data['issues']))
        self.assertEqual(len(data['items']), 3)
        self.assertTrue(all(item['claim']['state'] == 'unknown' for item in data['items']))
        self.assertEqual(before, self.snapshot())

    def test_review_stale_surface_uses_overdue_dispositions(self):
        self.init()
        for task_id in ('expired', 'unknown', 'orphan'):
            self.add(task_id)
            self.call('claim', task_id, '--holder', 'worker')
        self.expire('expired')
        (self.home / 'claims/unknown.lock').write_text('{')
        (self.home / 'claims/orphan.lock').unlink()
        overdue = {item['task_id']: item for item in self.call('overdue')['data']['items']}
        self.assertEqual({k: v['issue'] for k, v in overdue.items()},
                         {'expired': 'surface', 'unknown': 'surface', 'orphan': 'orphan'})
        stale = {item['task_id']: item for item in self.call('surface')['data']['stale']}
        self.assertEqual(stale, overdue)

    def test_review_human_surface_bounds_escaped_unicode_bytes(self):
        self.init()
        for index in range(33):
            title = 'a' * 140 if index == 0 else '\U0001f680' * 140
            self.add(f'task-{index:02}', '--title', title)
            if index < 20:
                self.call('claim', f'task-{index:02}', '--holder', 'worker')
        data = self.call('surface')['data']
        self.assertEqual(len(data['inflight']), 20)
        self.assertEqual(len(data['queue']), 12)
        self.assertEqual(data['overflow']['queue'], 1)
        command = [BIN, '--home', str(self.home), 'surface']
        result = subprocess.run(command, capture_output=True, cwd=self.tmp.name, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout), 32 * 1024)
        self.assertIn(b'a' * 140, result.stdout)
        self.assertIn(b'omitted: 1', result.stdout)
        self.assertEqual(result.stdout, subprocess.check_output(command, cwd=self.tmp.name))

    def test_S09_independent_subprocess_consumer(self):
        self.init(); self.add()
        evidence = Path(self.tmp.name) / 'consumer-evidence.json'
        evidence.write_text(json.dumps({'id': 'receipt-1', 'source': 'independent-consumer', 'artifact': 'synthetic-v1',
            'observed_at': '2026-10-15T00:00:00Z', 'scope': 'Synthetic consumer receipt', 'ref': 'artifact:receipt-1'}))
        command = [str(Path(BIN).with_name('python')), str(ROOT / 'examples/cli_consumer.py'),
                   '--pm', BIN, '--home', str(self.home), '--task', 'one', '--holder', 'consumer', '--evidence', str(evidence)]
        p = subprocess.run(command, capture_output=True, text=True, timeout=10, cwd=self.tmp.name)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(json.loads(p.stdout)['state'], 'observed_result')
        final = self.call('show', 'one')['data']
        self.assertEqual(final['task']['status'], 'done')
        self.assertEqual(final['claim']['state'], 'absent')
        fake = Path(self.tmp.name) / 'unsupported-pm'
        fake.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps({"api_version":99,"ok":True}))\n')
        fake.chmod(0o700)
        command[command.index('--pm') + 1] = str(fake)
        p = subprocess.run(command, capture_output=True, text=True, timeout=10, cwd=self.tmp.name)
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        self.assertEqual(self.call('show', 'one')['data'], final)

    def test_S10_adapter_handles_winner_loss_timeout_and_release_failure(self):
        import sys
        sys.path.insert(0, str(ROOT / 'examples'))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / 'examples')))
        try:
            from cli_consumer import PMClient, BoundaryError
            from browser_starter import run
        except ImportError:
            self.fail('Browser composition example has not been implemented')
        self.init()
        class Browser:
            version = 'synthetic-native-driver-v1'
            def __init__(self, failure=None):
                self.calls, self.failure = [], failure
            def lease(self):
                self.calls.append('lease')
                if self.failure == 'unavailable':
                    raise OSError('unavailable')
                return 'native-lease-1'
            def read(self, lease):
                self.calls.append('read')
                if self.failure == 'timeout':
                    raise TimeoutError('unknown read')
                if self.failure == 'interrupt':
                    raise KeyboardInterrupt
                return {'title': 'Synthetic public page', 'ref': 'artifact:public-synthetic-page'}
            def release(self, lease):
                self.calls.append('release')
                return self.failure != 'release'
        self.add('winner')
        browser = Browser()
        result = run(PMClient(BIN, str(self.home)), 'winner', 'worker', browser, Path(self.tmp.name) / 'receipts')
        self.assertEqual(result['state'], 'observed_result')
        self.assertEqual(browser.calls, ['lease', 'read', 'release'])
        for failure in ('unavailable', 'timeout', 'release', 'interrupt'):
            self.add(failure)
            browser = Browser(failure)
            with self.assertRaises(KeyboardInterrupt if failure == 'interrupt' else BoundaryError):
                run(PMClient(BIN, str(self.home)), failure, 'worker', browser, Path(self.tmp.name) / failure)
            self.assertEqual(self.call('show', failure)['data']['task']['status'], 'in_progress')
            self.assertEqual(browser.calls.count('read'), 0 if failure == 'unavailable' else 1)
        self.add('loser'); self.call('claim', 'loser', '--holder', 'existing')
        browser = Browser()
        with self.assertRaises(BoundaryError):
            run(PMClient(BIN, str(self.home)), 'loser', 'loser', browser, Path(self.tmp.name) / 'loser')
        self.assertEqual(browser.calls, [])

    def test_review_renewal_span_and_maintenance_payload(self):
        self.init(); self.add()
        data = self.call('claim', 'one', '--holder', 'worker', '--ttl-hours', '24')['data']
        result = self.call('renew', 'one', '--holder', 'worker', '--generation', data['claim']['generation'], '--ttl-hours', '24')['data']
        self.assertEqual(result['claim']['state'], 'live')
        before = self.snapshot()
        self.call('claim-admission', 'acquire', '--holder', 'maint', '--reason', '\U0001f680' * 4096, code=2)
        self.assertEqual(before, self.snapshot())

    def test_review_postwrite_read_failure_is_mutation_unknown(self):
        self.init()
        p = self.injected(['add', '--id', 'one', '--title', 'one', '--project', 'sample'],
             "with mock.patch.object(store.Store,'view',side_effect=store.PMError('state_unknown','Injected read failure',5)):\n    raise SystemExit(cli.main())")
        self.assertEqual(p.returncode, 7, p.stdout + p.stderr)
        self.assertEqual(json.loads(p.stdout)['error']['code'], 'mutation_unknown')
        self.assertEqual(self.call('show', 'one')['data']['task']['status'], 'backlog')

    def test_review_timestamp_order_and_repository_shape(self):
        self.init(); self.add('earlier'); self.add('later')
        for task_id, ts in [('earlier', '2026-10-15T00:00:00Z'), ('later', '2026-10-15T00:00:00.5Z')]:
            path = self.home / f'arcs/{task_id}.json'
            data = json.loads(path.read_text()); data['updated_at'] = ts
            path.write_text(json.dumps(data))
        self.assertEqual(self.call('surface')['data']['queue'][0]['id'], 'later')
        self.assertEqual(self.call('claim-next', '--holder', 'picker')['data']['task']['id'], 'later')
        config = self.call('projects', 'list')['data']
        bad = Path(self.tmp.name) / 'repo.json'
        bad.write_text(json.dumps({'id': 'repo', 'repository': {'path': self.tmp.name, 'remote': 'origin', 'github_repository': []}}))
        self.call('projects', 'add', '--input', bad, '--expect-config-revision', config['config_revision'], code=2)

    def test_S08_local_reads_do_not_invoke_network_or_process_tools(self):
        self.init(); self.add()
        script = ("import sys,socket,subprocess\nfrom unittest import mock\nfrom orion_pm import cli\n"
                  + 'prefix=' + repr(['orion-pm', '--json', '--home', str(self.home)]) + '\n'
                  + "with mock.patch.object(socket,'socket',side_effect=AssertionError('network')), mock.patch.object(subprocess,'run',side_effect=AssertionError('process tool')):\n"
                  + "    for command in [['show','one'],['list'],['rollup'],['probe','one'],['surface'],['audit'],['events'],['overdue'],['triage','one'],['projects','list'],['claim-admission','status'],['evidence','list','one']]:\n"
                  + "        sys.argv=prefix+command\n        assert cli.main()==0\n")
        p = subprocess.run([str(Path(BIN).with_name('python')), '-c', script], capture_output=True, text=True, cwd=self.tmp.name, timeout=10)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_S11_artifact_contents_and_runtime_dependencies(self):
        wheel = ROOT / 'dist/orion_pm-0.1.1-py3-none-any.whl'
        source = ROOT / 'dist/orion_pm-0.1.1.tar.gz'
        self.assertTrue(wheel.exists()); self.assertTrue(source.exists())
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            runtime = {n for n in names if n.startswith('orion_pm/') and n.endswith('.py')}
            self.assertEqual(runtime, {'orion_pm/' + n + '.py' for n in ('__init__', 'store', 'claim', 'admission', 'surface', 'events', 'cli')})
            metadata = archive.read(next(n for n in names if n.endswith('/METADATA'))).decode()
            self.assertNotIn('Requires-Dist:', metadata)
            for name in names:
                self.assertNotIn(b'/home/', archive.read(name))
        with tarfile.open(source) as archive:
            names = archive.getnames()
            for required in ('README.md', 'specs/orion-pm-core-spec.md', 'docs/runbooks/local-store.md',
                             'examples/cli_consumer.py', 'scripts/check.py',
                             'docs/releases/browser-composition-0.1.1.json'):
                self.assertTrue(any(n.endswith('/' + required) for n in names), required)
            self.assertFalse(any('/.private/' in n or '/.venv/' in n or '/.git/' in n for n in names))

    def test_review_expiry_crossing_cannot_promote_or_renew(self):
        self.init(); self.add()
        patch = ("from datetime import timedelta\noriginal=claim.exclusive\n"
                 "def delayed(s,record):\n    original(s,record)\n    future=store.parse_time(record['expires_at'])+timedelta(seconds=1)\n    store.now=lambda:future\n"
                 "with mock.patch.object(claim,'exclusive',side_effect=delayed):\n    raise SystemExit(cli.main())")
        p = self.injected(['claim', 'one', '--holder', 'worker'], patch)
        self.assertEqual(p.returncode, 7, p.stdout + p.stderr)
        self.assertEqual(self.call('show', 'one')['data']['task']['status'], 'backlog')
        # Renew a different claim while time crosses its expiry after the read.
        self.add('renewal')
        claimed = self.call('claim', 'renewal', '--holder', 'worker')['data']
        patch = ("from datetime import timedelta\noriginal=claim.read\n"
                 "def delayed(s,task):\n    current=original(s,task)\n    future=store.parse_time(current['expires_at'])+timedelta(seconds=1)\n    store.now=lambda:future\n    return current\n"
                 "with mock.patch.object(claim,'read',side_effect=delayed):\n    raise SystemExit(cli.main())")
        p = self.injected(['renew', 'renewal', '--holder', 'worker', '--generation', claimed['claim']['generation']], patch)
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)

    def test_review_invalid_unicode_details_remain_unknown(self):
        self.init()
        self.add('one')
        path = self.home / 'arcs/one.json'
        original = path.read_bytes()
        for field in ('description', 'next_action'):
            with self.subTest(field=field):
                record = json.loads(original)
                record[field] = chr(0xD800)
                path.write_text(json.dumps(record))
                before = path.read_bytes()
                result = self.call('show', 'one', code=5)
                self.assertEqual(result['error']['code'], 'state_unknown')
                self.assertEqual(self.call('probe', 'one')['data']['coverage'], 'unknown')
                result = self.call('claim-next', '--holder', 'worker', code=5)
                self.assertEqual(result['error']['code'], 'coverage_unknown')
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(any((self.home / 'claims').iterdir()))
        path.write_bytes(original)
        self.assertEqual(self.call('show', 'one')['data']['task']['id'], 'one')

    def test_review_legacy_maintenance_is_indeterminate(self):
        self.init()
        (self.home / 'claim-admission.lock').write_text('{}')
        self.assertEqual(self.call('claim-admission', 'status')['data']['admission']['state'], 'unknown')
        self.call('claim-next', '--holder', 'worker', code=5)


if __name__ == '__main__':
    unittest.main()
