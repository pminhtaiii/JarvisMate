"""notes: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Notes(App):
    name = "notes"

    @read
    def list(self, **_):
        return self.read("notes")

    @write
    def create(self, title=None, content=None, **_):
        return App.create(self, "notes", "note", defaults={"title": ""}, title=title, content=content)

    @write
    def append(self, note_id=None, content=None, **_):
        note = self.find("notes", note_id)
        if note is None:
            return self.noop(f"không tìm thấy note_id={note_id!r}")
        old = note.get("content") or ""
        note["content"] = f"{old}\n{content}" if old else content
        return {"ok": True, "item": note}
