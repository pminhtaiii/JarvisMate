"""chat_ott: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class ChatOtt(App):
    name = "chat_ott"

    @read
    def list_chats(self, **_):
        return self.read("chats", drop=("messages",))

    @read
    def read_chat(self, chat_id=None, limit=None, **_):
        chat = self.find("chats", chat_id)
        if chat is None:
            return self.empty("messages")
        return {"ok": True, "messages": chat.get("messages", [])[-(limit or 20):]}

    @write
    def send_message(self, chat_id=None, content=None, **_):
        chat = self.find("chats", chat_id)
        if chat is None:
            return self.noop("không tìm thấy chat_id")
        msg = {"from": "me", "content": content if content is not None else ""}
        chat.setdefault("messages", []).append(msg)
        return {"ok": True, "message": msg}

    @write
    def send_location(self, chat_id=None, **_):
        chat = self.find("chats", chat_id)
        if chat is None:
            return self.noop("không tìm thấy chat_id")
        msg = {"from": "me", "type": "location", "content": "Vị trí hiện tại"}
        chat.setdefault("messages", []).append(msg)
        return {"ok": True, "message": msg}

    @write
    def call(self, chat_id=None, video=None, **_):
        """OTT call log kept in chat_ott.calls[] (phone.calls is the cellular log)"""
        if self.find("chats", chat_id) is None:
            return self.noop("không tìm thấy chat_id")
        r = self.create("calls", "ott_call", chat_id=chat_id, video=bool(video), status="dialing")
        return {"ok": True, "call": r["item"]}
