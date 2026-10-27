"""phone: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Phone(App):
    name = "phone"

    @write
    def call(self, contact_id=None, phone_number=None, **_):
        contact_id, phone_number = self.contact_ref(contact_id, phone_number)
        call = {"id": self.new_id("calls", "call"), "contact_id": contact_id, "phone_number": phone_number, "status": "dialing"}
        self.state.setdefault("calls", []).append(call)
        return {"ok": True, "call": call}

    @read
    def recent_calls(self, **_):
        return self.read("calls")
