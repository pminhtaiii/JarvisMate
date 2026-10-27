"""banking: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Banking(App):
    name = "banking"

    @read
    def get_balance(self, **_):
        return self.read("accounts")

    @read
    def list_transactions(self, account_id=None, **_):
        return self.read("transactions", eq={"account_id": account_id})

    @read
    def list_beneficiaries(self, **_):
        return self.read("beneficiaries")

    @write
    def transfer(self, from_account_id=None, beneficiary_id=None, amount=None, note=None, **_):
        acc = self.find("accounts", from_account_id)
        ben = self.find("beneficiaries", beneficiary_id)
        if acc is None or ben is None:
            return self.noop("không tìm thấy tài khoản hoặc người thụ hưởng")
        if acc["balance"] < amount:
            return self.noop("số dư không đủ")
        acc["balance"] -= amount
        tx = {"id": self.new_id("transactions", "tx"), "account_id": acc["id"], "beneficiary_id": ben["id"], "amount": -amount, "note": note}
        self.state.setdefault("transactions", []).append(tx)
        return {"ok": True, "transaction": tx, "balance": acc["balance"]}

    @write
    def open_savings(self, from_account_id=None, amount=None, term_months=None, **_):
        acc = self.find("accounts", from_account_id)
        if acc is None:
            return self.noop("không tìm thấy from_account_id")
        if acc["balance"] < amount:
            return self.noop("số dư không đủ")
        acc["balance"] -= amount
        r = self.create("savings", "sav", account_id=acc["id"], amount=amount, term_months=term_months, status="active")
        return {"ok": True, "savings": r["item"], "balance": acc["balance"]}
