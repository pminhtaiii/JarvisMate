# Baseline implementation handoff

**Initial delivery**: 2026-10-27. **Ledger clarification**: 2026-10-28.
**Delivery branch**: `baseline`. **Review**: [Draft PR #5](https://github.com/pminhtaiii/JarvisMate/pull/5).
**Evidence level**: source authored and statically inspected only.

The user requested implementation followed by a branch push, with execution deferred
to another teammate. No Python install/build/import, unit test, supplied-runtime smoke,
ASR/LLM inference, model download, training, or benchmark evaluation was performed.
There is no model-accuracy, runtime, reproducibility or acceptance-pass claim.

## Authored coverage

| Tasks | Delivered source | Remaining acceptance |
|---|---|---|
| T001-T002 | Installable `python/` package, CLI entry, contracts/protocols/failure codes | Install/build/import and behavioral checks on receiving host |
| T003-T008 | Dataset/runtime/artifact implementations and their focused tests | Execute tests; inspect I/O, catalog, path and label-isolation checks |
| T009-T016 | Structured prompt/ReAct, local Qwen adapter, CLI, controlled tests, opt-in real-runtime test | All tests unrun; real package/model compatibility unverified |
| T017 | Commands and evidence requirements in Python README | Real pretrained transcript runs on one then four IDs |
| T018-T020 | Sequential model reuse, fail-fast batch, durable partial/final artifacts and tests | Execute success/failure/storage/publication cases |
| T021 | Preflight/smoke entry points and layout instructions | Receiving host validates actual paths and runs supplied-runtime smoke; no alias/data changes made here |
| T022-T024 | WAV/history preparation, local Whisper/PhoWhisper adapter and tests | Execute controlled and real-adapter checks |
| T025 | Same-ID transcript/audio comparison instructions | Run both ASR candidates separately with real snapshots |
| T026 | This handoff record and test suite | Run focused suite and available opt-in checks, recording actual outcomes |
| T027 | README/context/spec status updates | Final consistency and measured-evidence refresh after receiving-machine validation |

The [task ledger](tasks.md) now checks the 23 source/test-authoring/documentation
deliverables: T001-T016, T018-T020, T022-T024 and T027. This records implementation
delivery, not passing verification. T017, T021, T025 and T026 remain open because
they require execution. Package/foundation and controlled-integration checkpoints
are also unverified, explicitly listed as NOT RUN in the ledger and covered by T026.
Keep source delivery separate from acceptance evidence when reporting progress.

## Receiving-machine sequence

1. Check out `baseline`; use [python/README.md](../../python/README.md) for setup.
2. Install core package and run the standard-library controlled suite. Record command,
   Python/platform versions, exit status and failures before fixing anything.
3. Point `--data-root` at the actual complete split and run `check-data` for
   `train_1748`, then `train_1748` through `train_1751` in audio mode.
4. Explicitly enable the no-model supplied-runtime smoke. Confirm one environment,
   allowed read, authoritative call log/hash and terminal trace.
5. Provision local snapshots and pinned inference dependencies. Record publisher
   revision/weight hashes, GPU/driver, dtype and actual resolved package versions.
6. Run real planner transcript checkpoints, then audio with each ASR candidate in
   separate fresh directories. Keep 120-second development runs labeled accordingly;
   the default 30-second constraint still needs A30 evidence.
7. Inspect traces, exact prediction fields, failed/incomplete coverage and paired
   transcript/audio paths. Gold Train references belong only in separate evaluation.
8. Update this file and the remaining execution checkboxes only with observed evidence. Continue to
   frozen Train Validation/error analysis per the [roadmap](../../context/roadmap.md).

## Known limits requiring verification

- Inference extras are pinned candidates, not a tested environment lock. Their APIs,
  actual model snapshots, GPU behavior and resource use remain unverified here.
- Greedy/seed settings do not establish measured determinism across hardware.
- Deadline enforcement is cooperative; a blocked native/tool call needs an outer
  supervisor for hard termination. Final Docker and failed-sample submission handling
  are outside feature 001.
- Config/tokenizer hashes are recorded, but immutable weight identities must also be
  retained by the teammate provisioning snapshots.
- The four smoke IDs are not a held-out validation set or a full submission.
- No SFT exporter/trainer, model tuning, custom scoring implementation, TypeScript
  transport, network service or UI is included.

Static Git whitespace/diff inspection is separate from running the implementation.
No acceptance check should be inferred from the branch existing or a successful push.
