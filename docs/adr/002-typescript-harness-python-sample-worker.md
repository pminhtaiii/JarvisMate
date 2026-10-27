---
status: accepted
---

# Use a TypeScript harness around a complete Python sample worker

TypeScript owns the outer harness for scheduling, configuration, reporting, and development-facing access; Python owns each complete sample's ASR, planning loop, and execution through its single organizer-supplied `ToolEnv`. Compared with an all-Python implementation, this preserves the team's TypeScript tooling preference; compared with TypeScript directing individual tool calls across a language boundary, it keeps authoritative execution, results, call logging, and state hashes together. Models stay loaded in a persistent Python worker across samples, while each sample receives exactly one isolated `ToolEnv`; the process protocol is described below and no speed improvement from the language split is claimed.

Current choices and implementation status live in [the technology stack](../../context/tech_stack.md).

## Communication

Use JSON Lines over process stdin/stdout inside the container, with worker logs on stderr and explicit sample identifiers and success/failure outcomes in responses. This avoids an internal HTTP server while keeping the Python worker persistent. A separate thin development HTTP service accepts teammates' requests and queues them into the same harness; the final runner does not depend on that network service.
