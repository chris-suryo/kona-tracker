# Fi probe fixes — Codex handoff

This branch follows Claude's probe implementation. It adds no web UI,
camera code, hosting configuration, or dependencies.

## Changes

- Login and HTTP failures report status and local explanations without
  printing response bodies. GraphQL errors retain only complete, recognized
  unknown-field validation messages; arbitrary messages and extensions are
  omitted. Unrecognized hints are deliberately omitted too.
- Connection failures become handled Fi errors. After login, a failed query
  is recorded and other independent queries continue; the summary is saved.
  If pet discovery fails, pet queries cannot run, but schema discovery can.
- The summary includes returned SLEEP/NAP durations with date windows and
  daily/weekly steps, goals, and distances. Missing/null values are labeled
  unavailable, preserving measured zero. Units remain raw until verified.
- Successful speculative-query responses are saved for inspection.

## Verification and limits

Regression tests use synthetic responses only. No Fi credentials were used.
The collar arrives tomorrow; live login, schema compatibility, units, and
behavior values remain unverified. Schema names alone do not confirm collar
support. Follow up on discovered fields with read-only queries when available.

The raw JSON files remain private and gitignored. Key-based redaction is not
a guarantee that arbitrary data is safe to publish. Review any report before
copying it to docs; never publish raw response bodies for debugging.

## Work ownership

- Codex: these probe reliability fixes and tests.
- Claude Code: camera integration and deployment planning.
- Claude Design: visual design.
- Chris: camera hardware selection and setup; Fi account/collar setup.

Integrate through a pull request. Do not start competing edits to these probe
files while reviewing this branch. No production merge or deployment is part
of this handoff.
