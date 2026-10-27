"""habit_tracker: one method per tool of the app."""
from __future__ import annotations

from datetime import date as _date, timedelta

from .base import App, read, write


class HabitTracker(App):
    name = "habit_tracker"

    @read
    def list_habits(self, **_):
        return self.read("habits")

    @write
    def log(self, habit_id=None, date=None, **_):
        h = self.find("habits", habit_id)
        if h is None:
            return self.noop(f"không tìm thấy habit_id={habit_id!r}")
        d = _date.fromisoformat(str(date))  # catalog format "date"
        day = d.isoformat()
        if h.get("last_logged") == day or any(x.get("habit_id") == h["id"] and x.get("date") == day for x in self.state.get("logs", [])):
            return self.noop(f"đã ghi {h['id']} ngày {day} rồi")
        last = h.get("last_logged")
        if last == (d - timedelta(days=1)).isoformat():
            h["streak"] = (h.get("streak") or 0) + 1
        elif not last or day > last:
            h["streak"] = 1
        # a back-filled earlier day leaves the streak unchanged
        if not last or day > last:
            h["last_logged"] = day
        r = self.create("logs", "log", habit_id=h["id"], date=day)
        return {"ok": True, "log": r["item"], "streak": h["streak"]}
