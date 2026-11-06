# Native runtime handoff

Target [feature 002's runtime](../../002-docker-integration/contracts/runtime.md).
Its canonical decision is one eligible call or finish; code owns all execution,
bounds and authoritative output. Training does not replace the executor.

## Serialization

The native adapter provides a shared pure renderer for whitelisted request/context/
history, eligible tool schemas, ordered actual call/result pairs and optional
supervised final decision. Use the pinned checkpoint's actual chat template.
Verify that training prompt prefixes equal inference prefixes for identical inputs.

The target is one native call or explicit native no-tool/finish with correct
terminal tokens. Resolve finish text and terminal IDs through actual tokenizer
tests, then pin their protocol identity before marking any export ready. Never
substitute legacy JSON action text accidentally. Reflection/rationale is not a target.

```text
ASR once per distinct clip -> next call -> execute in ToolEnv
                          -> actual call/result messages -> next action
```

Waiting clarification stops in deterministic code. Historical actions are not
replayed. Empty finish stays distinct from failure, truncation or timeout.

## Export verification

Merge into a fresh original unquantized base and save FP16 weights/tokenizer/
special tokens/chat template/model and generation config. Verify offline reload
without PEFT/bitsandbytes in the inference environment. Test call/finish/clarification/
dependent-call render and parse with the actual tokenizer. Compare fixed-prompt
outputs and available diagnostics against the selected adapter and record drift;
quantized training and FP16 export are not assumed bitwise equivalent.

## Assessment

Use fixed recorded validation IDs with predicted calls and actual results, one
split-matched ToolEnv per sample, its `get_tool_calls()` and `get_state_hash()`.
Gold prefixes never enter live inference. Use supplied scoring semantics where
available; unavailable reference hashes/aggregation rules remain explicit.

Use feature 002's supervisor for full preparation/ASR/LLM/tools/durable-output
timing, failure counts, p50/p95/max and timeouts. Accepted attempts must be strictly
<30s. 5090/H200 measurements do not establish A30 compliance. Offline Docker,
deterministic reruns and model/context limits remain external acceptance gates.
