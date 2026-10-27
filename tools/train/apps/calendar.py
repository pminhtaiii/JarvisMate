"""calendar: one method per tool of the app."""
from __future__ import annotations

from datetime import datetime, timedelta

from .base import App, read, write


class Calendar(App):
    name = "calendar"

    @read
    def list_events(self, date_from=None, date_to=None, **_):
        return self.read("events", date_range=("start", date_from, date_to))

    @write
    def create_event(self, title=None, start=None, end=None, location=None, attendees=None, **_):
        if end is None and isinstance(start, str) and start:
            try:  # no end spoken: one hour after start (the catalog states this default)
                end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
            except ValueError:
                pass
        return self.create("events", "evt", defaults={"status": "confirmed"}, title=title, start=start, end=end, location=location, attendees=attendees)

    @write
    def update_event(self, event_id=None, title=None, start=None, end=None, location=None, **_):
        return self.patch("events", "event_id", event_id, title=title, start=start, end=end, location=location)

    @write
    def cancel_event(self, event_id=None, **_):
        return self.patch("events", "event_id", event_id, set={"status": "cancelled"})



