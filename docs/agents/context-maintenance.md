# Context Maintenance

After implementation and verification, review [the context index](../../context/README.md) against the actual changes. Update every affected document, including architecture, approved stack choices, runtime policies, state, permissions, standards, testing, and implementation status when relevant. Preserve each document's headings, tables, terminology, and level of detail; edit the owning statement rather than appending a second version. Keep target design separate from implemented behavior. Progress claims cite inspected paths and actual verification commands/results; a passing helper test does not verify a product runtime capability. Record unresolved conflicts instead of inventing a decision.

The implementing agent writes the new content from its code inspection and test evidence. The updater applies those edits mechanically; it does not infer architecture or verification from file presence. Prepare an update plan in the managed session folder, with the SHA-256 of each current file and exact, uniquely matching passages:

```json
{
  "updates": [
    {
      "file": "context/architecture.md",
      "sha256": "<SHA-256 of the current file bytes>",
      "edits": [
        { "oldText": "<exact existing passage>", "newText": "<evidence-based replacement>" }
      ]
    }
  ]
}
```

Use `Get-FileHash -Algorithm SHA256 context/architecture.md` in PowerShell to capture a file hash. Include all affected existing `context/*.md` files in the plan. Use `active-task.mjs` for the shared task view. New documents or heading reorganizations need a separate intentional edit and an updated README route.

```powershell
node scripts/agents/update-context.mjs --updates .agent-work/<date>/<session>/context-updates.json
node scripts/agents/update-context.mjs --updates .agent-work/<date>/<session>/context-updates.json --apply
```

Both commands accept `--root <checkout>`; the updates path is relative to the calling shell. Preview shows the proposed file contents without writes. Apply checks source hashes and unique passage matches, preserves headings and newline style, writes the batch, and runs the context consistency check. Invalid context rolls back this run's changes; concurrently edited files are retained for inspection. A stale hash requires reinspection and a new plan. The updater lock serializes updater runs; other editors must still coordinate file ownership. After applying, review the diff for semantic conflicts and report the updated documents and validation result before finishing the active task. If inspection finds no context changes needed, use `{"updates":[]}` and run apply to validate the existing context, then report that conclusion.
