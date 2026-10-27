"""medication: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Medication(App):
    name = "medication"

    @read
    def list(self, **_):
        return self.read("schedules")

    @write
    def add(self, name=None, times=None, days=None, **_):
        return self.create("schedules", "med", defaults={"days": "daily"}, name=name, times=times, days=days)

    @write
    def log_taken(self, schedule_id=None, time=None, **_):
        s = self.find("schedules", schedule_id)
        if s is None:
            return self.noop("không tìm thấy schedule_id")
        entry = {"schedule_id": s["id"], "time": time}
        self.state.setdefault("logs", []).append(entry)
        return {"ok": True, "log": entry}

    @write
    def remove(self, schedule_id=None, **_):
        return self.delete("schedules", "schedule_id", schedule_id)



