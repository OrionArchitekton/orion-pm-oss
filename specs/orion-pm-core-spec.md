# Orion PM core v0.1 specification

Status: public standalone implementation contract, 2026-10-15.
This specifies required behavior and does not replace the existing estate PM
specification, runtime, or store. Installed behavior is established by separate
artifact-specific test receipts, not by this document.

Implementation profile: `0.1.1`, API 1/store format 1. All required
capabilities are included; optional `git-recovery.v1` is omitted. Its flags reject,
and triage remains local/report-only. MIT is selected for this private release candidate. This profile has no
publication approval. Actual-browser and additional-platform receipts remain separate from
local core acceptance.

## Outcome and scope

A developer running cooperating agents on one Linux machine can record tasks,
discover potentially overlapping work, acquire exclusive task ownership, finish
or relinquish work, and recover honestly after interruption. Another package can
use that coordination through the installed CLI without importing private helpers
or editing PM state. The package is useful by itself and can later join a
versioned distribution.

The core includes local tasks, project grouping, coverage, claims, guarded
transitions, bounded evidence references, maintenance admission, read-only views,
and best-effort events. It has no daemon, scheduler, account, model provider,
database, dispatch engine, automatic board policy, approval broker, transcript
reader, process controller, or mandatory shared SDK. Runtime imports use the
Python standard library only. Installing the package does not install a hook,
edit harness settings, start a service, download a model, or sign into anything.

Initial target: Python 3.11+ on Linux with a tested local filesystem supporting
exclusive file creation, atomic replacement, and advisory file locking. Release
support is limited to interpreter/filesystem combinations actually tested on the
built artifacts. WSL needs its own tested local Linux-filesystem row. Native
Windows, macOS, network/synchronized filesystems, cross-host ownership, hostile
same-user processes, and power-loss transaction durability are outside v0.1.

## Canonical language and authority

| Term | Meaning |
|---|---|
| Task | A durable unit of requested work with a stable opaque ID. Replaces public use of `arc`. |
| Project | An explicitly configured task grouping. Replaces public use of lane `slug`. |
| Group | Optional project rollup label, default `workspace`. Replaces public use of lane `business`. |
| Owner | Descriptive task metadata, default `unassigned`; grants no authority. |
| Holder | Caller-chosen identity for one cooperating session; never inferred from a human or harness name. |
| Claim | Exclusive local coordination record for one task, with an expiry and a generation. |
| Generation | Fresh opaque identifier for each acquisition or takeover; unchanged by renewal. |
| Revision | Opaque content token for a validated durable task or project configuration snapshot. |
| Request ID | Optional caller-supplied correlation for one command; not an idempotency or approval token. |
| Evidence reference | Bounded pointer plus artifact/source identity, observation time, and narrowly stated scope. |
| Admission | Whether a new task-claim generation may be created. |

Task IDs, holders, revisions, generations, statuses, and evidence are coordination
data. They do not authorize publishing, sending, merging, deployment, spending,
credential access, or execution by another tool. A task marked `done` records the
caller's disposition; PM does not independently certify the work or its approval.
Task text, evidence text, and imported handoffs remain untrusted data.

A claim prevents a second sanctioned local holder from acquiring the same task.
Expiry or takeover does not stop an old process, undo an external action, release
a browser/phone lease, or fence execution on another host. Executors retain their
own permissions, approval checks, request semantics, and resource leases.

## Stable integration seam

The installed `orion-pm` CLI with `--json` is the supported cross-language seam.
Python module names and on-disk representation are private implementation details.
Extensions must use the CLI for task/claim reads and all mutations. There is no
plugin loading, arbitrary patch operation, external event injection, or public
Python API in v0.1.

`--json` is a global option placed before the command. Other global options are
`--home ABSOLUTE_PATH`, optional `--request-id TEXT`, and `--api-version N`
(default 1; other requested versions return `unsupported_api`). Usage errors, including
parser errors, use the same JSON envelope when `--json` was requested. Standard
output contains exactly one UTF-8 JSON object plus a newline; diagnostics never
mix into it. Human output is intended for people and is not a parsing contract.
JSON strings escape control characters; human views escape terminal controls.

Every envelope has exactly these required top-level fields:

```json
{
  "api_version": 1,
  "command": "claim",
  "request_id": "operation-17",
  "ok": true,
  "outcome": "committed",
  "data": {},
  "warnings": [],
  "error": null
}
```

`request_id` is null when absent. `command` is the canonical command name, or
`unknown` when parsing could not identify one. Warnings are objects with `code`
and `message`. An error has `code` and `message`; rejected/indeterminate results
have `ok=false`, `data=null`, and a non-null error. Messages are informational;
consumers branch on codes. Valid diagnostic reports can contain findings while
remaining `ok=true`.

