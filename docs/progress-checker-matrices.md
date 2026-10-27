# Target Capability Verification Matrices

These tables preserve target evidence criteria for the planned slop-loop runtime and evaluation system. They do not report current implementation status. See [`context/progress_checker.md`](../context/progress_checker.md) for repository observations. Listing a capability here does not select it for scope or show that it exists.

`OUT_OF_SCOPE` is a scope decision, not a verification status. The first implementation batch selected UC-03, UC-04, and UC-05; UC-01 later received separate local authorization through T010 on 2026-10-19 (Asia/Bangkok). Assignments, dependencies, and delivery briefs live in the [delegation map](use-case-delegation.md). The final submitted set remains open. Record scope separately from whether a capability is implemented or verified.

## Repository tools and security

| Target capability | Minimum evidence |
|---|---|
| `list_dir` | Workspace-bounded tests |
| `read_file` | Workspace boundary, secret-denylist, and output-bound tests; approved source excerpts reach model/reviewer context with provenance, while secrets embedded in permitted source are sanitized or rejected and source bodies stay out of traces |
| `search_code` | Search against real repository content |
| `apply_patch` | Unified-diff application tests |
| Existing-test protection | Rejection tests for attempts to weaken existing tests |
| `run_tests` | Initial target `pytest` execution and timeout evidence |
| `run_command` allowlist | Tests for allowed commands and rejected commands |
| Git operations | Permission and approval evidence |
| Workspace containment | Path traversal and symlink/junction escape tests for reads and writes |
| Secret-file protection | Rejection tests for `.env`, PEM, and SSH access |
| Command executable and arguments | Exact executable and argument validation; no-shell execution; injection attempts cannot launch another command |
| Subprocess sandbox | Restricted environment inheritance, filesystem access, process resources, and network by default; provider credentials are unavailable to repository commands |
| Test network isolation | Evidence that a repository-command network attempt is blocked |
| Finite execution limits | Configured finite timeout, output, CPU, memory, process, repair, review, token, and cost bounds; missing required bounds reject the operation |
| Prompt-injection resistance | Attack evaluation cases |
| Audit logging | Structured metadata, sanitized approved command details, and bounded redacted diagnostics or protected-artifact references; raw prompts, secrets, and protected payloads are absent |

A tool is not verified by a successful ordinary call alone; its safety constraints also need evidence.

## Task workflow

The target end-to-end flow is issue intake, structured triage, planning, baseline, repository modification, focused verification, regression verification, bounded repair, review, and a final delivery report. Evidence must show one task can traverse the applicable stages end to end; not every task needs every stage.

## Verification and repair

| Target capability | Minimum evidence |
|---|---|
| Pre-edit baseline | Baseline result is persisted |
| Focused post-edit verification | Relevant tests are executed |
| Regression gate | Previously passing tests remain green |
| Verification state model | Explicit state transitions are recorded |
| Failed-patch handling | Retry is controlled and evidenced |
| Bounded repair cycles | Retry limit is enforced |
| Repair evidence propagation | A failed result informs the next repair |
| Controlled termination | Budget or repair exhaustion stops the task |

Applied code with incomplete required verification remains `IMPLEMENTED_UNVERIFIED` and must not be reported as complete.

## Human approval

| Target capability | Minimum evidence |
|---|---|
| Approval classification | Risky actions are identified correctly |
| Workflow pause | Execution stops before the action |
| Approval binding | Decision is bound to the normalized action, repository identity/state, and policy identity/version |
| Approve and resume | Resume occurs at the interrupted point only while the approval binding remains valid |
| Reject and adapt | Rejection stops all agents on the task; no indirect retry or autonomous workaround; explicit developer direction is required before continuation, with fresh approval for revised approval-required actions |
| Modify then approve | Revised action runs only after approval |
| Forbidden-action handling | A forbidden action cannot be approved |
| Approval audit trail | Decision records include the action and outcome |

Approval applies to a specific proposed action; materially changed actions are reevaluated. Rejection cannot be bypassed through an equivalent tool or command form. Under [ADR-0006](adr/0006-uc05-cli-and-human-control.md), pending approval pauses the entire task, including model calls and background investigation. Rejection and pending pauses survive restart; cancellation and durable outcome recording may continue. Explain stale bindings before requesting a fresh decision. These are target criteria, not evidence of runtime enforcement.

## State, checkpoint, and recovery

