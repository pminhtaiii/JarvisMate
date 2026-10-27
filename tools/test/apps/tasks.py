"""tasks: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Tasks(App):
    name = "tasks"

    @read
    def list(self, status=None, **_):
        where = {} if status is None else {"done": status == "done"}
        return self.read("tasks", where=where)

    @write
    def add(self, title=None, due=None, priority=None, **_):
        return App.create(self, "tasks", "task", defaults={"due": "", "priority": "normal", "done": False}, title=title, due=due, priority=priority)

    @write
    def complete(self, task_id=None, **_):
        return self.patch("tasks", "task_id", task_id, set={"done": True})
