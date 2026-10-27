# Open a single repository PR

Use `scripts/agents/open-pr.mjs` when this checkout publishes to one GitHub repository. It accepts an explicit remote and base, so it works with JarvisMate's `jarvismate` remote and `main` base:

```sh
node scripts/agents/open-pr.mjs --remote jarvismate --base main --title "Add feature" --body-file .agent-work/pr-body.md
```

The checkout must be a clean `feat/scope-description` branch. The helper fetches the selected remote base, requires that exact tip to be an ancestor of the feature head, and then runs `node scripts/ci/check-context.mjs`, `pnpm run lint`, and `pnpm run test:contributors`. A failed gate stops before push. It pushes with a normal fast-forward push and asks `gh` to create a draft PR with the supplied title and body file. `gh` uses its configured authentication or `GH_TOKEN` from the environment; provide credentials externally and never place them in arguments, files, or logs.

If the command is retried after PR creation, it returns the matching open PR when exactly one exists for the same head and base. It refuses ambiguous matches and does not merge or mark the PR ready.
