# State-reference investigation (LL023)

**Status:** investigation notes only. No reference replay was executed, authorized or
trusted; State Match and state-gated F1 stay `null` (`trusted_reference_unavailable`).

## Evidence in the organizer runtime (read-only)

- [tools/train/README.md](../tools/train/README.md): organizers score by replaying
  submitted `tool_calls` on the initial state with the same package and comparing the
  result with their reference state; `env.get_state()` is described for debugging or
  comparison with a Train sample's `label.final_state`.
- [tools/train/executor.py](../tools/train/executor.py): `Session.get_state` documents
  checking a Train sample by running `label.tool_calls` and comparing changed apps with
  `label.final_state`; `Executor.replay` replays calls from the initial state.

So the organizer documents a Train-gold replay as a *consistency check*. It does not
document a trusted full-state hash reference for evaluation, and `label.final_state`
is changed-app partial state, never a hash source.

## Conditions before any reference-only replay (RV023)

1. Separate explicitly invoked process with its own RuntimeFactory and exactly one
   ToolEnv per source; never inside a prediction run, never a second environment there.
2. Recorded dataset/catalog/runtime/canonicalization identities matching the
   evaluation profile, and the gold call list as the only input.
3. Replay/result consistency checks against `label.tool_results`, full 309-source
   coverage, and an explicit trust decision recorded with the evaluator identity.
4. No reading, copying or parsing of `*_environment/` files by pipeline code.

Until these exist and the replay is separately authorized, `metrics.closed_loop_metrics`
accepts only an explicit `trusted_state` mapping; partial mappings keep state metrics null.
