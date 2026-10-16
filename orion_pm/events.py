"""Bounded best-effort observation, never ownership or a complete undo journal."""
import fcntl
import json
import os
import stat
import time
from . import store


def read(s, task_id=None, limit=50):
    if not 1 <= limit <= 200:
        store.fail('invalid_input', 'Event limit must be 1..200.')
    result = {'events': [], 'history_complete': False, 'scanned_bytes': 0, 'truncated': False,
              'skipped_lines': 0, 'read_state': 'absent'}
    fd = None
    try:
        fd = os.open(s.home / 'events.jsonl', os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise OSError('unsafe log')
        start = max(0, info.st_size - 1024 * 1024)
        os.lseek(fd, start, os.SEEK_SET)
        raw = b''
        while len(raw) < 1024 * 1024:
            part = os.read(fd, min(65536, 1024 * 1024 - len(raw)))
            if not part:
                break
            raw += part
        result.update(scanned_bytes=len(raw), truncated=bool(start), read_state='ok')
        if start:
            raw = raw.partition(b'\n')[2]
        valid = []
        for index, line in enumerate(raw.splitlines(keepends=True)):
            try:
                if len(line) > 4096 or not line.endswith(b'\n'):
                    raise ValueError
                record = json.loads(line.decode('utf-8'), object_pairs_hook=store._pairs)
                if not isinstance(record, dict) or not {'task_id', 'event', 'ts', 'appended_at'} <= set(record):
                    raise ValueError
                if not set(record) <= {'task_id', 'event', 'ts', 'appended_at', 'actor', 'request_id', 'from_status', 'to_status'}:
                    raise ValueError
                store._depth(record)
                store.canonical(record)
                store.parse_time(record['ts']); store.parse_time(record['appended_at'])
                if not isinstance(record['task_id'], str) or not isinstance(record['event'], str):
                    raise ValueError
                if task_id is None or record['task_id'] == task_id:
                    valid.append((store.parse_time(record['ts']), index, record))
            except (ValueError, UnicodeError, TypeError, RecursionError):
                result['skipped_lines'] += 1
        valid.sort(key=lambda row: (row[0], row[1]))
        result['events'] = [row[2] for row in valid[-limit:]]
    except FileNotFoundError:
        pass
    except OSError:
        result['read_state'] = 'unknown'
    finally:
        if fd is not None:
            os.close(fd)
    return result


def emit(s, record):
    """Observe a completed operation; loss/ordering are explicitly non-authoritative."""
    fd = None
    try:
        record = {'ts': store.timestamp(), **record}
        fd = os.open(s.home / 'events.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            return
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.01)
        record['appended_at'] = store.timestamp()
        raw = store.canonical(record) + b'\n'
        if len(raw) > 4096:
            return
        original = os.fstat(fd).st_size
        position = 0
        try:
            while position < len(raw):
                n = os.write(fd, raw[position:])
                if n <= 0:
                    raise OSError('short event write')
                position += n
        except BaseException:
            try:
                os.ftruncate(fd, original)
            except OSError:
                pass
            raise
    except Exception:
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
