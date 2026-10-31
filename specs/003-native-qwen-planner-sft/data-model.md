# Data model

## ProtocolProfile

ID (`structured-v1`/`qwen-native-v1`), prompt hash, tokenizer/template hash, constraint
version, final-text policy, decoding/limits. All affect run identity/resume compatibility.

## NativeConversation and NativeDecision

Ordered role/content messages plus eligible function definitions. Initial data has
request/context/history without labels or duplicated schemas. Executed calls use
assistant `tool_calls` with name/object arguments; results use `tool` role and exact
serialized result. Rejections are correction data. Historical context is never replayed.

A decision records bounded raw generation, token count, EOS/termination reason,
kind (`call`/`finish`/`rejected`) and canonical decision if valid. A cut output has no
executable decision. Only actual canonical attempts enter the organizer call log.

## SourcePartition

Source/catalog hashes, grouping algorithm/version, seed `20261027`, fit/validation
IDs and group IDs, intended validation fraction ~0.2, duplicate audit, actual counts.
Conversation/template/exact and near-duplicate groups stay together per the versioned
training-contract policy. Roadmap smoke IDs 1748–1751 stay fit-side; report actual
coverage. A comparison uses an immutable manifest. Reuse feature 002 partition v1:
`partition_schema_version`, `dataset_sha256`, `grouping_method` and `members` with
`id`, `group_id`, `partition`, `source_sha256`. Add catalog hash, seed, grouping
parameters, duplicate decisions and coverage as auditable manifest metadata; validate
the same members through `prompt_profiles.validate_partition_manifest`.

## SFTStep and ExportManifest

Row provenance: source/group ID, step, partition and target kind; kept outside prompt.
Input: whitelisted request/context/history/tools and strictly earlier paired calls/results.
Completion: one native call or declared neutral final text. Labels are `-100` outside
the final completion; target includes EOS. Prompt plus output fits the <=16,384 cap;
overflow is excluded explicitly. No silent loss of grounding evidence.

Manifest: source/partition/exporter/protocol/base/tokenizer/template identities,
sample/row counts, per-tool/finish/clarification distribution, lengths, exclusions,
weighting. Initial ordinary row-level completion NLL weights long trajectories by
their greater step count; report this rather than implying sample-balanced training.

## TrainingRun

Audited fit identity, package lock, device/VRAM, base, method, adapter settings,
optimizer/LR/schedule/batch/accumulation/epochs/seed, context/memory settings and
checkpoints. States: preflight -> fit -> adapter-saved -> merged-export -> inference-verified.
Failed stages retain evidence but do not qualify for promotion.

## CandidateEvaluation

Base/candidate exports, protocol/runtime/ASR identities, frozen IDs, per-ID status,
calls/hash, evaluator outcomes, full-attempt timing/hardware, coverage, regressions
and promotion reasons. Stages: protocol comparison -> SFT eligibility -> tuned/base
comparison -> target acceptance. Missing evidence stays unavailable, not zero/success.
