"""Installed cross-language command interface."""
import argparse
import json
import sys
from . import __version__
from . import store

CAPABILITIES = ['tasks.v1', 'coverage.v1', 'claims.v1', 'transitions.v1', 'evidence.v1',
                'admission.v1', 'views.v1', 'events.v1']
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class Parser(argparse.ArgumentParser):
    def error(self, message):
        store.fail('invalid_input', 'Invalid command arguments; see --help.')


def parser():
    p = Parser(prog='orion-pm')
    p.add_argument('--json', action='store_true')
    p.add_argument('--home')
    p.add_argument('--request-id')
    p.add_argument('--api-version', type=int, default=1)
    sub = p.add_subparsers(dest='command', required=True, parser_class=Parser)
    sub.add_parser('version')
    q = sub.add_parser('init'); q.add_argument('--projects', required=True)
    q = sub.add_parser('add')
    q.add_argument('--id', required=True); q.add_argument('--title', required=True)
    q.add_argument('--project', required=True); q.add_argument('--owner', default='unassigned')
    q.add_argument('--status', choices=store.STATUSES, default='backlog')
    q.add_argument('--priority', type=float, default=0)
    q.add_argument('--description'); q.add_argument('--next-action')
    q = sub.add_parser('show'); q.add_argument('task_id')
    q = sub.add_parser('projects')
    qs = q.add_subparsers(dest='project_action', required=True, parser_class=Parser)
    qs.add_parser('list')
    r = qs.add_parser('add'); r.add_argument('--input', required=True); r.add_argument('--expect-config-revision', required=True)
    q = sub.add_parser('list')
    q.add_argument('--project', action='append'); q.add_argument('--status', action='append', choices=store.STATUSES)
    q.add_argument('--limit', type=int, default=50); q.add_argument('--offset', type=int, default=0)
    sub.add_parser('rollup')
    q = sub.add_parser('probe'); q.add_argument('keywords', nargs='+'); q.add_argument('--project')
    for name in ('claim', 'claim-next'):
        q = sub.add_parser(name)
        if name == 'claim':
            q.add_argument('task_id')
        else:
            q.add_argument('--project', action='append')
        q.add_argument('--holder', required=True); q.add_argument('--branch')
        q.add_argument('--ttl-hours', type=int, default=4)
    for name in ('renew', 'release', 'transition'):
        q = sub.add_parser(name); q.add_argument('task_id')
        if name == 'transition':
            q.add_argument('status', choices=store.STATUSES); q.add_argument('--actor')
        q.add_argument('--holder', required=name != 'transition')
        q.add_argument('--generation', required=name != 'transition')
        if name == 'renew':
            q.add_argument('--ttl-hours', type=int, default=4)
        else:
            q.add_argument('--expect-revision', required=True)
    q = sub.add_parser('evidence')
    qs = q.add_subparsers(dest='evidence_action', required=True, parser_class=Parser)
    r = qs.add_parser('list'); r.add_argument('task_id')
    r = qs.add_parser('attach'); r.add_argument('task_id'); r.add_argument('--input', required=True)
    r.add_argument('--expect-revision', required=True); r.add_argument('--holder'); r.add_argument('--generation')
    for name in ('takeover', 'recover'):
        q = sub.add_parser(name); q.add_argument('task_id')
        q.add_argument('--expect-revision', required=True); q.add_argument('--reason', required=True)
        if name == 'takeover':
            q.add_argument('--holder', required=True); q.add_argument('--expect-generation', required=True)
            q.add_argument('--expect-expires-at', required=True); q.add_argument('--branch')
            q.add_argument('--ttl-hours', type=int, default=4)
    q = sub.add_parser('triage'); q.add_argument('task_id')
    sub.add_parser('overdue')
    q = sub.add_parser('claim-admission')
    qs = q.add_subparsers(dest='admission_action', required=True, parser_class=Parser)
    qs.add_parser('status')
    r = qs.add_parser('acquire'); r.add_argument('--holder', required=True); r.add_argument('--reason', required=True)
    r.add_argument('--ttl-minutes', type=int, default=15)
    r = qs.add_parser('release'); r.add_argument('--holder', required=True); r.add_argument('--lease-id', required=True)
    sub.add_parser('surface'); sub.add_parser('audit')
    q = sub.add_parser('events'); q.add_argument('--task'); q.add_argument('--limit', type=int, default=50)
    return p


