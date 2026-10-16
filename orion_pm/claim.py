"""Structural local ownership; exact generations are concurrency guards, not auth."""
from datetime import timedelta
import os
import re
import secrets
from . import store
MAX_CORPUS_BYTES = 16 * 1024 * 1024


def path(s, task_id):
    return s.claims / (store.safe_id(task_id) + '.lock')


def read(s, task_id):
    if hasattr(s, '_claim_snapshot'):
        return s._claim_snapshot.get(task_id, {'state': 'absent' if s._claim_scan_complete else 'unknown'})
    try:
        rec = store.read_json(path(s, task_id), 65536)
        if (not isinstance(rec, dict) or set(rec) != {'task_id', 'holder', 'generation', 'acquired_at', 'expires_at', 'branch'}
                or rec['task_id'] != task_id or not isinstance(rec['generation'], str)
                or not re.fullmatch('[0-9a-f]{32}', rec['generation'])):
            raise ValueError
        store.text(rec['holder'], 'holder')
        if rec['branch'] is not None:
            store.text(rec['branch'], 'branch', 4096)
        store.parse_time(rec['acquired_at']); store.parse_time(rec['expires_at'])
        if not store.parse_time(rec['expires_at']) > store.parse_time(rec['acquired_at']):
            raise ValueError
        return {'state': 'expired' if store.now() >= store.parse_time(rec['expires_at']) else 'live', **rec}
    except store.PMError as exc:
        if exc.code == 'not_found':
            return {'state': 'absent'}
        return {'state': 'unknown'}
    except (ValueError, TypeError, OverflowError):
        return {'state': 'unknown'}


def corpus(s):
    if hasattr(s, '_claim_snapshot'):
        return s._claim_snapshot, s._claim_scan_issues
    snapshot, issues, scanned = {}, [], 0
    complete = True
    try:
        with os.scandir(s.claims) as entries:
            for index, entry in enumerate(entries):
                if index >= 20000:
                    complete = False
                    issues.append({'code': 'limit_exceeded', 'task_id': None, 'message': 'Claim entry limit.'})
                    break
                if entry.name == '.claim-admission':
                    continue
                scanned += entry.stat(follow_symlinks=False).st_size
                if scanned > MAX_CORPUS_BYTES:
                    complete = False
                    issues.append({'code': 'limit_exceeded', 'task_id': None, 'message': 'Claim byte limit.'})
                    break
                aid = entry.name[:-5] if entry.name.endswith('.lock') else None
                try:
                    store.safe_id(aid)
                except store.PMError:
                    issues.append({'code': 'unexpected_claim_entry', 'task_id': None, 'message': 'Unexpected claim entry.'})
                    continue
                snapshot[aid] = read(s, aid)
                if snapshot[aid]['state'] == 'unknown':
                    issues.append({'code': 'unknown_claim', 'task_id': aid, 'message': 'Claim cannot be validated.'})
    except OSError:
        complete = False
        issues.append({'code': 'state_unknown', 'task_id': None, 'message': 'Claim enumeration failed.'})
    s._claim_snapshot, s._claim_scan_complete, s._claim_scan_issues = snapshot, complete, issues
    return snapshot, issues


def ttl(value):
    if type(value) is not int or not 1 <= value <= 24:
        store.fail('invalid_input', 'TTL must be an integer from 1 to 24 hours.')
    return value


def payload(task_id, holder, branch, hours):
    store.text(holder, 'holder')
    if branch is not None:
        store.text(branch, 'branch', 4096)
    moment = store.now()
    return {'task_id': task_id, 'holder': holder, 'generation': secrets.token_hex(16),
            'acquired_at': moment.isoformat(), 'expires_at': (moment + timedelta(hours=ttl(hours))).isoformat(),
            'branch': branch}


def exclusive(s, record):
    p = path(s, record['task_id'])
    raw = store.canonical(record) + b'\n'
    fd = None
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        store.mutation_started = True
        inode = os.fstat(fd).st_ino
        position = 0
        while position < len(raw):
            n = os.write(fd, raw[position:])
            if n <= 0:
                raise OSError('short write')
            position += n
        os.fsync(fd)
    except FileExistsError:
        store.fail('held', 'Task already has a present claim.', 3)
    except OSError:
        if fd is not None:
            try:
                if p.lstat().st_ino == inode:
                    p.unlink()
            except OSError:
                pass
        store.fail('mutation_unknown', 'Claim write failed; inspect task and claim.', 7)
    finally:
        if fd is not None:
            os.close(fd)


