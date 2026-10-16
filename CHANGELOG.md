# Changes

## 0.1.1

- Apply the bounded claim scan to `overdue`; incomplete claim coverage remains partial and unscanned claims remain unknown.
- Match stale surface item classifications to `overdue`: `surface` or `orphan`, with the same observed claim and task revision.
- Bound escaped human fields so a full Unicode surface stays below 32 KiB while retaining all visible rows and omitted counts.

API 1 and store format 1 remain compatible. No runtime dependency, store migration or account/service change. Version 0.1.0 release artifacts remain immutable.
