---
status: accepted
---

# Use one general planner for the MVP

Use one general planner per sample, exposing only that sample's available tools, rather than routing requests among domain-specialist agents. This keeps cross-app requests in one execution loop and avoids routing and handoff complexity while the team establishes a runnable baseline; domain-specific prompts or agents remain a future experiment whose accuracy benefit must be measured. The trade-off is less domain-specific prompting in the initial system; this decision does not establish measured accuracy.
