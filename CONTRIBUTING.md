# Contributing to Orion PM core

Use a fresh isolated checkout, a dedicated environment, and synthetic state only.
The living contract is `specs/orion-pm-core-spec.md`. Implement one installed-CLI
vertical slice through RED -> GREEN before the next. Keep process races real;
use clock/I/O injection only for otherwise irreproducible failures. No production
test-mode flags, internal-import integration API or automatic runtime migration.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install build 'setuptools>=77'
.venv/bin/python scripts/check.py
```

Run the suite against clean wheel and sdist installations. Inspect archive members
and dependencies; test from a working directory outside the source tree. Review
fail-open behavior, traversal/symlinks, injection, secret spill, truthful mutation
outcomes and generation/ID races. Capture exit codes and the artifact hashes.
Do not call selected tests a complete source-estate suite, or fake-browser results
actual browser compatibility. Update the spec/runbook when behavior changes.
