---
status: accepted
---

# Require execution traces from the first runnable baseline

Treat per-sample execution traces as a required output of development runs from the first baseline, alongside the competition result. Final-state success alone can conceal extra or incorrect tool calls, so inspect the planner's observable actions, actual calls, and tool results as well as the final state; this accepts additional instrumentation and local artifact handling instead of deferring observability until the pipeline works.

Keep development traces separate from submission rows and routine logs, preserving evidence of failures as well as successes. The environment's call log and state hash remain authoritative for submission; traces neither replace them nor justify reading hidden environment files. Capture requirements and local storage policy live in [testing guidance](../../context/testing.md). This decision requires observable execution evidence, not hidden model reasoning, and does not settle whether a batch stops or continues after a failure.

The subsequent batch-failure decision is recorded in [ADR 010](010-stop-development-batch-on-execution-failure.md).
