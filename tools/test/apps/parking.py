"""parking: one method per tool of the app. The tool `find` shadows App.find, so lookups here call App.find(self, ...).

State: {lots: [{id, name, address, area, price_per_hour, available_spots}], sessions: [{id, lot_id, from_time, hours, end_time, total, status}]}."""
from __future__ import annotations

from datetime import datetime, timedelta

from .base import App, read, write


class Parking(App):
    name = "parking"

    @read
    def find(self, near=None, **_):
        res = self.read("lots", contains={("name", "address", "area"): near})
        if not res["lots"]:  # nothing named like that: the lots the app knows are the ones around the user
            res = self.read("lots")
        return res

    @read
    def list_sessions(self, **_):
        lots = {l["id"]: l for l in self.state.get("lots", [])}
        return {"ok": True, "sessions": [{**s, "lot_name": lots.get(s.get("lot_id"), {}).get("name")} for s in self.state.get("sessions", [])]}

    @write
    def reserve(self, lot_id=None, from_time=None, hours=None, **_):
        lot = App.find(self, "lots", lot_id)
        if lot is None:
            return self.noop(f"không tìm thấy lot_id={lot_id!r}")
        try:
            start = datetime.fromisoformat(str(from_time))
        except ValueError:
            start = None
        if start is None or start.tzinfo is None:
            return self.noop("from_time phải có offset múi giờ, ví dụ 2026-11-11T05:30:00+07:00")
        if lot.get("available_spots", 1) <= 0:
            return self.noop("bãi đã hết chỗ")
        if "available_spots" in lot:
            lot["available_spots"] -= 1
        r = self.create("sessions", "park", lot_id=lot["id"], from_time=from_time, hours=hours,
                        end_time=(start + timedelta(hours=hours)).isoformat(), total=lot.get("price_per_hour", 0) * hours, status="reserved")
        return {"ok": True, "session": r["item"]}

    @write
    def end_session(self, session_id=None, **_):
        s = App.find(self, "sessions", session_id)
        if s is None:
            return self.noop(f"không tìm thấy session_id={session_id!r}")
        if s.get("status") == "ended":
            return self.noop("phiên đỗ đã kết thúc")
        s["status"] = "ended"
        lot = App.find(self, "lots", s.get("lot_id"))
        if lot is not None and "available_spots" in lot:
            lot["available_spots"] += 1
        return {"ok": True, "session": s}
