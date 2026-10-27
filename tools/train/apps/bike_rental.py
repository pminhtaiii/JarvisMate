"""bike_rental: one method per tool of the app.

State: {bikes: [{id, name, station, available, price_per_hour}], reservations: [{id, bike_id, station, status}]}."""
from __future__ import annotations

from .base import App, read, write
from ..utils import _fold


class BikeRental(App):
    name = "bike_rental"

    @read
    def find_bikes(self, near=None, **_):
        r = self.read("bikes", contains={("station", "name"): near})
        if near and not r.get("bikes"):  # a full address ('203 Lê Văn Sỹ, Quận 3') still finds 'Trạm Lê Văn Sỹ': match any word of 4+ letters
            q = " " + " ".join(_fold(near).replace(",", " ").split()) + " "
            def station_in(b):
                toks = [t for t in _fold(b.get("station") or "").split() if t not in ("tram", "ga", "ben")]
                return bool(toks) and all(f" {t} " in q for t in toks)
            hits = [b for b in self.state.get("bikes", []) if station_in(b)]
            if hits:
                r = {"ok": True, "bikes": hits}
        return r

    @write
    def reserve(self, bike_id=None, **_):
        b = self.find("bikes", bike_id)
        if b is None:
            return self.noop(f"không tìm thấy bike_id={bike_id!r}")
        if not b.get("available", True):
            return self.noop("xe đang được thuê, chọn xe khác")
        b["available"] = False
        r = self.create("reservations", "brs", bike_id=b["id"], station=b.get("station"), status="reserved")
        return {"ok": True, "reservation": r["item"]}