| Exit | Outcome | Meaning and representative codes |
|---|---|---|
| 0 | `observed`, `committed`, or `no_change` | Valid read, established mutation result, or explicitly harmless no-op. |
| 2 | `rejected` | Invalid request: `invalid_input`, `invalid_transition`, `unsupported_api`. |
| 3 | `rejected` | Concurrency/selection refusal: `held`, `not_claimable`, `stale_claim`, `revision_conflict`, `already_exists`, `no_candidate`, `admission_closed`. |
| 4 | `rejected` | `not_found`: requested task absent in a successfully read supported store. |
| 5 | `indeterminate` | `coverage_unknown`, `state_unknown`, `admission_unknown`, `limit_exceeded`, `incompatible_store`; cannot safely conclude absence or permission. |
| 6 | `rejected` | `unavailable`: required store/tool/lock unavailable, with no authoritative write attempted. |
| 7 | `indeterminate` | `mutation_unknown`: failure after an authoritative write may have begun. Re-read; do not blindly retry. |

`--json version` returns package version, API version, store-format version,
capability IDs, and supported-platform description, without reading/creating a
store. Required capability IDs are `tasks.v1`, `coverage.v1`, `claims.v1`,
`transitions.v1`, `evidence.v1`, `admission.v1`, `views.v1`, and `events.v1`.
Optional Git recovery advertises `git-recovery.v1` when implemented and tested.
There is no automatic fallback to a private helper if a capability is absent.

Unknown request fields/options are rejected. Consumers tolerate additional
response fields inside `data`, but must reject unknown API versions and unknown
decision-bearing enums instead of mapping them to success. API 1 changes to
required fields, semantics, enum meanings, or exit codes require an API version
change. Component release versions and store-format versions are independent;
the first distribution pins exact tested artifacts rather than inferring
compatibility from a `0.x` version range.

Every successful state-dependent reply has `data.store_id`; consumers bind
correlation to that store as well as task ID. All `data` values are objects. The
minimum required command-specific fields are:

| Command family | Fields in `data` in addition to store_id |
|---|---|
| `version` (no store_id) | `package_version`, `api_version`, `store_format_version`, `capabilities`, `platforms`. |
| `init`, `projects list`, `projects add` | `projects` (ID/group summaries), `config_revision`. |
| `add`, `show`, claim/renew/release/transition/takeover/recover, `evidence attach` | `task` (full public shape), `claim` (validated classification). |
| `list` | `tasks` (summaries), `total`, `offset`, `next_offset`, `completeness`, `issues`. |
| `rollup` | `by_project`, `by_group`, `by_status`, `invalid_count`, `issue_count`, `completeness`. |
| `probe` | `coverage`, `matches` (summaries), `issues`. |
| `overdue` | `items` (task ID/revision, claim view, issue), `completeness`, `issues`. |
| `triage` | `task_id`, `revision`, `claim`, `disposition`, `evidence` (three-valued recovery findings). |
| `claim-admission status/acquire/release` | `admission` (validated classification). |
| `evidence list` | `task_id`, `revision`, `evidence`. |
| `surface` | The projection fields defined below. |
| `audit` | `findings` (code/task ID where known), `completeness`. |
| `events` | `events`, `history_complete`, `scanned_bytes`, `truncated`, `skipped_lines`, `read_state`. |

`by_status` maps status to count directly; `by_project`/`by_group` map their IDs
to such status maps. Missing status counts are zero. Diagnostic `issues` and
`findings` have stable `code`, nullable `task_id`, and informational `message`.
Diagnostic reports can be `partial` or `unknown` with `ok=true`; a caller making
a coverage/admission/ownership decision must inspect the corresponding explicit
classification. Strict mutations instead refuse unknown prerequisites. Claim-next
uses `coverage_unknown` when the task corpus cannot support safe selection.

## Store selection, initialization, and projects

Selection order: `--home`, then non-empty `ORION_PM_HOME`, then
`$XDG_DATA_HOME/orion-pm`, falling back to `~/.local/share/orion-pm` when the XDG
variable is absent. Explicit roots and an XDG root must be absolute. Invalid or
empty explicit overrides fail; they never fall back to another store. No current
directory search, estate registry, home-wide repository scan, or automatic import
is performed.

`init --projects FILE` creates a new owner-private store from bounded neutral JSON.
The input object has `schema_version: 1` and a non-empty `projects` array. Each
project has `id`, optional `group`, and optional `repository`. Repository data is
`{path, remote, github_repository}`: an explicit absolute existing repository directory,
explicit remote name, and optional `owner/repository` identity. It is used only by
opt-in recovery; it grants no account or Git authority. Configuration paths may
contain private information and are not included in normal task/surface output.

