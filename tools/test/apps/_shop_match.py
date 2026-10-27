"""Shared helpers for the shopping/food apps (recipes, grocery, ecommerce, pantry): tolerant free-text matching and
quantity checks. No App subclass here, so apps/__init__ registers nothing from this module."""
from __future__ import annotations

from ..utils import _fold

# filler words dropped from a spoken query before token matching ("tìm công thức súp bí đỏ" -> "súp bí đỏ")
_STOP = {_fold(w) for w in ("tìm", "kiếm", "công", "thức", "cách", "nấu", "làm", "món", "mua", "cho", "tôi", "mình", "em", "anh", "chị",
                            "của", "và", "với", "loại", "cái", "chiếc", "các", "những", "một", "giúp", "xem", "đơn", "hàng", "sản", "phẩm")}


def match_items(items, query, fields, extra=None):
    """Items whose text matches `query`, deterministic order. `fields`: top-level keys (str or list values) searched;
    `extra(item) -> str` adds nested text (e.g. ingredient names). Empty / "*" query -> all items.
    1) items containing the whole folded query as a substring (state order);
    2) otherwise items sharing at least half of the query's meaningful tokens (more shared tokens first, then state order)."""
    q = _fold(query or "")
    if not q or q == "*":
        return list(items)

    def text(it):
        parts = []
        for f in fields:
            v = it.get(f)
            parts.extend(v if isinstance(v, list) else [v])
        if extra:
            parts.append(extra(it))
        return _fold(" ".join(str(p) for p in parts if p is not None)) or ""

    hits = [it for it in items if q in text(it)]
    if hits:
        return hits
    toks = [t for t in q.split() if t not in _STOP] or q.split()
    need = max(1, (len(toks) + 1) // 2)
    scored = []
    for i, it in enumerate(items):
        words = set(text(it).split())
        s = sum(1 for t in toks if t in words)
        if s >= need:
            scored.append((-s, i, it))
    return [it for _, _, it in sorted(scored, key=lambda x: (x[0], x[1]))]


def positive_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def cart_add(app, product_id, quantity):
    """Add `quantity` of products[product_id] to cart[] ({product_id, name, price, quantity}); same product -> quantity summed."""
    p = app.find("products", product_id)
    if p is None:
        return app.noop("không tìm thấy product_id")
    if p.get("in_stock") is False:
        return app.noop(f"sản phẩm {product_id} đang hết hàng")
    cart = app.state.setdefault("cart", [])
    line = next((x for x in cart if x.get("product_id") == product_id), None)
    if line is None:
        line = {"product_id": product_id, "name": p.get("name"), "price": p.get("price", 0), "quantity": 0}
        cart.append(line)
    line["quantity"] += quantity
    return {"ok": True, "cart": cart, "cart_total": sum(x.get("price", 0) * x.get("quantity", 0) for x in cart)}


def cart_checkout(app, **fields):
    """Turn cart[] into a new orders[] entry (status placed) and empty the cart."""
    cart = app.state.get("cart") or []
    if not cart:
        return app.noop("giỏ hàng đang trống")
    order = {"id": app.new_id("orders", "ord"), "items": [dict(x) for x in cart],
             "total": sum(x.get("price", 0) * x.get("quantity", 0) for x in cart), "status": "placed"}
    order.update({k: v for k, v in fields.items() if v is not None})
    app.state.setdefault("orders", []).append(order)
    app.state["cart"] = []
    return {"ok": True, "order": order}
