"""Bounded validated observation shared by human and machine consumers."""
import os
from . import admission, claim, store


def findings(s, tasks, task_issues):
    result = list(task_issues)
    known = {t['id'] for t in tasks}
    claim_records, scan_issues = claim.corpus(s)
    result.extend(scan_issues)
    for task in tasks:
        c = claim.read(s, task['id'])
        code = None
        if c['state'] == 'unknown':
            code = 'unknown_claim'
        elif task['status'] == 'in_progress' and c['state'] != 'live':
            code = 'progress_without_live_claim'
        elif task['status'] != 'in_progress' and c['state'] in ('live', 'expired'):
            code = 'provisional_claim' if task['status'] in ('backlog', 'todo') else 'status_exit_residue'
        if code:
            result.append({'code': code, 'task_id': task['id'], 'message': 'Task/claim needs explicit recovery.', 'claim': c})
    for aid, observed in claim_records.items():
        if aid not in known:
            result.append({'code': 'orphan_claim', 'task_id': aid, 'message': 'Claim has no validated task.', 'claim': observed})
    if admission.status(s)['state'] == 'unknown':
        result.append({'code': 'admission_unknown', 'task_id': None, 'message': 'Maintenance authority unknown.'})
    return sorted(result, key=lambda f: (f['task_id'] or '', f['code']))


def projection(s, store_id):
    tasks, issues = s.corpus()
    faults = findings(s, tasks, issues)
    inflight, stale = [], []
    queue = []
    for task in tasks:
        c = claim.read(s, task['id'])
        if task['status'] == 'in_progress' and c['state'] == 'live':
            inflight.append(s.summary(task))
        if c['state'] in ('expired', 'unknown') or task['status'] == 'in_progress' and c['state'] == 'absent':
            report = claim.triage(s, task)
            stale.append({'task_id': task['id'], 'revision': report['revision'],
                          'claim': report['claim'], 'issue': report['disposition']})
        if task['status'] in ('backlog', 'todo') and c['state'] == 'absent':
            queue.append(task)
    queue.sort(key=lambda t: t['id'])
    queue.sort(key=lambda t: store.parse_time(t['updated_at']), reverse=True)
    queue.sort(key=lambda t: t['priority'], reverse=True)
    class Rollup:
        command = 'rollup'
    rollup = s.observe(Rollup(), store_id)
    rollup.pop('store_id')
    counts = {'inflight': max(0, len(inflight) - 20), 'stale': max(0, len(stale) - 20),
              'claim_issues': max(0, len(faults) - 20), 'queue': max(0, len(queue) - 12)}
    return {'store_id': store_id, 'rollup': rollup, 'inflight': inflight[:20], 'stale': stale[:20],
            'claim_issues': faults[:20], 'queue': [s.summary(t) for t in queue[:12]],
            'admission': admission.status(s), 'completeness': 'partial' if faults else 'complete', 'overflow': counts}


def render(data):
    # Escaping via JSON string form keeps terminal control sequences inert.
    import json
    def clip(value):
        text = str(value)[:140]
        rendered = json.dumps(text, ensure_ascii=True)
        # Bound the escaped field, including quotes. With at most 72 rows
        # and two fields per row, this keeps the complete text below 32 KiB.
        while len(rendered.encode('ascii')) > 142:
            text = text[:-1]
            rendered = json.dumps(text, ensure_ascii=True)
        return rendered
    lines = ['Orion PM local tasks', 'State: ' + data['completeness'],
             'Claim admission: ' + data['admission']['state']]
    for label in ('inflight', 'stale', 'claim_issues', 'queue'):
        lines.append(label + ':')
        for item in data[label]:
            lines.append('  ' + clip(item.get('id', item.get('task_id'))) + ' ' + clip(item.get('title', item.get('code', item.get('issue', '')))))
        if data['overflow'][label]:
            lines.append('  omitted: ' + str(data['overflow'][label]))
    return '\n'.join(lines)