| Target capability | Minimum evidence |
|---|---|
| Structured task state | Persisted task state |
| Step states (`todo`, `doing`, `done`, `failed`) | State-transition tests |
| Checkpoint after task steps | Checkpoint is persisted |
| Process restart recovery | Terminate and restart the runtime, then restore state |
| Resume without duplicate work | Completed steps are not rerun unnecessarily; uncertain non-idempotent outcomes are reconciled before retry |
| Goal, constraints, and acceptance criteria | Each survives restart |
| Cumulative budget recovery | Repair, reviewer-iteration, token, and cost limits, consumption, scopes, and reservations survive process restart; a new run ID cannot reset a task-scoped allowance; exhausted or missing accounting prevents the next constrained action |
| Interrupted budgeted action | Terminate after reservation and before result settlement; resume keeps the reservation charged until reconciled, without restoring spent allowance or repeating an uncertain side effect |
| Context compaction | Long-context test |
| Compaction summary validation | Required summary fields are retained |
| Long-term repository memory | A new session consumes a stored convention |

Continuing in the same process is not evidence of restart recovery. Resume must validate the current repository against saved assumptions.

## Reviewer and observability

| Target capability | Minimum evidence |
|---|---|
| Separate reviewer role | Distinct reviewer configuration |
| Read-only reviewer permissions | Write and execute attempts are rejected |
| Structured review output | Output schema is validated |
| File and line validation | Findings point to real lines in the diff |
| Logic, security, and missing-test findings | Seeded review cases |
| Bounded coder-reviewer loop | Iteration limit is enforced |
| Reviewer quality | Evaluation against known-good and known-bad diffs |
| Run identity and workflow trace | Unique run ID and node-level records |
| Tool, skill, error, approval, and verification trace | Metadata and sanitized, bounded approved command details under [runtime policy](../context/runtime_policy.md), with outcomes, timing, decisions, and protected-artifact references; no raw prompts, tool output, or protected payloads |
| Token usage and cost | Per-run accounting and estimate |

Trace records should explain how the final task state was reached.

## Skills

A skill requires a defined contract, runtime selection/loading, enforcement of its constraints, and one successful representative task before it can be considered verified.

| Candidate skill | Contract | Runtime integration | Evaluation |
|---|---|---|---|
| Bug fixing | To be defined | To be evaluated | To be defined |
| Unit-test generation | To be defined | To be evaluated | To be defined |
| Bug triage | To be defined | To be evaluated | To be defined |
| Code review | To be defined | To be evaluated | To be defined |
| Release-note generation | To be defined | To be evaluated | To be defined |

Track only skills selected for implementation.

## Candidate use cases and knowledge coverage

The table below is the use-case catalog. UC-03, UC-04, and UC-05 were selected for the first implementation batch; UC-01 has subsequent local authorization through T010, and the remaining entries are candidates. Selection does not establish implementation readiness or verification.

| ID | Candidate use case |
|---|---|
| UC-01 | Issue triage |
| UC-02 | Codebase questions and answers |
| UC-03 | End-to-end bug fix |
| UC-04 | Multi-step feature with resume |
| UC-05 | Human approval |
| UC-06 | Reviewer agent |
| UC-07 | Unit-test generation |
| UC-08 | CI/test-log analysis |
| UC-09 | PR/release notes |
| UC-10 | Behavior-preserving refactor |
| UC-11 | MCP repository tools |

A selected use case needs functionality, harness requirements, required evaluation cases, and recorded evidence before it is verified.

| Knowledge area | Required capability |
|---|---|
| K1 | Model, structured output, and agent loop |
| K2 | Tool use and skills |
| K3 | Retrieval-augmented generation |
| K4 | Memory, state, and context |
| K5 | Workflow and human-in-the-loop |
| K6 | Multi-agent coordination and MCP |
| K7 | Verification and evaluation |
| K8 | Security and observability |

The final submitted use cases must cover every required knowledge area. After choosing that set, map each area to selected use cases and record scope decisions separately from verification status.

## Evaluation infrastructure

| Target capability | Minimum evidence |
|---|---|
| Seeded bug dataset | Required bug cases exist |
| Feature acceptance cases | Required feature cases exist |
| Hidden grading tests | The agent cannot inspect them during execution |
| Security attack cases | Required attack cases exist |
| One-command evaluation runner | Complete evaluation can be invoked in one command |
| Structured evaluation output | Results are machine-readable |
| Regression comparison | At least two evaluation runs can be compared |
| Metrics reporting | Metrics are reported for each selected use case |

## Initial vertical-slice target

The first vertical slice proves the controlled repository-tool and verification path: receive an issue, read the repository, run a baseline test, apply a controlled patch, run a focused test, run regression tests, and produce an evidence-backed report. Bounded repair and reviewer stages remain separate evidence requirements for the full task workflow above.

Exit evidence should show repository reads stay inside the workspace, patches use the controlled mechanism, existing tests cannot be weakened, focused and regression checks pass, tool actions are traceable, and the final report distinguishes implementation from verification.
