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

Exit `0`: 303 tests, OK, 15 skipped (3 baseline skips from T001; 7 character-grammar
tests because the inference extra is not installed globally; 5 opt-in real-tokenizer
tests, see T013). Counts include the PR #10 review fixes below. Per file:

| File | Tests | Result |
|---|---|---|
| `test_qwen_protocol.py` (new) | 30 | OK, 12 skipped |
| `test_inference.py` | 41 | OK |
| `test_agent.py` | 17 | OK |
| `test_cli.py` | 36 | OK |
| `test_checkpoint.py` | 10 | OK |
| `test_reporting.py` | 47 | OK |
| `test_selection.py` | 6 | OK |
| `test_artifacts.py` | 28 | OK |

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
  template identity: the planner tokenizer files are hashed into `execution_identity`.
  That covers `tokenizer_config.json` and, after review, also a standalone
  `chat_template.jinja`, which Transformers 4.57 loads when present. Tests show a
  changed template changes that identity and requires `--allow-mixed-resume`, which
  marks the run a development composite that comparisons reject. For native runs,
  `effective_prompt` names the native system prompt, matching the top-level
  `prompt_version`/`prompt_sha256`. The existing `compare-runs` factors now also
  reject a protocol difference; report/compare reject an unknown `planner_protocol`
  value. The new `protocol` factor itself is T017.
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
  appear only with `--trace-payloads`. It is traced on failure too. Trace redaction now
  removes whole quoted secret values inside non-JSON text such as a `<tool_call>`
  block, whether the key is bare, single-quoted, double-quoted or JSON-escaped, and
  including a whole-word `token`. Previously a multiword value kept everything after
  its first space, and single-quoted, escaped and bare `token` forms leaked; tests
  cover each form and check that look-alike keys such as `max_tokens` stay visible. Planner metadata
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

## T014, T015, T017 — Partition and comparison factors, controlled (recorded 2026-11-01)

