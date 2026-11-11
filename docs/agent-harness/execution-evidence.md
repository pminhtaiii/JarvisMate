# Execution evidence for native planning

## Accepted scope

The native integration planner receives bounded, deterministic evidence about its
actual tool observations without retraining or additional model calls. Initial
request and retrieved skill guidance stay fixed. The model retains responsibility
for intent, entity disambiguation, next-tool selection, clarification and finish.

1. Maintain per-sample evidence incrementally from actual observations. Extract
   record references only from supported catalog/tool result shapes, retain tool,
   step and reference provenance, and distinguish failed results from successful
   operations. Never interpret generic success as completion of the user's intent.
2. Give the planner compact execution-aware facts and guidance alongside actual
   observations. Keep original results unchanged and prior rendered turns stable
   when another observation is added. Facts are data, not new user instructions.
3. Observed IDs are candidates, not an exhaustive validity allowlist. Preserve the
   ability to use IDs supplied in the request, context or history. Do not require
   lookups, automatically select an ambiguous entity, or impose a skill workflow.
4. Bound ledger storage, extraction work and rendered guidance. Add no model pass,
   new dependency, environment read, tool call or execution retry. Drop optional
   evidence guidance before it alone would cause context overflow; keep authoritative
   observations, existing context/output limits and deadline enforcement.
5. Preserve the single ToolEnv, eligibility checks, attempted-call log, state hash,
   uncertain-execution policy and legacy runner. Keep shared default rendering used
   by SFT compatible; native runtime explicitly supplies execution evidence.

## Implementation plan

Add a small pure evidence component and connect it to the native planner's existing
sample lifecycle and observation rendering. Derive facts from known tool metadata
and result structures rather than recursively guessing IDs in arbitrary strings.
Append bounded facts after their source result, retaining stable initial skills.
Use existing planner token-budget handling with a fallback that omits optional
facts. Do not add per-turn full skill retrieval or dynamic ID-enum grammars.

Focused checks cover provenance, ambiguous candidates, errors and malformed data,
bounded extraction/storage, sample isolation, unchanged tool results and initial
guidance, stable historical message prefixes, context-budget fallback, and native
integration compatibility. Controlled checks establish behavior only; target-GPU
latency and model quality remain the teammate's evaluation work.

## Verification

The native runtime enables the ledger; the default pure renderer still omits it.
Facts are capped at 16 observations, eight references per observation, 128
characters per ID and 4096 serialized UTF-8 bytes across the sample. Source results
remain intact. The supported reference shapes are top-level collection arrays
whose app/collection is declared by catalog `x-ref`, and the simulator's `item.id`
envelope. Unsupported or oversized IDs are omitted, never guessed or shortened.
No hard ID allowlist or full skill-workflow execution was added.

Controlled checks on 2026-11-11, with `TEMP`/`TMP` set to the workspace's ignored
`.agent-test-tmp` and `PYTHONPATH=python/src;python/tests`:

```powershell
python -m unittest test_execution_evidence test_qwen_native test_qwen_kv test_integration_pipeline test_skills test_sft_export
git diff --check
```

The unittest command ran 93 tests in 32.088 seconds: OK, 33 skipped. The skipped
checks require optional tokenizer/model libraries or local tokenizer assets.
`git diff --check` passed. These are controlled checks, not model-accuracy results.

A CPU-only synthetic timing used the Train catalog and 16 observations of eight
contact records, with ledger initialization and all 16 incremental updates per
sample. Command: `PYTHONPATH=python/src python .agent-work/execution-evidence/bench_evidence.py`
(PowerShell: set `$env:PYTHONPATH` first). Across 500 samples after 20 warmups,
sample-level ledger time was p50 15.159 ms, p95 48.586 ms and max 202.675 ms on the
authoring machine; the byte budget retained five fact records. The local script is
ignored session evidence. This excludes prompt rendering, tokenization, inference
and tool execution and establishes no A30 latency result. Evidence can add prompt
tokens and up to two extra render/tokenization fits near the context limit.

Independent Standards and Spec review reports are pinned to a source-hash snapshot
under the ignored `.agent-work/execution-evidence/reviews/` session directory.
