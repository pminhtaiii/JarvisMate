"""contacts: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Contacts(App):
    name = "contacts"

    @read
    def search(self, query=None, **_):
        """query optional: substring (lower, no diacritics) on name, relation, phone; no query -> whole address book"""
        return self.read("contacts", contains={("name", "relation", "phone"): query})

    @read
    def get(self, contact_id=None, **_):
        return self.read("contacts", eq={"id": contact_id})

    @write
    def update(self, contact_id=None, phone=None, email=None, **_):
        return self.patch("contacts", "contact_id", contact_id, phone=phone, email=email)
