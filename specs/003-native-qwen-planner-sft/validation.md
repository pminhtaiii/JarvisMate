# Native Qwen protocol and planner SFT validation

Execution and evidence ledger for [tasks](tasks.md). A task is checked only when its
behavior was verified and the check is recorded here. Absent runs are recorded as
NOT RUN with the reason; they are never inferred from source inspection.

## T001 — Baseline (recorded 2026-11-01)

**Branch**: `feat/native-qwen-protocol`, created from
`6860c737c80dc3542c231c0eb85ca777f07ff533` (`origin/main`, merge of PR #9 with the
spec 003 planning documents). Working tree clean at branch creation; no dirty files
to preserve.

**Environment**: Python 3.13.1, Windows-11-10.0.26200. Package not installed; tests run
directly against `python/src`.

**Controlled baseline suite (executed)**, from `python/`:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py"
```

Exit status `0`: 241 tests ran, OK, 3 skipped — two `test_dataset.py` symlink cases
("Host cannot create symlinks") and `test_real_samples.py` (no `LIFEMATE_REAL_*` /
`LIFEMATE_RUNTIME_DIR` variables set).

**Asset availability**:

| Asset | Status |
|---|---|
| Supplied runtimes `tools/train`, `tools/test` | Present in the repository |
| Competition Train records/audio (`LIFEMATE_REAL_DATA_ROOT`) | Not configured in this environment |
| Local Qwen3-4B-Instruct-2507 checkpoint/tokenizer | Not configured (`LIFEMATE_QWEN_TEST_MODEL` unset) |
| Inference extra (`torch`, `transformers`, `lm-format-enforcer`) | Not installed |
| CUDA GPU | None detected (`nvidia-smi` unavailable) |
| Official evaluator / A30 target hardware | Not available |

Consequence: US1 controlled engineering (parser, rendering, configuration, adapter
wiring with mocked tokenizer/model) can be implemented and verified here. Actual
tokenizer/LMFE grammar proofs (T013), protocol comparisons (US2) and all fitting
(US4) are blocked in this environment until those assets exist.

**Feature 002 status**: measurement/reporting source and controlled tests are present
on the base revision (see
[002 validation](../002-measurement-prompt-experiments/validation.md)). Its
real-model, GPU and evaluator acceptance remains unestablished; this task list does
not establish it.

## T002–T012 — Native protocol MVP, controlled (recorded 2026-11-01)

**Evidence level**: controlled unittest suite with model/tokenizer doubles, plus the
character-level native grammar executed against the real pinned
`lm-format-enforcer==0.11.3`. No tokenizer, weights, GPU, Train data or evaluator was
used. This verifies adapter/runner behavior, not model accuracy or latency.

Full suite, from `python/`, package not installed:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py"
```

Exit `0`: 297 tests, OK, 15 skipped (3 baseline skips from T001; 7 character-grammar
tests because the inference extra is not installed globally; 5 opt-in real-tokenizer
tests, see T013). Per file:

| File | Tests | Result |
|---|---|---|
| `test_qwen_protocol.py` (new) | 30 | OK, 12 skipped |
| `test_inference.py` | 40 | OK |
| `test_agent.py` | 17 | OK |
| `test_cli.py` | 36 | OK |
| `test_checkpoint.py` | 9 | OK |
| `test_reporting.py` | 46 | OK |
| `test_selection.py` | 6 | OK |

Native grammar against the pinned library: `lm-format-enforcer==0.11.3` (with its
declared dependencies) installed in an isolated temporary venv outside the repository;
the global interpreter was left unchanged.

```bash
PYTHONPATH=src <venv>/python -X utf8 -m unittest discover -s tests -p "test_qwen_protocol.py"
```

Exit `0`: 30 tests, OK, 5 skipped (the opt-in real-tokenizer class only).
`node scripts/ci/check-context.mjs` passed; `git diff --check` passed.

What the evidence covers:

- **T002/T003**: `--planner-protocol structured-v1|qwen-native-v1` (default
  structured). `RunConfig` rejects unknown protocols, and native with `precise-v1` or a
  few-shot bundle, before model load. The manifest records `planner_protocol` and the
  native prompt version/hash; structured runs keep `lifemate-react-v4` and the original
  prompt hash (pinned by a test). A protocol mismatch blocks resume even with
  `--allow-mixed-resume`; manifests written before this feature count as
  `structured-v1`, so existing structured runs remain resumable and comparable. Chat
  template identity: the planner tokenizer files (including `tokenizer_config.json`)
  are already hashed into `execution_identity`; a test shows a changed template changes
  that identity and requires `--allow-mixed-resume`, which marks the run a development
  composite that comparisons reject. `provenance.py` needed no change for this. The
  existing `compare-runs` factors now also reject a protocol difference (the new
  `protocol` factor itself is T017).
