"""sys: one method per tool of the app."""
from __future__ import annotations

from .base import App, meta


class Sys(App):
    name = "sys"

    @meta
    def ask_missing_info(self, tool_name=None, params=None, **_):
        """Recorded in the call list only; touches no state."""
        return {"ok": True, "waiting_for_user": True}
