---
verified: 2026-10-15
review_after: 2026-11-15
topics: [installation, local-store, claims, recovery, backup, rollback]
references:
  - specs/orion-pm-core-spec.md
  - orion_pm/store.py
  - orion_pm/claim.py
  - orion_pm/admission.py
  - orion_pm/events.py
---
# Local store operation and recovery

Verified scope: private synthetic installed-CLI tests on WSL2/ext4 with Python
3.11.14. This does not authorize or establish adoption by a private estate runtime.

## Install and validate

Install a reviewed wheel into a dedicated environment, using README commands and
an explicit new absolute store path. Keep its executable separate from existing
PM commands. Package installation performs no hook/settings/service/account change.
Verify `--json version`, capabilities and the tested support matrix. Initialize
from the synthetic project config; legacy/non-empty unrecognized stores refuse.

Validate add -> probe -> competing claims -> renew -> release/complete -> show,
plus audit and surface, against an isolated store. Read the explicit coverage,
claim and admission classification, not only exit 0. Unknown is never clear/open.

## Normal operation and monitoring

Probe only work already requested. Claim before working and retain exact holder,
generation and task revision. Renew live ownership; read back the current revision
before a guarded edit. A transition out of progress clears the exact claim; release
returns progress to todo. Resources retain their native leases and cleanup.

`surface`, `audit`, `overdue`, `triage TASK`, and admission status are local read-only
checks. Surface clips entries and reports overflow/completeness; show reads one full
task. Events are incomplete observations, never authoritative undo or approval.
No recurring monitor/timer is installed. Select checks deliberately when operating.

## Maintenance and drain

Acquire a bounded maintenance lease with explicit holder/reason/TTL and save the
returned lease ID. Confirm active admission closure. Existing holders can renew,
attach evidence and finish/release; new claims and takeover refuse. Release with
the exact maintenance holder and ID. Old IDs cannot release a replacement.

Maintenance expires; it neither freezes file writes nor stops workers. Stop or
drain every sanctioned writer before an offline operation. Confirm native resources
and outside processes separately. Unknown maintenance authority closes admission
and requires containment, not forced deletion or an assumption that nothing runs.

## Interrupted or ambiguous operation

A missing command response, timeout or `mutation_unknown` means inspect task,
claim and external resource/request state before choosing another action. Never
retry blindly based on an absent response. Event absence proves no non-occurrence.

A valid expired claim can be explicitly taken over using the observed generation,
exact expiry and task revision plus a reason. This creates a new generation and
does not stop the old worker. Expired workers cannot renew or complete; the exact
expired handle may release unfinished work. A progress orphan with **verifiably
absent** claim can be recovered to todo with its revision and a reason. No TTL
reaper or network recovery capability is present in this profile.

Unknown/corrupt/symlinked/special authority is never auto-removed. Stop writers and
independently contain any related process/resource first. Preserve an owner-private
offline copy and its hashes. Quarantine only the exact unsafe entry outside the
store under operator control; never blanket-delete claims or edit task JSON to
manufacture ownership. Re-run audit, then use sanctioned recovery for remaining
progress orphans. Filesystem quarantine is an offline human recovery procedure,
not an extension API or permission to bypass action approvals.

## Backup, restore and upgrade

Stop/drain writers and reconcile resources first; a live copy is not a transferable
lease. Preserve the marked store, project configuration and durable tasks in an
owner-private offline backup bound to the artifact/format version. Claims can be
preserved separately for forensic reference, but must not be restored as live
ownership. Do not back up unrelated accounts, profiles, handoffs or transcripts.

Restore into a separate absolute private directory while the original is inactive.
Restore the compatible marker/configuration/tasks; create a new empty owner-private
claim area. Audit, then explicitly recover each progress orphan before admitting
work. Do not run two copies of the same store identity as one cross-host domain.
Do not alter JSON status to hide failed recovery.

Use a compatible reviewed artifact; unsupported format versions refuse. Upgrade
and restore are deliberate offline operations. There is no automatic startup
migration or private-estate deployment helper.

## Rollback and uninstall

Stop the candidate and its callers, retain the failing snapshot privately, and
select the prior artifact plus its known-compatible offline state backup. Validate
capabilities, audit, competing claim behavior and a guarded persisted transition
before resuming. If compatibility is uncertain, remain stopped and inspect it.

Uninstall removes the package/environment, leaving user state for deliberate
retention or separately selected removal. Do not overwrite another PM installation,
restore live claims, or install/uninstall harness hooks as part of package rollback.
