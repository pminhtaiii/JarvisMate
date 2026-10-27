"""home_automation: one method per tool of the app (daily on/off rules for smart_home devices)."""
from __future__ import annotations

from .base import App, read, write


class HomeAutomation(App):
    name = "home_automation"

    @read
    def list_rules(self, **_):
        return self.read("rules")

    @write
    def create_rule(self, device_id=None, action=None, time=None, title=None, **_):
        """rules[]: {id, device_id, action on|off, time HH:MM, title, enabled}; device_id must exist in smart_home.devices
        when smart_home is installed in the sample (otherwise accepted as is)"""
        devices = ((getattr(self.session, "states", None) or {}).get("smart_home") or {}).get("devices")
        if isinstance(devices, list) and not any(isinstance(d, dict) and d.get("id") == device_id for d in devices):
            return self.noop(f"không tìm thấy device_id={device_id!r} trong smart_home.devices")
        hhmm = str(time).strip()[:5]  # catalog format "time" guarantees HH:MM[:SS]; seconds dropped
        r = self.create("rules", "rule", defaults={"title": ""}, device_id=device_id, action=action, time=hhmm, title=title, enabled=True)
        return {"ok": True, "rule": r["item"]}

    @write
    def delete_rule(self, rule_id=None, **_):
        return self.delete("rules", "rule_id", rule_id)