Initialization writes a random `store_id` and `store_format_version: 1` marker,
project configuration, and empty task/claim areas. It refuses any non-empty
unrecognized destination, including a legacy estate store. A matching initialized
store plus identical configuration returns `no_change`; differing configuration
returns `already_exists`. Interrupted initialization is recognized as incomplete
and never adopted by a normal command. Restrictive owner-only directory/file
permissions are the default; group/world-writable authority paths are rejected.
Symlinked authority roots/components and non-regular authority files are refused.
Store ID is a stable opaque 32-character lowercase hexadecimal identifier. A
copied/restored store must not be concurrently used as the same ownership domain
on another host; restored ephemeral ownership is handled by the runbook.

`projects list` returns IDs, groups, and `config_revision` without repository
paths. `projects add --input FILE --expect-config-revision R` appends one validated
project atomically. Duplicate IDs or a stale revision refuse without changes.
v0.1 has no project deletion, rename, or repository-path editing command; these
need a later explicit compatible operation rather than extension file edits.

Every state-dependent command requires a recognized marker and supported format.
Missing, unsupported, incomplete, or unsafe stores never appear as an empty board.
Reads never initialize or repair state. A future format upgrade requires an
explicit offline operation and compatible backup/rollback, not implicit startup
migration. Existing private stores and deployed consumers retain their versions.

## Task interface

The public task shape includes `id`, `title`, `project`, `group`, `status`,
`owner`, `priority`, `description`, `next_action`, `created_at`, `updated_at`,
`evidence`, and `revision`. Description/next action default to null, evidence to
an empty list, and priority to zero. Timestamps are timezone-aware UTC RFC 3339.
Revision is a lowercase SHA-256 of the canonical persisted task object: UTF-8,
keys sorted, compact separators, no non-finite numbers, no revision field. A
project configuration revision uses the same canonicalization over its object.
Any successful durable task change changes its revision unless it is explicitly
reported as `no_change`. Renewal alone changes no task field or revision.

| Command | Required arguments and behavior |
|---|---|
| `add` | `--id ID --title TEXT --project ID`; optional `--owner`, `--priority`, `--description`, `--next-action`, `--status` (default `backlog`). Create only; never overwrite. |
| `show` | `TASK_ID`; return full validated task and claim view in one observation. |
| `list` | Optional repeatable `--project` / `--status`; `--limit` (default 50, max 200), `--offset` (default 0). Return task summaries sorted by ID. |
| `rollup` | Counts by project/group/status plus invalid/unknown counts. |
| `probe` | One or more non-empty keywords and optional `--project`; case-insensitive ANY substring match on task ID, title, project and group among active tasks. |

Summaries include ID, title (clipped to 140 characters with `title_truncated`),
project, group, status, owner, priority, revision, and claim classification.
List replies include `total`, `offset`, and `next_offset` (null when finished).
`total` counts validated matching tasks; incomplete observations cannot establish
the count of unknown tasks and must retain their issues/completeness.
Pagination describes successive observations, not a snapshot maintained across
commands; a caller needing a fresh selection must re-read and use mutation guards.

IDs are opaque case-sensitive safe ASCII segments matching
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. No separator, parent traversal, NUL, or implicit
normalization is accepted. Project/group IDs follow the same grammar. Priority is
a finite JSON number in [-1000000, 1000000]; booleans are not numbers. Caller
timestamps, revisions, group overrides, and arbitrary extra metadata are refused.
The owner is descriptive even when equal to a holder string.

Retained statuses are `backlog`, `todo`, `in_progress`, `blocked`, `done`,
`cancelled`, `deferred`, `superseded`, `requires_ratification`. Active means
`backlog`, `todo`, `in_progress`, `blocked`, or `requires_ratification`. Creation
allows every status except `in_progress`; only claim acquisition enters that
status. `requires_ratification` means a task needs a person's disposition; it is
neither approval storage nor authorization. Terminal/deferred work is never
silently resurrected or selected by claim-next.

`probe` returns `coverage: clear|matches|unknown`, `matches`, and `issues`.
`clear` means no keyword match within the validated active corpus, not absence of
all possible overlapping work. Probe is heuristic and grants no work authority.
Unreadable, malformed, unsupported, over-limit, or incompletely enumerated task
state yields a successful diagnostic report with `coverage: unknown`, explicit
issues, and any valid matches. A matching unknown/corrupt claim also prevents a
clear result. A top-level unavailable store instead uses the error envelope.
Never treat parse/permission/tool failure as an empty or clear result.
`show` refuses a malformed requested task with `state_unknown`; it does not
require unrelated tasks to be healthy. List/rollup may report validated subsets
with explicit issues/completeness and never call them a complete empty corpus.

