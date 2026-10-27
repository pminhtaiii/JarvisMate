"""Shared helpers: text normalisation for searches, and the canonical state / state_hash the scorer compares."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata


def _norm(s):
    return " ".join(str(s).lower().split()) if s is not None else None


def _fold(s):
    """lower-case, Vietnamese diacritics removed (Hương, Hường, huong -> huong), spaces collapsed; used by free-text search"""
    if s is None:
        return None
    t = unicodedata.normalize("NFD", str(s).lower()).replace("đ", "d")
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def _tokens(s):
    """Set of word tokens of _fold(s): letters/digits only, so 'Hồ Tây' -> {'ho', 'tay'} and '7:00' -> {'7', '00'}."""
    return set(re.findall(r"[^\W_]+", _fold(s) or ""))


def _eq(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return _norm(a) == _norm(b)
    return a == b


# Information apps (their data is read-only and not part of the compared state)
LIVE_APPS = {"fuel_price", "gold_price", "weather"}
# free-text fields (the catalog's x-match: fuzzy parameters): dropped from the state before it is compared or hashed
FREE_TEXT_KEYS = {"address", "body", "content", "dropoff", "label", "location", "name", "note", "pickup", "subject", "text", "title"}  # place strings are spoken free text too (scored by fuzzy x-match)


_NUM_UNIT = re.compile(r"(\d)\s+(?=[^\W\d_])")  # '700 cm' -> '700cm', '2 kg' -> '2kg'


def _canon_scalar(v):
    """A scalar as compared: strings lower-cased, whitespace collapsed, no space between a number and a unit."""
    if isinstance(v, str):
        return _NUM_UNIT.sub(r"\1", " ".join(v.lower().split()))
    return v


def canon(state: dict) -> dict:
    """State as the scorer compares it: without _meta, live apps and free-text fields (those are scored on the call arguments).
    Strings are lower-cased with whitespace collapsed and '700 cm' == '700cm'; a list of scalars is compared as a set (sorted);
    lists of dicts keep their order; dict keys are unchanged."""
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k not in FREE_TEXT_KEYS}
        if isinstance(v, list):
            out = [strip(x) for x in v]
            if all(not isinstance(x, (dict, list)) for x in out):
                out = sorted(out, key=lambda x: (type(x).__name__, str(x)))
            return out
        return _canon_scalar(v)
    return {app: strip(st) for app, st in state.items() if app != "_meta" and app not in LIVE_APPS}


def state_hash(state: dict) -> str:
    """sha256 of canon(state) serialised as sorted, compact, ASCII JSON — the value submitted as state_hash."""
    return hashlib.sha256(json.dumps(canon(state), sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
