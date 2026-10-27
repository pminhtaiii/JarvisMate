# Competition tools

This directory contains the organizer's Vietnamese tool catalogs and split-specific Python simulators. Keep the supplied catalogs and simulator implementations authoritative for execution, validation, and replay. The package READMEs in `train/` and `test/` are translated into English.

- `train_tools_catalog.json`: 46 apps and 147 tools.
- `public_test_tools_catalog.json`: 36 apps and 122 tools.

Use the Vietnamese catalog descriptions for planner-facing tools. Preserve tool and app identifiers, parameter names, constraints, enum values, and references. Filter tools to those available in the current sample; do not automatically translate tool arguments or returned data.

## Execution environment

The supplied `train/` and `test/` directories contain Python simulator implementations for the training and public-test splits respectively. They are separate versions: do not assume identical tools or behavior across splits. Preserve the supplied code. The package README documents an expected `zaic_tools` import inside the complete split layout; the uploaded directory names alone do not establish that runnable layout.

Each sample runs in exactly one split-matched `ToolEnv`. The agent calls `env.validate(name, arguments)` to check schemas without execution and `env.call(name, arguments)` to execute. The environment records attempted calls, including rejected ones. Collect the submission from `env.get_tool_calls()` and `env.get_state_hash()`.

`ok: true` alone does not mean the requested action was completed: a tool may return `done: false` or an empty result. Inspect the full returned result. `sys.ask_missing_info` records the missing-information request and returns `waiting_for_user: true`; it does not supply a new user answer. Weather tools read simulated sample data rather than an external weather API.

A real benchmark run also requires input records, audio, and per-sample environments in the expected layout; the tool upload alone is insufficient. Some audio is now present under `sample/`, but a complete runnable split has not been verified. Access app data only through the official tool API, never by reading files in `<split>_environment/`. Catalog wording that mentions state does not authorize direct access to hidden state.
