"""home_security: one method per tool of the app."""
from __future__ import annotations

from datetime import datetime

from .base import App, read, write


def _dt(v):
    try:
        d = datetime.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo is not None else None


class HomeSecurity(App):
    name = "home_security"

    @read
    def list_alerts(self, since=None, **_):
        """alerts[]: {id, time, type, location, message, acknowledged}; since keeps alerts at or after that instant"""
        if since in (None, ""):
            return self.read("alerts")
        t0 = _dt(since)
        if t0 is None:  # schema guarantees date-time; a naive timestamp (no offset) cannot be compared: nothing matched
            return self.empty("alerts")
        out = [dict(a) for a in self.state.get("alerts", []) if _dt(a.get("time")) and _dt(a.get("time")) >= t0]
        return {"ok": True, "alerts": out}

    @read
    def get_camera(self, location=None, **_):
        return self.read("cameras", contains={("location", "name"): location})

    @write
    def arm(self, mode=None, **_):
        self.state["mode"] = mode
        return {"ok": True, "mode": mode}

    @write
    def acknowledge_alert(self, alert_id=None, **_):
        return self.patch("alerts", "alert_id", alert_id, set={"acknowledged": True})
