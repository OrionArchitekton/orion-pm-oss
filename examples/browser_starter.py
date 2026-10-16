"""Adapter recipe over caller-supplied native lease/read/release operations.

This is an example seam, not a new browser API. An actual driver must bind the
released browser's real contract and prove its own lease cleanup separately.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from cli_consumer import BoundaryError


def run(pm, task_id, holder, browser, receipt_dir):
    data = pm.acquire(task_id, holder)  # The losing claimant never touches browser.
    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    request_id = uuid.uuid4().hex
    correlation = {'store_id': data['store_id'], 'task_id': task_id,
                   'claim_generation': data['claim']['generation'], 'request_id': request_id,
                   'component': str(browser.version), 'native_resource_id': None,
                   'delivery_state': 'not_sent'}
    lease, result, released = None, None, False
    error = None
    try:
        lease = browser.lease()
        if not isinstance(lease, str) or not lease:
            raise BoundaryError('unknown native lease outcome')
        correlation.update(native_resource_id=lease, delivery_state='accepted')
        result = browser.read(lease)
        if (not isinstance(result, dict) or not isinstance(result.get('title'), str) or not result['title']
                or len(result['title']) > 4096 or not isinstance(result.get('ref'), str) or not result['ref']
                or len(result['ref']) > 2048):
            raise BoundaryError('unknown native read result')
    except BaseException as exc:
        correlation['delivery_state'] = 'timed_out' if isinstance(exc, TimeoutError) else 'unknown'
        error = exc
    finally:
        if lease is not None:
            try:
                released = browser.release(lease) is True
            except Exception:
                released = False
        if not released:
            correlation['delivery_state'] = 'unknown'
        correlation['observed_at'] = datetime.now(timezone.utc).isoformat()
        (receipt_dir / 'correlation.json').write_text(json.dumps(correlation, indent=2) + '\n')
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        raise error
    if error is not None or not released:
        raise BoundaryError('Native operation or release is unknown; reconcile it without blind retry.')
    correlation['delivery_state'] = 'observed_result'
    (receipt_dir / 'correlation.json').write_text(json.dumps(correlation, indent=2) + '\n')
    evidence = {'id': 'browser-' + request_id, 'source': 'starter-browser-adapter',
                'artifact': 'sha256:' + hashlib.sha256(result['title'].encode()).hexdigest(),
                'observed_at': correlation['observed_at'],
                'scope': 'Observed the public synthetic page title and successful native lease release.',
                'ref': result['ref']}
    filename = receipt_dir / 'evidence.json'
    filename.write_text(json.dumps(evidence) + '\n')
    return pm.attach_and_finish(data, str(filename))
