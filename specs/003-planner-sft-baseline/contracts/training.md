# Training CLI and artifact contract

**Status**: Implemented interface, exercised with controlled inputs and CPU doubles. The
NF4/GPU path has never run; see [recorded evidence](../quickstart.md#recorded-evidence).

## Configuration

`configs/planner-sft.example.toml` defines `[data]` train/validation/catalog paths
and role declarations; `[model]` local base path; `[training]` fixed recipe, seed,
microbatch and accumulation; `[limits]` total sequence/output budget; `[output]`
experiment directory. Reject unknown fields, missing inputs, aliased/overlapping
sets, test roles, incompatible base/template and batch product other than 16.
Record normalized config identity. Limit CLI overrides to paths, selected device,
microbatch/accumulation, output and explicit resume checkpoint.

Optional `data.audit_resolutions` names a reviewed JSON file. Each entry has `source_id`,
`reason`, `decision` (`exclude` or `keep`) and a nonempty `note`. Only `UNGROUNDED_ID`
and `SCHEMA_INVALID_TARGET` can be kept; a resolution matching no audit entry is rejected.

## Commands

```text
python -m lifemate.sft preflight --config <toml>
python -m lifemate.sft prepare --config <toml>
python -m lifemate.sft train --config <toml> [--resume <checkpoint>] [--smoke]
python -m lifemate.sft export --config <toml> --selection <selection.json>
python -m lifemate.sft diagnose --config <toml> --selection <selection.json>
```

Preflight checks configuration/data roles/snapshot/template/eligibility metadata.
Prepare reads only labeled JSONL and catalog; creates no ToolEnv and reads no
environment-directory data. Train requires ready exports and a compatible recorded
environment; performs actual NF4 BF16 backward/memory feasibility, then 500 updates.
A smoke-only mode must be explicit and isolated from the full-run identity.
Export loads the original fresh unquantized base and selected committed adapter.
Diagnose compares greedy adapter and merged outputs on eight fixed validation prompts (T020).

Train traverses all rows before repeats; reject insufficient 500*16 coverage budget.
Each checkpoint persists unique row/source coverage and expected totals. Evaluate
early checkpoints for diagnostics, but exclude them from selection/export until
all ready training rows and sources have contributed to optimizer updates. Reject
selection if no fully covered finite-NLL candidate exists; resume restores coverage.
Export verifies eligibility against the matching manifest/checkpoint rather than
trusting an unchecked selection-file assertion.
Validation uses all valid supplied rows without gradients, augmentation or prompt
example reuse. No split, row sampling or automatic recipe fallback is introduced.

Normalize training loss over all supervised tokens in the complete 16-example
accumulation window. Changing microbatch factorization must preserve that objective;
test 1x16 versus 4x4 gradients with unequal target lengths and dropout disabled.

Exit zero means that stage completed. Invalid config/data, unresolved exclusions,
identity mismatch, incompatible kernels, OOM, nonfinite diagnostics, incomplete
checkpoint and export failure yield nonzero plus bounded stage/reason evidence.

## Artifacts

```text
<experiment>/
  effective_config.json
  environment.json
  sft/train.jsonl
  sft/validation.next_action.jsonl
  sft/export_manifest.json
  sft/audit.jsonl
  checkpoints/step-0100/ ... step-0500/
  smoke/                       # isolated; only with --smoke
  training_metrics.jsonl
  selection.json
  adapter/
  merged_fp16/
  export_manifest.json
  export_diagnostics.json
  assessment/
```

Save resolved package/CUDA/driver/GPU/revision identities and sufficient resume
state. Data-derived artifacts/weights/traces remain ignored. Routine logs contain
bounded metadata; explicit debug traces follow existing testing guidance.
