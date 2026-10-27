"""ride_hailing: one method per tool of the app."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import App, read, write

_VN = timezone(timedelta(hours=7))


def _parse(s, default_tz):
    """ISO-8601 -> aware datetime: 'Z' accepted, a naive value is read in `default_tz` (the user's zone, +07:00)."""
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo is not None else d.replace(tzinfo=default_tz)


def _is_past_or_now(when, now):
    """True when `when` (ISO-8601) is not later than `now`; unparsable values -> False (kept as given)."""
    try:
        now_dt = _parse(now, _VN)
        return _parse(when, now_dt.tzinfo) <= now_dt
    except (TypeError, ValueError, AttributeError):
        return False


class RideHailing(App):
    name = "ride_hailing"

    @read
    def get_quotes(self, vehicle=None, **_):
        return self.read("quotes", eq={"vehicle": vehicle})

    @write
    def book(self, pickup=None, dropoff=None, vehicle=None, schedule_time=None, payment=None, **_):
        """schedule_time omitted, equal to or earlier than current_time -> an immediate ride (no schedule_time stored)."""
        if schedule_time is not None and _is_past_or_now(schedule_time, getattr(self.session, "now", None)):
            schedule_time = None
        return self.create("rides", "ride", defaults={"status": "booked"}, pickup=pickup, dropoff=dropoff, vehicle=vehicle, schedule_time=schedule_time, payment=payment)

    @write
    def cancel(self, ride_id=None, **_):
        return self.patch("rides", "ride_id", ride_id, set={"status": "cancelled"})

    @read
    def get_ride(self, ride_id=None, **_):
        """ride_id given -> that ride; otherwise the current ride = the latest one not cancelled"""
        if ride_id:
            ride = self.find("rides", ride_id)
        else:
            ride = next((r for r in reversed(self.state.get("rides", [])) if r.get("status") != "cancelled"), None)
        if ride is None:
            return self.noop("không có chuyến xe nào" if not ride_id else "không tìm thấy ride_id")
        return {"ok": True, "ride": ride}
