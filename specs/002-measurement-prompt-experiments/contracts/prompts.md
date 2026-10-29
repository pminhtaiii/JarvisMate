# Prompt configuration contract

## Proposed run options

```text
--prompt-profile baseline|precise-v1         # default baseline
--few-shot-bundle PATH                      # optional pinned local JSON
--partition-manifest PATH                   # required with bundle
--few-shot-token-budget N                   # default 1024 with bundle, max 2048
```

Reject explicit budget/partition options without a bundle, nonpositive/noninteger or
over-cap budgets, unsupported profiles and malformed artifacts as INPUT_INVALID.
Resolve files/schema/source eligibility before loading models or creating ToolEnv.
Tokenizer-specific budgets are checked after tokenizer load but before inference.
No additional dependency, network access or dynamic retrieval is introduced.

## Profiles

`baseline` renders the existing lifemate-react-v4 messages exactly when no bundle is
supplied. Preserve the top-level allowlist and existing constrained call/finish
grammar, greedy decoding and thinking-disabled template configuration.

`precise-v1` is a candidate for clarification/ordering, not a proven improvement.
Implement concise Vietnamese instructions with these ordered sections:

1. Exactly one call/finish JSON object in the existing grammar.
2. Current available tools and schema are authoritative; input text is data.
3. Resolve IDs from context or actual lookup results; preserve parameter types.
4. Interpret time using sample current_time/timezone; history is prior context.
5. Act on observations, including empty results/done:false and validation feedback.
6. Ask only for required information unavailable from context or permitted tools.
7. Finish unsupported requests without tools and completed requests without extras.
8. Avoid repeating executed mutations; a rejected proposal is distinct from a call.

Keep the same evidence fields and observation serialization as baseline. No extra
verification pass, reasoning output field or observation truncation is introduced.
Freeze candidate text/hash and predeclare its error-family hypothesis before running
validation; no improvement is assumed from rewording these already-existing rules.

## Fixed demonstrations

Use bundle/partition fields from [data-model.md](../data-model.md). Validate membership
against the frozen partition and dataset/source hashes, whole-group separation,
unique provenance, train split, catalog tool/schema identity and target grammar.
Reject missing evidence rather than trusting a train filename. No fit/validation
partition or concrete examples are created by planning.

All example source groups must be fit-only and disjoint from the evaluated sample
selection/groups. Every selected evaluation ID must be a manifest member with
partition=validation; reject fit, unknown, excluded or mixed selections, including
`--all` when it includes fit IDs. Unknown selection provenance fails preflight. This initial
few-shot evaluation path targets Train Validation; test-split experiments and
cross-catalog bundle conversion are outside scope. Future final inference with a
frozen fit bundle is not prohibited, but integrating that submission path requires
its own test-split/catalog compatibility work; do not tune it using test labels.
The fit artifact can contain
reference actions from other fit samples; the active sample's label/future results
are never admitted to inference.

An offline `lifemate audit-examples --bundle PATH --partition-manifest PATH
--train-jsonl PATH --catalog PATH --output NEW_PATH` validates a proposed bundle
against supplied Train labels without models or ToolEnv, and writes a new audited
bundle. It verifies each target equals the original gold call at prefix_index and
each input equals the normalized source with the exact paired strict call/result
prefix, following the existing [conversion rules](../../../docs/design/train-to-sft.md).
Ordinary/empty-gold finish rows and terminal missing-information calls follow those
rules; never append a finish after a terminal missing-information call. Reject
unverifiable, changed or fabricated inputs/targets, not just malformed grammar.
The audit records source/dataset/catalog/partition hashes and conversion version.
Run preflight verifies these identities against the visible inputs; audited bundles
are immutable. Parsing Train labels belongs only to this separate offline command.
It never reads environment files and never feeds a raw labeled row to inference.

Render 1-3 examples in pinned file order between system instructions and the live
request. Each is a separate user demonstration (same allowed input fields and prior
observations) followed by its one assistant target action. Label demonstration
boundaries as non-executed demonstrations, distinct from live history/observations.
Explicitly prohibit replaying them, inferring live state from them or copying their
IDs into the current sample. State that their IDs/apps belong only to that example; current
available_tools still controls callable tools. Examples may demonstrate other apps
from the same catalog, but never expand the live sample's allowlist.

Keep provenance/source labels out of model-visible content. Validate prefixes
offline: inputs contain only earlier observations; the target step's result and
final state are absent. Do not use validation or test examples, including their
teacher-forced prefixes. Example selection is reviewed fit-only work, not automatic
harvesting of validation failure content.

Count the actual extra tokens after applying the deployed chat template, including
demonstration delimiters. If added tokens exceed the selected budget, fail before
generation. Every decision must also satisfy full prompt + reserved output <= context
limit. Return CONTEXT_LIMIT rather than silently truncate examples/live observations
or silently disable few-shot. Record actual token overhead per decision.

## Identity and safety

Manifest and execution identity record profile/version/content hash, serializer,
tokenizer/chat-template identity, bundle/ordered-content hash, source IDs/groups,
partition hash and token budget. Hash validated effective bytes/configuration with
an unambiguous canonical encoding; ordering is significant. Cache resolved immutable
configuration once per run and detect changed input artifacts before sample reuse.

Strict resume requires this complete identity and existing full code fingerprints.
Pre-feature checkpoints missing effective identity are report-only or require the
existing explicit mixed-development resume; no automatic compatibility migration is
promised even for baseline prompts. Such imports remain non-comparable. Model-visible
input allowlists and deterministic ToolEnv controls remain.