**Branch**: `feat/native-sft-partition`, stacked on `feat/native-qwen-protocol` (PR #10).
**Evidence level**: controlled unittest suite on synthetic Train rows and run
manifests. No real Train data, model or evaluator was used.

```bash
PYTHONPATH=src python -X utf8 -m unittest discover -s tests -p "test_*.py"
```

Exit `0`: 331 tests, OK, 15 skipped (the same skips as above). New or extended files:
`test_training_data.py` 22 OK; `test_reporting.py` 51 OK; `test_cli.py` 37 OK;
`test_agent.py` 18 OK. The pinned-LMFE grammar run of `test_qwen_protocol.py` is
unchanged (30, 5 skipped). Counts include the PR #12 review fixes: malformed tool,
history or decision entries now fail with `INPUT_INVALID` instead of a traceback; a
`null` decisions file is rejected; a split with no validation members is rejected;
`train.jsonl` and the catalog are hashed from the same bytes that are parsed; a failed
write leaves no partial manifest; label-missing rows still count toward
`long_history`; both model factors require each run's prompt identity to match its
declared protocol; and `planner-model` also compares the loaded tokenizer class.
Run against the previous source, each new check fails.

- **T014**: `python -m lifemate.training partition --data-root PATH --output PATH
  [--seed 20261027] [--validation-fraction 0.2] [--decisions PATH]` reads only
  `train/train.jsonl` and the validated catalog, writes a partition-v1 manifest checked
  by `prompt_profiles.validate_partition_manifest`, and refuses an existing output or an
  output inside the data root. Grouping (`lifemate-train-grouping-v1`) unions
  conversation links (a history replaying another sample's turns, or a shared opening
  turn) and exact normalized duplicates. It reports near-duplicate (token-set Jaccard
  ≥ 0.8) and masked request-skeleton candidates within one installed-tool signature and
  co-groups them unless a recorded review decision separates them; every decision,
  candidate, rule, parameter and limitation is written to the manifest. Smoke IDs
  `train_1748`–`train_1751` and their groups are pinned to fit. Groups are assigned with
  seed `20261027` toward the validation fraction; per-partition coverage counts
  empty-gold, missing-info, multi-app and long-history samples and per-app usage, and
  lists categories/apps absent from validation. Gold labels are read only for that
  coverage audit. The command imports no model or training library, and no
  `*_environment` file is opened (both tested). Visible Train inputs have no explicit
  conversation or template IDs, so those links are inferred; paraphrase detection is
  lexical only, and the manifest says so.
- **T015**: tests cover partition-v1 shape and canonical `source_sha256`, determinism,
  group separation, smoke IDs at a 0.9 validation fraction, exact duplicates (case and
  whitespace only, diacritics kept, across tool signatures), transitive conversation
  links, near-duplicates limited to one tool signature, skeleton masking of times and
  names, unrelated same-tool requests, review decisions and their rejections, coverage,
  no-overwrite, data-root output rejection and environment isolation.
- **T017**: `compare-runs --factor protocol|planner-model`. `protocol` accepts only a
  structured-v1 baseline against a qwen-native-v1 candidate with the identical planner
  checkpoint/tokenizer, ASR, packages, code, dtype, limits and settings, the baseline
  instruction policy, no examples and the selection filter off; only the protocol
  prompt identity may differ. `planner-model` accepts two native runs that differ only
  in planner weight/config files, with identical tokenizer and chat-template files,
  loaded template hash, prompt, ASR, packages, code, limits and settings. Both report
  `promotion_status: exploratory` and never an automatic recommendation. The existing
  factors keep rejecting changed weights and protocol changes.

## T016, T018, T019 — NOT RUN (2026-11-01)

Blocked in this environment, not failed. T016 needs the real Train JSONL/catalog to
freeze the actual partition under `.agent-work/lifemate-runs/native-sft/`, plus the
eligible checkpoint and runtime identities. T018 needs the Train data, the
Qwen3-4B-Instruct-2507 checkpoint, an ASR checkpoint and GPU time for paired
transcript/audio runs. T019 depends on T018 and evaluator output. None of these assets
is available here, so no partition, comparison report, protocol decision or SFT
eligibility exists yet.

## T020–T023, T025 — Native SFT export, controlled (recorded 2026-11-01)

**Branch**: `feat/native-sft-export`, stacked on `feat/native-sft-partition` (PR #12).
**Evidence level**: controlled unittest fixtures with a character-level tokenizer that
renders Qwen3's tool-call template. The native grammar is the real pinned LMFE parser in
the isolated venv run, and a schema stand-in otherwise. No real Train data, Qwen
tokenizer or weights were used. Export engineering proceeds ahead of the T019 gate, as
the task dependencies allow; this record is not SFT eligibility.

```bash
PYTHONPATH=src python -X utf8 -m unittest discover -s tests -p "test_*.py"
```

Exit `0`: 356 tests, OK, 15 skipped (the same skips as above).
`test_training_data.py` has 47 tests, OK: the 22 partition tests and 25 new export tests.
The same file and `test_qwen_protocol.py` were also run in an isolated temporary venv
with `lm-format-enforcer==0.11.3`, outside the repository:

```bash
PYTHONPATH=src <venv>/python -X utf8 -m unittest discover -s tests -p "test_training_data.py"
PYTHONPATH=src <venv>/python -X utf8 -m unittest discover -s tests -p "test_qwen_protocol.py"
```

Exit `0`: 47 OK with the real grammar deciding target admission; 30 OK, 5 skipped
(the opt-in real-tokenizer class). `node scripts/ci/check-context.mjs` and
`git diff --check` passed.

- **T020**: fixtures cover:
  - future-result sentinels at and after their own step;
  - label, `final_state`, sample-ID and group-ID exclusion from prompts;
  - exact runtime prompt parity, grammar key order, sorted prior-call arguments,
    completion-only masks and EOS;
  - history as context only, empty gold, terminal, non-terminal and inconsistent
    missing-info cases;
  - invalid gold: missing label, pairing mismatch, bad shape, unavailable tool,
    schema-invalid and ungrounded targets;
  - prompt and target overflow, inseparable token boundaries and a non-extending
    template;
  - validation separation, manifest identities and digests, determinism, mismatched
    partitions/sources, zero accepted rows, no overwrite, protected output paths and
    untouched environment files.
- **T021**: `gold_rows` builds each row through the inference whitelist
  (`normalize_record`, `prepare_request`, `planner_input`). Labels supply only the target
  and earlier paired observations, and the final row is a declared `policy_finish`.
  `leakage_audit` re-derives every prefix from the source labels. The environment
  existence check moved from `normalize_record` to `preflight`, so conversion never
  touches `*_environment/`; inference preflight still checks each selected sample.
- **T022**: `python -m lifemate.training export` validates the partition's dataset/catalog
  hashes, membership and per-row source hashes. It writes `fit.jsonl`, optional
  `validation.next_action.jsonl`, `exclusions.jsonl` and `export_manifest.json` through one
  staged rename. It refuses existing outputs and outputs inside the data root or base model.
- **T023**: the planner and exporter share `qwen_protocol.render_prompt`. `render_row`
  checks grammar admission, template extension, token-boundary separability, EOS-only
  completion labels, the runtime budget rule and decode round-trip.
  **Finding**: with the pinned grammar, the `sms.send` gold arguments in content-first
  order are rejected and the required-first order is accepted. Targets are therefore
  serialized in grammar order, with values unchanged.
- **T025**: `docs/design/train-to-sft.md` records the implemented native serialization,
  exclusion reasons, artifacts and evidence limits. Its conversion invariants stay the
  single source; the training contract marks `partition`/`export` implemented and
  `fit`/`merge` proposed.

## T024 — Actual-tokenizer export audit (NOT RUN, 2026-11-01)

Blocked in this environment, not failed. It needs the Qwen3-4B-Instruct-2507 tokenizer
and chat template, the inference extra, the real Train JSONL/catalog and the frozen
partition from T016. Command once they exist (from `python/`):

```bash
python -m lifemate.training export --data-root <data> --partition ../.agent-work/lifemate-runs/native-sft/partition.json --base-model <Qwen3-4B-Instruct-2507> --output ../.agent-work/lifemate-runs/native-sft/sft
```

Until then, no real export, row count, length distribution or exclusion review exists.
The real template's tool-call rendering, token boundary and EOS behavior are proven only
by the T013 smoke tests, which have not run either.
