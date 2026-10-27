"""ewallet: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Ewallet(App):
    name = "ewallet"

    @read
    def get_balance(self, **_):
        return {"ok": True, "balance": self.state.get("balance", 0)}

    @write
    def transfer(self, contact_id=None, phone=None, amount=None, note=None, **_):
        if self.state.get("balance", 0) < amount:
            return self.noop("số dư ví không đủ")
        if not contact_id and phone:  # a phone number that belongs to exactly one contact is recorded as that contact (same rule as phone.call)
            contact_id, _ = self.contact_ref(None, phone)
        self.state["balance"] -= amount
        tx = {"id": self.new_id("transactions", "tx"), "type": "transfer", "to": contact_id or phone, "amount": -amount, "note": note}
        self.state.setdefault("transactions", []).append(tx)
        return {"ok": True, "transaction": tx, "balance": self.state["balance"]}

    @write
    def topup_mobile(self, phone=None, amount=None, **_):
        if self.state.get("balance", 0) < amount:
            return self.noop("số dư ví không đủ")
        self.state["balance"] -= amount
        tx = {"id": self.new_id("transactions", "tx"), "type": "topup_mobile", "phone": phone, "amount": -amount}
        self.state.setdefault("transactions", []).append(tx)
        return {"ok": True, "transaction": tx, "balance": self.state["balance"]}

    @write
    def pay_qr(self, merchant_id=None, amount=None, **_):
        if self.state.get("balance", 0) < amount:
            return self.noop("số dư ví không đủ")
        self.state["balance"] -= amount
        tx = {"id": self.new_id("transactions", "tx"), "type": "pay_qr", "merchant_id": merchant_id, "amount": -amount}
        self.state.setdefault("transactions", []).append(tx)
        return {"ok": True, "transaction": tx, "balance": self.state["balance"]}
