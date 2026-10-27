# Agent Dump Workspace

Use the integration checkout's ignored `.agent-work/` for temporary agent artifacts. Read this before creating worker worktrees or cleaning a run. This directory is local working storage, not the canonical feature specification or task ledger.

App-owned T3 worktrees outside `.agent-work/worktrees/` require `agent-worktree.mjs register --external-app-owned`. The helper can retain and accept their evidence, but it never removes those worktrees, even after acceptance.

## Layout and ownership

| Location relative to the integration checkout | Contents |
|---|---|
| `.agent-work/<date>/<session-id>/` | Managed session: briefs, notes, logs, snapshots, worker ownership receipts, and its generated progress view |
| `.agent-work/worktrees/<unique-worker-id>/` | Registered Git worktree, kept outside deletable session folders |
| `.agent-work/worktree-receipts/` | Helper-owned ownership, accepted-head, and evidence-hash receipts |
| `.agent-work/state/` | Shared contributor assignments and lock, used by all linked worktrees |

Start a managed session with the existing `agent-work.mjs` helper described in [the contributor workflow](../../context/workflow.md#agent-coordination). Before delegating into a new worktree, fetch `origin/development`, capture its full SHA, and reserve each worker with `active-task.mjs reserve`. Reservation requires that SHA to match both the parent checkout's `HEAD` and `refs/remotes/origin/development`; it records repository/base identity without claiming a worker checkout or HEAD. After T3 creates the worktree, run `bind --worktree <absolute-path>` from the same repository. For a reserved assignment, run `edit-ready` before editing: it records the owner/task/session, checkout, repository, branch, and base only while the worktree is clean at the exact creation SHA. `handoff` requires that receipt to match. Repeating `edit-ready` for the same identity retains the original receipt; it cannot create a late pre-edit receipt after changes. This records CLI lifecycle completion and does not prevent arbitrary filesystem writes. Binding checks the registered Git worktree, common repository, branch, assignment identity, and exact creation base. Later worker commits and integration merges do not change that saved base. Use `start` for work that continues in an existing checkout; `existing-checkout` assignments keep their compatibility path. Worker assignments list exact owned files with repeated `--owned-path <repo-relative-path>` options. `agent-worktree.mjs register` receipts retain path, owner/task, branch, creation base, integration ref, and session. Both helpers accept `--root <checkout>`; worktree retirement resolves the primary checkout automatically. Keep briefs and logs in the session, and durable verification outside the deletable dump area. Existing Markdown receipts are historical notes, not automatic cleanup authority.

Active schema-v1 reservations are unsupported because they did not record the original coordinator checkout or a readiness receipt. The helper fails closed without changing the row; it never infers a path. Preserve the row, have the coordinator confirm the old worker stopped, then record a superseding reservation under a new owner/task identity that references the old row. Terminal schema-v1 rows remain readable history. This is separate from legacy `start`/`existing-checkout` bindings, which keep their in-place compatibility path.

`agent-work.mjs start` creates or reactivates the selected session marker. After an `active-task.mjs` assignment command, `render --output .agent-work/<date>/<session-id>/progress.md --root <checkout>` initializes or refreshes only that session's generated view. It preserves shared assignments, other session views, and unfinished work. A terminal `render` without `--output` prints a compact list and does not rewrite `context/active_task.md`. Keep [`active_task.md`](../../context/active_task.md) as static navigation and read commands; do not maintain progress rows there. Follow the [active-task handoff](../../context/workflow.md#active-task-handoff) for the register-before-dispatch lifecycle and explicit recovery of unfinished assignments.

Use the contributor workflow's compact reports to inspect session and assignment state before opening detailed records. After an interruption, run `node scripts/agents/recovery-report.mjs [--owner <id>] [--task <id>] [--root <checkout>]` to correlate assignment/checkpoint data with actual Git worktree state, changed paths, and any existing receipt. Its agent status is `unknown` unless a host-level source establishes liveness; an active assignment or session marker alone does not prove that an agent is running. An explicit `active-task.mjs reassign` preserves the source assignment and evidence, then creates a linked successor without completing work or reclaiming locks. Worker successors continue in the same source checkout with a fresh `existing-checkout` binding under the new owner identity; reservation/readiness authority is never copied. Reserved workers need a new reservation after the old worker is resolved. Pre-binding unreserved worker rows without a reassignment successor marker may hand off only as unverified records; no owned-path snapshot is synthesized.

## Isolated implementation

For a new worker, fetch `origin/development` to select its full SHA, then reserve before dispatch. `reserve` itself performs one bounded fetch with an explicit `development` to `refs/remotes/origin/development` refspec, then requires that freshly fetched SHA, the supplied SHA, and parent `HEAD` to match exactly. A failed fetch or mismatch writes no reservation. If the remote advances between selecting the SHA and reserving it, select the new SHA and run the preflight again; `reserve` does not retry. A stale local `development` or feature tip cannot start the worker. T3 may create an app-owned worktree outside the managed directory; bind it only after it appears in Git's worktree inventory.

```powershell
git -C <parent-checkout> fetch origin development
if ($LASTEXITCODE -ne 0) { throw "Could not fetch origin/development; stop before reserving or dispatching." }
$baseSha = git -C <parent-checkout> rev-parse refs/remotes/origin/development
if ($LASTEXITCODE -ne 0 -or $baseSha -notmatch '^[0-9a-fA-F]{40,64}$') { throw "Could not read a full fetched origin/development SHA; stop before reserving or dispatching." }
node scripts/agents/active-task.mjs reserve --owner <owner> --task <task> --session <date/session-id> --base-sha $baseSha --owned-path <repo-relative-path> --summary "<assignment>" --next "<next action>" --root <parent-checkout>
git -C <parent-checkout> worktree add -b <unique-task-branch> <absolute-worker-path> $baseSha
node scripts/agents/active-task.mjs bind --owner <owner> --task <task> --worktree <absolute-worker-path> --root <parent-checkout>
node scripts/agents/active-task.mjs edit-ready --owner <owner> --task <task> --root <absolute-worker-path>
node scripts/agents/agent-worktree.mjs register --id <worker-id> --path <absolute-worker-path> --integration-ref <integration-branch> --session <date/session-id> --owner <owner> --task <task> [--external-app-owned]
```

An app-owned T3 dispatch starts from the parent commit, so check that the parent commit equals the captured fetched SHA before dispatch. A mismatch fails closed; any exception needs separate user authorization and a recorded reason. A name collision stops worktree creation; choose another worker path instead of replacing an existing checkout. Keep work on the assigned branch. For reserved assignments, `bind` then recorded `edit-ready` are required before edits; handoff rejects a skipped or mismatched readiness receipt. Existing-checkout continuation uses `start` and keeps its current checkout.

Keep workers on their assigned task branches. Integrate through the approved feature workflow; creating a dump space does not authorize commits, merges, pushes, or source edits in another checkout.

## Gemini task briefs

Use the concise brief and final handoff shape in the [contributor workflow](../../context/workflow.md#task-briefs-and-handoffs), with the exact checkout, branch, and acceptance commands. Keep raw notes in the managed session. After one failed tool call, allow one named fallback and ask the worker to report a blocker if it also fails; browse only when the task needs current factual research.

## Repository package manager

Use `pnpm` for repository installs and package scripts. The root `package.json` pins pnpm; npm versions that support `devEngines.packageManager` reject npm installs and scripts, and Corepack refuses Yarn for this package. These settings do not intercept arbitrary shell commands or Yarn invoked outside Corepack. Contributor and runtime CI also install with pnpm.

The `pnpm install` prepare step selects the repository's `.githooks` directory when Git is available and no custom `core.hooksPath` is set. It skips setup when Git is missing or the checkout is outside a Git repository. The pre-commit hook checks staged regular text blobs from the index and rejects implementation files over 20,000 bytes (about 5,000 tokens at bytes/4). It skips top-level `tests/` and `specs/` trees case-insensitively, exact package lockfile names, `node_modules/`, root-level `dist/` and `coverage/`, and codegen filenames containing `.generated.` or `.g.` before an extension; the limit is path-based and does not exempt other files by source extension. During an active merge, it exempts a staged regular blob only when its mode and blob ID exactly match a regular file in `HEAD` or any actual `MERGE_HEAD` commit, regardless of pathname; this covers renames while keeping other resolutions checked. Malformed merge refs fail closed. Do not mark authored files as generated to avoid splitting. Split an oversized file by cohesive responsibility, keep a small entry point, then rerun `pnpm run check:staged-size`. Contributor CI exercises this staged-index checker with temporary Git indexes; it does not scan the pull-request tree. A custom Git hook path is preserved, and installs with `--ignore-scripts` do not configure the hook; run `pnpm run prepare` after a skipped lifecycle install when no custom hook path is configured.

## Retirement

Use the `clean-agent-dump` skill when a run is ready for cleanup. After the shared owner/task handoff is completed, the coordinator reviews the result and attests that workers stopped. Accept the receipt with a verification file outside `.agent-work/` and Git metadata, inside the primary checkout:

```powershell
node scripts/agents/agent-worktree.mjs accept --id <worker-id> --evidence docs/<verification-file> --workers-stopped
node scripts/agents/agent-worktree.mjs cleanup --id <worker-id>
```

The preview reports eligibility or a retention reason. It checks registered/canonical paths, branch and accepted HEAD, any active/blocked shared assignment for the worker checkout, dirty/untracked/ignored content, ancestry into the recorded integration ref, and the retained evidence hash. This retirement check remains checkout-wide even when the assignment belongs to another session. A clean tree alone does not prove integration. `--workers-stopped` is the coordinator's explicit attestation, not process discovery by the CLI.

When removal is authorized, repeat the targeted cleanup command with `--apply`. Under shared locks the helper rechecks eligibility and uses Git's non-forced worktree removal, retaining the branch and ownership receipt. It rejects the invoking checkout, primary checkout, unknown owners, and paths outside the managed area. Session cleanup remains separate; its helper retains active, linked, malformed, and Git-containing folders. Neither operation deletes the dump root or overrides a safety refusal.
