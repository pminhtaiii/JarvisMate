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

Exit `0`: 361 tests, OK, 15 skipped (the same skips as above).
`test_training_data.py` has 52 tests, OK: 24 partition tests and 28 export tests. The counts
include the PR #13 review fixes:
- a chat-template exception now excludes only its row (`template_render_failed`);
- `train.jsonl` reads are capped at 256 MiB;
- the partition manifest is written to a staging file and then published without
  replacing an existing path, so an interrupted write leaves no partial manifest;
- the export claims its output with an exclusive `mkdir`, so it never replaces even an
  empty directory created after the early check.
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
  `validation.next_action.jsonl`, `exclusions.jsonl` and `export_manifest.json`. All are
  staged first, then moved into an exclusively created output directory with the manifest
  last, so a directory without it is incomplete. It refuses existing outputs and outputs
  inside the data root or base model.
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

## T027–T030 — Adapter fit and merge, controlled plus CPU smoke (recorded 2026-11-01)

**Branch**: `feat/native-sft-fit`, stacked on `feat/native-sft-export` (PR #13); code at
`2be14cb`. **Evidence level**: controlled unittest fixtures, plus a real CPU
fit/save/reload/merge/inference smoke on a tiny random two-layer Qwen3 checkpoint. The
test generates that checkpoint with a character-level fast tokenizer and a Qwen3-style
tool template. No Qwen3-4B weights, real tokenizer, Train data, GPU or evaluator was
used. This proves the code path and its refusals, not Qwen3-4B memory, speed or quality.

The isolated environment is a fresh venv outside the repository (Python 3.13.1,
Windows-11-10.0.26200, CPU only), built from the candidate pins and then frozen into
`python/requirements-training.txt`. The global interpreter has no training library.

```bash
# from python/, global interpreter (no torch/transformers/peft)
PYTHONPATH=src python -X utf8 -m unittest discover -s tests -p "test_*.py"
# from python/, isolated training venv
PYTHONPATH=src <venv>/python -X utf8 -m unittest discover -s tests -p "test_*.py"
```

Exit `0` both times: 388 tests, OK. Global: 19 skipped, which are the 15 from T020–T025
plus 4 in `test_training_fit.py` (the three `RealStackSmoke` tests and the CUDA-only
QLoRA test). Venv: 10 skipped (2 symlink cases, 5 opt-in real-tokenizer tests,
`test_real_samples.py`, the CUDA-only QLoRA preflight, and the missing-library check,
which applies only outside the training environment). `test_training_fit.py` has 27
tests: global OK with 4 skipped, venv OK with 2 skipped in 42 s.

- **T027**: `training/fit.py` validates a strict JSON config: every field is required,
  unknown fields are rejected, and relative paths resolve against the config file.
  - The input gate accepts only unmodified, unique rows of the export's `fit.jsonl`.
    That file's digest must match an export manifest with zero leakage and partition
    failures, packing off, ignore index `-100` and the current native protocol prompt.
    Validation diagnostics and relabelled validation rows are rejected.
  - The base tokenizer re-derives every row's completion-only labels, which must equal
    the export's token counts and decode to the canonical target. A row over
    `context_limit` or `max_target_tokens` stops the run with `CONTEXT_LIMIT`; nothing
    is dropped or truncated.
  - Every lock pin must match the installed version, and the lock's sha256 must match
    the config. A missing GPU, CUDA without BF16 or a microbatch that does not fit stops
    the run; precision, method and device are never changed.
  - Training uses all-linear LoRA, or NF4 double-quant BF16-compute QLoRA with k-bit
    preparation. Base weights are BF16 with fp32 adapters and SDPA attention. The data
    order is seeded per epoch; AdamW uses linear warmup/decay and gradient clipping 1.0.
    The loss is row-level mean completion NLL. Logits are computed only at completion
    positions (`logits_to_keep` with left padding), so a full-vocabulary matrix is
    never built over a long prompt.
  - Training libraries are lazy imports; the existing subprocess probe still finds none
    of them imported by `python -m lifemate.training`.
- **T028**: `fit --config PATH [--preflight-only]` claims a new output directory. Its
  `fit_manifest.json` follows `preflight` → `fit` → `adapter-saved`, and a failed run
  keeps the failing check and error. Each epoch writes `checkpoint-epoch-<n>/`: the PEFT
  adapter plus `lifemate_adapter.json` with the full base file identity, protocol,
  export/rows/config/lock digests and adapter digest. It is published only after the
  saved tensors reload equal to the trained ones. On CPU, two runs of one config wrote
  byte-identical adapters for both epochs. `--preflight-only` audits inputs, packages,
  device and one longest-row forward/backward pass, then stops without a checkpoint.
- **T029**: `merge --base-model --adapter --output` (`training/export.py`) refuses:
  an incomplete or tampered adapter; a non-native or foreign trainer; a base whose
  weight, config or tokenizer files differ from the adapter's provenance; an existing
  output; and outputs inside the base or adapter. All refusals happen before training
  libraries load or the output exists. It merges in BF16 and copies tokenizer and
  template files byte for byte, so the `planner-model` factor still sees the identical
  tokenizer. The reloaded export's state dict must equal the merged weights. It writes
  `lifemate_export.json` last and removes its own output on failure.
- **T030**: in the venv, `RealStackSmoke` exports four fit rows through the real
  tokenizer and pinned LMFE grammar, then fits, checkpoints, reloads and merges. A
  finish-only adapter, merged and loaded by the unchanged native `LocalPlanner`,
  returned the canonical finish with stop reason `eos`. Merging the same adapter onto a
  second random base was refused with `INPUT_INVALID`. Only CUDA branches did not run:
  peak-VRAM and headroom measurement, the out-of-memory refusal and QLoRA loading. On
  CPU the manifest records the probe length and optimizer-state estimate only.

## T026 — Training environment and lock (PARTIAL, NOT CHECKED, 2026-11-01)

`python/requirements-training.txt` holds the candidate lock. It pins PEFT 0.17.1,
Accelerate 1.10.1 and bitsandbytes 0.48.1, the inference pins (PyTorch 2.9.0,
Transformers 4.57.1, NumPy 2.3.4, LMFE 0.11.3) and their resolved dependencies. TRL is
not used: the exporter's verified explicit labels replace `completion_only_loss`. The
CPU smoke above passed with exactly this lock.

Not done: the GPU one-batch smoke at real Qwen3-4B lengths, BF16 support, VRAM, the
LoRA versus QLoRA choice, and a Linux install from this lock. Torch's CUDA wheels and
platform installer packages are pinned by their parents, not by the lock. On the
training host, run from `python/`:

```bash
python -m lifemate.training fit --config <config.json> --preflight-only
```

## T031, T032 — NOT RUN (2026-11-01)

Blocked, not failed. Both need T016/T019 (frozen real partition, protocol comparison,
SFT eligibility), the Qwen3-4B checkpoint, a GPU and the evaluator; T032 also needs the
offline A30 target. No real adapter, merged export, tuned/base comparison, score,
latency or promotion decision exists. The native base remains the fallback.

## T033–T035 — Documentation and handoff (recorded 2026-11-01)

- **T033**: `python/README.md`, `context/architecture.md`, `context/tech_stack.md`, the
  [training contract](contracts/training.md), the [quickstart](quickstart.md) and the
  [SFT design](../../docs/design/train-to-sft.md) describe the implemented commands and
  only the evidence above. `structured-v1` stays the default control, and experiment
  trade-offs stay open.
- **T034**: quickstart checks at their applicable scope, from `python/`, each exit `0`:

  | Check | Global interpreter | Training venv |
  |---|---|---|
  | `test_qwen_protocol.py` | 30 OK, 12 skipped | 30 OK, 5 skipped (real tokenizer) |
  | `test_inference.py` | 41 OK | 41 OK |
  | `test_agent.py` | 18 OK | 18 OK |
  | `test_checkpoint.py` | 10 OK | 10 OK |
  | `test_cli.py` | 37 OK | 37 OK |
  | `test_training_data.py` | 52 OK | 52 OK |
  | `test_training_fit.py` | 27 OK, 4 skipped | 27 OK, 2 skipped |

  Not runnable here: the `LIFEMATE_QWEN_TEST_MODEL` checks (section 1), partition freeze
  and protocol comparison (section 2), the real export audit (section 3), a real fit
  (section 4) and deployment evaluation (section 5). They need the assets listed in
  T001. `node scripts/ci/check-context.mjs` and `git diff --check` passed.
- **T035**: FR-001–011 and FR-015 have controlled evidence (T002–T025, T027–T030).
  FR-012 is implemented and CPU-smoked, but its GPU lock smoke (T026) is open. FR-013
  and FR-014 (closed-loop tuned/base evaluation, A30 timing) have not run. Relative
  links in the touched documents resolve. Data, partitions, exports, adapters, merged
  checkpoints and run manifests default to the ignored `.agent-work/` tree
  (`git check-ignore` confirmed), and no dataset, audio, JSONL or weight file is
  tracked. The fit/merge work is under review in
  [PR #14](https://github.com/pminhtaiii/JarvisMate/pull/14).
