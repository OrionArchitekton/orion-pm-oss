"""One fail-closed maintenance generation, sharing the task mutation lock."""
from datetime import timedelta
import hashlib
import os
import re
import secrets
from . import store


def _directory(s):
    return s.claims / '.claim-admission'


def _record(s):
    if os.path.lexists(s.home / 'claim-admission.lock'):
        return {'unknown': True}
    directory = _directory(s)
    if not os.path.lexists(directory):
        return None
    try:
        store.directory(directory)
        with os.scandir(directory) as entries:
            names = []
            for entry in entries:
                names.append(entry.name)
                if len(names) > 64:
                    raise ValueError
        if not names:
            return None
        if len(names) != 1 or not re.fullmatch('[0-9a-f]{32}[.]json', names[0]):
            raise ValueError
        rec = store.read_json(directory / names[0], 16384)
        if (not isinstance(rec, dict) or set(rec) != {'schema_version', 'holder', 'reason', 'lease_id', 'acquired_at', 'expires_at'}
                or type(rec['schema_version']) is not int or rec['schema_version'] != 1
                or rec['lease_id'] + '.json' != names[0]):
            raise ValueError
        store.text(rec['holder'], 'holder'); store.text(rec['reason'], 'reason', 4096, controls=True)
        acquired, expires = store.parse_time(rec['acquired_at']), store.parse_time(rec['expires_at'])
        if not timedelta(0) < expires - acquired <= timedelta(minutes=60):
            raise ValueError
        return rec
    except (store.PMError, OSError, TypeError, ValueError, KeyError):
        return {'unknown': True}


def status(s):
    rec = _record(s)
    if rec is None:
        return {'state': 'open', 'claims_admitted': True}
    if rec.get('unknown'):
        return {'state': 'unknown', 'claims_admitted': False}
    state = 'expired' if store.now() >= store.parse_time(rec['expires_at']) else 'active'
    return {'state': state, 'claims_admitted': state == 'expired', 'holder': rec['holder'],
            'lease_id': rec['lease_id'], 'acquired_at': rec['acquired_at'], 'expires_at': rec['expires_at'],
            'reason_sha256': hashlib.sha256(rec['reason'].encode()).hexdigest()}


def require_open(s):
    state = status(s)
    if state['state'] == 'unknown':
        store.fail('admission_unknown', 'Claim admission is indeterminate.', 5)
    if not state['claims_admitted']:
        store.fail('admission_closed', 'Claim admission is paused.', 3)


def mutate(s, args):
    store.text(args.holder, 'holder')
    if args.admission_action == 'acquire':
        store.text(args.reason, 'reason', 4096, controls=True)
        if type(args.ttl_minutes) is not int or not 1 <= args.ttl_minutes <= 60:
            store.fail('invalid_input', 'Maintenance TTL must be 1..60 minutes.')
        preflight = {'schema_version': 1, 'holder': args.holder, 'reason': args.reason,
                     'lease_id': '0' * 32, 'acquired_at': '0' * 32, 'expires_at': '0' * 32}
        if len(store.canonical(preflight)) + 1 > 16384:
            store.fail('invalid_input', 'Encoded maintenance record exceeds 16 KiB.')
    elif not re.fullmatch('[0-9a-f]{32}', args.lease_id):
        store.fail('invalid_input', 'Invalid maintenance generation.')
    with s.locked(True) as store_id:
        old = _record(s)
        if args.admission_action == 'release':
            if old is None or old.get('unknown') or old['holder'] != args.holder or old['lease_id'] != args.lease_id:
                store.fail('stale_claim', 'Exact maintenance holder and generation required.', 3)
            try:
                store.mutation_started = True
                (_directory(s) / (old['lease_id'] + '.json')).unlink()
            except OSError:
                store.fail('mutation_unknown', 'Maintenance release uncertain; inspect admission.', 7)
        else:
            require_open(s)
            d = _directory(s)
            d.mkdir(mode=0o700, exist_ok=True)
            moment = store.now()
            rec = {'schema_version': 1, 'holder': args.holder, 'reason': args.reason,
                   'lease_id': secrets.token_hex(16), 'acquired_at': moment.isoformat(),
                   'expires_at': (moment + timedelta(minutes=args.ttl_minutes)).isoformat()}
            fd = None
            try:
                fd = os.open(d / (rec['lease_id'] + '.json'), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                store.mutation_started = True
                raw = store.canonical(rec) + b'\n'
                while raw:
                    n = os.write(fd, raw)
                    if n <= 0:
                        raise OSError('short maintenance write')
                    raw = raw[n:]
                os.fsync(fd)
                if old is not None:
                    (d / (old['lease_id'] + '.json')).unlink()
            except OSError:
                store.fail('mutation_unknown', 'Maintenance acquisition uncertain; inspect admission.', 7)
            finally:
                if fd is not None:
                    os.close(fd)
            if store.now() >= store.parse_time(rec['expires_at']):
                store.fail('mutation_unknown', 'Maintenance expired during creation.', 7)
        return {'store_id': store_id, 'admission': status(s)}, 'committed'
