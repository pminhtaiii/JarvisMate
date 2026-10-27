"""train_bus_tickets: one method per tool of the app.

State: {trips: [{id, type, operator, origin, destination, date, depart, arrive, price, seats_left}], bookings: [...]}."""
from __future__ import annotations

from .base import App, read, write
from ._geo import city_match


class TrainBusTickets(App):
    name = "train_bus_tickets"

    @read
    def search(self, origin=None, destination=None, date=None, type=None, **_):
        out = [t for t in self.state.get("trips", [])
               if city_match(origin, t.get("origin")) and city_match(destination, t.get("destination"))
               and (not date or str(t.get("date")) == str(date)) and (not type or t.get("type") == type)]
        return {"ok": True, "trips": [dict(t) for t in out]}

    @read
    def my_bookings(self, **_):
        return self.read("bookings")

    @write
    def book(self, trip_id=None, seats=None, **_):
        t = self.find("trips", trip_id)
        if t is None:
            return self.noop(f"không tìm thấy trip_id={trip_id!r}")
        if seats > t.get("seats_left", seats):
            return self.noop(f"chuyến chỉ còn {t.get('seats_left')} chỗ")
        if "seats_left" in t:
            t["seats_left"] -= seats
        r = self.create("bookings", "tk", trip_id=t["id"], seats=seats, total=t.get("price", 0) * seats, status="confirmed")
        return {"ok": True, "booking": r["item"]}

    @write
    def cancel(self, booking_id=None, **_):
        b = self.find("bookings", booking_id)
        if b is None:
            return self.noop(f"không tìm thấy booking_id={booking_id!r}")
        if b.get("status") == "cancelled":
            return self.noop("vé đã huỷ trước đó")
        b["status"] = "cancelled"
        t = self.find("trips", b.get("trip_id"))
        if t is not None and "seats_left" in t:
            t["seats_left"] += b.get("seats", 0)
        return {"ok": True, "booking": b}
