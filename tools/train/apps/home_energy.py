"""home_energy: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write

PERIODS = ("today", "week", "month")


class HomeEnergy(App):
    name = "home_energy"

    @read
    def get_usage(self, period=None, **_):
        """usage{today|week|month: {from, to, kwh, cost, ...}} stored in state; nothing is computed from the clock"""
        u = (self.state.get("usage") or {}).get(period)
        if u is None:
            return self.noop(f"chưa có số liệu điện cho period={period!r}")
        return {"ok": True, "period": period, "usage": u, "alert_threshold_kwh": self.state.get("alert_threshold_kwh")}

    @write
    def set_alert(self, threshold_kwh=None, **_):
        self.state["alert_threshold_kwh"] = threshold_kwh
        month = ((self.state.get("usage") or {}).get("month") or {}).get("kwh")
        return {"ok": True, "alert_threshold_kwh": threshold_kwh, "month_kwh": month}
