"""exchange_rate: one method per tool of the app. State: {rates: [{from, to, rate}]}."""
from __future__ import annotations

from .base import App, read


class ExchangeRate(App):
    name = "exchange_rate"

    @read
    def get_rate(self, from_currency=None, to_currency=None, **_):
        return self.read("rates", eq={"from": from_currency, "to": to_currency})

    def _rate(self, a, b):
        """Rate a -> b from the live table: direct, inverse, or through a common currency (VND)."""
        if a == b:
            return 1.0
        rates = self.state.get("rates", [])
        rates = [rates] if isinstance(rates, dict) else rates
        table = {}
        for r in rates:
            if isinstance(r, dict) and r.get("rate"):
                f, t = str(r.get("from", "")).upper(), str(r.get("to", "")).upper()
                table[(f, t)] = float(r["rate"])
                table.setdefault((t, f), 1.0 / float(r["rate"]))
        if (a, b) in table:
            return table[(a, b)]
        for (f, mid), r1 in list(table.items()):
            if f == a and (mid, b) in table:
                return r1 * table[(mid, b)]
        return None

    @read
    def convert(self, amount=None, from_currency=None, to_currency=None, **_):
        a, b = str(from_currency or "").strip().upper(), str(to_currency or "").strip().upper()
        rate = self._rate(a, b)
        if rate is None:
            return self.noop(f"không có tỷ giá {a}/{b}")
        try:
            result = amount * rate
            result = round(result) if b == "VND" else round(result, 2)
        except (ArithmeticError, ValueError):
            return self.noop("amount quá lớn")
        return {"ok": True, "amount": amount, "from_currency": a, "to_currency": b, "rate": round(rate, 6), "result": result}
