---
status: accepted
---

# Configurable offline Docker integration continues after isolated sample failures

Add a separate integration entry point, `python -m lifemate.integration`, for the
[configurable offline Docker integration](../../specs/002-docker-integration/spec.md).
It runs ASR, native Qwen tool calling and deterministic `ToolEnv` execution inside one
offline container. The legacy `python -m lifemate run` command, its prompt, protocol,
defaults and stop-on-first-failure policy (ADR 010) remain unchanged for comparison.

## Decision

For this entry point only, at the user's explicit request:

- **Continue after isolated failures.** A failed, timed-out or uncertain sample is
  recorded as a terminal failure and the batch continues with later distinct samples.
  The run still exits nonzero and blocks complete-submission publication.
- **Enforce the deadline now.** An external supervisor bounds every full sample attempt
  to at most 30 seconds, from dispatch through durable per-sample staging. A result
  received at or after expiry is a timeout, never a success. Longer budgets are rejected.
- **Never replay uncertain effects.** Before dispatch the supervisor fsyncs a reservation
  binding sample, attempt, worker generation and configuration identity. A reservation
  without durable acceptance is uncertain after any crash and is never dispatched again,
  including through resume. One sample receives at most one `ToolEnv`.
- **Bounded recovery.** After a worker is lost, at most `recovery_attempts` (0 or 1)
  restarts are attempted, each within a finite startup timeout, for later samples only.
  Prior-worker termination must be confirmed before any further dispatch.

ADR 003's prohibition on automatic reruns of failed samples and uncertain calls still
applies. The constitution and ADR 010 still govern the legacy runner.

## Consequences

Failure evidence survives alongside accepted rows, and a slow or blocked sample cannot
silently consume the batch. The supervisor and journal add process and storage
complexity, recorded in the plan's complexity table. Startup, recovery and packaging
time are reported separately and included in total wall time. Organizer accounting for
initialization and the permitted failed-row format remain external acceptance gates.
