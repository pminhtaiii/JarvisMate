"""reminders: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Reminders(App):
    name = "reminders"

    @read
    def list(self, date=None, **_):
        return self.read("reminders", prefix={"time": date})

    @write
    def create(self, content=None, time=None, repeat=None, **_):
        return App.create(self, "reminders", "rem", defaults={"repeat": "once", "done": False}, content=content, time=time, repeat=repeat)

    @write
    def complete(self, reminder_id=None, **_):
        return self.patch("reminders", "reminder_id", reminder_id, set={"done": True})

    @write
    def delete(self, reminder_id=None, **_):
        return App.delete(self, "reminders", "reminder_id", reminder_id)
