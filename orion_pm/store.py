"""Bounded local store. Adapted from the reviewed exclusive/atomic file design."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import time

STATUSES = ('backlog', 'todo', 'in_progress', 'blocked', 'done', 'cancelled',
            'deferred', 'superseded', 'requires_ratification')
ACTIVE = ('backlog', 'todo', 'in_progress', 'blocked', 'requires_ratification')
TASK_BYTES = 4 * 1024 * 1024
mutation_started = False  # Per CLI invocation; no persistent transaction promise.
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')


class PMError(Exception):
    def __init__(self, code, message, exit_code=2):
        super().__init__(message)
        self.code, self.message, self.exit_code = code, message, exit_code


def fail(code, message, exit_code=2):
    raise PMError(code, message, exit_code)


def now():
    return datetime.now(timezone.utc)


def timestamp():
    return now().isoformat()


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.]\d{1,9})?(?:Z|[+]00:00)', value):
        raise ValueError('timestamp type')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError('UTC timestamp required')
    return dt


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def revision(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def text(value, label, limit=256, controls=False):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        fail('invalid_input', f'Invalid {label}.')
    if not controls and any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        fail('invalid_input', f'Controls in {label}.')
    try:
        value.encode('utf-8')
    except UnicodeError:
        fail('invalid_input', f'Invalid UTF-8 {label}.')
    return value


def safe_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail('invalid_input', 'Invalid identifier.')
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _depth(value, level=0):
    if level > 32:
        raise ValueError('JSON depth')
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, level + 1)


def read_json(path, cap=TASK_BYTES, *, input_file=False):
    code, ec = ('invalid_input', 2) if input_file else ('state_unknown', 5)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            mode = os.fstat(fd)
            if not stat.S_ISREG(mode.st_mode):
                raise ValueError('not regular')
            if not input_file and (mode.st_uid != os.getuid() or mode.st_mode & 0o022):
                raise ValueError('unsafe permissions')
            if mode.st_size > cap:
                raise ValueError('oversize')
            chunks, left = [], cap + 1
            while left:
                part = os.read(fd, min(left, 65536))
                if not part:
                    break
                chunks.append(part)
                left -= len(part)
            raw = b''.join(chunks)
        finally:
            os.close(fd)
        if len(raw) > cap:
            raise ValueError('oversize')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        _depth(value)
        return value
    except FileNotFoundError:
        fail('invalid_input' if input_file else 'not_found', 'Requested file is absent.', 2 if input_file else 4)
    except (OSError, ValueError, RecursionError, UnicodeError):
        fail(code, 'Cannot validate bounded JSON record.', ec)


def write_json(path, obj, cap=TASK_BYTES):
    global mutation_started
    raw = canonical(obj) + b'\n'
    if len(raw) > cap:
        fail('limit_exceeded', 'Record exceeds its byte bound.', 5)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix='.write-', dir=path.parent)
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        mutation_started = True
        os.replace(tmp, path)
    except OSError:
        fail('mutation_unknown', 'Write outcome is uncertain; inspect state.', 7)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def home_path(explicit=None):
    value = explicit
    if value is None and 'ORION_PM_HOME' in os.environ:
        value = os.environ['ORION_PM_HOME']
    if value is None:
        xdg = os.environ.get('XDG_DATA_HOME')
        value = str(Path(xdg) / 'orion-pm') if xdg is not None else str(Path.home() / '.local/share/orion-pm')
    if not value or not Path(value).is_absolute():
        fail('invalid_input', 'Store root must be an absolute non-empty path.')
    path = Path(value)
    if '..' in path.parts:
        fail('invalid_input', 'Store root may not traverse parents.')
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            fail('state_unknown', 'Symlinked store path is unsafe.', 5)
    return path


def directory(path):
    try:
        st = path.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
            fail('state_unknown', 'Unsafe authority directory.', 5)
    except FileNotFoundError:
        fail('unavailable', 'Store directory is absent; initialize explicitly.', 6)


def project(raw, *, stored=False):
    if not isinstance(raw, dict) or not set(raw) <= {'id', 'group', 'repository'} or 'id' not in raw:
        fail('invalid_input', 'Invalid project.')
    out = {'id': safe_id(raw['id']), 'group': safe_id(raw.get('group', 'workspace'))}
    if 'repository' in raw:
        repo = raw['repository']
        if not isinstance(repo, dict) or not {'path', 'remote'} <= set(repo) or not set(repo) <= {'path', 'remote', 'github_repository'}:
            fail('invalid_input', 'Invalid explicit repository configuration.')
        text(repo['path'], 'repository path', 4096)
        if not Path(repo['path']).is_absolute() or (not stored and not Path(repo['path']).is_dir()):
            fail('invalid_input', 'Repository path must be an explicit existing absolute directory.')
        text(repo['remote'], 'remote', 256)
        if 'github_repository' in repo:
            text(repo['github_repository'], 'GitHub repository', 256)
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo['github_repository']):
                fail('invalid_input', 'Repository identity must be explicit owner/repository.')
        out['repository'] = repo
    return out


def validate_evidence(raw):
    fields = {'id', 'source', 'artifact', 'observed_at', 'scope', 'ref'}
    if not isinstance(raw, dict) or set(raw) != fields:
        fail('invalid_input', 'Invalid evidence-reference fields.')
    safe_id(raw['id'])
    for key in fields - {'id', 'observed_at'}:
        text(raw[key], 'evidence ' + key, 2048, controls=True)
    try:
        parse_time(raw['observed_at'])
    except (ValueError, TypeError):
        fail('invalid_input', 'Evidence observation must be a UTC timestamp.')
    if len(canonical(raw)) > 4096:
        fail('invalid_input', 'Evidence exceeds 4 KiB.')
    return raw


class Store:
    def __init__(self, home):
        self.home = home
        self.arcs = home / 'arcs'
        self.claims = home / 'claims'

    def marker(self):
        directory(self.home)
        try:
            value = read_json(self.home / 'store.json', 4096)
        except PMError:
            fail('incompatible_store', 'Unrecognized or incomplete store; no automatic migration.', 5)
        if (not isinstance(value, dict) or set(value) != {'store_id', 'store_format_version'}
                or type(value['store_format_version']) is not int or value['store_format_version'] != 1
                or not isinstance(value['store_id'], str) or not re.fullmatch('[0-9a-f]{32}', value['store_id'])):
            fail('incompatible_store', 'Unsupported store marker.', 5)
        return value

    @contextmanager
    def locked(self, write=False):
        marker = self.marker()
        directory(self.arcs)
        directory(self.claims)
        fd = os.open(self.arcs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            deadline = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        fail('unavailable', 'Mutation lock unavailable within two seconds.', 6)
                    time.sleep(0.01)
            yield marker['store_id']
        finally:
            os.close(fd)

    def projects(self):
        if hasattr(self, '_config_cache'):
            return self._config_cache
        value = read_json(self.home / 'projects.json', 65536)
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'projects'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1):
            fail('state_unknown', 'Invalid project configuration.', 5)
        if not isinstance(value['projects'], list) or not 1 <= len(value['projects']) <= 200:
            fail('state_unknown', 'Invalid project count.', 5)
        try:
            normalized = [project(p, stored=True) for p in value['projects']]
            if normalized != value['projects'] or len({p['id'] for p in normalized}) != len(normalized):
                raise ValueError
        except (PMError, ValueError):
            fail('state_unknown', 'Invalid project configuration.', 5)
        self._config_cache = value
        return value

    def config_view(self, store_id):
        config = self.projects()
        return {'store_id': store_id, 'config_revision': revision(config),
                'projects': [{k: p[k] for k in ('id', 'group')} for p in config['projects']]}

    def initialize(self, filename):
        raw = read_json(filename, 65536, input_file=True)
        if (not isinstance(raw, dict) or set(raw) != {'schema_version', 'projects'}
                or type(raw['schema_version']) is not int or raw['schema_version'] != 1
                or not isinstance(raw['projects'], list) or not 1 <= len(raw['projects']) <= 200):
            fail('invalid_input', 'Expected schema_version 1 and bounded project list.')
        config = {'schema_version': 1, 'projects': [project(p) for p in raw['projects']]}
        if len({p['id'] for p in config['projects']}) != len(config['projects']):
            fail('invalid_input', 'Duplicate project ID.')
        if self.home.exists() and any(self.home.iterdir()):
            with self.locked() as store_id:
                if self.projects() != config:
                    fail('already_exists', 'Existing configuration differs.', 3)
                return self.config_view(store_id), 'no_change'
        try:
            self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory(self.home)
            self.arcs.mkdir(mode=0o700)
            self.claims.mkdir(mode=0o700)
            write_json(self.home / 'projects.json', config, 65536)
            write_json(self.home / 'store.json', {'store_id': secrets.token_hex(16), 'store_format_version': 1}, 4096)
        except FileExistsError:
            fail('incompatible_store', 'Interrupted or concurrent initialization; inspect state.', 5)
        with self.locked() as store_id:
            return self.config_view(store_id), 'committed'

    def load(self, task_id):
        value = read_json(self.arcs / (safe_id(task_id) + '.json'))
        try:
            fields = {'id', 'title', 'project', 'group', 'status', 'owner', 'priority',
                      'description', 'next_action', 'created_at', 'updated_at', 'evidence'}
            if not isinstance(value, dict) or set(value) != fields or value['id'] != task_id:
                raise ValueError
            safe_id(value['id']); safe_id(value['project']); safe_id(value['group'])
            if not any(p['id'] == value['project'] and p['group'] == value['group'] for p in self.projects()['projects']):
                raise ValueError('unknown project')
            text(value['title'], 'title', 4096, controls=True); text(value['owner'], 'owner')
            if value['status'] not in STATUSES:
                raise ValueError
            self.validate_details(value['priority'], value['description'], value['next_action'])
            parse_time(value['created_at']); parse_time(value['updated_at'])
            if not isinstance(value['evidence'], list) or len(value['evidence']) > 64:
                raise ValueError('evidence count')
            for evidence in value['evidence']:
                validate_evidence(evidence)
            if len({e['id'] for e in value['evidence']}) != len(value['evidence']):
                raise ValueError('duplicate evidence')
        except (PMError, ValueError, TypeError, KeyError, OverflowError):
            fail('state_unknown', 'Invalid task record.', 5)
        return value

    @staticmethod
    def validate_details(priority, description, next_action):
        if type(priority) not in (int, float) or not math.isfinite(priority) or not -1000000 <= priority <= 1000000:
            fail('invalid_input', 'Priority must be finite and bounded.')
        for label, value in (('description', description), ('next action', next_action)):
            if value is not None:
                if not isinstance(value, str):
                    fail('invalid_input', f'Invalid {label}.')
                try:
                    value.encode('utf-8')
                except UnicodeError:
                    fail('invalid_input', f'Invalid UTF-8 {label}.')
        if description is not None:
            if not isinstance(description, str) or len(description.encode('utf-8')) > 16384:
                fail('invalid_input', 'Description exceeds its bound.')
        if next_action is not None and (not isinstance(next_action, str) or len(next_action) > 4096):
            fail('invalid_input', 'Next action exceeds its bound.')

    def corpus(self):
        config = self.projects()
        projects = {p['id']: p['group'] for p in config['projects']}
        tasks, issues, scanned = [], [], 0
        try:
            with os.scandir(self.arcs) as entries:
                for index, entry in enumerate(entries):
                    if index >= 20000:
                        issues.append({'code': 'limit_exceeded', 'task_id': None, 'message': 'Corpus entry limit.'})
                        break
                    aid = entry.name[:-5] if entry.name.endswith('.json') else None
                    try:
                        if aid is None:
                            raise ValueError
                        safe_id(aid)
                        scanned += entry.stat(follow_symlinks=False).st_size
                        if scanned > 64 * 1024 * 1024:
                            issues.append({'code': 'limit_exceeded', 'task_id': None, 'message': 'Corpus byte limit.'})
                            break
                        task = self.load(aid)
                        if projects.get(task['project']) != task['group']:
                            raise ValueError
                        tasks.append(task)
                    except (PMError, OSError, ValueError):
                        issues.append({'code': 'unreadable_task', 'task_id': aid, 'message': 'Task entry cannot be validated.'})
        except OSError:
            issues.append({'code': 'state_unknown', 'task_id': None, 'message': 'Corpus enumeration failed.'})
        return sorted(tasks, key=lambda t: t['id']), issues

    def summary(self, task):
        from . import claim
        keys = ('id', 'project', 'group', 'status', 'owner', 'priority')
        return {**{k: task[k] for k in keys}, 'title': task['title'][:140],
                'title_truncated': len(task['title']) > 140, 'revision': revision(task),
                'claim': claim.read(self, task['id'])}

    def observe(self, args, store_id):
        from . import claim
        tasks, issues = self.corpus()
        _, claim_issues = claim.corpus(self)
        invalid_count = len(issues)
        issues += claim_issues
        completeness = 'partial' if issues else 'complete'
        if args.command == 'list':
            if not 1 <= args.limit <= 200 or args.offset < 0:
                fail('invalid_input', 'Invalid pagination bound.')
            selected = [t for t in tasks if (not args.project or t['project'] in args.project)
                        and (not args.status or t['status'] in args.status)]
            end = args.offset + args.limit
            return {'store_id': store_id, 'tasks': [self.summary(t) for t in selected[args.offset:end]],
                    'total': len(selected), 'offset': args.offset, 'next_offset': end if end < len(selected) else None,
                    'completeness': completeness, 'issues': issues}
        if args.command == 'probe':
            if not 1 <= len(args.keywords) <= 32:
                fail('invalid_input', 'Invalid keyword count.')
            words = [text(k, 'keyword', 256).lower() for k in args.keywords]
            matches = [self.summary(t) for t in tasks if t['status'] in ACTIVE
                       and (args.project is None or t['project'] == args.project)
                       and any(w in ' '.join(str(t[k]) for k in ('id', 'title', 'project', 'group')).lower() for w in words)]
            for matched in matches:
                if matched['claim']['state'] == 'unknown':
                    issues.append({'code': 'unknown_claim', 'task_id': matched['id'], 'message': 'Matching claim cannot be validated.'})
            return {'store_id': store_id, 'coverage': 'unknown' if issues else 'matches' if matches else 'clear',
                    'matches': matches, 'issues': issues}
        counts = {status: 0 for status in STATUSES}
        groups, projects = {}, {}
        for task in tasks:
            counts[task['status']] += 1
            for collection, label in ((groups, task['group']), (projects, task['project'])):
                collection.setdefault(label, {s: 0 for s in STATUSES})[task['status']] += 1
        return {'store_id': store_id, 'by_status': counts, 'by_group': groups, 'by_project': projects,
                'invalid_count': invalid_count, 'issue_count': len(issues), 'completeness': completeness}

    def add_project(self, args):
        item = project(read_json(args.input, 65536, input_file=True))
        with self.locked(True) as store_id:
            config = self.projects()
            if revision(config) != args.expect_config_revision:
                fail('revision_conflict', 'Project configuration changed.', 3)
            if any(p['id'] == item['id'] for p in config['projects']):
                fail('already_exists', 'Project ID already exists.', 3)
            if len(config['projects']) >= 200:
                fail('limit_exceeded', 'Project count limit.', 5)
            config['projects'].append(item)
            write_json(self.home / 'projects.json', config, 65536)
            return self.config_view(store_id), 'committed'

    def view(self, task_id, store_id):
        from . import claim
        task = self.load(task_id)
        return {'store_id': store_id, 'task': {**task, 'revision': revision(task)}, 'claim': claim.read(self, task_id)}

    def add(self, args):
        safe_id(args.id)
        text(args.title, 'title', 4096, controls=True)
        text(args.owner, 'owner')
        self.validate_details(args.priority, args.description, args.next_action)
        if args.status == 'in_progress':
            fail('invalid_transition', 'Only claiming enters in_progress.')
        with self.locked(True) as store_id:
            config = self.projects()
            selected = next((p for p in config['projects'] if p['id'] == args.project), None)
            if selected is None:
                fail('invalid_input', 'Unknown project.')
            path = self.arcs / (args.id + '.json')
            if os.path.lexists(path):
                fail('already_exists', 'Task ID exists; add never overwrites.', 3)
            from . import claim
            ownership = claim.read(self, args.id)
            if ownership['state'] != 'absent':
                fail('state_unknown' if ownership['state'] == 'unknown' else 'held',
                     'Existing claim authority prevents creating this task.', 5 if ownership['state'] == 'unknown' else 3)
            ts = timestamp()
            task = {'id': args.id, 'title': args.title, 'project': selected['id'], 'group': selected['group'],
                    'status': args.status, 'owner': args.owner, 'priority': args.priority,
                    'description': args.description, 'next_action': args.next_action,
                    'created_at': ts, 'updated_at': ts, 'evidence': []}
            write_json(path, task)
            return self.view(args.id, store_id), 'committed'
