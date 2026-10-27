"""alarm: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Alarm(App):
    name = "alarm"

    @read
    def list(self, **_):
        return self.read("alarms")

    @write
    def create(self, time=None, label=None, repeat=None, **_):
        return App.create(self, "alarms", "alm", defaults={"repeat": "once", "enabled": True}, time=time, label=label, repeat=repeat)

    @write
    def update(self, alarm_id=None, time=None, label=None, enabled=None, **_):
        return self.patch("alarms", "alarm_id", alarm_id, time=time, label=label, enabled=enabled)

    @write
    def delete(self, alarm_id=None, **_):
        return App.delete(self, "alarms", "alarm_id", alarm_id)
