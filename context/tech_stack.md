# LifeMate technology stack

This page records accepted technology directions and open choices. The
[Python baseline](../python/README.md) and controlled/opt-in tests are authored;
no installation, test run, real inference, score or timing has been measured here.
The author defers execution to the receiving teammate. See the
[handoff](../specs/001-python-sample-pipeline/validation.md), [architecture](architecture.md)
and [benchmark rules](benchmark.md).

## Accepted directions

- Use Python for model inference.
- Compare multilingual Whisper-small with VinAI PhoWhisper-small for offline ASR. Replace the original Wispr Flow proposal because its internet-dependent transcription does not fit final offline inference. The winning ASR model and inference runtime remain open.
- Use Qwen3-4B-Instruct-2507 as the first planner experiment, with context capped at 16,384 tokens. This is a candidate, not a measured winner or final commitment.
- Use structured ReAct for the first runnable baseline, with deterministic validation and execution between planner decisions. Prioritize runnable output before latency optimization; performance remains unmeasured and the competition deadline still applies. See [architecture](architecture.md) and [ADR 007](../docs/adr/007-react-first-runnable-baseline.md), which supersedes ADR 006.
- Follow the [roadmap](roadmap.md): pretrained baseline, evaluation on a frozen grouped Train fit/validation partition, error analysis, then fine-tuning only if justified. Compare supplied-transcript and ASR paths to separate planner from speech errors. The conditional [planner SFT design](../docs/design/train-to-sft.md) uses gold call/result prefixes to supervise the next action with target-only loss; validation records never enter fitting. Training method, hyperparameters, dependency choices, and the decision to train remain gated by measured errors and compute. See [ADR 005](../docs/adr/005-measure-baseline-before-fine-tuning.md).
- Use a teammate's RTX 5070 machine as a shared private development inference server, with separate training windows. GPU variant, VRAM, availability, and access setup remain unverified. The final pipeline must still execute inside the offline submission container.

## Accepted hybrid boundary

Use TypeScript for the outer harness: dataset scheduling, configuration, reporting, and development-facing access. Use Prettier for formatting and Vitest for TypeScript tests. Prettier and Vitest are not currently installed in the root package.

Delegate one complete sample to Python. Python owns ASR, the planning loop, tool execution through the supplied `zaic_tools` API, and collection of the authoritative attempted-call log and final state hash from that sample's single `ToolEnv`. Individual tool calls do not cross the TypeScript/Python boundary. Keep models loaded in a persistent Python worker across samples, while creating exactly one isolated `ToolEnv` per sample. Use JSON Lines over stdin/stdout between the TypeScript harness and persistent Python worker, with logs on stderr. Responses identify the sample and explicitly distinguish success from failure. Detailed failure-result handling remains open. No performance advantage from the language split has been measured.

## Accepted execution and failure policy

A thin development HTTP service accepts teammates' requests and queues them into the harness. This external access layer is separate from the internal process protocol and is not required by the final offline runner.

Process one sample at a time per GPU worker initially; queue development requests. Record worker crashes and sample timeouts as failures, distinct from valid empty tool-call results, and do not automatically rerun the failed sample. The initial development batch stops at its first execution failure, preserving traces and completed results and exiting nonzero; restarting a worker does not automatically resume that batch. Report execution time separately from development queue wait; verify organizer timing requirements before submission. See [ADR 003](../docs/adr/003-sequential-execution-without-automatic-sample-retries.md) and [ADR 010](../docs/adr/010-stop-development-batch-on-execution-failure.md).

## Remaining failure details

- A lost response after a tool execution leaves the caller uncertain whether the action happened. A timeout does not establish that execution failed.
- Do not automatically repeat an uncertain tool call. Extra calls affect benchmark scoring and mutations can duplicate effects.
- The accepted whole-sample boundary avoids individual tool-call replies crossing runtimes. Decide whether recovery of a completed sample result while a worker survives is needed; worker death fails the current sample without automatic rerun. An in-memory response cache would not survive worker death or make execution and durable recording atomic.
- Do not assume a sample can be restarted with another `ToolEnv`; the supplied rules require exactly one per sample. Any recovery policy must respect that requirement and the sample deadline.

The Python source implements selected-batch fail-fast handling and partial artifacts,
pending tests. Late-response recovery, hard process supervision, final submission
failure policy and cross-process transport remain open; no measured execution or
recovery guarantee is claimed.

## Authored baseline dependencies

Python 3.11+ core/tests use the standard library. The optional inference extra pins
PyTorch 2.9.0, Transformers 4.57.1 and NumPy 2.3.4 as candidates to validate on the
receiving host. Local Qwen3 and Whisper/PhoWhisper adapters disable downloads/remote
code, reuse weights and configure deterministic generation. Pins and settings do not
establish compatibility, model eligibility, accuracy, reproducibility or A30 latency.
No new Node dependencies or training libraries are added.

## Decision rationale

- [ADR 001: Competition-first offline pipeline](../docs/adr/001-competition-first-offline-pipeline.md)
- [ADR 002: TypeScript harness and Python sample worker](../docs/adr/002-typescript-harness-python-sample-worker.md)
- [ADR 003: Sequential execution without automatic sample retries](../docs/adr/003-sequential-execution-without-automatic-sample-retries.md)
- [ADR 004: Shared development GPU and training windows](../docs/adr/004-share-development-gpu-with-separate-training-windows.md)
- [ADR 005: Measure a baseline before fine-tuning](../docs/adr/005-measure-baseline-before-fine-tuning.md)
- [ADR 006: Plan, execute, and selectively replan](../docs/adr/006-plan-execute-with-selective-replanning.md)
- [ADR 007: Structured ReAct for the first runnable baseline](../docs/adr/007-react-first-runnable-baseline.md) (supersedes ADR 006)
- [ADR 008: One general planner for the MVP](../docs/adr/008-single-general-planner-for-mvp.md)
- [ADR 009: Execution traces from the first baseline](../docs/adr/009-require-execution-traces-from-first-baseline.md)
- [ADR 010: Stop the development batch on execution failure](../docs/adr/010-stop-development-batch-on-execution-failure.md)
