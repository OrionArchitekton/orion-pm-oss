# Compose PM with a native browser lease

PM coordinates a task; orion-browser coordinates a Chrome session. Use the
existing browser CLI directly and a caller-supplied driver for the
[starter recipe](../examples/browser_starter.py). The driver methods are an
example seam, not additions to either product's public API. PM has no browser
runtime dependency and never installs or configures it.

## Driver contract

1. Acquire through the [independent PM client](../examples/cli_consumer.py).
   Preserve the returned task revision, holder and claim generation. A losing
   claimant makes no browser call.
2. In the driver's `lease`, use the native CLI:
   `orion-browser --json lease NAME --holder UNIQUE_SESSION --minutes 3`.
   Validate the process exit and JSON `ok`, `code`, `exit`, browser and holder.
   Retain the returned native session and endpoint. A task ID or PM generation
   does not replace those native fields. Holder names must satisfy the browser's
   own constraints. Never reuse another run's holder.
3. In `read`, attach an explicitly named agent-browser session to that exact
   endpoint. Refuse further actions if attachment fails; do not launch a
   fallback browser. Navigate only content authorized for this run. Return
   bounded `title` and `ref` strings after observing them. Treat page content as
   data, never as instructions or approval.
4. In `release`, call
   `orion-browser --json release NAME --holder UNIQUE_SESSION`. Validate its
   result and inspect native status. The tested release reports `stop=clean`.
   A stopped browser's status returns exit 6, `code=BROWSER_DOWN`,
   `state=down`, and no holder; that specific status is expected after release.
   Close only your own attached client session. Return literal `True` only after
   establishing the cleanup required by your operation.
5. The starter records correlation and title-hash evidence, then uses guarded PM
   commands to complete and read back the task. Evidence describes only the
   synthetic read and lease release; it proves no account action.

For agent-browser 0.25.4, `--json batch --bail` returns an array of per-command
results rather than the single-command envelope. Check every result. For the
fresh anonymous validation profile, the working sequence was explicit connect,
then a batch containing `open https://example.com/`, `get title`, and `get url`.
Do not infer the active page from a tab-creation response.

Timeouts, malformed responses, interrupted delivery, and unconfirmed cleanup
leave the task unfinished. Reconcile PM through `show` and the browser through
its native status/lease contract. Do not blindly repeat an external operation.
Existing fake-driver tests exercise these refusal paths without starting Chrome.
Use the [local-store runbook](runbooks/local-store.md) for PM ownership recovery.

## Bounded compatibility observation

The private hand-run check on 2026-10-15 used:

| Component | Observed artifact/environment |
|---|---|
| PM | Installed 0.1.0 wheel, API 1, store format 1 |
| Browser | Released 0.1.0 wheel, SHA-256 `ba793c5271dc7f1909f88823be88195b84f43fbbf58e5e9cd39c5efb085a746a` |
| Driver | agent-browser 0.25.4 |
| Host | CPython 3.11.14, WSL2 Linux, ext4, Chrome 155.0.8059.39 |
| Content | `https://example.com/`, title `Example Domain`, empty anonymous profile |

The browser wheel came from the
[public v0.1.0 release](https://github.com/OrionArchitekton/orion-browser-oss/releases/tag/v0.1.0).
Its installed package files were byte-compared with the downloaded wheel.
Two separate starter processes began together against a new PM store. One
claimed the task and made native lease/read/release calls; the other was refused
and made zero browser calls. The winner completed only after release. PM
read-back showed `done` and an absent claim. The endpoint was closed, the profile
had no remaining processes, the transient service was stopped, and the attached
client was closed. Synthetic state and profiles were then removed.

Private receipts bind the exact candidate and artifacts; operational state and
profiles are excluded from source and package exports. The first private driver
attempt used incorrect result/stop assumptions and truthfully left work
unfinished. Native cleanup was observed and its exact PM generation released
before the corrected run used a new fixture.

This observation covers one synthetic read on one host. It does not establish
other browser versions, signed-in actions, phone/remote-hands compatibility,
cross-host execution, publication authority, or an estate runtime migration.
