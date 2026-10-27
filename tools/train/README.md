# zaic_tools

Local tool execution library for ZAC 2026, with a separate version for each split. The organizers score submissions by replaying `tool_calls` on the initial `state.json` using this exact package, comparing the resulting state with the reference, and calculating call F1.

```python
import json, sys
sys.path.insert(0, "public_test")                  # run from the dataset root (containing public_test/)
from zaic_tools import ToolEnv

SPLIT = "public_test"


def infer(item):
    env = ToolEnv(SPLIT, item["id"], root=".")     # exactly one session per sample; loads its environment and catalog
    # ASR -> LLM -> env.call(tool, arguments) -> LLM -> ...
    # env.validate("sms.send", {"content": "hi"})          # schema check only -> {"ok": False, "error": "..."}
    # env.call("smart_home.get_status", {})                # -> {"ok": True, "devices": [...]}; updates state in memory
    # env.call("smart_home.light_set", {"device_id": "light_kitchen", "power": "off"})
    # env.call("sys.ask_missing_info", {"tool_name": "sms.send", "params": ["contact_id"]})   # always available; records the request only
    return env.get_tool_calls(), env.get_state_hash()   # all attempted calls (including rejected calls) and the final state hash


with open(f"{SPLIT}/{SPLIT}.jsonl", encoding="utf-8") as fin, open("submission.jsonl", "w", encoding="utf-8") as fout:
    for line in fin:
        item = json.loads(line)
        tool_calls, state_hash = infer(item)
        fout.write(json.dumps({"id": item["id"], "tool_calls": tool_calls, "state_hash": state_hash}, ensure_ascii=False) + "\n")
```

- `ToolEnv(split, question_id, root)`: `root` is the directory containing the split directories. The environment loads `<split>_environment/<id>/state.json` and the catalog.
- `env.validate(tool, args)` returns `{"ok", "error"}` without execution. `env.call(tool, args)` returns the tool result and updates state in memory. `env.get_tool_calls()` and `env.get_state_hash()` provide the two result fields of a submission row. `env.get_state()` returns the current state of all apps for debugging or comparison with a training sample's `label.final_state`.
- A call is rejected (`{"ok": false, "error": ...}`, with no state change) **only for a schema error**: a tool absent from the catalog or unavailable to the installed apps, missing `required` parameters, invalid `type`/`enum`/`minimum`/`maximum`/`format`/`items`, or no parameter group satisfying `x-one-of`. A nonexistent ID, insufficient balance, or an empty search is not a rejection: the tool runs without changing state and returns `{"ok": true, "done": false, "message": ...}` or an empty list.
- Information apps (weather, gold_price, fuel_price, etc.) are read-only; their data is excluded from the state comparison used for scoring.
- CLI usage, from the dataset root with `PYTHONPATH=public_test`: execute a tool with `python -m zaic_tools --split public_test --root . --id public_0001 --tool smart_home.get_status --args '{}'`; validate the schemas of an entire submission with `python -m zaic_tools --split public_test --root . --validate submission.jsonl`; list apps and tools with `--apps`.

## Structure

| File | Purpose |
|---|---|
| `apps/<app>.py` | One module per app and one method per tool (`smart_home.get_status` maps to `apps/smart_home.py`, `SmartHome.get_status`). `@read`/`@write` mark tool kinds. `apps/_*.py` contains shared helpers. |
| `apps/base.py` | The `App` base class provides shared `read`, `create`, `patch`, and `delete` operations on an app's state. |
| `executor.py` | `Session` validates schemas, dispatches methods, and records calls; `Executor` loads an entire split. |
| `validate.py` | `schema_error` / `schema_validate` define the rejection rules shared by the executor, `env.validate`, CLI, and scorer. |
| `utils.py` | `canon(state)` excludes `_meta`, information apps, and free-text fields; `state_hash(state)` is the SHA-256 hash of `canon`. |

A sample's `installed_apps` and split catalog determine which tools it may call. Do not modify the runtime package or `*_environment/`: the scoring server uses the originals. Requires Python 3.10+ and no third-party libraries.
