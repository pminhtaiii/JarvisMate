# Extension hooks

Read this reference when `.specify/extensions.yml` exists. Use the hook definitions in that file as the source of truth.

For both `hooks.before_implement` and `hooks.after_implement`:

- If the YAML is invalid, or no hooks exist for that phase, continue without hooks.
- Skip entries with `enabled: false`; entries without `enabled` are enabled.
- Do not interpret a non-empty `condition`. Leave condition evaluation to the repository's HookExecutor; skip the hook when that executor is unavailable. A missing, null, or empty condition is executable.
- Convert dots in command names to hyphens when forming the slash command, such as `speckit.git.commit` to `/speckit-git-commit`.

For each executable mandatory pre-hook, emit and execute this form, then wait for the actual result before implementation:

```text
## Extension Hooks

**Automatic Pre-Hook**: {extension}
Executing: `/{command}`
EXECUTE_COMMAND: {command}
```

A failed result or unavailable command blocks implementation. The emitted label alone does not count as execution.

For an optional pre-hook, show:

```text
## Extension Hooks

**Optional Pre-Hook**: {extension}
Command: `/{command}`
Description: {description}

Prompt: {prompt}
To execute: `/{command}`
```

Run it only when the user asks.

Before completion, emit and execute each mandatory post-hook in this form, then wait for the actual result:

```text
## Extension Hooks

**Automatic Hook**: {extension}
Executing: `/{command}`
EXECUTE_COMMAND: {command}
```

A failed result or unavailable command blocks completion. For an optional post-hook, show the same optional form with **Optional Hook** in place of **Optional Pre-Hook** so the user can choose to run it.

If a post-hook changes implementation source, reopen the affected checks, convergence, and final review before reporting completion.
