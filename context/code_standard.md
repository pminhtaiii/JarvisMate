# LifeMate Code Standards

Use these standards for implementation and standards review across LifeMate components. The benchmark and the task's accepted scope define required behavior; this page defines how code should express and protect that behavior. It does not select a language, model, framework, or architecture beyond the active project context.

## Hard review rules

Review every changed behavior against the task and its evidence. A change is acceptable only when it meets these checks:

- **Scope:** The implementation is the smallest readable change that satisfies the requirement.
  It adds no unrelated feature, speculative abstraction, or dependency without a demonstrated need.
- **Trust boundaries:** Validate external or persisted data at the point it enters a component,
  before relying on its shape or meaning. This includes user input, configuration, model output,
  tool arguments/results, and restored state where applicable. Static declarations alone are not runtime validation.
- **Contracts:** Public component boundaries state their inputs, outputs, and failure behavior
  explicitly using the language's established conventions. Callers can distinguish success from
  expected rejection or failure without parsing human-readable messages.
- **Capability boundaries:** Keep speech recognition, request/tool planning, and tool execution
  behind separate interfaces. A component should own one clear capability; cross-capability calls
  use its contract rather than reaching into its internals.
- **Policy:** Authorization, schema validity, installed-app eligibility, and other hard constraints
  are enforced by deterministic code. Model or heuristic suggestions cannot bypass these checks.
- **Side effects:** Make state-changing effects visible at a boundary. A refusal or invalid request
  performs no downstream effect. Retries are bounded, limited to plausibly transient failures,
  and safe against duplicate effects; otherwise do not retry the mutation.
- **Failure safety:** Failures preserve valid state and expose a safe, useful outcome. Catch errors
  only to recover, translate, add needed context, or clean up. Do not silently swallow errors or
  log and rethrow the same failure at multiple layers.
- **Data handling:** Do not expose credentials, secrets, or unnecessary private/user data in logs
  or model/tool inputs. Logs and error details must be bounded and sanitized; they must not contain
  raw prompts or raw tool payloads by default.
- **Verification evidence:** Non-trivial behavior changes include focused behavioral checks for
  important success and failure paths. Report the exact checks actually run; do not describe
  unrun behavior as verified.

For benchmark-facing behavior, also check the applicable [benchmark rules](benchmark.md)
and competition brief. Apply only the requirements relevant to the changed behavior:

- A sample may use only tools available to its installed apps and the permitted system tool.
- Create one split-matched `ToolEnv` per sample; access simulated app state only through its tool calls, never by reading environment files.
- Record every attempted tool call as required, including calls that fail validation or execution.
- Preserve state-hash generation and exact replay behavior when changing environment interactions.
- Keep inference offline and deterministic where the competition requirements apply.
- Treat the split-matched environment and organizer replay as the evidence for benchmark results.

## Implementation preferences

Use these preferences unless concrete repository constraints or task requirements justify another choice:

- Prefer existing project conventions and standard-library facilities over new dependencies.
- Keep modules small at their public surface and group code by capability.
  Avoid cyclic dependencies and wrappers that only forward without a clear boundary.
  A boundary wrapper is valid when it preserves the input and result without adding policy or effects.
- Pass external services, clocks, storage, and other replaceable dependencies explicitly through
  parameters, constructors, or the project's existing mechanism. Do not introduce a
  dependency-injection framework just for testability.
- Keep pure decisions separate from IO where this makes behavior easier to inspect and verify.
  Make ordering, mutation, and merge behavior explicit when multiple operations can affect the same state.
- Use comments for non-obvious constraints or reasons, not as a restatement of code.
  Prefer clear names and direct control flow over clever compression.
- Choose test names and fixtures that describe observable behavior.
  Keep checks focused on the contract rather than implementation details.

## Reviewer checklist

For each changed boundary, ask:

1. Is incoming data validated before use, and are rejected cases side-effect free?
2. Is the contract clear about success, expected failure, and who owns each decision?
3. Can a retry, replay, or partial failure duplicate an effect or corrupt state?
4. Can logs, errors, or model/tool context reveal data they do not need?
5. Do focused checks support the claimed behavior, and is evidence described accurately?

If any answer is unclear, request a narrow change or evidence tied to that specific risk.
Do not block a change for a preference that is not required by the task or these hard rules.

Record unresolved implementation choices in the relevant issue or PR. Do not treat a preference here as a settled choice of language, model, component owner, or MVP scenario.