def queue(s):
    tasks, issues = s.corpus()
    if issues:
        store.fail('coverage_unknown', 'Cannot select from an incomplete task corpus.', 5)
    _, claim_issues = corpus(s)
    if claim_issues:
        store.fail('state_unknown', 'Cannot select while claim authority is unknown.', 5)
    tasks.sort(key=lambda t: t['id'])
    tasks.sort(key=lambda t: store.parse_time(t['updated_at']), reverse=True)
    tasks.sort(key=lambda t: t['priority'], reverse=True)
    return [t for t in tasks if t['status'] in ('backlog', 'todo') and read(s, t['id'])['state'] == 'absent']


def acquire(s, args):
    from . import admission
    store.text(args.holder, 'holder'); ttl(args.ttl_hours)
    with s.locked(True) as store_id:
        admission.require_open(s)
        if args.command == 'claim-next':
            candidates = [t for t in queue(s) if not args.project or t['project'] in args.project]
            if not candidates:
                store.fail('no_candidate', 'No claimable task in complete observed queue.', 3)
            task = candidates[0]
        else:
            task = s.load(args.task_id)
        if task['status'] not in ('backlog', 'todo'):
            store.fail('not_claimable', 'Task status is not claimable.', 3)
        current = read(s, task['id'])
        if current['state'] == 'unknown':
            store.fail('state_unknown', 'Claim state is unknown.', 5)
        if current['state'] != 'absent':
            store.fail('held', 'Task already has a present claim.', 3)
        record = payload(task['id'], args.holder, args.branch, args.ttl_hours)
        # Selection snapshots are read observations, never authority after a write.
        if hasattr(s, '_claim_snapshot'):
            del s._claim_snapshot
        exclusive(s, record)
        try:
            check_handle(read(s, task['id']), record['holder'], record['generation'])
            task['status'], task['updated_at'] = 'in_progress', store.timestamp()
            store.write_json(s.arcs / (task['id'] + '.json'), task)
        except store.PMError:
            # Status may already have committed; preserve an interpretable residue.
            # Recovery must inspect state instead of discarding uncertain ownership.
            raise
        return s.view(task['id'], store_id), 'committed'


def check_handle(current, holder, generation, *, expired=False):
    if current['state'] == 'unknown':
        store.fail('state_unknown', 'Cannot interpret claim authority.', 5)
    if (current['state'] not in (('live', 'expired') if expired else ('live',))
            or current.get('holder') != holder or current.get('generation') != generation):
        store.fail('stale_claim', 'Exact permitted claim generation is required.', 3)


def check_revision(task, expected):
    if store.revision(task) != expected:
        store.fail('revision_conflict', 'Task changed after observation.', 3)


def save_task(s, task):
    task['updated_at'] = store.timestamp()
    store.write_json(s.arcs / (task['id'] + '.json'), task)


def unlink(s, task_id, generation):
    current = read(s, task_id)
    if current.get('generation') != generation or current['state'] == 'unknown':
        store.fail('stale_claim', 'Claim changed before cleanup.', 3)
    try:
        store.mutation_started = True
        path(s, task_id).unlink()
    except OSError:
        store.fail('mutation_unknown', 'Claim cleanup is uncertain; inspect state.', 7)


