"""appliances: one method per tool of the app."""
from __future__ import annotations

from ..utils import _fold
from .base import App, read, write


class Appliances(App):
    name = "appliances"

    @read
    def list(self, type=None, **_):
        return self.read("appliances", eq={"type": type})

    @write
    def start_cycle(self, appliance_id=None, cycle=None, delay_minutes=None, **_):
        """cycle must be one of the appliance's cycles (codes like quick/normal/eco; case/diacritics ignored, stored as the code)"""
        a = self.find("appliances", appliance_id)
        if a is None:
            return self.noop(f"không tìm thấy appliance_id={appliance_id!r}")
        cycles = a.get("cycles", [])
        code = next((c for c in cycles if _fold(c) == _fold(cycle)), None)
        if code is None:
            return self.noop(f"{a['id']} không có chu trình {cycle!r}; chu trình khả dụng: {', '.join(cycles)}")
        st = a.setdefault("state", {})
        if st.get("status") in ("running", "scheduled"):
            return self.noop(f"{a['id']} đang chạy chu trình {st.get('cycle')!r}, cần dừng trước")
        st.update({"status": "scheduled" if delay_minutes else "running", "cycle": code, "delay_minutes": delay_minutes or 0})
        return {"ok": True, "item": a}

    @write
    def stop(self, appliance_id=None, **_):
        a = self.find("appliances", appliance_id)
        if a is None:
            return self.noop(f"không tìm thấy appliance_id={appliance_id!r}")
        a.setdefault("state", {}).update({"status": "idle", "cycle": None, "delay_minutes": 0})
        return {"ok": True, "item": a}