def execute(args):
    if args.api_version != 1:
        store.fail('unsupported_api', 'Only API version 1 is supported.')
    if args.request_id is not None:
        store.text(args.request_id, 'request ID')
    if args.command == 'version':
        return {'package_version': __version__, 'api_version': 1, 'store_format_version': 1,
                'capabilities': CAPABILITIES, 'platforms': ['Linux, local filesystem; see support matrix']}, 'observed'
    s = store.Store(store.home_path(args.home))
    if args.command == 'init':
        return s.initialize(args.projects)
    if args.command == 'add':
        return s.add(args)
    if args.command == 'projects' and args.project_action == 'add':
        return s.add_project(args)
    if args.command in ('claim', 'claim-next'):
        from . import claim
        return claim.acquire(s, args)
    if args.command in ('renew', 'release', 'transition') or (args.command == 'evidence' and args.evidence_action == 'attach'):
        from . import claim
        return claim.worker(s, args)
    if args.command in ('takeover', 'recover'):
        from . import claim
        return claim.recovery(s, args)
    if args.command == 'claim-admission' and args.admission_action != 'status':
        from . import admission
        return admission.mutate(s, args)
    with s.locked() as store_id:
        if args.command in ('surface', 'audit'):
            from . import surface
            if args.command == 'surface':
                return surface.projection(s, store_id), 'observed'
            tasks, issues = s.corpus()
            findings = surface.findings(s, tasks, issues)
            return {'store_id': store_id, 'findings': findings, 'completeness': 'partial' if findings else 'complete'}, 'observed'
        if args.command == 'events':
            from . import events
            return {'store_id': store_id, **events.read(s, args.task, args.limit)}, 'observed'
        if args.command == 'claim-admission':
            from . import admission
            return {'store_id': store_id, 'admission': admission.status(s)}, 'observed'
        if args.command in ('triage', 'overdue'):
            from . import claim
            return ({'store_id': store_id, **claim.triage(s, s.load(args.task_id))}
                    if args.command == 'triage' else claim.overdue(s, store_id)), 'observed'
        if args.command == 'projects':
            return s.config_view(store_id), 'observed'
        if args.command in ('list', 'rollup', 'probe'):
            return s.observe(args, store_id), 'observed'
        if args.command == 'evidence':
            task = s.load(args.task_id)
            return {'store_id': store_id, 'task_id': task['id'], 'revision': store.revision(task), 'evidence': task['evidence']}, 'observed'
        return s.view(args.task_id, store_id), 'observed'


def main():
    store.mutation_started = False
    argv = sys.argv[1:]
    json_mode = '--json' in argv
    reply = {'api_version': 1, 'command': 'unknown', 'request_id': None, 'ok': True,
             'outcome': 'observed', 'data': None, 'warnings': [], 'error': None}
    code = 0
    try:
        args = parser().parse_args(argv)
        reply['command'] = args.command
        if args.request_id is not None:
            store.text(args.request_id, 'request ID')
        reply['request_id'] = args.request_id
        if args.command == 'projects':
            reply['command'] += ' ' + args.project_action
        if args.command == 'evidence':
            reply['command'] += ' ' + args.evidence_action
        if args.command == 'claim-admission':
            reply['command'] += ' ' + args.admission_action
        reply['data'], reply['outcome'] = execute(args)
        if reply['command'] == 'events' and reply['data']['read_state'] == 'unknown':
            reply['warnings'].append({'code': 'event_read_unknown', 'message': 'Event history could not be read safely.'})
        if reply['outcome'] == 'committed':
            from . import events
            names = {'add': 'task_created', 'claim': 'claimed', 'claim-next': 'claimed', 'renew': 'renewed',
                     'release': 'released', 'transition': 'transition', 'takeover': 'takeover', 'recover': 'recovered',
                     'evidence attach': 'evidence_attached', 'projects add': 'project_added',
                     'claim-admission acquire': 'claim_admission_paused', 'claim-admission release': 'claim_admission_reopened', 'init': 'initialized'}
            task = reply['data'].get('task', {})
            events.emit(store.Store(store.home_path(args.home)),
                        {'event': names[reply['command']], 'task_id': task.get('id', '__store__'),
                         'actor': getattr(args, 'actor', None) or getattr(args, 'holder', None),
                         'request_id': args.request_id,
                         **({'to_status': task['status']} if task else {})})
    except store.PMError as exc:
        code = 7 if store.mutation_started else exc.exit_code
        reply.update(ok=False, data=None, outcome='indeterminate' if code in (5, 7) else 'rejected',
                     error={'code': 'mutation_unknown' if code == 7 else exc.code,
                            'message': 'Mutation result cannot be established; inspect state.' if code == 7 else exc.message})
    except OSError:
        code = 7 if store.mutation_started else 6
        reply.update(ok=False, data=None, outcome='indeterminate' if code == 7 else 'rejected',
                     error={'code': 'mutation_unknown' if code == 7 else 'unavailable',
                            'message': 'Local operation unavailable; inspect state if mutation began.'})
    wire = json.dumps(reply, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    if len(wire.encode('utf-8')) + 1 > MAX_OUTPUT_BYTES:
        code = 7 if reply['outcome'] == 'committed' else 5
        reply.update(ok=False, outcome='indeterminate', data=None,
                     error={'code': 'mutation_unknown' if code == 7 else 'limit_exceeded',
                            'message': 'Response exceeds byte bound; inspect a narrower view.'})
        wire = json.dumps(reply, ensure_ascii=True, separators=(',', ':'))
    if json_mode:
        print(wire)
    elif reply['ok']:
        if reply['command'] == 'surface':
            from . import surface
            print(surface.render(reply['data']))
        else:
            print(json.dumps(reply['data'], ensure_ascii=True, indent=2, allow_nan=False))
    else:
        print(reply['error']['code'] + ': ' + reply['error']['message'], file=sys.stderr)
    return code