## Claims and guarded mutations

Claim authority lives solely in the claim area, created with structural exclusive
creation. A task status or event is never alternative claim authority. Sanctioned
task writes, claim generation changes, and maintenance acquisition/release share
one local mutation lock. Reads of task/claim/configuration views take its shared
form so they do not report a half-completed sanctioned operation. Lock acquisition
is bounded to two seconds; unavailable locking yields an explicit error.

A public claim view has `state: absent|live|expired|unknown`. A valid present claim
also has `task_id`, `holder`, `generation` (32 lowercase hex characters),
`acquired_at`, `expires_at`, and optional `branch` (null when absent). The exact
claim handle is `(task_id, holder, generation)`. Host/PID, if retained internally,
are diagnostic metadata and never proof that a worker stopped. Read views expose
generation for recovery/correlation; it is a concurrency guard, not a secret or
an authentication credential.

| Command | Contract |
|---|---|
| `claim TASK_ID --holder H` | Optional `--branch B --ttl-hours N` (integer 1..24, default 4). Acquire only `backlog`/`todo` with absent claim and open admission. Return task and exact claim handle after promotion to `in_progress`. |
| `claim-next --holder H` | Same options, optional repeatable `--project`. Choose claimable tasks by priority DESC, updated_at DESC, ID ASC. Strict corpus validation precedes selection. Return `no_candidate` only after complete trustworthy enumeration. |
| `renew TASK_ID --holder H --generation G` | Same TTL range; exact live generation only. Set expiry from actual renewal time. Preserve generation and task revision. Expired renewal refuses; use explicit recovery. |
| `release TASK_ID --holder H --generation G --expect-revision R` | Exact valid live or expired generation. Relinquish by setting an `in_progress` task to `todo` and clearing that claim. A non-progress residue keeps its status while clearing the exact claim. No force release. |
| `transition TASK_ID STATUS --expect-revision R` | Required `--holder H --generation G` when a claim exists, including same-status requests; exact live claim for any transition except release. Optional `--actor A` is event attribution only. |
| `takeover TASK_ID --holder H --expect-generation G --expect-expires-at T --expect-revision R --reason TEXT` | Explicit expired-only recovery; optional branch/TTL. Compare all observations under lock, replace exact expired generation with a fresh one and enter/remain `in_progress`. Admission must be open. |
| `recover TASK_ID --expect-revision R --reason TEXT` | Explicit orphan recovery only when status is `in_progress` and claim is verifiably absent; move to `todo`. A present/unknown claim refuses. |

Every handle-bearing command compares holder **and generation**, even if the new
holder reused the old label. Every durable task edit compares revision under the
same mutation lock. Claim/claim-next observe the current task under that lock and
bind promotion to its revision internally; they accept no stale task snapshot.
Other edits require the caller-supplied revision. Missing required guards reject;
stale guards change nothing.
Generation checks also protect cleanup after a failed acquisition. A claim taken
before maintenance can renew, attach evidence, release, or transition during it.

Transition rules:

- Entry to `in_progress` is private to claim/takeover; the transition command
  rejects a request to enter it from another status.
- From `in_progress`, an exact live holder may move to any other retained status.
  The status write precedes removal of that exact generation under the same lock.
- A task outside `in_progress` with verifiably absent claim may move to any other
  status except `in_progress`, guarded by revision. This permits explicit
  reopening and optional board dispositions without exposing a general editor.
- Same-status transition with matching required guards returns `no_change` and
  leaves bytes/timestamps unchanged. Unknown claim/task state refuses mutations.
- Expired ownership does not permit completion or evidence edits. The exact
  expired holder may release; an operator may explicitly take over. Recovery
  never implies that an old external action was cancelled.

Claims and task writes are linearized for cooperating processes, but two-file
operations are not a crash-atomic transaction. A process killed between writes can
leave a provisional claim, an orphan progress task, or a status-exit claim residue.
Failed cleanup cannot remove another generation. `audit`, `show`, and `surface`
expose residues conservatively; none auto-repair them. If a command cannot
establish whether it committed, it returns `mutation_unknown` if it can still
respond. A killed process may return no envelope; consumers must then inspect the
authoritative state. They must not treat missing output as proof of no mutation.

## Recovery and maintenance

`overdue` is local/read-only and reports expired/unknown claims and progress
orphans. `triage TASK_ID` is also report-only by default, reporting the exact task
revision, observed generation/expiry, and recovery disposition. TTL alone never
causes automatic demotion or deletion. Corrupt authority is always surfaced for
manual containment/quarantine under the runbook, never automatically removed.

