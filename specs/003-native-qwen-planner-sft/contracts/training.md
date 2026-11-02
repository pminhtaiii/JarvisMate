# Offline training contract

All four commands are implemented with controlled evidence only (see
[validation](../validation.md)); `fit` and `merge` also ran end to end on CPU against a
tiny random Qwen3 checkpoint, and no real fit exists. All operate outside inference. Source data/weights/traces remain in ignored storage. Training dependencies
are optional and must not become mandatory imports for ordinary `lifemate run`.

## CLI surface

`python -m lifemate.training` exposes four sequential operations:

1. `partition --data-root PATH --output PATH --seed 20261027 --validation-fraction 0.2`
   reads supplied Train records/catalog only and writes a frozen grouped partition
   compatible with feature 002 partition-manifest v1, plus duplicate/coverage audit.
   Reuse its validator and add catalog/grouping/count provenance. Use roadmap grouping
   and fit-side smoke IDs. Refuse
   to overwrite an existing partition; intentional re-partitioning creates a new experiment.
2. `export --data-root PATH --partition PATH --base-model PATH --output PATH
   [--validation-diagnostics] [--context-tokens 16384] [--output-tokens 512]`
   validates source identities, exports fit-only prompt/completion rows, optional
   separately marked teacher-forced validation diagnostics, exclusions and manifest.
   Never create ToolEnv or read `*_environment/`; use supplied gold results.
   Rendering and parity checks are recorded in the
   [gold conversion design](../../../docs/design/train-to-sft.md#native-serialization-implemented).
3. `fit --config PATH [--preflight-only]` reads a JSON configuration and audited fit
   artifact, runs hardware/package/mask preflight and trains/saves adapter checkpoints.
   Refuse validation rows in optimizer input. Failure preserves a failed run manifest.
   `--preflight-only` stops after the one-batch memory probe, without a checkpoint.
4. `merge --base-model PATH --adapter PATH --output PATH` verifies matching base and
   tokenizer/protocol identity, loads original non-quantized base, merges adapter,
   and writes self-contained checkpoint/tokenizer plus export manifest
   (`lifemate_export.json`, written last in a staging directory that is then renamed
   to the output). Refuse overwrite and model/data input directories as output targets.
   Accepted limitation: Python has no portable no-replace directory rename, so on POSIX
   an empty directory created at the output between the existence check and the rename
   is replaced. No file data can be lost; Windows refuses the rename.

Each operation returns nonzero on input/audit/resource failure and a bounded summary
with artifact paths. An export can quarantine bad rows but must report exclusions
and reject a fit with zero accepted rows or failed leakage/mask/partition audit.
Review excluded tool/behavior coverage before training.

## Grouping policy

Version the deterministic grouping algorithm and parameters before partitioning.
Union known conversation/history links and explicit shared scenario-template IDs,
then exact normalized request/history duplicates. Normalize NFC, case and whitespace
without discarding Vietnamese diacritics or numbers. Generate near-duplicate candidate
pairs using token-set Jaccard >=0.8 on normalized request/history and a shared
installed-tool signature; also report matching request skeletons with variable
dates/numbers/entities masked as candidates. Candidate similarity is an audit aid,
not proof of equivalence. Review candidates and record grouping decisions before
freezing; conservatively co-group unresolved related cases. Record algorithm version,
thresholds, candidate counts and every override. Tests cover exact/near duplicates,
shared templates, transitive group union and unrelated same-tool requests. Document
missed paraphrase risk and coverage limits; do not claim semantic deduplication complete.

## Export and targets

Follow [gold conversion design](../../../docs/design/train-to-sft.md) for whitelisting,
strict prefixes, ID grounding, pairing, missing-info and exclusions. This feature
replaces custom model-action serialization with [native protocol](native-protocol.md).

- Ordinary/empty trajectories finish with assistant `Mình hiểu.` plus EOS; provenance
  marks it `policy_finish`, not original gold prose. Terminal waiting calls have no
  extra finish. Quarantine inconsistent gold continuing after terminal results.
- Previous calls/results are input only. Only final target completion/EOS receive
  loss; use prompt-completion `completion_only_loss=True` or verified explicit labels.
  Inspect actual token masks, including prompt/target boundary tokenization.
- Reuse runtime tool/message rendering, not a separate reconstructed template.
  Train/generation prefixes and template generation markers must be token-equivalent
  after excluding training-only mask markers. Pin any template patch and hash.
- Initial packing is off. Every accepted prompt + target fits context and output
  budgets; exclude overflowing rows explicitly. Never silently truncate grounding.
- Default ordinary row-level completion NLL; disclose long-trajectory weighting.
  No oversampling, synthesis, ASR-noise or failure-prefix augmentation initially.

## Fit configuration and preflight

Required JSON fields: base_model, export_manifest, fit_rows, output_dir, method
(`lora`/`qlora`), seed, context_limit, max_target_tokens, microbatch,
gradient_accumulation, learning_rate, epochs, adapter rank/alpha/dropout/targets,
optimizer/schedule/warmup, checkpoint cadence and exact package-lock identity.
The implemented schema (`schema_version: 1`) also requires `device` (`cpu`/`cuda`)
and `gradient_checkpointing`; `package_lock` is `{path, sha256}`; `optimizer`,
`schedule` and `checkpoint_cadence` accept only `adamw_torch`, `linear` and `epoch`.
Unknown fields are rejected; relative paths resolve against the config file. Fixed
settings (weight decay 0, gradient clipping 1.0, left padding, SDPA attention) are
recorded in each run manifest. Fit rows may be the export's `fit.jsonl` or an
unmodified subset of it. `fit` saves per epoch; it does not compute validation loss,
which stays an export-side teacher-forced diagnostic.

Initial experimental defaults: all-linear targets, rank 32, alpha 64, dropout 0.05,
LR 1e-4, AdamW, linear decay with 0.03 warmup ratio, effective batch about 16 rows,
microbatch 1 adjusted to measured memory, gradient checkpointing, evaluate/save at
each epoch through at most 3 epochs for the first run. Compare lower LR if evidence
requires it; no automatic sweep or prescribed total experiment count. Fixed seed
20261027. Final selection is closed-loop, not minimum train loss.

Choose BF16 LoRA if measured capacity supports actual lengths; otherwise QLoRA with
NF4, double quantization, BF16 compute and k-bit preparation. Check BF16/backend
support, GPU/VRAM, full one-batch forward/backward/optimizer/save/reload and maximum
accepted sequence-length feasibility before real fitting. A smaller context budget
requires explicit shared rendering/compaction review or reported row exclusions.
Resource failure blocks the run; it never silently changes precision or drops rows.

Bootstrap with a provisional exact candidate package lock, not floating latest.
Run the one-batch compatibility smoke, freeze the passing PEFT/Transformers/
bitsandbytes and transitive versions in `python/requirements-training.txt`, then
rerun and record the smoke with that frozen lock before a real fit. The trainer
consumes the exporter's verified explicit labels, so TRL is not needed. The current
lock passed only the CPU smoke; the GPU smoke is still required. Keep inference
pins separate and verify the merged export there.
Record license/release eligibility, base/adapter/deployed parameter counts, hardware,
seeds, data identities, hyperparameters, measured memory, revisions and diagnostics.

## Evaluation and deployment

Save adapters and provenance even when deploying merged weights. Merge from the
original non-quantized base for QLoRA; do not assume numerical equivalence to the
training-time quantized model. Verify actual export. Existing `--planner-model`
loads the self-contained export; no inference PEFT or bitsandbytes dependency is
required by this initial design. Any later deployment quantization is a separate
recorded candidate and must be evaluated again.

Gold-prefix validation loss is diagnostic. Closed-loop evaluation receives predicted
calls and real tool observations. Promotion follows [experiments](experiments.md).
Do not publish datasets, raw traces, adapters or weights through this repository.
