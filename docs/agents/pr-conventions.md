# Branch and PR conventions

This is the single source of truth for new contributor work (Option A). It preserves the `feat/` interface used by the [PR workflow](pr-workflow.md) and [paired publication](paired-publication.md).

## Feature branches

Use `feat/scope-short-description`, for example `feat/tooling-pr-conventions` or `feat/uc03-validate-repair`.

- `scope` is one lowercase alphanumeric token starting with a letter, such as `uc01`, `uc03`, `uc04`, `uc05`, `tooling` or `infra`.
- `short-description` is concise lowercase kebab-case and describes one objective.

Before creating a branch from fetched `origin/development`, inspect local branches, live heads on both publication remotes, and all PR history (open, closed and merged) in both repositories. Select an unused full branch name; use a more specific description if it already exists or appeared in a previous PR. Both paired branches use the same name. New names have no numeric prefix; Spec Kit directory numbers are independent. Historical branches retain their names.

`preflight` accepts current and historical branch syntax and checks freshness/dirty paths. The first `publish` and `prepare-next` enforce the current scoped shape and full-name inventory. New paired publication requires both development bases; historical main configuration is reserved for existing pairs. Publication reads live remote heads and paginated GitHub PR history, refusing incomplete history or access failures. The inventory is a check, not an atomic reservation across concurrent contributors; coordinate names and inspect any concurrent collision before retrying.

## PR titles

Use `<branch-name>: <action-summary>`. Both paired PRs must have the same title. The summary has 1–80 characters, occupies one line, and has no surrounding whitespace. Start with a clear lowercase action verb: `add`, `implement`, `fix`, `refactor`, `standardize`, `document`, `update`, `remove`, `preserve`, `prevent`, `support`, `configure`, `migrate`, `validate`, `test`, `improve`, `tighten`, `enforce`, `restore`, `repair`, `freeze` or `gate`.

Describe the resulting behavior, for example `feat/tooling-pr-conventions: standardize naming and paired development targets`. The title prefix must exactly match the branch name, including its scope and description, on both repositories. Avoid generic summaries such as “tooling changes”.

## PR descriptions

Use the [PR body skill](../../.agents/skills/pr/SKILL.md) with exactly these three level-two sections, in order:

| Section | Required content |
|---|---|
| `Summary` | What changes, why, and the affected scope; use a small diff sketch or diagram when useful. |
| `Evidence` | Actual test commands/results, before/after behavior, verification evidence and remaining limits. Distinguish failed or unrun checks. |
| `Merge Danger` | `**Door:**` (rollback/reversibility) and `**Blast Radius:**` (affected consumers and integration risks). |

Keep prose brief, professional and consistent with the [glossary](../../GLOSSARY.md). All three sections need explanatory text; fenced code examples do not supply section headings. Helpers validate structure, not the truth of claims: the coordinator must verify evidence against the final diff. Public content must preserve the [privacy boundary](paired-publication.md#privacy-and-configuration). The private body may append the public review link and its opaque recovery marker.

## Historical compatibility

Readers for status, review, recovery and completion retain the historical `feat/NNN-description` syntax and short-summary rules. Existing retained PR identities or publication intents without a convention version can resume without renaming or rewriting old descriptions. Version 1 records retain their numbered naming and inventory rules; new publication records version 2 with unnumbered naming and full-name inventory. Retries and repairs retain their recorded version and PR identity. A missing record is never permission to reset a PR's accounting.

Historical `submission/main` pairs retain their recorded target and ancestry. Follow the [target transition procedure](paired-publication.md#target-transition) rather than editing old records or retargeting PRs.
