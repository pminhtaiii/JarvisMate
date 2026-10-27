# Use-case Delegation Map

First implementation batch selected by the project owner: **UC-03, UC-04, and UC-05**. UC-01 subsequently received separate local implementation authorization through T006 on 2026-10-18, for T007–T008 and T009–T010 on 2026-10-19, and for mock-only T014 on 2026-10-20 (Asia/Bangkok); Thai owns its assessment boundary under [ADR-0005](adr/0005-uc01-triage-boundary-and-assessment.md). Real integration remains separately gated. Use the canonical zero-padded IDs from [the verification matrices](progress-checker-matrices.md#candidate-use-cases-and-knowledge-coverage).

This page owns colleague assignments, delivery boundaries, and dependencies. The matrices own target evidence; [implementation status](../context/progress_checker.md) owns observed capability status. Approved feature `tasks.md` files remain the only implementation task ledgers. An assignment or merged PR alone does not establish that a UC is verified.

## Assignments

Assignments use the colleague names supplied by the project owner. These rows are planning briefs; implementation starts after the relevant contracts and feature artifacts are approved.

| UC | Delivery | Owner | Start condition | Feature artifacts |
|---|---|---|---|---|
| UC-01 | Evidence-backed issue classification, severity, and backend destination recommendation | Thai | T001–T010 and mock-only T014 complete at the controlled local level; T014 authorized on 2026-10-20; T011–T013 and T015–T016 need separate authorization | Approved baseline [spec](../specs/002-uc01-issue-triage/spec.md), [plan](../specs/002-uc01-issue-triage/plan.md), [tasks](../specs/002-uc01-issue-triage/tasks.md); scope and user-confirmed consumer/fixture agreement in [decisions](../specs/002-uc01-issue-triage/contracts/decisions.md). Local mock behavior and real-runtime verification remain distinct; real adapters, production configuration and model-quality evaluation are separately gated |
| UC-03 | Evidence-backed end-to-end bug fix | Tai | Validated bug-task input contract; shared tools, verification, and UC-05 action gate integrated | Phase 1 build setup authorized: [spec](../specs/001-verified-code-repair/spec.md), [plan](../specs/001-verified-code-repair/plan.md), [tasks](../specs/001-verified-code-repair/tasks.md); shared contract agreement confirmed by user, production choices deferred before real execution per [decisions](../specs/001-verified-code-repair/contracts/decisions.md) |
| UC-04 | Multi-step feature with restart/resume | Thanh Tan | Shared persisted task/step contracts and budget ownership agreed; UC-05 binding contract agreed | Not created; link approved spec, plan, and task ledger here |
| UC-05 | Bound human approval and safe continuation | Trong Tan | Separately authorized T001–T019 and T023–T028 corrections complete locally through `391d3ff`; Phase 8 T019–T022 authorized on 2026-10-22; T020–T022 await external delivery gates | [Spec](../specs/023-uc05-human-approval/spec.md), [plan](../specs/023-uc05-human-approval/plan.md), [tasks](../specs/023-uc05-human-approval/tasks.md); shared baseline agreement, local Phase 7 authorization and remaining real/profile/restart gates in [decisions](../specs/023-uc05-human-approval/contracts/decisions.md). Mock/canonical-consumer checks do not establish production capability |

Other UCs remain unselected for implementation in this batch. UC-01's subsequent authorization covers only its named local tasks and does not expand other owners' assignments. This is not a permanent `OUT_OF_SCOPE` decision for the final project.

## Delivery order and shared work

### Shared foundation ownership

All owners use the [context index](../context/README.md) to load the implementation, standards, and policy guidance triggered by their boundary; the assignment report includes this entry point alongside its UC-specific links.

| Boundary | Owner | Deliverable |
|---|---|---|
| Foundation lead, bootstrap, shared contracts, repository tools, and evaluation infrastructure | Tai | Integrate the TypeScript/LangGraph bootstrap, model/tool contracts, controlled repository execution, verification results, budgets, sanitized traces, and evaluation entry point. Coordinate shared-file ownership before implementation. |
| Persistence and recovery | Thanh Tan | Own task/step storage, checkpoint contracts, persisted budget accounting, restart reconciliation, and the storage interface consumed by approvals. |
| Approval integration | Trong Tan | Own normalized action/policy identity, classification and decision contracts, and the approval gate used by repository tools and resumed workflows. |

**First integration milestone:** the three owners agree the task, action, verification, budget, and checkpoint contracts in approved feature artifacts. Then demonstrate one controlled bug-task fixture through baseline, patch, and verification, plus an approval-required action that pauses, survives process restart, and resumes exactly once after a valid decision. Required limits, isolation, and sanitized evidence must be enforced. Tai coordinates integration; Thanh Tan supplies recovery evidence and Trong Tan supplies approval-binding evidence. This milestone does not by itself verify every UC acceptance case below.

1. **Agree contracts and bootstrap.** Tai coordinates the shared-foundation owners above. Record the open stack choices from [tech_stack.md](../context/tech_stack.md#open-decisions), then approve the feature artifacts. Agree validated bug-task input, task/step state, normalized action identity, policy version, verification result, and cumulative budget accounting. Assign shared files to one owner.
2. **Build independent boundaries.** Thanh Tan's UC-04 persistence/recovery and Trong Tan's UC-05 approval can proceed in parallel against those contracts using controlled fixtures. Tai can prepare UC-03 seeded bug fixtures and acceptance tests while its tool and approval dependencies are being built.
3. **Integrate the bug-fix slice.** Integrate bounded repository tools, baseline/focused/regression verification, repair limits, and the approval gate before UC-03 executes real repository changes. Its ordinary path may use allowed actions; approval-required actions must pause through UC-05.
4. **Prove restart and approval together.** UC-04 integrates the feature workflow and UC-05 decisions, then demonstrates real process restart, retained budgets, and no duplicate side effects. Run each selected UC's evaluation cases and record evidence before updating capability status.

Shared foundation includes the model adapter and structured-output validation, LangGraph wiring, controlled repository tools, policy enforcement, state/checkpoint storage, finite budgets, sanitized traces, and evaluation fixtures. These are dependencies shared by the three UCs. The coordinator assigns their code ownership in the approved plans; suggested module boundaries below do not prescribe paths before that decision.

## UC-01: Issue triage planning

**Owner:** Thai. Agreed design: [ADR-0005](adr/0005-uc01-triage-boundary-and-assessment.md). One supplied issue and selected repository produce classification, P0–P3 severity recommendation (or `undetermined`), rationale, evidence, missing information, and a recommendation from application-configured backend destinations. Preserve reporter claims separately from inspected repository evidence; ask for material missing information without a separate prompt-rewriting call.

**Boundary:** consume Tai's shared read/search interfaces; use controlled fixtures until available. Additional shared capabilities require coordination with Tai. UC-03 owns debugging and repair; UC-04 owns durable recovery; UC-05 owns action approval. Clarification is not approval. Recommend destinations without dispatching work, and integrate with other UCs later through validated contracts.

**Next handoff:** T001–T010 in the approved [spec, plan and task ledger](../specs/002-uc01-issue-triage/plan.md) are complete at the controlled local level. Phase 5 T009–T010 was separately authorized on 2026-10-19 (Asia/Bangkok); see [decisions](../specs/002-uc01-issue-triage/contracts/decisions.md). Recommendation now validates configured compatible destinations and responsibility rationale, preserves material route uncertainty/questions and composes with existing bound clarification without dispatch. T014 safety regression consolidation was separately authorized on 2026-10-20 and is complete locally: 88 safety/238 UC-01 tests pass; T011–T013 and T015–T016 require separate authorization; real model/read adapters, durable accounting/policy/restart, receiving workflow and shared evaluation remain external delivery gates. Contributor CI and mock tests do not establish real provider quality or production readiness.

## UC-03: End-to-end bug fix

**Owns:** the bug-fix workflow from a validated bug task through evidence-backed delivery, composing the shared tools and verification/repair boundaries. For this batch, use directly supplied structured tasks or fixtures containing reproduction details and acceptance criteria; reject or request missing required information. Automated issue triage is deferred with UC-01.

**Deliver:** a seeded Python/`pytest` repository case processed by the TypeScript runtime: inspect, establish and persist baseline, apply a controlled patch, run focused and regression checks, handle failure within the persisted repair budget, and report the actual outcome. Follow the [initial vertical-slice criteria](progress-checker-matrices.md#initial-vertical-slice-target) and the fuller **Verification and repair** criteria. Runtime implementation remains TypeScript; Python is the initial target repository language.

**Acceptance handoff:** successful fix, repairable failed patch, exhausted repair budget, previously passing regression failure, attempted existing-test weakening, workspace escape, secret access, forbidden/injected command, and missing required execution limit. Repository-command isolation must be enforced before real command execution; mocked command results alone do not verify this UC. Incomplete required verification remains `IMPLEMENTED_UNVERIFIED`.

**Boundary:** use the shared bug-task input contract and UC-05's action gate; UC-01 is not a prerequisite for this batch. Own the bug-fix route, not independent copies of policy, persistence, or command execution. Tai owns the shared read-only runtime reviewer per the confirmed Phase 1 decision record; contributor CodeRabbit is not the runtime reviewer.

For source lookup, use the [UC-03 validator map](../context/architecture.md#uc-03-contract-validation) to reach the relevant contract modules and tests.

## UC-04: Multi-step feature with resume

The owner-confirmed first foundation and task-scoped pause/recovery behavior are in [ADR-0007](adr/0007-uc04-task-pause-and-recovery-foundation.md). The integrated feature workflow and cross-task repository memory remain later UC-04 phases.

**Owns:** durable task/step transitions, checkpoints, restart reconciliation, and feature-workflow continuation, under [state and memory](../context/state_and_memory.md).

**Deliver:** a representative multi-step feature whose goal, constraints, acceptance criteria, completed steps, and cumulative allowances survive process termination. Validate saved repository assumptions before continuing and reconcile uncertain non-idempotent outcomes before retrying.

**Acceptance handoff:** terminate and restart after a completed step; during a budget reservation before settlement; while awaiting approval; and after a side effect before its result is persisted. Prove completed work is not unnecessarily repeated, uncertain effects are reconciled, and a new run ID cannot reset task-scoped repair, reviewer, token, or cost allowances. Cover stale repository assumptions, exhausted/missing accounting, and required compaction-summary fields. Map evidence to **State, checkpoint, and recovery**.

**Boundary:** UC-04 owns recovery mechanics; UC-05 owns approval validity and decisions. A checkpoint continuing in the same process is insufficient restart evidence. Select the checkpoint backend explicitly rather than assuming LangGraph's presence supplies the guarantees.

## UC-05: Human approval

Agreed human-control behavior follows [ADR-0006](adr/0006-uc05-cli-and-human-control.md). T001–T019 and T023–T028 corrections are complete locally; [decisions](../specs/023-uc05-human-approval/contracts/decisions.md) records separate authorizations and owner boundaries. At integrated source `391d3ff9e484864f89cecf28133ec413b7607e86`, the full runtime gate passed typecheck, full lint, clean build and 1098 compiled tests; contributor tests passed 227/227 (exit 0). T019 source/emitted focused checks pass 2/2 each; each catalog run observes all 192 inherited approval checks in a fresh subprocess. C01–C24 have precise partial local scopes; all 104 required real/restart vectors remain not-run. Safe history/CLI separates immutable consent from current assessments and observed/unknown effects. Direct CLI composition remains unavailable. Phase 8 T019–T022 was separately authorized on 2026-10-22 (Asia/Saigon). T020–T022 remain blocked on external owner delivery and G-PROFILE/G-REAL/G-RESTART; real adapters, production profiles, durable atomicity, real execution and actual restart remain unverified. Full UC-05 acceptance remains unverified. Latency targets and benchmarks remain deferred.

**Owns:** action classification, approval pause, decision validation, and continuation at the interrupted action, following [tools and permissions](../context/tools_permissions.md) and [runtime policy](../context/runtime_policy.md).

**Deliver:** deterministic allowed/approval-required/forbidden decisions. Bind approval to the normalized action, repository identity/state, and policy identity/version. Persist the action and decision through UC-04's storage contract. A materially changed action requires reevaluation.

**Acceptance handoff:** allowed action, pause before a risky action, approve/resume, reject/adapt, revise then approve, forbidden action, stale decision, changed repository/policy, and restart while approval is pending. Prove rejection cannot be bypassed via an equivalent command and forbidden actions cannot be approved. Map evidence to every **Human approval** row; retain sanitized decision/outcome records.

**Boundary:** the product runtime approval gate is separate from a colleague approving a contributor PR. Keep approval decisions behind the shared execution boundary so no UC can bypass them.

## Knowledge coverage to validate

| Area | Candidate evidence owner in this batch | Remaining planning check |
|---|---|---|
| K1: Model, structured output, agent loop | UC-03 | Validated model results and bounded workflow execution |
| K2: Tool use and skills | UC-03 plus shared foundation | Assign and evaluate any selected runtime skill; repository helper skills do not prove runtime loading |
| K3: Retrieval-augmented generation | UC-03 repository evidence path | Define retrieval, provenance, and evidence reaching the model; a file-search demo alone does not establish coverage |
| K4: Memory, state, context | UC-04 | Include compaction and repository-memory evidence, beyond basic checkpoints |
| K5: Workflow and human-in-the-loop | UC-04 and UC-05 | Integrated pause/restart/resume cases |
| K6: Multi-agent coordination and MCP | Owner and scope decision pending | Three selected UCs do not by themselves demonstrate this area; assign explicit coordination/MCP evidence or select another UC later |
| K7: Verification and evaluation | Each UC owner; coordinator integrates runner | Identify cases, grading isolation, machine-readable results, metrics, and repeatable regression comparison |
| K8: Security and observability | Shared foundation and UC-05; exercised by UC-03 | Include isolation, injection resistance, protected-data handling, limits, and sanitized traces |

These are proposed evidence mappings, not claims of coverage. The matrices require every knowledge area in the final submitted set; resolve gaps before final scope approval.

## Assign and hand off

Before assigning or starting a UC, run `node scripts/agents/agent-context.mjs assignment --uc UC-03` (substitute the canonical ID). The JSON report derives the owner, prerequisites, brief, shared foundation, linked context, and feature artifacts from this map. `NEEDS_PLANNING` identifies missing owners or local planning links; `REVIEW_REQUIRED` means links exist, not that their approval or dependency evidence has passed. Confirm those conditions before implementation. The helper is read-only and does not assign GitHub users, rewrite this map, or update task status.

For each UC, fill its owner and link the approved feature artifacts. In those artifacts, assign one owner for shared code, identify dependencies and owned paths, and define executable acceptance checks. Use `UC-*` for use-case identity and the feature's own `T*` IDs for implementation tasks; maintain task completion only in that feature's `tasks.md`.

Colleagues follow the [contributor workflow](../context/workflow.md) for isolated worktrees, active-task registration, integration, and context refresh. A completion handoff includes the UC/task IDs, branch and revision, changed paths, focused/regression/evaluation commands and outcomes, evidence links, and remaining blockers. The coordinator updates observed implementation status only after reviewing integrated evidence.
