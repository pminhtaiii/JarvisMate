"""loyalty: one method per tool of the app.
State: {programs: [{id, name, merchant, points, tier, rewards: [{id, name, cost}]}], vouchers: [{id, merchant, name, value, expires, used}]}.
`program` is a program id or its name (case/diacritics-insensitive); `reward_id` is one of that program's rewards."""
from __future__ import annotations

from ..utils import _fold
from .base import App, read, write


class Loyalty(App):
    name = "loyalty"

    def _program(self, program):
        if not program:
            return None
        hit = self.find("programs", program)
        if hit is not None:
            return hit
        q = _fold(program)
        exact = [p for p in self.state.get("programs", []) if q in (_fold(p.get("name")), _fold(p.get("merchant")))]
        if len(exact) == 1:
            return exact[0]
        part = [p for p in self.state.get("programs", []) if q and (q in _fold(p.get("name") or "") or q in _fold(p.get("merchant") or ""))]
        return part[0] if len(part) == 1 else None

    @read
    def list_vouchers(self, merchant=None, **_):
        return self.read("vouchers", contains={("merchant", "name"): merchant})

    @read
    def get_points(self, program=None, **_):
        if program:
            p = self._program(program)
            if p is None:
                return self.empty("programs")
            return {"ok": True, "programs": [dict(p)]}
        return self.read("programs")

    @write
    def redeem(self, program=None, reward_id=None, **_):
        p = self._program(program)
        if p is None:
            return self.noop(f"không tìm thấy program={program!r}")
        rw = next((r for r in p.get("rewards", []) if r.get("id") == reward_id), None)
        if rw is None:
            return self.noop(f"không tìm thấy reward_id={reward_id!r}")
        cost = rw.get("cost") or 0
        if (p.get("points") or 0) < cost:
            return self.noop(f"không đủ điểm (có {p.get('points') or 0}, cần {cost})")
        p["points"] = (p.get("points") or 0) - cost
        r = self.create("vouchers", "vch", merchant=p.get("merchant") or p.get("name"), name=rw.get("name"), value=rw.get("value"),
                        program_id=p["id"], reward_id=rw["id"], used=False)
        return {"ok": True, "voucher": r["item"], "points": p["points"]}
