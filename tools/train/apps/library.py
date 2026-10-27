"""library: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Library(App):
    name = "library"

    @read
    def search(self, query=None, **_):
        return self.read("books", contains={("title", "author"): query})

    @write
    def reserve(self, book_id=None, **_):
        b = self.find("books", book_id)
        if b is None:
            return self.noop(f"không tìm thấy book_id={book_id!r}")
        if any(r.get("book_id") == b["id"] and r.get("status") in ("ready", "waiting") for r in self.state.get("reservations", [])):
            return self.noop(f"sách {b['id']} đã được đặt giữ rồi")
        status = "ready" if b.get("available") else "waiting"  # available: kept at the desk for pickup; on loan: joins the queue
        b["available"] = False
        r = self.create("reservations", "res", book_id=b["id"], status=status)
        return {"ok": True, "reservation": r["item"]}
