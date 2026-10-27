"""package_tracking (Theo dõi bưu kiện): one method per tool of the app. State: shipments[{id, tracking_id, carrier, name, status,
eta, scheduled_time?}] (status: in_transit | out_for_delivery | delivered), pickups[{id, address, date, status}]."""
from __future__ import annotations

from .base import App, read, write


class PackageTracking(App):
    name = "package_tracking"

    def _shipment(self, tracking_id):
        """A shipment by its tracking code (case/space-insensitive) or its state id."""
        key = "".join(str(tracking_id or "").split()).upper()
        for s in self.state.get("shipments", []):
            if key and (s.get("id", "").upper() == key or "".join(str(s.get("tracking_id", "")).split()).upper() == key):
                return s
        return None

    @read
    def track(self, tracking_id=None, **_):
        if tracking_id:
            s = self._shipment(tracking_id)
            if s is None:
                return self.empty("shipments")
            return {"ok": True, "shipments": [s]}
        return self.read("shipments")

    @write
    def reschedule_delivery(self, tracking_id=None, time=None, **_):
        s = self._shipment(tracking_id)
        if s is None:
            return self.noop("không tìm thấy tracking_id")
        if s.get("status") == "delivered":
            return self.noop(f"vận đơn {s.get('tracking_id')} đã giao, không hẹn lại được")
        s["scheduled_time"] = time
        return {"ok": True, "shipment": s}

    @write
    def schedule_pickup(self, address=None, date=None, **_):
        res = self.create("pickups", "pick", defaults={"status": "scheduled"}, address=address, date=date)
        return {"ok": True, "pickup": res["item"]}
