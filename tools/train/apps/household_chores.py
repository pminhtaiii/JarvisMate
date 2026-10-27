"""household_chores: one method per tool of the app."""
from __future__ import annotations

from ..utils import _fold
from .base import App, read, write


class HouseholdChores(App):
    name = "household_chores"

    @read
    def list_chores(self, **_):
        return {**self.read("chores"), "members": list(self.state.get("members", []))}

    @write
    def assign(self, chore_id=None, assignee=None, **_):
        if self.find("chores", chore_id) is None:
            return self.noop(f"không tìm thấy chore_id={chore_id!r}")
        members = self.state.get("members", [])
        who = next((m for m in members if _fold(m) == _fold(assignee)), None)
        if who is None:
            return self.noop(f"assignee phải là một trong {members}")
        return self.patch("chores", "chore_id", chore_id, assignee=who)
