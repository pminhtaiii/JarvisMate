"""Shared city matching for travel apps."""
from __future__ import annotations

from ..utils import _fold

_CITY_ALIASES = [{"ha noi", "hanoi", "hn"}, {"tp.hcm", "tp hcm", "tphcm", "hcm", "ho chi minh", "thanh pho ho chi minh", "sai gon", "saigon"},
                 {"da nang", "danang"}, {"nha trang"}, {"da lat", "dalat"}, {"hue", "thua thien hue"}, {"vung tau"}, {"phu quoc"}, {"hai phong"}, {"ha long"}]


def city_match(q, city):
    q, c = _fold(q) or "", _fold(city) or ""
    if not q:
        return True
    if q in c or c in q:
        return True
    return any(any(a in q for a in g) and any(a in c for a in g) for g in _CITY_ALIASES)