def worker(s, args):
    from datetime import timedelta
    evidence = None
    if args.command == 'evidence' and args.evidence_action == 'attach':
        evidence = store.validate_evidence(store.read_json(args.input, 4096, input_file=True))
    if args.command == 'renew':
        ttl(args.ttl_hours)
    for label in ('holder', 'actor'):
        value = getattr(args, label, None)
        if value is not None:
            store.text(value, label)
    with s.locked(True) as store_id:
        task, current = s.load(args.task_id), read(s, args.task_id)
        holder, generation = getattr(args, 'holder', None), getattr(args, 'generation', None)
        if current['state'] != 'absent' or holder is not None or generation is not None or args.command in ('renew', 'release'):
            check_handle(current, holder, generation, expired=args.command == 'release')
        elif task['status'] == 'in_progress':
            store.fail('state_unknown', 'Progress task without claim requires explicit recovery.', 5)
        moment = store.now()
        if args.command != 'release' and current['state'] == 'live' and moment >= store.parse_time(current['expires_at']):
            store.fail('stale_claim', 'Claim expired before the requested mutation.', 3)
        if args.command == 'renew':
            record = {k: v for k, v in current.items() if k != 'state'}
            record['expires_at'] = (moment + timedelta(hours=args.ttl_hours)).isoformat()
            store.write_json(path(s, task['id']), record, 65536)
        else:
            check_revision(task, args.expect_revision)
            if args.command == 'evidence':
                existing = next((e for e in task['evidence'] if e['id'] == evidence['id']), None)
                if existing is not None:
                    if existing != evidence:
                        store.fail('already_exists', 'Evidence ID has different content.', 3)
                    return s.view(task['id'], store_id), 'no_change'
                if len(task['evidence']) >= 64:
                    store.fail('limit_exceeded', 'Evidence count limit.', 5)
                task['evidence'].append(evidence)
                save_task(s, task)
            elif args.command == 'release':
                if task['status'] == 'in_progress':
                    task['status'] = 'todo'
                    save_task(s, task)
                unlink(s, task['id'], generation)
            else:
                if args.status == 'in_progress' and task['status'] != 'in_progress':
                    store.fail('invalid_transition', 'Only claim or takeover enters in_progress.')
                if args.status == task['status']:
                    return s.view(task['id'], store_id), 'no_change'
                task['status'] = args.status
                save_task(s, task)
                if current['state'] != 'absent':
                    unlink(s, task['id'], generation)
        return s.view(task['id'], store_id), 'committed'


def recovery(s, args):
    store.text(args.reason, 'reason', 4096, controls=True)
    with s.locked(True) as store_id:
        task, current = s.load(args.task_id), read(s, args.task_id)
        check_revision(task, args.expect_revision)
        if current['state'] == 'unknown':
            store.fail('state_unknown', 'Unknown authority requires offline containment.', 5)
        if args.command == 'recover':
            if task['status'] != 'in_progress' or current['state'] != 'absent':
                store.fail('not_claimable', 'Only an absent-claim progress orphan can be recovered.', 3)
            task['status'] = 'todo'
        else:
            from . import admission
            admission.require_open(s)
            if (current['state'] != 'expired' or current['generation'] != args.expect_generation
                    or current['expires_at'] != args.expect_expires_at):
                store.fail('stale_claim', 'Exact expired generation and expiry required.', 3)
            if task['status'] not in ('backlog', 'todo', 'in_progress'):
                store.fail('not_claimable', 'Status-exit residue must be released, not taken over.', 3)
            record = payload(task['id'], args.holder, args.branch, args.ttl_hours)
            store.write_json(path(s, task['id']), record, 65536)
            check_handle(read(s, task['id']), record['holder'], record['generation'])
            task['status'] = 'in_progress'
        save_task(s, task)
        return s.view(task['id'], store_id), 'committed'


def triage(s, task):
    current = read(s, task['id'])
    disposition = ('orphan' if task['status'] == 'in_progress' and current['state'] == 'absent'
                   else 'surface' if current['state'] in ('expired', 'unknown') else 'not_stale')
    return {'task_id': task['id'], 'revision': store.revision(task), 'claim': current,
            'disposition': disposition, 'evidence': {'worktree_present': None, 'on_remote': None,
            'has_open_pr': None, 'rule': 'local-report-only'}}


def overdue(s, store_id):
    tasks, issues = s.corpus()
    _, scan_issues = corpus(s)
    issues = [*issues, *scan_issues]
    items = []
    for task in tasks:
        report = triage(s, task)
        if report['disposition'] != 'not_stale':
            items.append({'task_id': task['id'], 'revision': report['revision'], 'claim': report['claim'],
                          'issue': report['disposition']})
    return {'store_id': store_id, 'items': items, 'completeness': 'partial' if issues else 'complete', 'issues': issues}
