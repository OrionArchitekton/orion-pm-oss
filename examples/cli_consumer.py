#!/usr/bin/env python3
"""Independent example: commands only, no PM imports or direct store access."""
import argparse
import json
import subprocess
import uuid


class BoundaryError(Exception):
    pass


class PMClient:
    def __init__(self, executable, home):
        self.executable, self.home, self.store_id = executable, home, None

    def call(self, *args):
        request = uuid.uuid4().hex
        try:
            p = subprocess.run([self.executable, '--json', '--home', self.home,
                                '--request-id', request, '--api-version', '1', *map(str, args)],
                               capture_output=True, text=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            raise BoundaryError('unknown: command delivery/result cannot be established; do not retry blindly') from None
        try:
            if len(p.stdout.encode()) > 8 * 1024 * 1024:
                raise ValueError
            result = json.loads(p.stdout)
            if (not isinstance(result, dict) or result.get('api_version') != 1 or result.get('request_id') != request
                    or result.get('ok') is not True or p.returncode != 0
                    or result.get('outcome') not in ('observed', 'committed', 'no_change')
                    or result.get('error') is not None or not isinstance(result.get('data'), dict)):
                raise ValueError
            data = result['data']
            if args[0] != 'version':
                if not isinstance(data.get('store_id'), str):
                    raise ValueError
                if self.store_id is not None and data['store_id'] != self.store_id:
                    raise ValueError
                self.store_id = data['store_id']
            return data
        except (ValueError, KeyError, TypeError):
            raise BoundaryError('rejected-or-unknown: inspect PM directly before taking another action') from None

    def check(self):
        version = self.call('version')
        required = {'tasks.v1', 'coverage.v1', 'claims.v1', 'transitions.v1', 'evidence.v1'}
        if version.get('api_version') != 1 or not required <= set(version.get('capabilities', [])):
            raise BoundaryError('unsupported PM capabilities')

    def acquire(self, task_id, holder):
        self.check()
        coverage = self.call('probe', task_id)
        if coverage.get('coverage') not in ('clear', 'matches'):
            raise BoundaryError('unknown task coverage')
        data = self.call('claim', task_id, '--holder', holder)
        if (data.get('task', {}).get('id') != task_id or data.get('task', {}).get('status') != 'in_progress'
                or data.get('claim', {}).get('state') != 'live' or data['claim'].get('holder') != holder):
            raise BoundaryError('unknown claim result')
        return data

    def attach_and_finish(self, data, evidence_file):
        task_id, c = data['task']['id'], data['claim']
        flags = ['--holder', c['holder'], '--generation', c['generation']]
        data = self.call('evidence', 'attach', task_id, '--input', evidence_file,
                         '--expect-revision', data['task']['revision'], *flags)
        result = self.call('transition', task_id, 'done', '--expect-revision', data['task']['revision'], *flags)
        observed = self.call('show', task_id)
        if (result['task']['status'] != 'done' or observed['task']['status'] != 'done'
                or observed['claim']['state'] != 'absent'):
            raise BoundaryError('completion not observed')
        return {'state': 'observed_result', 'store_id': observed['store_id'], 'task_id': task_id,
                'revision': observed['task']['revision']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pm', 'home', 'task', 'holder', 'evidence'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    client = PMClient(args.pm, args.home)
    try:
        data = client.acquire(args.task, args.holder)
        result = client.attach_and_finish(data, args.evidence)
    except BoundaryError as exc:
        print(json.dumps({'state': 'unknown_or_refused', 'message': str(exc)}))
        return 3
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
