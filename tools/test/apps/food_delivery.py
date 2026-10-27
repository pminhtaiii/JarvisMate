"""food_delivery: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class FoodDelivery(App):
    name = "food_delivery"

    @read
    def list_restaurants(self, **_):
        return self.read("restaurants", drop=("menu",))

    @read
    def get_menu(self, restaurant_id=None, **_):
        r = self.find("restaurants", restaurant_id)
        if r is None:
            return self.empty("menu")
        return {"ok": True, "menu": r.get("menu", [])}

    @read
    def order_history(self, **_):
        return self.read("orders")

    @write
    def place_order(self, restaurant_id=None, items=None, address=None, payment=None, **_):
        r = self.find("restaurants", restaurant_id)
        if r is None:
            return self.noop("không tìm thấy restaurant_id")
        menu = {m["id"]: m for m in r.get("menu", [])}
        lines, total = [], 0
        for it in items or []:
            m = menu.get(it.get("item_id"))
            if m is None:
                return self.noop(f"món {it.get('item_id')!r} không có trong thực đơn")
            q = it.get("quantity") or 1
            lines.append({"item_id": m["id"], "name": m["name"], "quantity": q, "note": it.get("note")})
            total += m["price"] * q
        if not lines:
            return self.noop("đơn không có món")
        order = {"id": self.new_id("orders", "ord"), "restaurant_id": r["id"], "items": lines, "total": total, "address": address, "payment": payment if payment is not None else "cash", "status": "placed"}
        self.state.setdefault("orders", []).append(order)
        return {"ok": True, "order": order}

    @write
    def cancel_order(self, order_id=None, **_):
        return self.patch("orders", "order_id", order_id, set={"status": "cancelled"})
