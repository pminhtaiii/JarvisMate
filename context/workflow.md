# Contributor Workflow

This workflow governs contributors implementing an approved local Spec Kit feature. The feature's `spec.md`, `plan.md`, and `tasks.md` are the source of truth for that feature's scope. For an explicitly authorized helper, documentation, or maintenance task without an approved feature, follow the user's stated scope and do not invent Spec Kit task IDs or planning artifacts. This describes repository work, not the slop-loop product runtime; see [architecture.md](architecture.md) for the target runtime flow.

## Input readiness

Before starting edits in an assigned feature checkout, run `node scripts/agents/pr-workflow.mjs preflight` and inspect its status, freshness, branch name, and dirty paths. Follow [the PR workflow](../docs/agents/pr-workflow.md#branch-and-size) for blocked reports; preserve existing work. For a selected use case, run `node scripts/agents/agent-context.mjs assignment --uc UC-03` with its canonical ID, then confirm the reported owner, prerequisites, and approved artifacts. `NEEDS_PLANNING` and `REVIEW_REQUIRED` are not implementation authorization. Before implementation, confirm the selected feature has `spec.md`, `plan.md`, and `tasks.md`, and resolve inconsistencies that block safe execution. Follow the [planning workflow](planning.md) to author or update specs, plans, and task breakdowns through its deterministic P0/P1 review loop before implementation authorization. Do not regenerate planning artifacts unless the user asks or a concrete gap requires it. `tasks.md` is the only task-status ledger.

## Active-task handoff

Before editing, establish scope from the feature task graph or approved maintenance brief, then register the coordinator or worker in shared state. Start the managed session with `agent-work.mjs` and render only its progress file under `.agent-work/<date>/<session-id>/`. All linked worktrees share the ignored `.agent-work/state/active-tasks.json`. [`active_task.md`](active_task.md) is the static command page; session progress stays in the selected session folder. `tasks.md` remains the only feature task-status ledger. Use the primary helper with `--root <worker-checkout>` when needed.

Use unique owner and task IDs. Register current coordinators and workers before dispatch with explicit sessions and exact owned paths via repeated `--owned-path` options; keep worker paths disjoint and later or blocked feature tasks in `tasks.md`. Assignment and status report progress, not authorization. `active_task.md` lists lifecycle commands. A worker handoff captures index and worktree hashes for its owned paths; the coordinator verifies them before integration or publication. Workers hand off local results and do not complete contributor work or edit another checkout's Markdown.

Update the next action at meaningful checkpoints; keep blocked or interrupted entries registered. Workers use `handoff`; coordinators use the publication workflow, app-link receipt, and `finish` gate. Finish requires a clean current PR, retained publication evidence, app link, all four current-head CI jobs, and no merge blocker; pending CI stays active under the app watcher. The human merge decision remains separate. Archive terminal work only after integration and durable evidence: preview the unique ignored output, then apply; only that matching terminal assignment may be cleared. Retain active/blocked assignments. Keep `docs/verification/` archives ignored and local; never force-add them or require them to exist for CI. Tracked docs may link immutable history or label local paths as code. If archive creation is interrupted, retry the same command and output; do not overwrite or substitute. The helper does not commit or push. See the [PR workflow](../docs/agents/pr-workflow.md) for contributor completion and paired publication.

Use the compact assignment list first. `recovery-report.mjs` correlates registry state with checkpoints, worktree changes, and receipts, but agent liveness remains `unknown` without host evidence. Reassign only for an explicit recovery decision; retain predecessor evidence and the linked successor. Use `agent-context.mjs resume` for dependency or authorization details. Follow the [workspace guide](../docs/agents/workspace.md) before worktree creation or cleanup; session finish blocks its active/blocked assignments and worktree retirement checks the whole checkout. Cleanup previews by default and requires explicit authorization to apply; archival never removes a worktree or its evidence. Legacy migration is explicit and preserves snapshots; shared writes use one lock. Keep rendered assignments out of unrelated PRs and workers within their owned paths.

## Workflow pipeline

```text
planning loop (plan, tasks, P0/P1 audit) -> build-spec (task graph and TDD) -> speckit-converge -> code-review (unless the user explicitly opts out) -> context refresh -> contributor PR/CI
```

`/build-spec` owns implementation and convergence; post-implementation code review follows the user's instruction. The contributor PR pilot has standing limited authorization for coordinator commits, feature-branch pushes, and draft PR creation/updates; workers have no remote authority. Follow the [PR and CI workflow](../docs/agents/pr-workflow.md). The pilot uses `development` as the base for both public and private PRs. Follow the [branch and PR conventions](../docs/agents/pr-conventions.md) before creating a new work branch or preparing PR metadata; new names omit numeric prefixes, remain unique across both repositories and historical PRs, and prefix their paired PR titles exactly. A human decides each merge; coordinator execution requires an explicit instruction for that PR and passing required checks. Remote issue changes and deployment remain separately authorized.

## Agent coordination

The coordinator does one bounded preflight, then repeats this loop:

1. Recompute the authorized ready frontier from task dependencies and registered owned paths. Serialize shared-path work and record the dependency or path conflict delaying any assignment.
2. For T3 dispatch, consult `orchestrator_capabilities` for supported providers, models, and option descriptors. Use native subagents only when they support the selected model and no options are requested or inherited. Otherwise, use `delegate_task` even for same-provider work, pass options through `target.options`, and verify the returned provider, model, and options.
3. Dispatch every independent authorized assignment in the current frontier concurrently, up to the API batch and concurrency limits, before waiting for any result. Use one batch call when available; otherwise launch independent calls concurrently. When the frontier exceeds capacity, dispatch queued work as slots free. Handle trivial indivisible tasks directly instead of creating a nominal worker.
4. Workers register exact owned paths, stay within them, and update active-task state at meaningful checkpoints. On a concrete blocker, they mark the assignment blocked with the next action and message the coordinator; when done, they send a final handoff. The coordinator waits for those events instead of polling, refreshes assignment state, integrates one result at a time, then repeats the loop.

For every new worker worktree, use the [workspace guide](../docs/agents/workspace.md) reservation/bind operations; they own base freshness and checkout verification. Reserve fetches `origin/development` and pins its exact SHA before creation. For app-owned dispatch, it compares fetched SHA, parent `HEAD`, and supplied base exactly, unless a user-authorized exception records an exact alternate SHA. Fetch or comparison failure returns nonzero before registry mutation, and dispatch stops on reserve failure; manual ref or ancestry checks are not a substitute. Create from the selected pin, never select a local `development`, feature, or integration ref as the default, and bind the checkout against the exact reservation SHA. A failed fetch or missing pin always blocks creation. A later remote advance does not invalidate the captured base. Before editing a reserved assignment, `edit-ready` requires a clean worktree at its exact creation SHA and records a readiness receipt bound to the owner, task, session, checkout, repository, branch, and base. `handoff` rejects missing or mismatched receipts. Repeating readiness for the same identity preserves its original receipt; readiness cannot be recorded retroactively after edits. This enforces the registered CLI lifecycle and does not prevent arbitrary filesystem writes. Existing-checkout `start` retains its compatibility path. Continuing an existing assigned checkout and merging worker or integration commits are separate operations and do not rewrite the creation base.

Use the task helper to derive context from the canonical ledger:

```powershell
node scripts/agents/agent-context.mjs handoff --tasks specs/<feature>/tasks.md [--root <checkout>]
node scripts/agents/agent-context.mjs task --tasks specs/<feature>/tasks.md --task T001 --plan specs/<feature>/plan.md [--root <checkout>]
```

These commands report task context only; they never change task status.

**Resume from compact evidence:**

Use the compact assignment list first; run the detailed ledger report when task context is needed:

```powershell
node scripts/agents/agent-context.mjs resume [--tasks <tasks.md>] [--authorization <repo-relative-path> ...] [--root <checkout>]
```

Use `active-task.mjs list --compact` first for owner/task/status/next; filter with `--owner`, `--task`, or `--status`. After interruption, inspect `recovery-report.mjs` before treating an active record as live or stale; the report marks agent liveness `unknown` without host-level evidence. Run `agent-context.mjs resume` only when the task frontier, dependencies, authorization pointers, or detailed verification context is needed. The resume report is read-only; its paths are pointers, not authorization. Check current user direction and the governing decision record before acting, then read only sources needed for the next action. If a read fails, inspect the error and retry once with a bounded supported read of that named source; if it fails again, record the blocker and stop.

Create a managed session directory before coordinated work:

```powershell
node scripts/agents/agent-work.mjs start --session <session-id> [--date YYYY-MM-DD] [--root <checkout>]
node scripts/agents/agent-work.mjs list [--root <checkout>]
node scripts/agents/agent-work.mjs finish --session <date>/<session-id> [--root <checkout>]
```

Keep drafts, worker notes, raw logs, and review snapshots in `.agent-work/<date>/<session-id>/`. Before creating task worktrees or cleaning a run, follow [the dump workspace guide](../docs/agents/workspace.md): worktrees live separately under `.agent-work/worktrees/`, with machine-readable ownership receipts. Keep approved specs, task ledgers, and concise verification records at their canonical paths. Leave a session active while work may resume. Session finish blocks active or blocked assignments whose explicit session matches; reassigned entries are terminal and no longer block the source session. Legacy assignments with unknown sessions block conservatively when their checkout resolves to the active checkout or is unknown; on Windows this includes short-name aliases. Worktree retirement remains checkout-wide: any active or blocked assignment for that checkout blocks deletion, even when it belongs to another session; reassigned predecessors do not block retirement. Cleanup previews by default; only explicitly authorized human action may apply cleanup.

### Task briefs and handoffs

A concise worker brief names task pointers, intended scope delta, exact owned paths, acceptance commands, exclusions, and where to record evidence. Link to general repository rules instead of repeating them. For parallel work, declare disjoint owned paths and record dependency or path-conflict reasons for serialization. Workers record progress in active-task state and message only for a concrete blocker or final handoff. Use the [orchestration output tools](../docs/agents/orchestration-tools.md) for bounded handoff JSON and log tails; a caller-supplied exit observation is not proof that a worker process succeeded. The final handoff lists the revision, changed paths, focused commands and results, remaining gaps, and evidence pointers. Reviewers own semantic, spec, and standards findings. The merger owns recorded-base and ancestry checks, scope and ownership, mechanical integration, and replaying recorded focused checks; it consumes pinned verified review reports instead of repeating semantic review. Workers, merger, and reviewers run focused checks. Publication alone runs the full runtime/contributor gate once for the integrated candidate; do not run the same full suite separately before publication. CI remains independent.

### Review snapshots

Pin the review to a base/target revision or create a file snapshot:

```powershell
node scripts/agents/agent-context.mjs snapshot --files <repo-relative-path>... [--root <checkout>]
node scripts/agents/agent-context.mjs verify --snapshot <snapshot.json> [--root <checkout>]
```

Verify the snapshot against the same checkout before relying on review findings. Keep Standards and Spec reviews independent. Maintain a shared finding ledger with each finding's ID, reproducer, regression coverage, disposition, and current SHA. When a candidate changes, rerun only the affected review axis; reuse another axis only after verifying its reviewed input hashes still match the candidate. Final acceptance may consume only pinned, verified reports.

### Skill evaluation evidence

Before each baseline or follow-up evaluation, use `agent-context.mjs snapshot --files ... --root <checkout>` to save that phase's exact source revision and hashes in its own session subfolder. Include the skill, loaded references, and helper source files that can affect the scenario; a no-skill baseline records the source environment and explicitly records that the skill was absent. Store the request, output, checks/exit statuses, and a relative pointer to that snapshot with the result. Verify the snapshot before dispatch and again after the evaluation; if verification fails, mark the result invalid and repeat against a new snapshot. Keep baseline and follow-up artifacts separate and keep each evaluated checkout unchanged while its agent runs. Historical evaluations without snapshots remain labelled unversioned, rather than assigning them inferred hashes later.

## Step 1: Implement with TDD (`/build-spec`)

Implement each ready task in a test-first vertical slice, following [testing.md](testing.md) and the existing-test protections in [tools_permissions.md](tools_permissions.md). Resolve unrelated harness failures before claiming a behavioral RED. Report actual commands and exit statuses, and leave failed or unintegrated tasks unchecked.

Integrate one worker at a time. Verify the checkout's recorded creation base exactly matches the reservation SHA, then check ancestry, approved scope and exact owned paths, mechanical integration, and recorded focused checks on the integrated candidate. Reviewers own semantic/spec/standards findings; consume their pinned, verified reports instead of repeating that review. For changed logic, acceptance requires evidence for both returned outcomes and persisted state; refusal evidence shows no state change or downstream effect. Record completion only after these checks pass.

## Step 2: Converge (`/speckit-converge`)

Assess the integrated implementation against the approved spec, plan, and task ledger. If actionable gaps are added as tasks, implement them through the same dependency and verification process, then rerun convergence until no actionable gaps remain.

## Step 3: Code review (`/code-review`)

Honor an explicit user request to skip post-implementation review; do not dispatch review agents for that task. This choice does not waive required task tests, acceptance checks, context refresh, or contributor gates. Follow [testing guidance](testing.md) when reporting verification.

When the user has not opted out, review the pinned integrated revision against [backend code standards](code_standard.md), other applicable repository conventions, and the originating specification. Keep Standards and Spec findings independent and maintain the shared finding ledger. Resolve blocking findings within the authorized task scope. If a candidate changes, rerun affected focused checks and only the review axis whose inputs changed; reuse another axis only after verifying its input hashes against the candidate. Final acceptance may consume pinned, verified reports.

## Context refresh

After implementation and verification, update affected context documents from inspected code and test evidence, preserving their existing format. Follow [context maintenance](../docs/agents/context-maintenance.md) for the update-plan format, preview/apply commands, and failure handling. Review semantic consistency and report validation before finishing the active task.

## Step 4: PR and CI (`/pr-feedback-loop`)

While waiting for a resolving PR review, assess each scoped paired ticket against all acceptance criteria, prepare evidence and preview [paired ticket completion](../docs/agents/paired-publication.md#complete-paired-tickets). Apply only after both resolving PRs merge, their source snapshots match and the public exact-head CI passes. CodeRabbit approval is advisory. Keep partial-close accounting and retry the same stable key; never infer completion from labels, age or CI alone. This issue lifecycle is separate from contributor handoff and human merge authority.

After implementation, refresh affected context before publishing. The approved contributor PR pilot authorizes the coordinator to run the [PR workflow](../docs/agents/pr-workflow.md) for draft creation and updates on `development`; workers do not write remotely. Only `READY_FOR_HUMAN` permits the `ready` command. A human decides each merge; the coordinator may execute it only when explicitly instructed for that PR, after required checks pass, following the linked workflow. Report missing or stale evidence as waiting or blocked, never as ready.
