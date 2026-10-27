---
name: clean-agent-dump
description: Use when an agent run has ended and its temporary sessions or task worktrees need cleanup, or when inspecting which dump artifacts can be retired.
---

# Clean Agent Dump

Retire owned, completed artifacts while retaining source work and verification evidence. Read [the workspace guide](../../../docs/agents/workspace.md) for worker registration, receipt acceptance, and shared storage. Run helpers from the primary checkout, or invoke their absolute paths with `--root <checkout>`; older worker checkouts may lack them.

## Inspect and propose

1. Inspect `agent-work.mjs list` and `active-task.mjs list`, and confirm the workers stopped. Session cleanup previews with `node scripts/agents/agent-work.mjs cleanup --session <date/id> --root <integration-checkout>`. A finished marker does not prove its evidence is expendable.
2. For each registered worker, run `node scripts/agents/agent-worktree.mjs cleanup --id <worker-id> --root <checkout>`. Use its eligibility result instead of reconstructing Git deletion checks. Missing receipts, unaccepted handoffs, unmerged commits, local content, resumed tasks, changed evidence, and locked worktrees stay retained. A historical Markdown receipt alone is insufficient.
3. Present exact eligible paths, retained paths with reasons, and the location of durable evidence. Default to preview unless the user has authorized applying cleanup to those paths.

## Apply authorized cleanup

Repeat only the targeted helper command with `--apply`. The worktree helper rechecks under shared locks and calls non-forced Git removal; it retains branches and receipt history. The session helper separately protects active, linked, malformed, and Git-containing folders. Keep evidence outside the deletable dump area before applying session cleanup.

Report command outcomes and retained paths. Stop on an unexpected state or tool refusal. The integration checkout, active sessions, unknown owners, and dump root remain. Cleanup may correctly remove nothing.

When evaluating this skill, use the [versioned evidence procedure](../../../context/workflow.md#skill-evaluation-evidence); results require their own verified source snapshot.
