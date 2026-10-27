---
status: accepted
---

# Stop the initial development batch on its first execution failure

Stop the initial development batch on the first execution failure, preserve available failure evidence and all completed sample results, and exit with a nonzero status. This prioritizes visible failures and diagnosis while establishing the runnable baseline over completing as many samples as possible; an incomplete result must not be presented as submission-ready. A continue-on-error mode is deferred.

Preflight input failures, including unreadable required inputs, stop the run and are recorded in the run manifest before sample traces or environments are created. After sample execution starts, worker crashes, exhausted execution bounds, and unrecoverable planner output are execution failures. Preserve any available traces, call logs, or hashes without requiring a failure trace when no sample has started or storage/process failure prevents writing one.

Normal tool outcomes, including empty searches or `done: false`, return to the planner rather than automatically failing the batch. Preserve ADR 003's prohibition on automatic sample reruns or retries of uncertain tool executions. This sets the development policy; organizer failure-output requirements for the final runner remain to be verified.
