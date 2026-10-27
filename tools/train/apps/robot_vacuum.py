"""robot_vacuum: one method per tool of the app."""
from __future__ import annotations

from ..utils import _fold
from .base import App, read, write

MIN_BATTERY = 15  # % needed to start a job


class RobotVacuum(App):
    name = "robot_vacuum"

    def _room_names(self):
        return [r.get("name") if isinstance(r, dict) else r for r in self.state.get("rooms", [])]

    @read
    def get_status(self, **_):
        st = self.state
        return {"ok": True, "battery": st.get("battery"), "status": st.get("status"), "mode": st.get("mode"),
                "rooms": self._room_names(), "current_job": st.get("current_job")}

    @write
    def start(self, rooms=None, mode=None, **_):
        """rooms: names from state.rooms (matched without case/diacritics, stored in state order); none = whole house"""
        names = self._room_names()
        by_fold = {_fold(n): n for n in names}
        picked = set()
        for r in rooms or []:
            n = by_fold.get(_fold(r))
            if n is None:
                return self.noop(f"không có phòng {r!r}; các phòng: {', '.join(names)}")
            picked.add(n)
        if (self.state.get("battery") or 0) < MIN_BATTERY:
            return self.noop(f"pin robot còn {self.state.get('battery')}%, cần sạc trước khi dọn")
        job = {"rooms": [n for n in names if n in picked] if picked else list(names), "whole_house": not picked,
               "mode": mode or self.state.get("mode") or "vacuum"}
        self.state["status"] = "cleaning"
        self.state["current_job"] = job
        return {"ok": True, "status": "cleaning", "current_job": job}

    @write
    def stop(self, **_):
        was = self.state.get("status")
        self.state["status"] = "docked"
        self.state["current_job"] = None
        return {"ok": True, "status": "docked", "was": was}
