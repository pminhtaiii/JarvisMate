"""stocks: one method per tool of the app.
State: {holdings: [{symbol, name, quantity, avg_price, price}], orders: [], alerts: [], quotes: [{symbol, name, price, change_pct}]}.
Quotes are read from state (quotes[], then holdings[].price): deterministic, no live feed. Unknown symbols are rejected."""
from __future__ import annotations

from .base import App, read, write


def _sym(s):
    return str(s or "").strip().upper()


class Stocks(App):
    name = "stocks"

    def _quote(self, symbol):
        sym = _sym(symbol)
        for q in self.state.get("quotes", []) or []:
            if _sym(q.get("symbol")) == sym:
                return {"symbol": sym, **{k: v for k, v in q.items() if k != "symbol"}}
        for h in self.state.get("holdings", []) or []:
            if _sym(h.get("symbol")) == sym and h.get("price") is not None:
                return {"symbol": sym, "name": h.get("name"), "price": h["price"], "change_pct": h.get("change_pct", 0.0)}
        return None

    @read
    def get_quote(self, symbol=None, **_):
        q = self._quote(symbol)
        if q is None:
            return self.noop(f"không tìm thấy mã {symbol!r}")
        return {"ok": True, "quote": q}

    @read
    def get_portfolio(self, **_):
        out = self.read("holdings")
        out["total_value"] = sum((h.get("price") or 0) * (h.get("quantity") or 0) for h in out["holdings"])
        return out

    @write
    def place_order(self, symbol=None, side=None, quantity=None, price=None, **_):
        q = self._quote(symbol)
        if q is None:
            return self.noop(f"không tìm thấy mã {symbol!r}")
        if q["symbol"].endswith("INDEX") or q["symbol"] in ("VN30", "HNX30"):
            return self.noop(f"{q['symbol']} là chỉ số, không đặt lệnh được")
        if side == "sell":
            held = sum(h.get("quantity") or 0 for h in self.state.get("holdings", []) if _sym(h.get("symbol")) == q["symbol"])
            if held < quantity:
                return self.noop(f"không đủ cổ phiếu {q['symbol']} để bán (đang có {held})")
        r = self.create("orders", "ord", symbol=q["symbol"], side=side, quantity=quantity,
                        type="limit" if price is not None else "market", price=price if price is not None else q.get("price"), status="placed")
        return {"ok": True, "order": r["item"]}

    @write
    def set_price_alert(self, symbol=None, price=None, direction=None, **_):
        q = self._quote(symbol)
        if q is None:
            return self.noop(f"không tìm thấy mã {symbol!r}")
        r = self.create("alerts", "alert", symbol=q["symbol"], price=price, direction=direction, active=True)
        return {"ok": True, "alert": r["item"]}
