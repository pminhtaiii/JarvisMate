"""email: one method per tool of the app. Inbox in emails[] (folder inbox/archive), outgoing mail in sent[], drafts in drafts[]."""
from __future__ import annotations

import re

from .base import App, read, write

_ADDR = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def _addresses(v, field):
    """(list, None) when v is a list of e-mail addresses, else (None, message). Presence/type is the catalog's job."""
    if v is None:
        return [], None
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        v = [v]
    bad = [a for a in v if not isinstance(a, str) or not _ADDR.match(a.strip())]
    if bad:
        return None, f"{field}: địa chỉ email không hợp lệ {bad[0]!r}"
    return [a.strip() for a in v], None


class Email(App):
    name = "email"

    @read
    def list(self, unread_only=None, **_):
        r = App.read(self, "emails", drop=("body",))
        if unread_only:
            r["emails"] = [e for e in r["emails"] if e.get("unread")]
        return r

    @read
    def read(self, email_id=None, **_):
        e = self.find("emails", email_id)
        if e is None:
            return self.noop(f"không tìm thấy email_id={email_id!r}")
        return {"ok": True, "email": dict(e)}

    def _outgoing(self, collection, prefix, to, subject, body, cc):
        to, err = _addresses(to, "to")
        if err:
            return self.noop(err)
        cc, err = _addresses(cc, "cc")
        if err:
            return self.noop(err)
        r = App.create(self, collection, prefix, to=to, cc=cc, subject=subject, body=body)
        return {"ok": True, "id": r["id"], collection[:-1] if collection == "drafts" else "email": r["item"]}

    @write
    def send(self, to=None, subject=None, body=None, cc=None, **_):
        return self._outgoing("sent", "sent", to, subject, body, cc)

    @write
    def create_draft(self, to=None, subject=None, body=None, cc=None, **_):
        return self._outgoing("drafts", "draft", to, subject, body, cc)

    @write
    def reply(self, email_id=None, body=None, **_):
        e = self.find("emails", email_id)
        if e is None:
            return self.noop(f"không tìm thấy email_id={email_id!r}")
        subj = e.get("subject") or ""
        r = App.create(self, "sent", "sent", to=[e.get("from")], cc=[], subject=subj if subj.lower().startswith("re:") else f"Re: {subj}", body=body, in_reply_to=e["id"])
        e["unread"] = False
        e["replied"] = True
        return {"ok": True, "id": r["id"], "email": r["item"]}

    @write
    def archive(self, email_id=None, action=None, **_):
        if action == "delete":
            return App.delete(self, "emails", "email_id", email_id)
        return self.patch("emails", "email_id", email_id, set={"folder": "archive"})
