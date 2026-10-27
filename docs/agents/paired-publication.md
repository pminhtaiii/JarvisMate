# Paired PR and ticket publication

The public `origin` repository is the review source of truth, including CodeRabbit. The private `submission` repository receives the same approved source for coursework. [publication-targets.json](../../publication-targets.json) enables this pairing with remote aliases; private repository identity stays in local Git configuration and ignored publication records.

## Pull requests

Follow the [branch and PR conventions](pr-conventions.md) for the shared feature branch, identical titles and PR descriptions. Use the existing publication command from the public checkout:

```powershell
node scripts/agents/pr-workflow.mjs publish --base development --body-file <body.md> --summary "<short summary>"
```

The helper validates both targets before publishing, runs the normal local gates, publishes the public feature PR against `development`, then creates or updates its submission partner against `development`. Both repositories receive feature branches, never direct writes to their default branches. Both PRs remain subject to human merge decisions.

The submission repository has separate Git history. Its feature commit has submission ancestry and an exact copy of the public source commit's tracked tree. This includes the project README at the repository root, replacing the initial submission README as approved. Ignored dependencies, local evidence and agent state are excluded. The source SHA and tree are retained as provenance; the two PR heads are intentionally different commits.

Two GitHub operations cannot be atomic. If publication stops after one target succeeds, retain `.agent-work/pr-workflow/` and `.agent-work/paired-prs/`, then rerun the same publish command. Recovery identifies the existing pair and resumes it; unexpected external branch/PR changes or changed target identities require inspection instead of overwriting remote work. A partial pair is not contributor completion.

After CodeRabbit or another contributor commits fixes to the public feature branch, pull those changes into the public checkout, verify them, and rerun publication to update the submission snapshot. This is explicit command-driven synchronization; opening a PR directly in GitHub does not run the helper.

Link both returned PR URLs in the app and import a receipt containing both through `record-app-state`. The completion gate checks the public current-head CI and both matching published PR identities. It does not claim the submission repository's CI passed without inspecting it. Public review comments remain advisory under the [PR workflow](pr-workflow.md).

## Target transition

New pairs use public `origin/development` and private `submission/development`. Repository default branches may remain `main`; this does not change PR bases. The first mirror commit is parented by the inspected submission base SHA; subsequent mirror commits advance the same feature branch by fast-forward. Schema-v1 records retain the historical field name `mainBase` for that configured base SHA.

Configuration and retained pair targets must agree. Historical `submission/main` configuration remains readable for recovery and verification; records and PRs are never automatically retargeted. A changed configuration on an active pair blocks publication, verification and contributor completion before remote writes. Keep the record and repair budget intact. Finish or inspect that pair in a separate checkout with its original configuration, then use a fresh unique branch for development-targeted work. Do not rewrite the private history, reset records, or force-update a branch to bypass the refusal. Historical paired-ticket completion likewise requires the original base configuration and exact recorded resolving PR identity; preview before applying.

An existing private feature branch or PR without retained accounting also blocks adoption. Retain both workflow and pair stores across partial publication. No transition writes to either base branch or to submission/main.

## Tickets

Create or update the same pair with a stable key:

```powershell
node scripts/agents/paired-issues.mjs publish --key localized-bug --title "Repair localized bug" --body-file <ticket.md>
```

Use the same key for later title/body updates. The default label is `needs-triage`; `--label` accepts the [canonical triage labels](triage-labels.md). Missing requested labels may be created, while existing label metadata is preserved. Issue numbers can differ between repositories; use the returned URLs rather than assuming a shared number.

The ticket helper validates both repository roles, write access and issue availability before writes. Opaque identity markers and ignored `.agent-work/paired-issues/` receipts support retries after partial writes or lost create responses. Duplicate markers or mismatched identities stop publication for inspection. Closed tickets remain closed; comments, assignees and issue state are not automatically synchronized.

### Complete paired tickets

During CodeRabbit review of a resolving PR, verify every acceptance criterion on both issues for the stable key, prepare evidence, and preview the completion command. An open PR is still waiting: apply only after both paired resolving PRs are merged, using the same source tree and confirming all four contributor/runtime CI jobs pass for the public PR's exact head. CodeRabbit approval is not required, and labels, age, or CI success alone do not establish that acceptance criteria are met.

The evidence file has this shape:

```json
{
  "schemaVersion": 1,
  "summary": "Verified repair evidence",
  "acceptance": [
    { "criterion": "<acceptance criterion>", "evidence": "<verification evidence>" }
  ]
}
```

Run from the public review checkout, naming the stable key and public resolving PR explicitly:

```powershell
node scripts/agents/complete-paired-issues.mjs --key <stable-key> --pr <public-PR-URL> --evidence-file <evidence.json> [--apply] [--root <checkout>]
```

Without `--apply`, the command previews and makes no remote changes. The explicit `--pr` URL and evidence file record the agent's assertion that every criterion is satisfied. Applying adds an idempotent audit comment to each exact paired issue, linking it to that repository's resolving PR, then closes both issues. If one close succeeds and the other fails, retain ignored `.agent-work/paired-issue-completion/` and `.agent-work/paired-issues/` records and retry the same command. Completion targets only the exact stable-key pair; it does not delete or reopen issues or promote labels. This explicit cleanup is separate from ticket publication, which preserves closed state and does not synchronize issue state.

Read the JSON `status`, not just the exit code: `READY_TO_COMPLETE` is an eligible preview, `COMPLETED` confirms both issues are closed, and `WAITING_*` or `BLOCKED` leaves cleanup pending. Evidence may be revised before apply begins; retain the same evidence when recovering an interrupted apply.

Changed acceptance criteria, resolving PR identity or evidence after an apply begins requires inspection and reconciliation. Preserve the records instead of deleting them to force a new attempt.

Audit comments publish only the resolving PR link, the number of attested criteria and the evidence digest. Detailed summary and criterion evidence stay in the local evidence file; they are never copied into GitHub comments. Admission is rechecked before each comment and each close.

## Privacy and configuration

Configure `origin` as the public review repository and `submission` as the private coursework repository. The helper refuses reversed visibility or identical repositories. Configuration without this file retains the original single-repository behavior for other checkouts and helper fixtures.

On a new clone, sign in with `gh auth login` and add the private remote with `git remote add submission <private-repository-url>`. The signed-in account needs write access to both repositories. Keep the submission URL in local Git configuration; do not add it to the tracked configuration file.

Public PR and ticket bodies contain no generated private repository URLs or names. Submission bodies may link back to the public review object. Both links are returned locally for the user and app. Never put credentials in repository configuration; `gh` uses the signed-in account.
