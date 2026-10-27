"""maps: one method per tool of the app. State: {places: [{id, name, address, category}], saved_places: [{id, place_id, label}]}.
get_route is deterministic: distance from a hash of the normalised origin + destination, duration from the mode's speed."""
from __future__ import annotations

import hashlib

from ..utils import _fold, _tokens
from .base import App, read, write

_SPEED = {"car": 24, "motorbike": 28, "walk": 5, "transit": 16}  # km/h in city traffic
# purely administrative words carry no information about a place: after fold 'quán' == 'quận' == 'quan', and every HCMC
# address has 'Quận N' / 'Phường N', so these tokens never count as a hit (the number of a district still does)
_ADMIN = {"quan", "phuong", "q", "p", "tp", "huyen", "thanh", "pho"}


def _alias_hit(q, aliases):
    """q (folded) matches an alias list when it contains an alias or an alias contains it (e.g. 'nha' ~ '25 lang ha, dong da, ha noi')."""
    for a in aliases or []:
        a = _fold(a) or ""
        if a and (a in q or q in a):
            return True
    return False


class Maps(App):
    name = "maps"

    @read
    def search_place(self, query=None, near=None, **_):
        """Keyword search: a place matches when ANY query token (after fold) is a word of its name, category, detail or address;
        `near` matches when any of its tokens is a word of the address, detail or name (so 'Hồ Tây' finds 'Tây Hồ', and 'Nhà hát
        Lớn' finds a place whose detail says 'Cách Nhà hát Lớn 300 m'); administrative words (quận/phường/q/p/tp) are ignored on
        both sides and every number of `near` must appear in the address ('Quận 3' never matches a place in Quận 1). Results are
        ranked by the number of matching tokens (ties keep the state order). An empty / '*' query lists every place."""
        q_toks = _tokens(query) - {"*"} - _ADMIN
        n_toks = _tokens(near) - _ADMIN
        n_nums = {t for t in n_toks if t.isdigit()}
        ranked = []
        for i, p in enumerate(self.state.get("places", [])):
            words = set()
            for k in ("name", "category", "detail", "address"):
                words |= _tokens(p.get(k))
            q_hits = len(q_toks & words)
            if q_toks and not q_hits:
                continue
            addr = _tokens(p.get("address"))
            n_hits = len(n_toks & (addr | _tokens(p.get("detail")) | _tokens(p.get("name"))))
            if n_toks and (not n_hits or not n_nums <= addr):
                continue
            ranked.append((-(q_hits + n_hits), i, dict(p)))
        return {"ok": True, "places": [p for _, _, p in sorted(ranked, key=lambda t: t[:2])]}

    @read
    def get_route(self, origin=None, destination=None, mode=None, **_):
        o, d = _fold(origin) or "", _fold(destination) or ""
        if not o or not d:
            return self.noop("thiếu origin hoặc destination")
        if o == d:
            return self.noop("điểm đi và điểm đến trùng nhau")
        mode = mode if mode in _SPEED else "motorbike"
        for r in self.state.get("routes", []):  # pinned routes: {"from": [aliases], "to": [aliases], "distance_km", "duration_min": {mode: min} | int}
            if _alias_hit(o, r.get("from", [])) and _alias_hit(d, r.get("to", [])):
                dur = r.get("duration_min", {})
                minutes = dur.get(mode, dur.get("car")) if isinstance(dur, dict) else dur
                dist = r.get("distance_km")
                if minutes is None:
                    minutes = max(3, round((dist or 5) / _SPEED[mode] * 60))
                return {"ok": True, "route": {"origin": origin, "destination": destination, "mode": mode, "distance_km": dist, "duration_min": minutes}}
        h = int(hashlib.sha256(f"{o}|{d}".encode()).hexdigest(), 16)
        dist = round(1.5 + (h % 2350) / 100, 1)  # 1.5 .. 25.0 km
        minutes = max(3, round(dist / _SPEED[mode] * 60))
        return {"ok": True, "route": {"origin": origin, "destination": destination, "mode": mode, "distance_km": dist, "duration_min": minutes}}

    @write
    def save_place(self, place_id=None, label=None, **_):
        if self.find("places", place_id) is None:
            return self.noop(f"không tìm thấy place_id={place_id!r}")
        for it in self.state.setdefault("saved_places", []):  # saving again only relabels
            if it.get("place_id") == place_id:
                if label is not None:
                    it["label"] = label
                return {"ok": True, "id": it["id"], "item": it}
        return self.create("saved_places", "fav", place_id=place_id, label=label)