- **T004–T006**: `adapters/qwen_protocol.py` renders eligible tools through `tools=`
  with catalog extensions verbatim. Executed observations render as assistant
  `tool_calls` plus `tool` results; validation rejections render only as user
  correction data. It decodes exactly one `<tool_call>` block or the exact text
  `Mình hiểu.`. Malformed, multiple, prose, duplicate-key, non-finite, non-object,
  unfinished and oversized outputs are rejected, never repaired. The native system
  policy lives in `prompting.py`; rendering lives in the adapter so `prompting.py`
  does not depend on adapters.
- **T007**: the native union is the exact final text, or per tool/one-of branch a
  literal prefix, a `JsonSchemaParser` bound to that tool, and a literal suffix
  (`SequenceParser`). Against the real 0.11.3 parser, `can_end()` is false at every
  proper prefix and true only after the closing delimiter or exact final text; nothing
  may follow. Unknown tools, cross-tool arguments, extra or missing arguments, wrong
  types, junk keys on zero-argument tools, a second call, prose and structured JSON
  are refused. Source inspection of 0.11.3 `TokenEnforcer` shows EOS is admitted
  exactly when the parser can end. It also falls back to EOS or a forced stop after an
  internal parser error, so strict decoding remains a required second gate.
- **T008–T010**: `LocalPlanner(protocol="qwen-native-v1")` reads the generated token
  IDs for EOS before `skip_special_tokens` decoding. Outcomes:
  - Deadline → `TIME_LIMIT`, even with complete-looking text.
  - Token budget exhausted without EOS → `OUTPUT_LIMIT`.
  - Any other stop without EOS → `PLANNER_ERROR`.
  - Malformed or ineligible output after EOS → `PLANNER_FORMAT`.
  - Otherwise the adapter returns the canonical call/finish JSON, so the runner
    interface is unchanged.

  The selection filter keeps its separate JSON protocol, and its rejected proposal
  renders as correction data, never as a native tool result. Each native generation
  is traced as `planner_native_output`: stop reason, token count and decision kind are
  always recorded as metadata; raw text and the canonical action are payload and
  appear only with `--trace-payloads`. It is traced on failure too. Planner metadata
  records the adapter, constraint schema `lifemate-native-tool-call-v1`, final text,
  EOS id and chat-template SHA-256.
- **T011/T012**: existing runner invariants are protocol-agnostic and still pass
  (schema-rejected attempts, `done:false`, empty finish, missing-info variants,
  uncertain execution). New native adapter/runner, CLI preflight and resume tests are
  listed above.

## T013 — Actual tokenizer and supplied runtime (NOT RUN, 2026-11-01)

Blocked in this environment, not failed:

- `RealTokenizerNativeProtocolSmoke` in `test_qwen_protocol.py` requires
  `LIFEMATE_QWEN_TEST_MODEL` (a local Qwen3-4B-Instruct-2507 tokenizer directory) and
  the inference extra. Neither is present; the class skips with that reason. When run,
  it checks:
  - EOS is `<|im_end|>`, and `<tool_call>` delimiters are not special tokens.
  - The checkpoint template renders executed calls in exactly the constrained envelope.
  - Through the real LMFE token mapping, every completion token is allowed, EOS is
    refused until the end, and only EOS follows a schema call, a zero-argument call or
    the final text.
- `test_real_samples.py` requires `LIFEMATE_REAL_DATA_ROOT`/`LIFEMATE_REAL_SAMPLE_ID`/
  `LIFEMATE_RUNTIME_DIR`; not configured, so it skips. That suite uses a controlled
  planner, so even when run it shows the dataset/runtime/ToolEnv path is undisturbed,
  not native generation.

Command to run once assets exist (from `python/`, inference extra installed):

```bash
LIFEMATE_QWEN_TEST_MODEL=<tokenizer dir> PYTHONPATH=src python -m unittest discover -s tests -p "test_qwen_protocol.py" -v
```

The native generation path has not run with real weights. No accuracy, latency or
protocol-comparison claim follows from this record.
