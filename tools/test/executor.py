"""ZAC 2026 tool runtime (zaic_tools) — runs the tools of a sample on that sample's own data (<split>/<split>_environment/<id>/state.json).

    from zaic_tools import ToolEnv
    env = ToolEnv("public_test", "public_0008")   # loads public_test/public_test_environment/public_0008/state.json + the split's catalog; one per sample
    env.validate("smart_home.light_set", {"power": "off"})   # schema check only -> {"ok": false, "error": "..."}
    env.call("smart_home.get_status", {})         # {"ok": true, "devices": [...]}; state updated in memory
    env.call("smart_home.light_set", {"device_id": "light_kitchen", "power": "off"})
    env.get_tool_calls(), env.get_state_hash()    # every call made (also the rejected ones) and the state_hash: the two fields of the submission line
    env.get_state()                               # current state of every app (debug / train check)

Lower level: Executor(environment_dir, catalog_path).open(sample_id) -> Session (the object ToolEnv returns).
CLI:  python -m zaic_tools --split public_test --root . --id public_0008 --tool smart_home.get_status --args '{}'

A call is rejected ({"ok": false, "error": ...}, state unchanged) only on a schema error (zaic_tools.validate): the tool
is not in the catalog or not in the sample's installed_apps, a `required` parameter is missing, a value has the wrong
type / enum / range / format, or no `x-one-of` group is present. Anything else (an ID that does not exist, not enough
balance, an empty search) is not an error: the tool runs, changes nothing and returns {"ok": true, "done": false,
"message": ...} or an empty list. Every tool returns a JSON dict; nothing raises. Submissions are scored by replaying
them with this same package on the original state.json, so what you see here is what the scorer sees. Python 3.10+, stdlib only.
"""
from __future__ import annotations

import copy
from pathlib import Path
import json
from datetime import datetime

from .apps import APPS, TOOLS, App  # noqa: F401  (apps/<app>.py: one method per tool)
from .utils import LIVE_APPS, FREE_TEXT_KEYS, canon, state_hash, _eq, _fold, _norm  # noqa: F401
from .validate import catalog_tools, schema_error, is_type as _is_type  # noqa: F401




class Simulator:
    def __init__(self, sample: dict, catalog: dict | None = None):
        """The schema checks are the only rejection rule, so a simulator always needs the split's catalog."""
        apps = sample["context"]["installed_apps"]
        self.states = {app: copy.deepcopy(a.get("state", {})) for app, a in apps.items()}
        self.now = sample["context"].get("current_time")  # ISO string; apps read it as self.session.now
        self.allowed = {t for a in apps.values() for t in a.get("tools", [])} | {"sys.ask_missing_info"}
        self.apps = {app: APPS[app](self, st) for app, st in self.states.items() if app in APPS}
        self.apps["sys"] = APPS["sys"](self, {})  # system tools keep no state
        self.tools = catalog_tools(catalog)  # {name: tool spec}; empty when no catalog given (then only the name is checked)
        self.log: list[dict] = []

    # -- public ---------------------------------------------------------------------------
    def call(self, name: str, arguments: dict | None) -> dict:
        arguments = arguments or {}
        err = schema_error(name, arguments, self.tools, self.allowed)
        if err is None and name not in TOOLS:
            err = f"tool '{name}' chưa được simulator hỗ trợ"
        if err is not None:
            return self._fail(name, arguments, err)
        app, tool = name.split(".", 1)
        try:
            result = getattr(self.apps[app], tool)(**{k: v for k, v in arguments.items() if isinstance(k, str) and k.isidentifier()})
        except Exception as e:  # never raise into the agent loop; not a schema error, so the call stands and changes nothing
            result = {"ok": True, "done": False, "message": f"{type(e).__name__}: {e}"}
        result = copy.deepcopy(result)  # results must not alias live state (later writes would rewrite earlier read outputs)
        self.log.append({"name": name, "arguments": arguments, "result": result})
        return result

    def validate(self, name: str, arguments: dict | None = None) -> dict:
        """Schema check only, nothing executed: {"ok": True, "error": None} or {"ok": False, "error": "..."}."""
        err = schema_error(name, arguments or {}, self.tools, self.allowed)
        return {"ok": err is None, "error": err}

    @staticmethod
    def kind(name: str) -> str:
        return TOOLS.get(name, "write")

    def _fail(self, name, arguments, msg):
        r = {"ok": False, "error": msg}
        self.log.append({"name": name, "arguments": arguments, "result": r})
        return r


class Session(Simulator):
    """One sample's state plus the ordered list of calls made on it (self.calls, rejected calls included)."""

    def __init__(self, sample_id: str, entry: dict, catalog: dict | None):
        meta = entry["_meta"]
        apps = {}
        for t in meta.get("tools", []):
            apps.setdefault(t.split(".", 1)[0], {"tools": []})["tools"].append(t)
        for app, st in entry.items():
            if app != "_meta":
                apps.setdefault(app, {"tools": []})["state"] = st
        sample = {"id": sample_id, "context": {"current_time": meta["current_time"], "user_profile": {"city": meta.get("city")}, "installed_apps": apps}}
        super().__init__(sample, catalog)
        self.sample_id = sample_id
        self.calls: list[dict] = []

    def call(self, name: str, arguments: dict | None = None) -> dict:
        arguments = arguments or {}
        self.calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
        return super().call(name, arguments)

    def get_tool_calls(self) -> list[dict]:
        """Every call made in this session, in order, rejected calls included: the tool_calls field of the submission line."""
        return copy.deepcopy(self.calls)

    def get_state(self) -> dict:
        """Copy of the current state of every app (what get_state_hash() hashes after canon); for debugging and for checking a train
        sample: run label.tool_calls, then get_state()[app] == label.final_state[app] for every changed app."""
        return copy.deepcopy(self.states)

    def get_state_hash(self) -> str:
        """sha256 of the canonical current state (zaic_tools.state_hash): the state_hash field of the submission line."""
        return state_hash(self.states)


def load_environment(path) -> dict:
    """{sample_id: state}. `path` is an environment directory (<split>/<split>_environment/<id>/state.json) or one json file {id: state}."""
    p = Path(path)
    if p.is_dir():
        return {d.name: json.load(open(d / "state.json", encoding="utf-8")) for d in sorted(p.iterdir()) if (d / "state.json").is_file()}
    return json.load(open(p, encoding="utf-8"))


class Executor:
    """All samples of a split: Executor(environment_dir, catalog).open(sample_id) -> Session."""

    def __init__(self, env_path: str, catalog_path: str | None = None):
        self.db = load_environment(env_path)
        self.catalog = json.load(open(catalog_path, encoding="utf-8")) if catalog_path else None

    def ids(self) -> list[str]:
        return list(self.db)

    def open(self, sample_id: str) -> Session:
        if sample_id not in self.db:
            raise KeyError(f"unknown sample id {sample_id!r}")
        return Session(sample_id, copy.deepcopy(self.db[sample_id]), self.catalog)

    def replay(self, sample_id: str, tool_calls: list[dict]) -> tuple[list[dict], dict]:
        """Run a submission's tool_calls from the initial state. Returns (results, state of apps changed by a write)."""
        s = self.open(sample_id)
        before = copy.deepcopy(s.states)
        results = [s.call(c.get("name", ""), c.get("arguments") or {}) for c in tool_calls]
        changed = {app: st for app, st in s.states.items() if st != before.get(app)}
        return results, changed