Optional `triage --git-evidence` uses only the project's explicit repository and
the claim's explicit branch. Local worktree evidence can be gathered offline;
remote/PR checks require the additional `--allow-network` flag. Bare names,
ambiguous roots, no branch, absent tools, failed authentication, denied access,
timeouts, pagination uncertainty, or mismatched remote/GitHub identity are unknown.
No credential discovery or interactive authentication is performed. Checks use
argument arrays, a five-second per-check timeout, and a fifteen-second total
budget; captured errors are bounded and do not echo credentials or remote URLs.

An automatic-recovery candidate requires **all three positively determined**:
no matching worktree, no branch on the reachable configured remote, and no open PR
for the exact configured repository/branch. These are repository inactivity
evidence, not proof an arbitrary process died. If the optional capability is
omitted, triage can only report unknown/surface and explicit recovery remains
available; no dead-evidence behavior is simulated.

`triage TASK_ID --git-evidence --allow-network --apply --expect-generation G
--expect-expires-at T --expect-revision R` gathers fresh evidence, then under the
mutation lock compares all three supplied observations and rechecks expiry.
Only the three-positive rule can demote `in_progress` to `todo` and remove that
exact claim; any concurrent renewal, replacement, or task edit returns a conflict.
There is no timer, bulk `--apply`, caller-supplied `dead=true`, or TTL-only reaper.

Triage `disposition` is `not_stale|surface|orphan|would_demote|demoted`.
`would_demote` is a report-only complete three-positive finding; `demoted` requires
the guarded apply path. Recovery `evidence` includes `worktree_present`,
`on_remote`, and `has_open_pr` as true/false/null (null means unknown), plus a
bounded `rule` label. Default local triage leaves uncollected evidence null.
An apply request with unknown evidence refuses with `state_unknown`; positively
present work refuses with `not_claimable`; stale observations return the relevant
claim/revision conflict. No refused apply reports `demoted`.

`claim-admission status` reports `state: open|active|expired|unknown` and
`claims_admitted`. Only absent or one valid expired maintenance generation admits
new claims. `claim-admission acquire --holder H --reason TEXT --ttl-minutes N`
(integer 1..60, default 15) acquires one generation-qualified maintenance lease.
`claim-admission release --holder H --lease-id G` can remove only that exact
generation. Multiple, unreadable, malformed, linked, or unsafe authority entries
are unknown and close admission. No maintenance renewal is included in v0.1.

Maintenance status/acquisition returns holder, lease ID, acquisition/expiry,
claims_admitted, and a SHA-256 of the reason; the reason text is not echoed or
emitted as an event. Concurrent maintenance acquisition and new claim acquisition
have one linear order. Active/unknown maintenance blocks claim, claim-next, and
takeover before a new generation or task promotion. It does not freeze task
administration, drain existing holders, fence shells, or prove deployment safety.

## Evidence, views, and events

`evidence attach TASK_ID --input FILE --expect-revision R` adds one reference.
When a claim exists it also requires `--holder H --generation G` for the exact
live generation. Without a claim it can edit only a task outside `in_progress`.
It refuses unknown/expired authority and never changes status or claim. The input
object has exactly `id`, `source`, `artifact`, `observed_at`, `scope`, and `ref`.
ID uses the task ID grammar; source is a component/source label; artifact is an
explicit immutable identifier asserted by the producer (such as a digest or
commit); observed_at is timezone-aware RFC 3339; scope says precisely what was
observed; ref is an opaque pointer. All are non-empty strings. PM validates shape
but does not authenticate the producer, dereference the pointer, embed a file,
fetch a URL, execute content, or certify the claim made by the reference.

An evidence ID is unique within its task. An identical reference with that ID and
matching guards returns `no_change`; differing content returns `already_exists`.
No replacement/removal of evidence is exposed in v0.1. `evidence list TASK_ID`
returns the bounded list and task revision. Evidence is useful for later browser,
handoff, review, board, or desktop adapters without arbitrary task metadata or a
PM dependency in those packages. Evidence references alone are insufficient to
implement durable undo, accounting, approval, or exactly-once external actions.

`surface` returns a bounded text view or JSON projection with `rollup`, `inflight`,
`stale`, `claim_issues`, `queue`, `admission`, `completeness`, and overflow counts.
`inflight`/`queue` contain task summaries; `stale` uses overdue item shape;
`claim_issues` uses diagnostic finding shape plus the observed claim view.
`rollup` and `admission` use their command shapes. `overflow` is a map with
`inflight`, `stale`, `claim_issues`, and `queue` counts for omitted entries.
`completeness` is `complete|partial|unknown`; unknown inputs never read as a healthy
empty board. Unknown admission is prominently reported. Only validated live
claims paired with `in_progress` tasks appear as in-flight. Missing, expired,
unknown, provisional, and status-exit residue claims are visible as issues, not
as valid ownership. Orphan claim records with no matching task are also issues.

