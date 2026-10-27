---
status: superseded by ADR-007
---

# Plan first, execute resolved steps, and replan selectively

Use a bounded hybrid of plan-then-execute and reactive planning within the Python sample worker. The model proposes a structured sequence with explicit dependencies; deterministic code executes resolved steps through the sample's single `ToolEnv`, pausing for model decisions only when required information remains unresolved or observed results invalidate the remaining plan. This trades additional executor logic for fewer routine model passes than replanning after every result, while retaining adaptation that a fixed one-shot call list lacks; accuracy and latency benefits remain unmeasured.

## Execution constraints

- Resolve dependencies only through explicit, validated rules over observed results; never invent lookup IDs or treat unresolved arguments as executable.
- Replanning receives the original request/context, completed calls, and observed results. Revise remaining work without blindly repeating completed effects.
- Failed tool calls remain in the authoritative environment log. Replanning is not permission to retry an uncertain execution or restart a sample; [ADR 003](003-sequential-execution-without-automatic-sample-retries.md) still applies.
- The executor must enforce a bounded number of model/tool steps and the fixed 30-second per-sample deadline in code. Only the internal model/tool-step bound and the plan schema remain implementation choices to validate with baseline measurements.
- Stop when the plan is complete without a mandatory model pass solely to generate a closing message.

See [architecture](../../context/architecture.md) for the runtime outline. This decision selects the baseline architecture, not an implemented or measured capability.
