"""pantry (Tủ bếp): one method per tool of the app. State: items[{id, name, stock (int), unit}]."""
from __future__ import annotations

from .base import App, read, write


class Pantry(App):
    name = "pantry"

    @read
    def list_items(self, **_):
        return self.read("items")

    @write
    def consume(self, item_id=None, quantity=None, **_):
        item = self.find("items", item_id)
        if item is None:
            return self.noop("không tìm thấy item_id")
        stock = item.get("stock") or 0
        if stock < quantity:
            return self.noop(f"không đủ {item.get('name', item_id)}: còn {stock} {item.get('unit', '')}".strip())
        item["stock"] = stock - quantity
        return {"ok": True, "item": item}
