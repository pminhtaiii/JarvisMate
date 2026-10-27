"""Schema validation of a tool call against the catalog — the only reason a call is rejected ({"ok": false}).

A call is a schema error when: the tool name is not in the catalog (or not installed in the sample), a `required`
parameter is missing (None, "", [], {} count as missing — an empty optional value is simply ignored), a value has the wrong `type`, is outside its `enum`, violates
`minimum` / `maximum` / `exclusiveMinimum` / `exclusiveMaximum`, does not match its `format` (date, date-time, time),
an array item has the wrong `items.type` / `items.enum`, or no group of `x-one-of` (parameters level) is fully present.
Everything else — an ID that does not exist, an empty search, not enough balance — is NOT an error: the tool runs,
changes nothing and returns {"ok": true, "done": false, "message": ...} (or an empty list for a read).

Participants can validate before executing, with the same function the executor and the scorer use:

    from zaic_tools import schema_validate, ToolEnv
    env = ToolEnv("public_test", "public_0008")
    env.validate("sms.send", {"content": "hi"})          # -> {"ok": False, "error": "..."} (uses the session's catalog + installed apps)
    schema_validate(calls, catalog)                      # -> one {"ok", "error", "name"} per call; catalog = the split's *_tools_catalog.json
"""
from __future__ import annotations

import math
import re
from datetime import date

EMPTY = (None, "", [], {})
# formats by regex (not datetime.fromisoformat, whose accepted inputs differ between Python 3.10 and 3.11)
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATETIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def catalog_tools(catalog) -> dict:
    """{name: tool} from a catalog file dict ({"tools": [...]} or {"apps": [{"tools": [...]}]}), a list of tools, or an already-keyed dict."""
    if catalog is None:
        return {}
    if isinstance(catalog, list):
        return {t["name"]: t for t in catalog}
    if "tools" in catalog:
        return {t["name"]: t for t in catalog["tools"]}
    if "apps" in catalog:
        return {t["name"]: t for a in catalog["apps"] for t in a.get("tools", [])}
    return catalog  # already {name: tool}


def is_type(v, t: str | None) -> bool:
    return {"string": lambda x: isinstance(x, str), "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
            "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool), "boolean": lambda x: isinstance(x, bool),
            "array": lambda x: isinstance(x, list), "object": lambda x: isinstance(x, dict)}.get(t, lambda x: True)(v)


def format_ok(v, fmt: str) -> bool:
    if not isinstance(v, str):
        return False
    if fmt == "date":
        m = _DATE.match(v)
    elif fmt == "date-time":  # ISO-8601 'YYYY-MM-DDTHH:MM[:SS[.fff]][offset]'; the offset is optional
        m = _DATETIME.match(v)
    elif fmt == "time":
        return bool(_TIME.match(v)) and int(v.split(":")[0]) < 24 and int(v.split(":")[1]) < 60
    else:
        return True
    if not m:
        return False
    try:
        date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return False
    if fmt == "date-time":
        hh, mm = v[11:13], v[14:16]
        return int(hh) < 24 and int(mm) < 60
    return True


def _value_error(k: str, v, p: dict) -> str | None:
    t = p.get("type")
    if not is_type(v, t):
        return f"{k} phải là {t}"
    if p.get("enum") and not any(x == v and isinstance(x, bool) == isinstance(v, bool) for x in p["enum"]):
        return f"{k} phải là một trong {p['enum']}"
    if t in ("integer", "number"):
        if isinstance(v, float) and not math.isfinite(v):
            return f"{k} phải là số hữu hạn"
        if "minimum" in p and v < p["minimum"]:
            return f"{k} phải >= {p['minimum']}"
        if "exclusiveMinimum" in p and v <= p["exclusiveMinimum"]:
            return f"{k} phải > {p['exclusiveMinimum']}"
        if "maximum" in p and v > p["maximum"]:
            return f"{k} phải <= {p['maximum']}"
        if "exclusiveMaximum" in p and v >= p["exclusiveMaximum"]:
            return f"{k} phải < {p['exclusiveMaximum']}"
    if p.get("format") and not format_ok(v, p["format"]):
        return f"{k} phải có dạng {p['format']}" + {"date": " (YYYY-MM-DD)", "date-time": " (ISO-8601, ví dụ 2026-11-16T17:00:00+07:00)", "time": " (HH:MM)"}.get(p["format"], "")
    if t == "array" and isinstance(p.get("items"), dict):
        it = p["items"]
        for x in v:
            e = _value_error(f"{k}[]", x, it)
            if e:
                return e
    return None


def schema_error(name: str, arguments: dict | None, catalog, allowed=None) -> str | None:
    """None when the call is schema-valid, else the error message (Vietnamese, the executor's {"error": ...}).
    catalog: see catalog_tools. allowed: the tool names installed in the sample (None = every catalog tool)."""
    tools = catalog_tools(catalog)
    args = arguments if isinstance(arguments, dict) else {}
    if not isinstance(name, str) or (tools and name not in tools):
        return f"tool '{name}' không có trong catalog"
    if allowed is not None and name not in allowed:
        return f"tool '{name}' không thuộc app đã cài"
    spec = (tools.get(name) or {}).get("parameters") or {}
    props = spec.get("properties") or {}
    missing = [k for k in spec.get("required", []) if args.get(k) in EMPTY]
    if missing:
        return "thiếu tham số bắt buộc: " + ", ".join(missing)
    groups = spec.get("x-one-of") or []
    if groups and not any(all(args.get(k) not in EMPTY for k in g) for g in groups):
        return "cần một trong: " + " / ".join(" + ".join(g) for g in groups)
    bad = [e for k, p in props.items() if args.get(k) not in EMPTY for e in [_value_error(k, args[k], p)] if e]  # an empty value = not given
    if bad:
        return "sai tham số: " + "; ".join(bad)
    return None


def schema_validate(calls, catalog, allowed=None) -> list[dict]:
    """Validate one call ({"name", "arguments"}) or a list of them; returns [{"name", "ok", "error"}] in order."""
    if isinstance(calls, dict):
        calls = [calls]
    out = []
    for c in calls:
        name = c.get("name") if isinstance(c, dict) else None
        err = schema_error(name, (c.get("arguments") if isinstance(c, dict) else None) or {}, catalog, allowed)
        out.append({"name": name, "ok": err is None, "error": err})
    return out
