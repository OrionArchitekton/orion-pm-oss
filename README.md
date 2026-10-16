# Orion PM core

MIT-licensed v0.1.1. Local task coordination for cooperating agents, with
structural exclusive claims, exact generation guards, durable task revisions,
conservative recovery, bounded evidence references and read-only views.

A task claim coordinates work on one machine. It grants no execution, account,
merge, deployment or publishing authority and does not stop an expired worker.
Browser/phone leases and desktop request delivery stay with those tools.

## Quickstart

Use a dedicated virtual environment and an explicit new store. Keep the new
executable separate from any existing PM installation.

Download the wheel and `SHA256SUMS` from the [v0.1.1 release](https://github.com/OrionArchitekton/orion-pm-oss/releases/tag/v0.1.1).
From a source checkout (for the example project config), place the wheel in `dist/`
and verify its checksum against the release manifest before installing.

```sh
python3 -m venv .venv
.venv/bin/pip install --no-index --no-deps dist/orion_pm-0.1.1-py3-none-any.whl
.venv/bin/orion-pm --json --home /tmp/pm-example init --projects examples/project-config.json
.venv/bin/orion-pm --json --home /tmp/pm-example add --id example --title "Example work" --project sample --status todo
.venv/bin/orion-pm --json --home /tmp/pm-example probe example
.venv/bin/orion-pm --json --home /tmp/pm-example claim example --holder session-a
.venv/bin/orion-pm --home /tmp/pm-example surface
```

Keep the returned task revision and claim generation. Renew with the exact holder
and generation; complete or release with both that handle and the current task
revision. Never derive ownership from task status or an event log. See the
[two-agent example](examples/two-agents.md) and [local-store runbook](docs/runbooks/local-store.md).

## Stable interface

`orion-pm --json` is the integration interface. API 1 returns one envelope with
explicit exit/outcome, typed data and stable error codes. `version` advertises
capabilities. Unknown coverage, claim state or admission must never be interpreted
as clear, absent or open. Request IDs correlate operations; they do not provide
idempotency or approval. Every caller must reconcile an interrupted command or
`mutation_unknown` response before deciding whether another action is safe.

[Full contract and acceptance scenarios](specs/orion-pm-core-spec.md).
[Architecture and limitations](docs/architecture.md).
[Independent CLI consumer](examples/cli_consumer.py).
[Browser composition recipe and compatibility scope](docs/browser-composition.md).

The default store is `$XDG_DATA_HOME/orion-pm` or `~/.local/share/orion-pm`.
Explicit `--home` takes precedence over `ORION_PM_HOME`. Initialization is explicit;
legacy/unmarked stores are refused and never imported or migrated automatically.
Normal operations are offline. Version 0.1 deliberately omits the optional
`git-recovery.v1` capability; triage is report-only and Git/network flags reject.
Expired takeover and verifiably absent-claim orphan recovery are explicit commands.

## Support and release state

Locally verified: CPython 3.11.14 on WSL2 Linux, ext4. Other Linux/interpreter rows
remain unverified until their installed-artifact tests run. Native Windows/macOS,
network/synchronized storage, cross-host fencing, adversarial same-user clients
and power-loss atomic multi-file transactions are unsupported.

The wheel has no third-party runtime dependency. Development uses setuptools,
`build`, pip and the Python standard-library test runner. Nothing installs hooks,
modifies harness settings, creates services, signs in or enables recurring work.

Source and release artifacts are published under the [MIT license](LICENSE).
Install from GitHub Releases; this version is not published to a package index.
The [composition receipt](docs/releases/browser-composition-0.1.1.json) records
a check of the public PM 0.1.1 wheel with the exact released orion-browser 0.1.0
wheel with agent-browser 0.25.4 on the environment above: only the winning PM
worker read a synthetic public page, released the native lease and completed.
This is a bounded compatibility receipt, not a browser dependency or a claim
about signed-in workflows. Private operational consumers retain their versions.
