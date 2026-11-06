# P0/P1 Design Review

**Date**: 2026-11-06
**Initial candidate**: `307e4b3036f4883dc64549f6d1daefdf6d29870b`
**Scope**: Feature spec, plan, research, data model, contracts, quickstart and tasks.

Three independent sub-agents reviewed requirements/benchmark coverage, runtime/deadline
safety, and implementation-plan completeness. Each reported the same P1; no P0 was
reported. All three re-reviewed the changed documents and verified closure, with no
residual P0/P1 findings. This records a design review, not runtime acceptance.

## Finding R1: Crash recovery could replay uncertain tool effects (P1, fixed)

**Reproducer**: The supervisor dies after a worker performs a mutation but before a
terminal record is durable. Without a durable pre-dispatch record, resume may treat
the ID as never attempted and create a second environment.

**Fix**: [Runtime contract](contracts/runtime.md) now requires durable reservation
before dispatch, exclusive run ownership, confirmed old-worker termination, uncertain
classification for reserved IDs without durable acceptance, corrupt-journal refusal,
and durable acceptance before the next dispatch. Spec FR-008a and the data model
carry the same boundary. Reservation bookkeeping is separately timed, performs no
sample processing and cannot overlap an active attempt or block its watchdog.

**Required regression coverage**: T006 and T015–T018 implement/verify reservation and
acceptance ordering; [quickstart](quickstart.md) includes supervisor death before
dispatch, after mutation and before acceptance fsync, journal/write failures and
exclusive ownership. IPC deadlines explicitly cover dispatch writes/partial frames.
These runtime tests remain pending implementation.

## Verification

Spec Kit artifacts/internal links, task numbering (34 unchecked implementation tasks),
cross-document crash-recovery requirements and `git diff --check` passed after edits.
Reviewer input hashes and per-axis reports are retained in ignored local review
storage. No model, tool-execution, Docker or GPU tests were run for this document fix.
