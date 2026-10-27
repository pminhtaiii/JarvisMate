"""event_tickets: one method per tool of the app.

State: {events: [{id, name, category, date, time, venue, price, available}], bookings: [{id, event_id, quantity, total, status}]}."""
from __future__ import annotations

from .base import App, read, write


class EventTickets(App):
    name = "event_tickets"

    @read
    def search(self, query=None, **_):
        return self.read("events", contains={("name", "category", "venue"): query or ""})

    @write
    def book(self, event_id=None, quantity=None, **_):
        e = self.find("events", event_id)
        if e is None:
            return self.noop("không tìm thấy event_id")
        if isinstance(e.get("available"), int) and quantity > e["available"]:
            return self.noop(f"chỉ còn {e['available']} vé")
        if isinstance(e.get("available"), int):
            e["available"] -= quantity
        r = self.create("bookings", "tk", event_id=e["id"], quantity=quantity, total=(e.get("price") or 0) * quantity, status="confirmed")
        return {"ok": True, "booking": r["item"]}
