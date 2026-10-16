# Two cooperating processes

Initialize the sample project and add `example` with the README commands. Start
these in two terminals against the same supported local store:

```sh
.venv/bin/orion-pm --json --home /tmp/pm-example claim example --holder session-a
.venv/bin/orion-pm --json --home /tmp/pm-example claim example --holder session-b
```

Exactly one receives a live claim and progress task; the other gets exit 3. The
winner retains `data.claim.generation` and `data.task.revision`. Inspect with
`show example`; status alone is not ownership. All global flags precede the command.

Renew with the winning holder and returned generation, replacing `HOLDER` and
`GENERATION` with those observed values. Either session can win:

```sh
.venv/bin/orion-pm --json --home /tmp/pm-example renew example --holder HOLDER --generation GENERATION
```

Only the winning holder works. To finish, pass the current revision as well:

```sh
.venv/bin/orion-pm --json --home /tmp/pm-example transition example done --holder HOLDER --generation GENERATION --expect-revision REVISION
```

Use `release example` with those same guards to return unfinished work to todo.
After a release/reclaim, the old generation fails even if the holder label is
reused. Expired renewal/completion refuse. `overdue`, `triage example` and `audit`
are read-only; takeover needs exact observed expiry/generation/revision and an
explicit reason. An orphan progress task with verifiably absent claim can be
recovered to todo. Unknown/corrupt authority needs offline containment, not force.

## Browser composition

`browser_starter.py` is a recipe whose caller supplies an adapter to the actual
native browser's lease/read/release interface. Those Python callback names are
example-local, not an invented public browser API. Task and request IDs remain
separate. A losing PM claimant never asks for a browser; incomplete reads, timeout,
interruption and unconfirmed release cannot complete the task. Abrupt process death
may bypass cleanup; reconcile native browser state separately before reuse.

The automated tests use a synthetic native driver. Before a distribution claims
compatibility, bind an actual supported released browser artifact, lease a permitted
browser, read a public synthetic page, observe native release and PM evidence/
completion, and capture that separate version-bound receipt. No account posting,
sending or browser setup is part of the PM example or package installation.
