"""public_transit: one method per tool of the app.

State: {card_balance, routes: [{id, name, type, stops: [..], fare, duration_min, headway_min}],
        departures: [{stop, route, time}], topups: []}.
find_routes is deterministic: routes from state whose stop list contains both places (in order); when none match, a
route is derived from a hash of the two (folded) place names so the same question always gets the same answer."""
from __future__ import annotations

import hashlib

from .base import App, read, write
from ..utils import _fold


def _hit(q, s):
    q, s = _fold(q) or "", _fold(s) or ""
    return bool(q) and (q in s or s in q)


def _stop_index(stops, place, aliases=None):
    """Index of the stop matching `place`; route-level aliases ({"nhà": "Láng Hạ", "25 Láng Hạ...": "Láng Hạ"}) are tried first."""
    for alias, stop in (aliases or {}).items():
        if _hit(place, alias):
            place = stop
            break
    return next((i for i, s in enumerate(stops) if _hit(place, s)), None)


class PublicTransit(App):
    name = "public_transit"

    @read
    def find_routes(self, origin=None, destination=None, **_):
        out = []
        for r in self.state.get("routes", []):
            stops = r.get("stops", [])
            a, b = _stop_index(stops, origin, r.get("aliases")), _stop_index(stops, destination, r.get("aliases"))
            if a is not None and b is not None and a != b:
                n = abs(b - a)
                per = max(1, round(r.get("duration_min", 30) / max(1, len(stops) - 1)))
                out.append({"route_id": r["id"], "name": r.get("name"), "type": r.get("type", "bus"), "board_at": stops[a], "alight_at": stops[b],
                            "stops_count": n, "duration_min": per * n, "fare": r.get("fare", 7000), "headway_min": r.get("headway_min")})
        if not out:  # deterministic fallback: a pure function of the two place names
            h = int(hashlib.sha256(f"{_fold(origin)}|{_fold(destination)}".encode()).hexdigest(), 16)
            num = 1 + h % 150
            out.append({"route_id": f"bus_{num:02d}", "name": f"Tuyến {num}", "type": "bus", "board_at": origin, "alight_at": destination,
                        "stops_count": 4 + h % 12, "duration_min": 20 + (h >> 8) % 41, "fare": 7000 if (h >> 16) % 3 else 10000,
                        "headway_min": (10, 15, 20)[(h >> 20) % 3]})
        return {"ok": True, "routes": out}

    @read
    def next_departures(self, stop=None, route=None, **_):
        names = {r["id"]: r.get("name") for r in self.state.get("routes", [])}
        out = []
        for d in self.state.get("departures", []):
            if not _hit(stop, d.get("stop")):
                continue
            if route and not (_hit(route, d.get("route")) or _hit(route, names.get(d.get("route"), ""))):
                continue
            out.append({**d, "route_name": names.get(d.get("route"))})
        out.sort(key=lambda d: str(d.get("time")))
        return {"ok": True, "departures": out}

    @write
    def topup_card(self, amount=None, **_):
        self.state["card_balance"] = (self.state.get("card_balance") or 0) + amount
        t = self.create("topups", "top", amount=amount, status="done")
        return {"ok": True, "topup": t["item"], "card_balance": self.state["card_balance"]}
