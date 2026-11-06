# Data model

## DatasetIdentity

Role (`train`/`validation`), explicit JSONL/catalog paths, content hashes, supplied
version, permitted-use declaration, source IDs and available conversation/group IDs.
Validate finite JSON/required shapes and cross-role overlap before expansion.
Missing grouping metadata is an audit limitation; ID and normalized visible-input
duplicate checks remain mandatory. Roles never change automatically.

## NextActionRow

Schema version; provenance (source ID, role, digest, decision index); whitelisted
request/context/history; exact eligible tool schemas; ordered strict-prefix
call/result pairs; one semantic call or finish target. Provenance stays outside
rendered input. Results are observations, not targets. Preserve Unicode, argument
values/types and ordering; native serialization implements the semantic action.

Ordinary n-call trajectories emit n calls plus finish; empty gold emits finish.
Successful waiting clarification emits its call and stops without finish.
Later gold after terminal waiting is an audit failure, not silently discarded.

## ExportManifest and AuditEntry

Manifest: code/config/source/base/tokenizer/template hashes; source accounting;
row/tool/finish/clarification counts; token lengths; limits; overlap/grouping checks;
audit counts and readiness. Audit entry: source/index, reason and resolution status.
States: `unvalidated -> audited -> ready`, or `blocked`. Every source has rows or
an audit entry. Unresolved training exclusions block full-dataset readiness.

## TokenizedExample

Input IDs, attention mask, labels, target span, terminal IDs and lengths. Labels
are -100 outside the final completion and at padding positions. Terminal tokens
retain loss even if pad shares their ID; at least one target token is required.
Verify boundaries with the real template/tokenizer instead of substring matching.
Rendered prompt plus reserved output must fit the configured competition cap.

## TrainingRun, Checkpoint and SelectionRecord

Run identity includes data/base/config digests, software lock, hardware, seeds,
batch factors, actual coverage/epochs and diagnostics. Checkpoints include adapter,
optimizer, scheduler, RNG and deterministic sampler progress, staged then atomically
committed. Persist the unique row/source coverage tracker with sampler state so
resume cannot reset or overstate checkpoint eligibility. Explicit resume requires
matching complete identities.

Selection records candidate update/digest, token-weighted validation NLL, finite
status, unique row/source coverage counts and expected totals, eligibility and tie
rule. Only 100%-covered candidates are eligible; no eligible finite candidate is
an explicit selection failure. Validation runs no-grad/eval and restores training mode;
it does not alter training sampler or optimizer progress.

## PlannerExport and Assessment

Export identity includes original base/adapter digests, dtype, model/tokenizer/
template/config hashes, parameter count, software and reload/protocol results.
States: `selected -> merged -> reload_verified -> assessed`, with explicit failures.

Assessment records fixed validation IDs, transcript/audio mode, runtime/scorer,
executed calls/hash, available metrics, categories/failures/timeouts, complete sample
timing and GPU/CPU/RAM. Missing gold hashes are unavailable, never inferred from
`label.final_state`. Teacher-forced diagnostics and competition evidence stay separate.
