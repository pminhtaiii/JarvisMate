---
status: accepted
---

# Process samples sequentially without automatic execution retries

Initially process one sample at a time per GPU worker, queueing development requests, to make memory use, isolation, and timing easier to measure. A worker crash or exceeded sample deadline is recorded as a failure, distinct from a valid empty call list; do not automatically rerun that sample or repeat an uncertain tool execution, because a lost reply does not prove the action failed and the supplied rules require one `ToolEnv` per sample. A fresh worker may process subsequent samples, accepting model reload cost, while execution time and development queue wait are reported separately.

## Open details

The protocol, late-response handling, recovery of an already completed result, and submission behavior for failed samples remain to be designed. Do not fabricate an empty successful result or state hash for a failure. Organizer timing and failure-output requirements must be checked against final runner instructions; this decision is not an implemented recovery guarantee.
