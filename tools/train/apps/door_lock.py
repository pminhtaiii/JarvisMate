"""door_lock: one method per tool of the app."""
from __future__ import annotations

import hashlib
from datetime import datetime

from .base import App, read, write


class DoorLock(App):
    name = "door_lock"

    @read
    def list_locks(self, **_):
        return self.read("locks")

    @write
    def set_lock(self, lock_id=None, locked=None, **_):
        if self.find("locks", lock_id) is None:
            return self.noop(f"không tìm thấy lock_id={lock_id!r}")
        return self.patch("locks", "lock_id", lock_id, set={"locked": locked})

    @write
    def grant_guest_code(self, lock_id=None, valid_until=None, label=None, **_):
        """guest_codes[]: {id, lock_id, code, valid_until, label}; the 6-digit code is a pure function of (lock_id, valid_until)"""
        if self.find("locks", lock_id) is None:
            return self.noop(f"không tìm thấy lock_id={lock_id!r}")
        try:
            until = datetime.fromisoformat(str(valid_until))
        except (TypeError, ValueError):
            until = None
        if until is None or until.tzinfo is None:
            return self.noop("valid_until phải là ISO-8601 có múi giờ, ví dụ 2026-11-11T18:00:00+07:00")
        code = f"{int(hashlib.sha256(f'{lock_id}|{valid_until}'.encode()).hexdigest(), 16) % 1_000_000:06d}"
        r = self.create("guest_codes", "gc", lock_id=lock_id, code=code, valid_until=valid_until, label=label)
        return {"ok": True, "guest_code": r["item"]}
