# Core architecture

The package is a local coordination module with one stable seam: the installed
CLI/JSON interface. Internal Python names and persisted representation are not
extension contracts. Task/configuration validation and coverage are together in
`store.py` for this cut; separating files merely to match a private source inventory
would not add an interface users need.

A marked store contains `store.json`, `projects.json`, `arcs/*.json`, ephemeral
`claims/*.lock`, optional generation-qualified maintenance records under
`claims/.claim-admission/`, and a best-effort `events.jsonl`.

The claim area is the sole claim authority. Exclusive file creation gives one
winner. Shared/exclusive advisory locks on the task directory serialize sanctioned
reads/mutations, configuration changes and maintenance. Holder **and generation**
guard workers; task/configuration revisions guard edits. Maintenance blocks every
new generation and lets existing holders drain. It is not a deployment fence.

One process can die between claim and task changes: there is no multi-file crash
transaction or power-loss guarantee. A provisional claim, progress orphan or
status-exit residue remains visible. Read commands never initialize, repair, scan
transcripts, invoke Git/gh or access a network. Strict selections cannot treat
unknown/over-limit records as clear. Events are emitted outside the mutation lock;
loss and delayed append are tolerated. Their `ts` is the local completed-operation
observation time, not an exact serialization point, process liveness or causal
sequence. `__store__` identifies a store-scoped event, not a claimable task ID.

No extension writes raw task files. Bounded evidence attachment supports later
consumers without arbitrary patches, external event injection or content fetching.
Evidence is a producer's assertion; its truth/approval is not authenticated by PM.
A request ID correlates a command and supplies no replay protection. Unknown
command delivery must be reconciled before another attempt.

Task text, handoffs, resource replies and evidence are untrusted data. Same-user
hostile processes, cross-host ownership and external actions are outside the local
cooperative guarantee. Each browser, phone, desktop bridge, provider and harness
retains its own state, lease, authorization and recovery. No shared SDK or global
configuration database is required.

This profile exposes all required API 1 capabilities and omits `git-recovery.v1`.
Default triage reports; explicit expired takeover and absent-claim recovery work
locally. Repository metadata is optional; later Git recovery must freshly validate
its exact root/remote/identity before any evidence-based demotion.
