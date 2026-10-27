"""shopping_list: one method per tool of the app. State: items[{id, name, quantity (int), checked}]."""
from __future__ import annotations

from .base import App, read, write


class ShoppingList(App):
    name = "shopping_list"

    @read
    def get(self, **_):
        return self.read("items")

    @write
    def add(self, name=None, quantity=None, **_):
        if not str(name).strip():  # whitespace-only name: `required` only rejects ""
            return self.noop("thiếu name")
        if quantity is None:
            quantity = 1
        res = self.create("items", "item", defaults={"checked": False}, name=name, quantity=quantity)
        return {"ok": True, "item": res["item"]}

    @write
    def remove(self, item_id=None, **_):
        return self.delete("items", "item_id", item_id)

    @write
    def check(self, item_id=None, **_):
        return self.patch("items", "item_id", item_id, set={"checked": True})
