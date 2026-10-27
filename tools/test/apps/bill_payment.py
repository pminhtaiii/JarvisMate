"""bill_payment: one method per tool of the app."""
from __future__ import annotations

from ..utils import _eq
from .base import App, read, write


class BillPayment(App):
    name = "bill_payment"

    @read
    def list_bills(self, type=None, **_):
        return self.read("bills", eq={"type": type}, where={"paid": False})

    @write
    def pay(self, bill_id=None, source=None, **_):
        bill = self.find("bills", bill_id)
        if bill is None:
            return self.noop("không tìm thấy bill_id")
        if bill.get("paid"):
            return self.noop("hoá đơn đã thanh toán")
        amount = bill.get("amount", 0)
        if source == "ewallet":  # paying from the wallet needs the wallet and enough balance; the wallet is debited
            wallet = self.session.states.get("ewallet")
            if wallet is None:
                return self.noop("chưa cài ví điện tử")
            if wallet.get("balance", 0) < amount:
                return self.noop(f"số dư ví không đủ ({wallet.get('balance', 0)} < {amount})")
            wallet["balance"] -= amount
            wallet.setdefault("transactions", []).append({"id": self.new_id("transactions", "tx", state=wallet), "type": "bill_payment", "bill_id": bill["id"], "amount": -amount})
        bill["paid"] = True
        bill["paid_with"] = source
        return {"ok": True, "bill": bill}

    @write
    def schedule_autopay(self, type=None, enabled=None, **_):
        """autopays[]: one entry per bill type {id, type, enabled}; calling again for the same type updates it"""
        for ap in self.state.get("autopays", []):
            if _eq(ap.get("type"), type):
                ap["enabled"] = enabled
                return {"ok": True, "autopay": ap}
        r = self.create("autopays", "ap", type=type, enabled=enabled)
        return {"ok": True, "autopay": r["item"]}
