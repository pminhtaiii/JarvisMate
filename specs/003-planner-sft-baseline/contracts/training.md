# Training CLI and artifact contract

**Status**: Implemented interface, exercised with controlled inputs and CPU doubles. The
NF4/GPU path has never run; see [recorded evidence](../quickstart.md#recorded-evidence).

## Configuration

`configs/planner-sft.example.toml` defines `[data]` train/validation/catalog paths,
role declarations and `validation_mode`; `[model]` local base path; `[training]` fixed
recipe, seed, microbatch and accumulation; `[limits]` total sequence/output budget;
`[output]` experiment directory. Reject unknown fields, missing inputs, aliased/overlapping
sets, test roles, incompatible base/template and batch product other than 16.
Record normalized config identity. Limit CLI overrides to paths, selected device,
microbatch/accumulation, output and explicit resume checkpoint.

Optional `data.audit_resolutions` names a reviewed JSON file. Each entry has `source_id`,
`reason`, `decision` (`exclude` or `keep`) and a nonempty `note`. Only `UNGROUNDED_ID`
and `SCHEMA_INVALID_TARGET` can be kept; a resolution matching no audit entry is rejected.
Validation mode never changes this: an unresolved training source blocks `prepare` in both
modes. Supplied Train v3.2.0 has one such source, `train_1696` (`UNGROUNDED_ID`), which
needs a reviewed `exclude` or `keep` before any run.

## Validation modes

`data.validation_mode` is run-defining. It has no CLI override and is part of the config
identity, so artifacts from one mode are rejected by the other.

| | `separate` (default when the key is absent) | `none` |
|---|---|---|
| Data keys | `validation_jsonl`, `validation_catalog`, `validation_role` required | Those three keys rejected; `--validation-*` overrides rejected |
| Fitted rows | All approved Train sources | All approved Train sources; nothing split off |
| Overlap audit | Train/validation IDs, inputs, conversations, groups | `not_applicable`: Train is the only role |
| Checkpoints | Updates 100, 200, 300, 400, 500 | Updates 100, 200, 300, 400, 500 |
| Per-checkpoint metric | Token-weighted validation NLL | None: `validation_nll` and `finite` are `null` |
| Selection `mode` | `lowest_validation_nll` | `final_update` |
| Selection rule | Lowest finite NLL among fully covered checkpoints; earlier update on exact tie | Update 500, only once its checkpoint is committed, digest-verified and fully covered |
| `diagnose` | Eight fixed validation prompts | Refused with `SFT_DIAGNOSTICS`; Train prompts are never substituted |

Mode `none` keeps every hyperparameter. Its recorded recipe is `RECIPE` plus
`"validation": "none"` and the final-update `selection` text. Mode `separate` records
`RECIPE` unchanged, so its config identity matches identities from before the key existed.
Selection records without `mode` were written before modes existed and count as
`lowest_validation_nll`.

Test data stays excluded in both modes. Paths with a `public_test` or `private_test`
component or file name, and environment directories, are rejected at configuration. Rows
with `public`/`private` IDs or without a transcript and label are rejected when read.

## Commands

```text
python -m lifemate.sft preflight --config <toml>
python -m lifemate.sft prepare --config <toml>
python -m lifemate.sft train --config <toml> [--resume <checkpoint>] [--smoke]
python -m lifemate.sft export --config <toml> --selection <selection.json>
python -m lifemate.sft diagnose --config <toml> --selection <selection.json>   # separate mode only
```

Preflight checks configuration/data roles/snapshot/template/eligibility metadata.
Prepare reads only labeled JSONL and catalog; creates no ToolEnv and reads no
environment-directory data. Train requires ready exports and a compatible recorded
environment; performs actual NF4 BF16 backward/memory feasibility, then 500 updates.
A smoke-only mode must be explicit and isolated from the full-run identity. In mode
`none` smoke runs the same 2 NF4 updates, gradient and frozen-base checks without
validation data, and records `validation_limit: null` in its plan identity.
Export loads the original fresh unquantized base and selected committed adapter.
Diagnose compares greedy adapter and merged outputs on eight fixed validation prompts (T020).

Train traverses all rows before repeats; reject insufficient 500*16 coverage budget.
Each checkpoint persists unique row/source coverage and expected totals. In mode
`separate`, evaluate early checkpoints for diagnostics, but exclude them from
selection/export until all ready training rows and sources have contributed to
optimizer updates. Reject selection if no fully covered finite-NLL candidate exists. In
mode `none`, reject selection when the update-500 checkpoint is missing (training stopped
earlier) or lacks full coverage; earlier checkpoints are listed but never eligible.
Resume restores coverage. Export verifies eligibility and selection mode against the
matching manifest/checkpoints rather than trusting an unchecked selection-file assertion.
In mode `separate`, validation uses all valid supplied rows without gradients,
augmentation or prompt example reuse. No split, row sampling or automatic recipe or
mode fallback is introduced.

A run interrupted after committing step 500 but before writing `selection.json` resumes
from `--resume <experiment>/checkpoints/step-0500`. No update runs, and the committed
checkpoint is verified and selected without being rewritten.

Normalize training loss over all supervised tokens in the complete 16-example
accumulation window. Changing microbatch factorization must preserve that objective;
test 1x16 versus 4x4 gradients with unequal target lengths and dropout disabled.

Exit zero means that stage completed. Invalid config/data, unresolved exclusions,
identity mismatch, incompatible kernels, OOM, nonfinite diagnostics, incomplete
checkpoint and export failure yield nonzero plus bounded stage/reason evidence.

## Artifacts

```text
<experiment>/
  effective_config.json          # data.validation_mode, data.selection_mode, recipe
  environment.json
  sft/train.jsonl
  sft/validation.next_action.jsonl   # separate mode only
  sft/export_manifest.json       # validation_mode, selection_mode
  sft/audit.jsonl
  checkpoints/step-0100/ ... step-0500/
  smoke/                       # isolated; only with --smoke
  training_metrics.jsonl
  selection.json                 # mode, rule, candidates, selected_update, adapter_sha256
  adapter/
  merged_fp16/
  export_manifest.json           # validation_mode, selection_mode; validation_nll only if separate
  export_diagnostics.json        # separate mode only
  assessment/
```

Save resolved package/CUDA/driver/GPU/revision identities and sufficient resume
state. Data-derived artifacts/weights/traces remain ignored. Routine logs contain
bounded metadata; explicit debug traces follow existing testing guidance.
