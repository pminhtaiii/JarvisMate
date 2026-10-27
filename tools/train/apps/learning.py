"""learning: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Learning(App):
    name = "learning"

    @read
    def list_courses(self, **_):
        return self.read("courses")

    @write
    def enroll(self, course_id=None, **_):
        c = self.find("courses", course_id)
        if c is None:
            return self.noop(f"không tìm thấy course_id={course_id!r}")
        if c.get("enrolled"):
            return self.noop(f"đã đăng ký khoá học {c['id']} rồi")
        c["enrolled"] = True
        return {"ok": True, "item": c}

    @write
    def schedule_lesson(self, course_id=None, time=None, **_):
        if self.find("courses", course_id) is None:
            return self.noop(f"không tìm thấy course_id={course_id!r}")
        r = self.create("lessons", "les", course_id=course_id, time=time, status="scheduled")
        return {"ok": True, "lesson": r["item"]}

    @write
    def log_progress(self, course_id=None, minutes=None, **_):
        c = self.find("courses", course_id)
        if c is None:
            return self.noop(f"không tìm thấy course_id={course_id!r}")
        c["progress_minutes"] = (c.get("progress_minutes") or 0) + minutes
        r = self.create("progress", "prog", course_id=c["id"], minutes=minutes)
        return {"ok": True, "progress": r["item"], "total_minutes": c["progress_minutes"]}
