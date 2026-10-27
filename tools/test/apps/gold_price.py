"""gold_price: one method per tool of the app."""
from __future__ import annotations

from .base import App, read


class GoldPrice(App):
    name = "gold_price"

    @read
    def get_price(self, type=None, **_):
        return self.read("prices", eq={"type": type})
