"""subscriptions: one method per tool of the app. State: {subscriptions: [{id, name, price, next_billing, status}]}."""
from __future__ import annotations

from .base import App, read, write


class Subscriptions(App):
    name = "subscriptions"

    @read
    def list(self, **_):
        return self.read("subscriptions")

    @write
    def cancel(self, subscription_id=None, **_):
        sub = self.find("subscriptions", subscription_id)
        if sub is None:
            return self.noop(f"không tìm thấy subscription_id={subscription_id!r}")
        if sub.get("status") == "cancelled":
            return self.noop(f"gói {subscription_id} đã huỷ trước đó")
        sub["status"] = "cancelled"
        return {"ok": True, "item": sub}
