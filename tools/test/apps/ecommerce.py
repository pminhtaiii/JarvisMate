"""ecommerce (Mua sắm online): one method per tool of the app. State: products[{id, name, price, seller, category, rating, in_stock}],
cart[{product_id, name, price, quantity}], orders[{id, items, total, status, placed_at, delivered_at?, payment?, address?}],
returns[{id, order_id, reason, status}]. Order status: placed | shipping | delivered | cancelled | return_requested."""
from __future__ import annotations

from ._shop_match import cart_add, cart_checkout, match_items
from .base import App, read, write

REASONS = ("wrong_item", "damaged", "changed_mind", "other")


class Ecommerce(App):
    name = "ecommerce"

    @read
    def search(self, query=None, max_price=None, **_):
        hits = match_items(self.state.get("products", []), query, ("name", "category", "seller", "tags"))
        if isinstance(max_price, (int, float)) and not isinstance(max_price, bool):
            hits = [p for p in hits if (p.get("price") or 0) <= max_price]
        return {"ok": True, "products": hits}

    @read
    def order_status(self, order_id=None, **_):
        if order_id:
            o = self.find("orders", order_id)
            if o is None:
                return self.empty("orders")
            return {"ok": True, "orders": [o]}
        return self.read("orders")

    @write
    def add_to_cart(self, product_id=None, quantity=None, **_):
        return cart_add(self, product_id, quantity)

    @write
    def checkout(self, address=None, payment=None, **_):
        return cart_checkout(self, address=address, payment=payment if payment is not None else "cod")

    @write
    def cancel_order(self, order_id=None, **_):
        o = self.find("orders", order_id)
        if o is None:
            return self.noop("không tìm thấy order_id")
        if o.get("status") not in ("placed", "shipping"):
            return self.noop(f"đơn {order_id} đang ở trạng thái {o.get('status')}, không huỷ được")
        o["status"] = "cancelled"
        return {"ok": True, "order": o}

    @write
    def request_return(self, order_id=None, reason=None, **_):
        o = self.find("orders", order_id)
        if o is None:
            return self.noop("không tìm thấy order_id")
        if any(r.get("order_id") == order_id for r in self.state.get("returns", [])):
            return self.noop(f"đơn {order_id} đã có yêu cầu trả hàng")
        if o.get("status") != "delivered":
            return self.noop(f"đơn {order_id} chưa giao (trạng thái {o.get('status')}), chưa trả hàng được")
        res = self.create("returns", "ret", defaults={"status": "requested"}, order_id=order_id, reason=reason)
        o["status"] = "return_requested"
        return {"ok": True, "return": res["item"], "order": o}
