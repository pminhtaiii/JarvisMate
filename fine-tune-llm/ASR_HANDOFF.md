# Selected ASR and cache handoff

## Explicit preparation from the imported E4 run

The combined L0–L3 launcher can prepare missing ASR caches only under the explicit
approved E4 selection and exact resume-job bindings in ignored
`.agent-work/llm-finetune/orchestration.json`. It reuses ready caches and refuses
unapproved selection, mismatched bindings or arbitrary latest-job resume.
To review the existing E4 provenance and the required audio scopes without loading
a model, run `CHAY_TUNING_LLM.ps1 -PrepareASR -Preview`. The receiving inventory has
4,083 Fit turns and 953 Validation turns, including original-index user history.
Old E4 predictions cover only309 current Validation turns and cannot fill these caches.

An explicit, separate operator request can select E4 provisionally for LLM
development and create genuine caches using the existing export:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\JarvisMate_5\JarvisMate\CHAY_TUNING_LLM.ps1" -PrepareASR -AcceptProvisionalE4
```

This is **ASR inference on 5,036 frozen audio turns**, not ASR/Qwen training. It
copies the export into an ignored derived directory; the original export/logs are
unchanged. It verifies the original selected checkpoint, Fit-only membership,
stored primary evaluation and selection-policy source hash captured by the original
run. Selection evidence records the actual operator's explicit provisional choice;
it never upgrades missing semantic-slot or deployment acceptance. The base revision,
actual model/processor hashes and pinned LocalASR decoding are bound to the handoff.

The model receives audio paths only. No gold audio_text/reference/result is used as
a prediction or failure fallback. Successful turns are fsynced to partial files;
failures stop with an explicit failed row. `-ResumeAsrJob PATH` is an explicit resume
of unchanged successful prefixes, not a retry of failed rows. Original/raw artifacts
stay ignored. Only after strict export/cache validation does the preparer back up
and update `.agent-work/llm-finetune/local-suite.json`; it never starts Qwen afterward.
If the config changes while inference runs, completed assets remain for review and
the config is not overwritten.

The default full-suite command now invokes this preparation when required, waits
for its success, reloads the updated config, and only then enters L0–L3. The
`-PrepareASR` mode remains available for ASR-only work. Later qualification, pilot
review, Fit semantic-view and policy gates remain enforced. Preparing ASR does not
certify those. The stopped job currently retains175 successful Fit rows; restarting
the combined command explicitly resumes that recorded job with its unchanged
producer binding. ASR was not restarted while implementing this integration.

## Artifact contracts

This is a strict bridge to externally selected, fine-tuned PhoWhisper-large assets.
It does not select/train/export ASR or generate caches. Existing ASR folders are
not automatically accepted. Preserve original ASR reports and reconcile their
evidence into the following ignored handoff artifacts after operator review.

`asr_model_dir/llm-handoff.json` uses schema `lifemate-selected-asr-handoff-v1` and
exact fields: `base_model` (`vinai/PhoWhisper-large`), immutable 40-hex
`base_revision`, `selected_experiment` (E1–E4), `checkpoint_sha256`,
`processor_sha256`, `selection`, `training_source_ids`, `split_identity`, `files`,
`logical_parameters`, `decoding`. Fit membership must be nonempty, unique, entirely
within the frozen Fit set and disjoint from Validation. Large architecture and
all model/processor asset hashes are checked. Processor identity is the canonical
hash of the processor asset name→hash mapping (preprocessor, tokenizer config,
vocab/merges and optional tokenizer/normalizer/added/special-token files).

`selection` records experiment/checkpoint, `policy_file`/`policy_sha256` and
`evidence_file`/`evidence_sha256`, all inside the export directory. The selection
evidence schema is `lifemate-asr-selection-evidence-v1`, status `selected`; it binds
experiment, checkpoint, policy hash, canonical sorted Fit membership hash and
canonical export-files mapping hash. The operator must supply genuine frozen ASR
selection evidence; this code does not manufacture it from a directory name.

The current LocalASR bridge requires the explicit decoding contract:

```json
{"language":"vi","task":"transcribe","do_sample":false,"num_beams":1,"max_new_tokens":440}
```

An incompatible existing ASR decoding/cache profile is blocked for review, not
silently rewritten or substituted. Full-audio loading verifies actual ASR parameter
count against the manifest and checks the real joint ASR/Qwen logical budget.

Each `fit-cache.jsonl` or `validation-cache.jsonl` has a sibling `.manifest.json`
with schema `lifemate-asr-turn-cache-v1`, partition, split identity, export identity,
cache SHA256 and package identities. Export identity is the ordered hash of the
handoff body. Each turn has exactly:

```text
source_id, group_id, partition, turn, audio, wav_sha256, pcm_sha256,
export_identity, processor_sha256, decoding_sha256, status, transcript, elapsed
```

`turn` is `current` or `history:N` using the original zero-based history index.
Audio paths are relative to the Train split. WAV/PCM hashes, source/group/turn,
processor/decoding/export and partition are validated. Validation cache coverage
requires every current/historical user turn; failed turns remain explicit and
cannot yield gold fallback. Fit cache may be partial: missing views are excluded.

Non-surface Fit review schema `lifemate-asr-prefix-review-v1` binds base row ID,
clean/noisy ordered row hashes, reviewer/policy, evidence paths/affected slots,
decision and `full_original_prefix_valid`. Only accepted-equivalent or certified
unaffected rows may enter views. A changed amount can leave an independent lookup
valid but cannot automatically preserve the transfer or downstream finish.
`manual_reviews` points to these records for `build-asr-views`; use a separate
review file/config override from clean quality-audit review records.