The visible queue has the same eligibility, ownership classification, and ordering
as claim-next: priority DESC, updated_at DESC, ID ASC; a present claim, including
expired/unknown residue, excludes the task from the claimable queue. Admission is
reported separately: a queue is potential work, never permission to acquire it.
Surface is an observation, not a reservation or selection guarantee. It cannot
make a strict claim-next selection safe when corpus validation failed.

Text and JSON use one validated projection. Text clips human fields to at most 140
characters, further limiting escaped fields to 142 ASCII bytes including quotes, displays at most 20 each of in-flight/stale/issues and 12 queue entries,
and states omitted counts. JSON collections use the same limits and overflow
counts so a display cannot accidentally export the whole board. Neither format
embeds a current timestamp, session ID, hostname, or volatile duration; output is
byte-identical for the same observed state and the same side of each expiry.
Time crossing an expiry can legitimately change the projection. `show` is the
explicit operation for a complete task, not surface.

Read operations (`show`, `list`, `rollup`, `probe`, `projects list`, `overdue`,
default `triage`, `claim-admission status`, `surface`, `audit`, `evidence list`,
`events`) create/alter no files, timestamps, leases, or repair records. Ordinary
filesystem access-time behavior is outside this guarantee. They perform no
network, Git/gh invocation, transcript scan, or harness/config edits; only
explicit Git evidence flags enable the documented recovery probes.

`audit` reports malformed/unreadable tasks, unsafe/unknown claim or maintenance
records, orphan/provisional/status-exit residues, unsupported state, and corpus
limits. It is read-only and returns findings with `completeness`. Known-invalid
rows can be quarantined in diagnostic views with a count; a strict coverage or
selection decision must remain unknown. It never repairs by writing raw JSON.

`events [--task ID] [--limit N]` (default 50, max 200) reads bounded observational
events. Events use `task_id`, `event`, `ts`, `appended_at`, optional `actor`, and
optional from/to status and request ID. Event names cover task creation, claim,
renewal, release, transition, takeover, recovery, evidence attachment, project
addition, and maintenance pause/reopen. An event carries no task description,
evidence body, repository path, or maintenance reason. Event failures never undo
an established authoritative mutation or turn it into phantom failure. The log
may be incomplete; append order may differ from mutation order. This profile
captures `ts` when it observes a completed operation, outside the mutation lock;
it does not claim exact serialization time. Readers sort by that timestamp then
physical line order for ties; neither implies causal order. Store-scoped events
use reserved `task_id: __store__`, which is not a claimable task ID.

The event reader scans only the most recent 1 MiB, skips the first partial line
when starting mid-file, and returns at most the requested records. Malformed,
oversized, or torn lines are skipped with counts. Replies report `history_complete:
false`, scanned/truncated state, and read warnings. An absent log is an observed
empty best-effort history; an unreadable/unsafe log is visible as unknown, never
silently empty. No extension may use events as the claim authority, a complete
transaction journal, a reliable undo source, or an authenticated approval ledger.
Event `read_state` is `ok|absent|unknown`; read warnings distinguish unsafe or
unreadable state from a legitimately absent log. The mutation lock and event
append lock are never held together; append acquisition is bounded and failure
is best-effort, so an event logger cannot indefinitely park task mutation callers.

## Bounded and conservative processing

| Input or observation | Limit/behavior |
|---|---|
| Task record / task input | 4 MiB encoded JSON; depth at most 32. Strict UTF-8; duplicate keys, non-finite JSON values, wrong types and unsupported schema reject. |
| Task corpus | At most 20,000 entries and 64 MiB cumulative record bytes per observation; unexpected entries are issues, not silently ignored. |
| Claim corpus / maintenance area | At most 20,000 claim entries and 16 MiB cumulative claim bytes per observation. Maintenance enumeration is capped at 64 entries; unexpected/multiple records or a cap leave admission unknown/closed. |
| Project configuration | 64 KiB, at most 200 projects; same strict JSON rules. |
| Claim / maintenance record | 64 KiB / 16 KiB; regular no-follow bounded reads; unsafe or malformed means unknown. |
| Holder / owner / actor / request ID | Non-empty text, at most 256 characters; no control characters. No default holder. |
| Branch | Optional non-empty string at most 4,096 characters, no controls; Git recovery additionally validates exact Git-ref syntax and uses option-safe argument arrays. |
| Title / description / next action | Non-empty title at most 4,096 characters; description at most 16 KiB UTF-8; next action at most 4,096 characters. |
| Evidence | At most 64 references per task, each at most 4 KiB JSON; source/artifact/ref/scope each at most 2,048 characters within that byte cap. |
| Reason | Non-empty text at most 4,096 characters, within the enclosing record cap. |
| Keywords | 1..32 keywords, each at most 256 characters; whitespace-only is invalid. |
| Output | JSON envelope at most 8 MiB; human surface at most 32 KiB. Fail explicitly rather than emitting partial JSON. |
| Event | At most 4 KiB per complete line; oversized event drops are best-effort observations, not task mutation failures. |

