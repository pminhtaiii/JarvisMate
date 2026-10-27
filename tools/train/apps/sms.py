"""sms: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Sms(App):
    name = "sms"

    @write
    def send(self, contact_id=None, phone_number=None, content=None, **_):
        contact_id, phone_number = self.contact_ref(contact_id, phone_number)
        msg = {"id": self.new_id("messages", "msg"), "contact_id": contact_id, "phone_number": phone_number, "direction": "outgoing", "content": content if content is not None else ""}
        self.state.setdefault("messages", []).append(msg)
        return {"ok": True, "message": msg}

    @read
    def read_recent(self, contact_id=None, **_):
        return self.read("messages", eq={"contact_id": contact_id})
