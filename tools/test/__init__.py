"""zaic_tools — local tool runtime for ZAC 2026. Submissions are scored by replaying them with this same package.

    from zaic_tools import ToolEnv
    env = ToolEnv("public_test", "public_0123")   # one independent session per sample, created once, loaded from <split>/<split>_environment/<id>/state.json
    env.validate("sms.send", {"content": "hi"})   # schema check only (same rule as the executor and the scorer), nothing executed
    env.call("smart_home.get_status", {})         # tool_result; state is updated in memory
    env.get_tool_calls(), env.get_state_hash()    # the submission line: {"id": ..., "tool_calls": env.get_tool_calls(), "state_hash": env.get_state_hash()}
"""
from __future__ import annotations

import json
from pathlib import Path

from .executor import Executor, Session, load_environment  # noqa: F401
from .utils import LIVE_APPS, FREE_TEXT_KEYS, canon, state_hash  # noqa: F401
from .validate import schema_error, schema_validate, catalog_tools  # noqa: F401
from .apps import APPS, TOOLS, App  # noqa: F401

_HERE = Path(__file__).resolve().parent
# default data root: <package>/../data when the package sits next to a data/ folder, else the folder holding the split folders
# (a released package lives at <root>/<split>/zaic_tools, so the root is two levels up)
DATA_ROOT = _HERE.parent / "data" if (_HERE.parent / "data").is_dir() else _HERE.parent.parent


def catalog_path(split: str, root: str | Path | None = None) -> Path:
    """<root>/<split>/<split>_tools_catalog.json"""
    root = Path(root) if root else DATA_ROOT
    p = root / f"{split}/{split}_tools_catalog.json"
    return p


def ToolEnv(split: str, question_id: str, root: str | Path | None = None) -> Session:
    """Session on the initial state of `question_id`, read from `<root>/<split>/<split>_environment/<question_id>/state.json`.
    `root` defaults to the data/ folder next to this package. Calling ToolEnv again gives a fresh session (reset)."""
    root = Path(root) if root else DATA_ROOT
    state_path = root / split / f"{split}_environment" / question_id / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"no state for {question_id!r}: {state_path}")
    cp = catalog_path(split, root)
    catalog = json.load(open(cp, encoding="utf-8")) if cp.is_file() else None
    return Session(question_id, json.load(open(state_path, encoding="utf-8")), catalog)


__all__ = ["ToolEnv", "schema_validate", "state_hash"]  # participant API; the other names stay importable for the scorer
