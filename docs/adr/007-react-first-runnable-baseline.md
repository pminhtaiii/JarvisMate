---
status: accepted
---

# Use structured ReAct for the first runnable baseline

The first baseline uses a bounded ReAct loop inside the Python sample worker: the planner proposes a structured tool call, deterministic code validates and executes it, and the observed result returns to the planner for its next decision. This supersedes ADR 006 for the initial pipeline, trading additional model passes for a smaller executor and earlier runnable submission; selective replanning remains a possible later optimization supported by measurements.

Prioritize a working pipeline and complete prediction artifact before latency optimization, developer UI, or richer reports. Record elapsed time from the start; the competition's 30-second per-sample limit remains a submission constraint, and a slower development run does not establish compliance. Preserve the single ToolEnv per sample and no automatic retry of uncertain executions. No implementation or runtime performance is established by this decision.
