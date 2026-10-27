# Python CLI contract

These commands are planned; no Python implementation exists yet.

## Entry point

Install `python/` as an editable package, then invoke `python -m lifemate`.
Commands: `check-data` and `run`. Diagnostics go to stderr; stdout contains a single
machine-readable command summary on ordinary completion/failure. Do not mix model
progress output or data-bearing traces into stdout.

## Shared dataset arguments

| Argument | Meaning |
|---|---|
| `--data-root PATH` | Root containing `<split>/<split>.jsonl` and expected split assets |
| `--split train\|public_test` | One split per process |
| `--runtime-dir PATH` | Trusted organizer package directory, e.g. `tools/train` |
| `--id ID` (repeatable) | Explicit selected IDs; execute in dataset order |
| `--all` | Explicitly select every record; mutually exclusive with `--id` |
| `--input-mode transcript\|audio` | Transcript only for train; audio for actual prediction input |

Selection is required. Zero matches, duplicate selected IDs, unknown IDs, or duplicate
dataset IDs are errors. Do not auto-select intersection with available assets.
Unselected malformed JSON/duplicate identities still invalidate the input file;
unselected missing audio/environments do not invalidate a selected subset.

## check-data

Validate JSONL parsing, selected record schemas/history, catalog validity and runtime
tool coverage, allowed-tool references, safe relative audio paths, and required selected
assets. Check hidden state-path existence only; never open it. Audio mode requires
current/history-user WAVs; transcript mode requires their supplied text, not WAV files.
Require the catalog at `<data-root>/<split>/<split>_tools_catalog.json`; fail rather
than allow ToolEnv's missing-catalog fallback. Detect the misspelled environment
folder and explain the required layout; do not rename data as a side effect.

This command loads neither model weights nor a sample environment. Exit 0 only
after selected preflight succeeds. Summary includes split, mode, selected IDs/count,
total dataset IDs, catalog identity, and coverage scope.

## run

Runs check-data-equivalent preflight, then loads local models and executes sequentially.

| Argument | Meaning |
|---|---|
| `--planner-model PATH` | Local Qwen snapshot directory; required |
| `--asr-model PATH` | Local compatible Whisper/PhoWhisper snapshot; audio mode only |
| `--device cpu\|cuda` | Explicit device; unavailable device fails clearly |
| `--run-dir PATH` | New run directory; refuse existing path |
| `--max-steps N` | Positive decision bound, default 16 |
| `--sample-timeout-seconds N` | Positive sample budget, default 30 |
| `--trace-payloads` | Explicit detailed dataset-debug payload capture in local traces |

Keep model/token settings in versioned code/configuration and record them. No
production scripted-planner option: tests inject controlled adapters directly.
Inference uses local files only and never downloads models implicitly.

Detailed baseline inspection uses `--trace-payloads`; otherwise required metadata
traces mark payload omissions and do not satisfy baseline-validation evidence.
Data-bearing payloads stay out of routine stdout/stderr.

On success, stdout summary identifies run manifest and completed prediction path.
On the first failure, stop before the next sample, retain partial results, and identify
the failure trace. Exit codes: `0` complete selected run/preflight; `2` invalid arguments
or input/preflight; `1` model/execution/artifact failure. No automatic resume or rerun.
Unhandled hard process death may prevent a structured summary; partial artifacts
remain incomplete and are not promoted on the next invocation.

## Integration boundary

The Python library exposes complete sample execution. A later TypeScript harness
will use a persistent stdin/stdout JSONL worker per ADR 002. That transport is not
implemented by this feature; CLI stdout summaries are not the future worker protocol.
