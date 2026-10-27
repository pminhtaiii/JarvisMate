"""lottery: one method per tool of the app."""
from __future__ import annotations

from .base import App, read
from ..utils import _eq, _fold

PROVINCE_ALIAS = {"sai gon": "TP.HCM", "ho chi minh": "TP.HCM", "tp ho chi minh": "TP.HCM", "tp. ho chi minh": "TP.HCM", "thanh pho ho chi minh": "TP.HCM", "tphcm": "TP.HCM", "hcm": "TP.HCM",
                  "ha noi": "Hà Nội", "hanoi": "Hà Nội", "da nang": "Đà Nẵng", "danang": "Đà Nẵng", "dong nai": "Đồng Nai"}


def _province(p):
    """Spoken names of a draw ('Sài Gòn', 'Hồ Chí Minh', 'thành phố Hồ Chí Minh') map to the canonical key."""
    if not p:
        return p
    key = _fold(str(p))
    for pre in ("dai ", "tp. ", "tp ", "thanh pho "):
        if key.startswith(pre) and key[len(pre):] in PROVINCE_ALIAS:
            key = key[len(pre):]
    return PROVINCE_ALIAS.get(key, p)


class Lottery(App):
    name = "lottery"

    @read
    def get_results(self, province=None, date=None, **_):
        return self.read("results", eq={"province": _province(province), "date": date})

    @read
    def check_ticket(self, province=None, date=None, number=None, **_):
        province = _province(province)
        for r in self.state.get("results", []):
            if _eq(r.get("province"), province) and r.get("date") == date:
                num = str(number if number is not None else "")
                won = [p for p, v in r.get("prizes", {}).items() if num and num.endswith(str(v)[-len(num):]) and str(v).endswith(num[-len(str(v)):])]
                return {"ok": True, "won": bool(won), "prizes": won}
        return self.noop("chưa có kết quả cho đài/ngày này")
