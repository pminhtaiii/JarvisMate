"""video_meeting: one method per tool of the app."""
from __future__ import annotations

import hashlib

from .base import App, read, write


def meeting_link(meeting_id, start):
    """Deterministic room link from the meeting id + start (independent of the free-text title)."""
    h = hashlib.sha256(f"{meeting_id}|{start}".encode()).hexdigest()
    code = "".join(chr(ord("a") + int(h[i:i + 2], 16) % 26) for i in range(0, 20, 2))
    return f"https://meet.example.test/{code[:3]}-{code[3:7]}-{code[7:10]}"


class VideoMeeting(App):
    name = "video_meeting"

    @read
    def list_meetings(self, **_):
        r = self.read("meetings")
        r["meetings"].sort(key=lambda m: str(m.get("start", "")))
        return r

    @write
    def create(self, title=None, start=None, attendees=None, **_):
        attendees = attendees if attendees is not None else []
        book = ((getattr(self.session, "states", None) or {}).get("contacts") or {}).get("contacts")
        if isinstance(book, list):
            ids = {c.get("id") for c in book if isinstance(c, dict)}
            missing = [a for a in attendees if a not in ids]
            if missing:
                return self.noop(f"không tìm thấy attendees={missing[0]!r} trong contacts.contacts")
        return App.create(self, "meetings", "meet", title=title, start=start, link=meeting_link(self.new_id("meetings", "meet"), start), attendees=list(attendees), status="scheduled")

    @write
    def join(self, meeting_id=None, **_):
        m = self.find("meetings", meeting_id)
        if m is None:
            return self.noop(f"không tìm thấy meeting_id={meeting_id!r}")
        if m.get("status") == "cancelled":
            return self.noop("cuộc họp đã bị huỷ")
        m["status"] = "joined"
        return {"ok": True, "item": m, "link": m.get("link")}