Validate bounded input before taking the mutation lock. Reject oversized JSON
before unbounded deserialization, including nested/recursive abuse. Revalidate
decision-bearing stored objects and guards under the lock. No-follow regular-file
checks, safe IDs, bounded reads, atomic replacement, and exact-generation cleanup
must survive extraction. Existing legacy tolerance of non-finite priorities must
not produce NaN ordering; new writes reject them and malformed legacy state is
diagnostic unknown. An aggregate scan limit cannot become a false absence result.

## Scenarios and acceptance criteria

Each scenario is a vertical slice through the installed command, validation,
authority, persistence, and subsequent consumer read. Scenario IDs are the living
acceptance references. They describe target behavior, not checks already passed.

| ID | Demonstration and required result |
|---|---|
| S01: isolated start | Install the built wheel in a clean supported environment; initialize a synthetic project/store, add a task, show/list/probe it, and read it in a new process. No estate files, credentials, provider account, or local-operation network access are needed. Repeat init changes no bytes; a legacy/incomplete destination is refused. |
| S02: project and coverage | Add a second project using a configuration revision, create tasks with every permitted creation status, and inspect group/status counts. Active keyword matches and no-match are truthful. Invalid IDs, duplicate tasks, unknown projects, stale configuration revisions and invalid priorities change nothing. A corrupt active corpus prevents clear/strict selection. |
| S03: competing ownership | Two separate processes compete for one todo task. Exactly one returns a claim handle and observes `in_progress`; the loser returns a distinct refusal. Reusing the same holder label does not create second ownership. Claim-next uses the same queue ordering, skips present claims and cannot resurrect nonclaimable work. |
| S04: guarded worker lifecycle | The holder renews, attaches evidence, completes, and observes no claim. Stale task revisions fail. Release returns work to todo. After release/reclaim with the same holder name, the old generation cannot renew, release, transition, or attach evidence. An expired worker cannot renew or complete. |
| S05: explicit recovery | Observe an expired claim; stale takeover observations refuse after renewal/replacement. Explicit takeover creates a fresh generation. Orphan recovery requires verifiably absent claim. Default overdue/triage only report. Unknown evidence never demotes; optional recovery applies only after all three positive absence checks plus exact expiry/generation/revision rechecks. |
| S06: maintenance/drain | Race new claim and maintenance acquisition in separate processes; only the two valid linear orders occur. Active/unknown maintenance blocks every new generation including takeover and claim-next, even with an empty queue. Existing live holders renew, attach evidence and finish/release. A stale maintenance lease ID cannot remove its replacement. |
| S07: interruption and ambiguity | Interrupt claim/promotion/status-exit at controlled failure points; short writes, replacement failures, lock timeout and event failure never release another generation or report fabricated success. Audit/view expose resulting residues. A no-output or mutation-unknown caller reconciles through read commands; automatic retry is absent. |
| S08: trustworthy display | Text/JSON views agree on claims, counts, queue, maintenance and overflow. Fixed-state renders are identical before expiry; crossing expiry changes classification. Corrupt, linked, special, oversized, inaccessible and orphan records stay visible as issues. Read commands leave directory entries and file contents/mtime unchanged and invoke no network/transcript/tooling side effects. |
| S09: extension lifecycle | A separate subprocess consumer uses only API 1 to read/probe, claim, add a synthetic evidence reference, transition and read back its result. Unsupported capability/API, conflict, unknown and malformed replies stop the consumer safely. It neither imports PM internals nor edits the store. |
| S10: browser composition | Two starter workers compete through installed PM; only the winner invokes the existing browser's native lease/read/release interface on a public synthetic page. The adapter records bounded correlation/evidence and completes only after observing the required read result and lease release. Losing claim, unavailable browser, timeout/unknown delivery, and interruption do not become successful completion or blind resend. |
| S11: artifact and quickstart | Clean wheel and sdist installations expose only the core, run the synthetic quickstart/conformance suite, and contain no excluded code/state/private identifiers. Imports require no excluded modules. Installing/uninstalling changes no harness, service or account state. Artifact-specific provenance/license/notices and support rows are reviewed before any release. |

### Test seams and proof limits

