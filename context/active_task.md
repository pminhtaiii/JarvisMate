# Active-task Navigation

The primary checkout's ignored `.agent-work/state/active-tasks.json` is the shared task register. This tracked page is a stable navigation aid; do not add assignment rows here. See the [active-task handoff workflow](workflow.md#active-task-handoff) for contributor gates and worker handoffs.

## Inspect shared work

```powershell
node scripts/agents/active-task.mjs list --compact
node scripts/agents/active-task.mjs list --owner <owner-id> --task <task-id>
node scripts/agents/active-task.mjs list --status blocked
```

`list` without `--compact` returns full JSON records. The shared register is authoritative across linked worktrees.

## Start and refresh session progress

Create or reactivate the ignored session marker, then initialize its generated progress view from the shared register:

```powershell
node scripts/agents/agent-work.mjs start --session <session-id> --date <YYYY-MM-DD> --root <checkout>
node scripts/agents/active-task.mjs render --output .agent-work/<YYYY-MM-DD>/<session-id>/progress.md --root <checkout>
```

The first `render --output` creates the selected session view with `ready` or its current assignment states. Re-run the same command after `active-task update`, `start`, `handoff`, or another lifecycle command to replace that generated view from canonical state. It writes only that session's `progress.md` under ignored `.agent-work`; it does not change assignments or this tracked page. It refuses traversal, linked directories/files, and unmarked or other-session files. The view links to the canonical registry and points back to each assignment's `active-task.mjs list` command. Keep task state in the registry, not in the generated view.

`node scripts/agents/active-task.mjs render` without `--output` prints a compact assignment list to the terminal and writes no files.

Use `active-task.mjs start` and `update` to record owner, task, session, goal, next action, status, and verification evidence. Use `handoff` for worker results and `verify-handoff` to check the owned paths. Use `reassign` to record a successor, `archive` to preserve terminal evidence before clearing, and `finish` only through the contributor completion gate.

## Migrate old managed views

```powershell
node scripts/agents/active-task.mjs migrate-legacy
```

Migration saves exact snapshots of marker-based `context/active_task.md` views under ignored `.agent-work/state/legacy-active-task` before import. It merges distinct, unambiguous owners into the shared register, keeps existing canonical rows on collisions, and reports conflicting legacy owner/task pairs for review. Their source snapshots remain available; migration never overwrites a current assignment with a stale view. If shared state is absent, legacy rows remain read-only until this explicit migration runs.
