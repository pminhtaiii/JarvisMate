# LifeMate technology stack

This page records accepted technology directions and open choices. No listed model, server, or benchmark pipeline has been implemented or measured by this design discussion. See [architecture](architecture.md) for capability and trust boundaries and [benchmark rules](benchmark.md) for submission constraints.

## Accepted directions

- Use Python for model inference.
- Compare multilingual Whisper-small with VinAI PhoWhisper-small for offline ASR. Replace the original Wispr Flow proposal because its internet-dependent transcription does not fit final offline inference. The winning ASR model and inference runtime remain open.
- Use Qwen3-4B-Instruct-2507 as the first planner experiment, with context capped at 16,384 tokens. This is a candidate, not a measured winner or final commitment.
- Use plan-then-execute with selective replanning as the baseline planning architecture; model decisions occur at unresolved dependencies or when observations invalidate remaining work. See [architecture](architecture.md) and [ADR 006](../docs/adr/006-plan-execute-with-selective-replanning.md). Performance remains unmeasured.
- First build and measure an end-to-end baseline with pretrained models; defer fine-tuning until baseline failures have been analyzed. Later tuning may use supplied training data, preserving an untouched validation subset and comparing with the same model before training. The target component, tuning method, and split design remain open. Compare planning on supplied training transcripts with planning on ASR transcripts to distinguish speech and planning errors. See [ADR 005](../docs/adr/005-measure-baseline-before-fine-tuning.md).
- Use a teammate's RTX 5070 machine as a shared private development inference server, with separate training windows. GPU variant, VRAM, availability, and access setup remain unverified. The final pipeline must still execute inside the offline submission container.

## Accepted hybrid boundary

Use TypeScript for the outer harness: dataset scheduling, configuration, reporting, and development-facing access. Use Prettier for formatting and Vitest for TypeScript tests. Prettier and Vitest are not currently installed in the root package.

Delegate one complete sample to Python. Python owns ASR, the planning loop, tool execution through the supplied `zaic_tools` API, and collection of the authoritative attempted-call log and final state hash from that sample's single `ToolEnv`. Individual tool calls do not cross the TypeScript/Python boundary. Keep models loaded in a persistent Python worker across samples, while creating exactly one isolated `ToolEnv` per sample. Use JSON Lines over stdin/stdout between the TypeScript harness and persistent Python worker, with logs on stderr. Responses identify the sample and explicitly distinguish success from failure. Detailed failure-result handling remains open. No performance advantage from the language split has been measured.

## Accepted execution and failure policy

A thin development HTTP service accepts teammates' requests and queues them into the harness. This external access layer is separate from the internal process protocol and is not required by the final offline runner.

Process one sample at a time per GPU worker initially; queue development requests. Record worker crashes and sample timeouts as failures, distinct from valid empty tool-call results, and do not automatically rerun the failed sample. Restarting a worker for subsequent samples is permitted. Report execution time separately from development queue wait; verify organizer timing requirements before submission. See [ADR 003](../docs/adr/003-sequential-execution-without-automatic-sample-retries.md).

## Remaining failure details

- A lost response after a tool execution leaves the caller uncertain whether the action happened. A timeout does not establish that execution failed.
- Do not automatically repeat an uncertain tool call. Extra calls affect benchmark scoring and mutations can duplicate effects.
- The accepted whole-sample boundary avoids individual tool-call replies crossing runtimes. Decide whether recovery of a completed sample result while a worker survives is needed; worker death fails the current sample without automatic rerun. An in-memory response cache would not survive worker death or make execution and durable recording atomic.
- Do not assume a sample can be restarted with another `ToolEnv`; the supplied rules require exactly one per sample. Any recovery policy must respect that requirement and the sample deadline.

Late-response handling, recovery of completed results, and final submission handling of failures remain open. No execution or recovery guarantees have been implemented.

## Decision rationale

- [ADR 001: Competition-first offline pipeline](../docs/adr/001-competition-first-offline-pipeline.md)
- [ADR 002: TypeScript harness and Python sample worker](../docs/adr/002-typescript-harness-python-sample-worker.md)
- [ADR 003: Sequential execution without automatic sample retries](../docs/adr/003-sequential-execution-without-automatic-sample-retries.md)
- [ADR 004: Shared development GPU and training windows](../docs/adr/004-share-development-gpu-with-separate-training-windows.md)
- [ADR 005: Measure a baseline before fine-tuning](../docs/adr/005-measure-baseline-before-fine-tuning.md)
- [ADR 006: Plan, execute, and selectively replan](../docs/adr/006-plan-execute-with-selective-replanning.md)