The primary seam is the **installed CLI/JSON interface**, exercised through real
subprocesses and isolated synthetic stores. A representative extension consumes
that same seam; it is not a second implementation of PM. Use the fewest lower
seams necessary: controlled clock/I/O failure injection and barriers around
authority commits for otherwise irreproducible races, plus subprocess Git/gh
fakes for optional recovery failures. No production test-mode flags, arbitrary
clock settings, or failure hooks are exposed to users. Lower-level tests prove
specific race/failure properties; they do not replace installed consumer tests.

Tests use one failing scenario at a time, implement the smallest end-to-end slice,
then rerun its installed consumer path before the next slice. Do not write all
tests first and implement horizontal layers afterward. Concurrency acceptance
requires real process competition, not merely sequential mocks.

S10 has two distinct receipts: deterministic adapter tests with a fake native
browser interface, and an observed run against an actual supported released
browser artifact with synthetic public content. The fake proves branch/failure
handling; it cannot prove browser compatibility. Browser state/lease cleanup is
verified separately and is never inferred from PM completion. Browser access for
that future run needs its own requested, permitted session context.

Spec acceptance is a coherent, reviewable contract plus implementation sequence.
Implementation acceptance requires S01-S09 and S11 on built artifacts; the first
distribution additionally requires S10's actual-browser receipt. Public source,
package-index upload, Works microsite, canonical guide, watched/listened video,
and private runtime adoption each retain separate acceptance and outward-action
authority. A successful test run or demo is not any of those releases.

## Later packages and distribution compatibility

| Consumer | PM interaction | Consumer-owned state/authority |
|---|---|---|
| Browser / phone | Optional task correlation in an adapter; claim and evidence through CLI. | Native resource lease, profile/device, sign-in, action permissions and cleanup. |
| Remote Hands | Optional task pointer and observed-result evidence. | Request ID, accepted/unknown/completed semantics, local authentication, supported actions and refusal/kill paths. |
| Claude Code / Codex / Grok skills | Commands and opt-in surface formatting. | Each harness's tested event/config contract; installing PM registers no hook. |
| Handoff engine | Stable task ID, revision/generation, baseline and evidence references. | Handoff schema, freshness, selection and the resuming session's independent authorization. |
| Board lifecycle / review tooling | Read/probe, guarded transition, evidence, admission status. | Policy, provider errors, approvals and its own durable operation receipts for reliable reversal. No raw task edits or event-log undo. |
| Dot / Grok Bot / other front doors | Optional adapter invokes supported local commands after its own checks. | Vendor account/access, transport, request journal and execution approval. PM defines no vendor API. |
| Thin distribution | Pin package/API/capability/platform combinations and run conformance. | Manifest, profile examples and user-selected installation; no new scheduler or global state database. |

Adapter correlation may record `store_id`, `task_id`, `claim_generation`,
`request_id`, component artifact/version, native resource/request identifier,
delivery state, observation time, and evidence reference. This record belongs to
the adapter; it is not a mandatory schema imposed on existing browser/phone APIs.
Adapter delivery values are `not_sent`, `accepted`, `unknown`, `timed_out`, and
`observed_result`; existing native API enums remain the adapter's responsibility.
A PM task ID must not substitute for a fresh external operation's request ID.

The first bundle needs PM plus existing browser/skills interfaces only. Phone,
Remote Hands, handoffs, board policy, provider front doors, shared SDKs and broader
memory/governance systems do not gate standalone PM. A shared library is justified
later only by duplicated validated behavior across actual consumers.

## Build, release, and operational handoff requirements

Prepare the core privately from reviewed source through an exact allowlist and
new curated history. Do not export a private repository/history wholesale. Bind
the private lineage record to source hashes, sanitized commit, wheel/sdist digests,
and eventually each internal consumer version. Existing deployed PM remains
unchanged until a separately scoped migration is authorized and verified.

The implemented package ships a local-store runbook with freshness frontmatter
(`verified`, `review_after`, `topics`, `references`), installation/support matrix,
backup, drain, unsafe-state containment, explicit recovery, upgrade, validation,
uninstall and rollback. Backup is offline after sanctioned writers are stopped
or drained; never call a live copy of claims an authoritative transferable lease.
Restore must discard/quarantine ephemeral ownership under documented offline
control, audit durable task state, and explicitly reconcile progress orphans before
admitting work. No backup may copy accounts, private handoffs or unrelated state.

Rollback uses a compatible prior artifact and its known-compatible offline state
backup; an older binary must reject a newer unsupported format. Uninstall leaves
user state unless explicitly selected for removal. Publication binds the exact
destination, source commit, artifact digests, chosen license/notices and launch
assets to its own approval. License selection and provenance are release work;
MIT is selected for the private release candidate; inclusion of LICENSE does not
authorize public export or resolve third-party rights.
