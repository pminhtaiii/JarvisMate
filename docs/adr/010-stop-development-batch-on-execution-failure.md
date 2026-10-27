---
status: accepted
---

# Stop the initial development batch on its first execution failure

Stop the initial development batch on the first execution failure, save its trace and all completed sample results, and exit with a nonzero status. This prioritizes visible failures and diagnosis while establishing the runnable baseline over completing as many samples as possible; an incomplete result must not be presented as submission-ready. A continue-on-error mode is deferred.

Worker crashes, unreadable required inputs, exhausted execution bounds, and unrecoverable planner output are execution failures. Normal tool outcomes, including empty searches or `done: false`, return to the planner rather than automatically failing the batch. Preserve ADR 003's prohibition on automatic sample reruns or retries of uncertain tool executions. This sets the development policy; organizer failure-output requirements for the final runner remain to be verified.
