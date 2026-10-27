# Orchestration output tools

Use [`agent-output.mjs`](../../scripts/agents/agent-output.mjs) to save a small JSON handoff and inspect a bounded log tail from an active contributor session. It accepts JSON on stdin, writes only inside the selected session, and prints a JSON receipt. It does not launch or verify another process.

## Save a handoff

Start the managed session first, and use the task output already provided by [`agent-context.mjs task`](../../scripts/agents/agent-context.mjs) for approved feature work. Add only the brief delta the worker needs; this tool does not parse or duplicate the task ledger.

```powershell
# Use the session identity from the registered assignment.
$sessionDate = $registeredSessionDate
$sessionId = $registeredSessionId
$workspace = (Get-Location).Path
$session = "$sessionDate/$sessionId"
node scripts/agents/agent-work.mjs start --session $sessionId --date $sessionDate --root $workspace

# Set these from the already-authorized feature assignment.
$tasksFile = $approvedTasksFile
$taskId = $approvedTaskId
$planFile = $approvedPlanFile
$taskContext = node scripts/agents/agent-context.mjs task --tasks $tasksFile --task $taskId --plan $planFile

$payload = @{
  brief = @{
    taskContext = $taskContext -join "`n"
    delta = 'Describe only the scoped change the worker needs.'
  }
  exitObservation = @{
    code = 0
    signal = $null
  }
}
$handoffJson = $payload | ConvertTo-Json -Depth 30 -Compress
$oldOutputEncoding = $OutputEncoding
$oldConsoleEncoding = [Console]::OutputEncoding
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
try {
  $OutputEncoding = $utf8NoBom
  [Console]::OutputEncoding = $utf8NoBom
  $receiptJson = $handoffJson | node scripts/agents/agent-output.mjs --workspace $workspace --session $session --output 'handoff.json'
} finally {
  $OutputEncoding = $oldOutputEncoding
  [Console]::OutputEncoding = $oldConsoleEncoding
}
$receipt = $receiptJson | ConvertFrom-Json
$receipt | Format-List status, output, bytes, exitObservation
```

The `--workspace` value must be a Git checkout root. The example sets PowerShell's native pipeline and console encodings to UTF-8 without a BOM for Windows PowerShell 5.1 and PowerShell 7, then restores both settings. PowerShell passes each option value as a separate argument; the JSON travels through stdin, so paths and JSON strings do not need shell interpolation. `handoff.json` is written as UTF-8 without a BOM under `.agent-work/<date>/<session-id>/`. The output must be a single `.json` filename that does not already exist. If passed, `--log` must name an existing regular file in the same session directory.

`exitObservation` is caller-supplied metadata copied to the receipt. A code of `0` does not prove the observed process succeeded: the CLI does not run that process. The CLI's own exit status is `0` only when it writes the handoff and receipt successfully.

| Bound | Limit |
|---|---:|
| JSON on stdin | 256 KiB, one UTF-8 object, no BOM |
| Log tail in the JSON receipt | 16 KiB and 100 lines |
| Output path | One filename inside the active session |

Malformed or oversized JSON is rejected before any output write. Existing files, linked session directories, and invalid output names are refused. Log text is returned as UTF-8 text with file size, retained byte and line counts, and a truncation flag; the CLI does not return a base64 or full log copy.

## Source boundary lint

ESLint applies two restrictions only to files under `src/`: access to the mock-private `transitionContexts` property, including dot and computed-string access, and imports from `tests/runtime/support`. Runtime test support remains available to tests. The public `StatePort` methods and ordinary `unknown` casts remain usable.
