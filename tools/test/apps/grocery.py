"""grocery (Đi chợ online): one method per tool of the app. State: products[{id, name, price, unit, category, in_stock}],
cart[{product_id, name, price, quantity}], orders[{id, items, total, status, address?, delivery_time?}]."""
from __future__ import annotations

from ._shop_match import cart_add, cart_checkout, match_items
from .base import App, read, write


class Grocery(App):
    name = "grocery"

    @read
    def search(self, query=None, **_):
        return {"ok": True, "products": match_items(self.state.get("products", []), query, ("name", "category", "tags"))}

    @write
    def add_to_cart(self, product_id=None, quantity=None, **_):
        return cart_add(self, product_id, quantity)

    @write
    def checkout(self, address=None, delivery_time=None, **_):
        return cart_checkout(self, address=address, delivery_time=delivery_time)
