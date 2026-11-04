# Server inference handoff

## Repository branch

- Repository: `pminhtaiii/JarvisMate`
- Branch: `test` (use the latest pushed branch head)
- Do not switch to `main` for this run.

## Prompt/model pairing

- ASR: selected PhoWhisper **E4** export.
- LLM: Qwen **L1** export.
- Use P1 **v1** with the existing L1 export. Its hash is recorded in
  `fine-tune-llm/prompts/manifest.json` and must match the L1 export contract.
- P1 **v2** is included as a separate reference version; it is not the runtime
  prompt for L1.

## Ordered file flow for a one-sample audio inference

1. `fine-tune-llm/configs/suite.json` — use as the configuration template; the
   server agent supplies server-local resource paths in an ignored local config.
2. `fine-tune-llm/prompts/README.md`, `manifest.json`, and
   `native-p1-vi-v1.txt` — confirm the L1 prompt identity before loading models.
3. `python/src/lifemate/cli.py` — run the application data/runtime check first,
   then the single-sample audio inference with E4 and Qwen L1. Do not select all
   samples for this smoke run.
4. Runtime modules used by that entrypoint: `python/src/lifemate/dataset.py`,
   `runtime.py`, `agent.py`, `prompting.py`,
   `adapters/asr.py`, and `adapters/planner.py`. These are dependencies, not
   separate commands to invoke.

## Ordered file flow for the strict LLM evaluation pipeline

Use this only when creating the selected-ASR handoff and the full ASR caches
required by the fine-tune evaluation workflow; it is unnecessary for a direct
one-sample smoke through `lifemate.cli`.

1. `fine-tune-llm/ASR_HANDOFF.md` — review the source-artifact prerequisites.
2. `python/src/lifemate/llm_training/asr_handoff.py` — preview/validate the
   original E4 provenance first. Its source plan expects the original E4 run and
   export evidence, not only a copied `best` directory. If those artifacts are
   absent, stop and locate them; do not invent handoff metadata.
3. The explicit ASR preparation through `asr_handoff.py` creates the handoff and
   Fit/Validation turn caches by running E4 inference. It does not train E4 or
   load/run Qwen.
4. `python/src/lifemate/llm_training/__main__.py` and `cli.py` — continue the
   model-free resource/suite checks and then the explicitly selected evaluation
   phases. Verify the actual Qwen L1 export before treating results as formal
   evaluation; the currently reported L1 export status is pending verification.
5. Underlying phase modules, invoked through the package entrypoint as needed:
   `inventory.py`, `corpus.py`, `tokenization.py`, `acceptance.py`,
   `export.py`, `evaluation.py`, and `pilot.py`.

## Scope notes

- `CHAY_TUNING_LLM.ps1` is the Windows wrapper; it is not the Ubuntu server
  entrypoint. Use the Python package entrypoints above.
- The direct application smoke and the strict fine-tune evaluation are distinct
  paths. A successful smoke does not create a certified E4 handoff, ASR caches,
  verified Qwen export, or full evaluation evidence.
- This handoff defines order and source files only. The server agent chooses the
  appropriate server-specific invocation and Slurm details.
