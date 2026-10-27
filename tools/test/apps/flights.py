"""flights: one method per tool of the app. State: {flights: [{id, origin, destination, date, depart, arrive, airline, price, flight_no}], bookings: []}.
origin/destination are stored as IATA codes; search accepts the code, the city name or the airport name (diacritics ignored)."""
from __future__ import annotations

from ..utils import _fold
from .base import App, read, write

# IATA code -> city / airport names it answers to (compared after _fold: lower-case, no diacritics)
AIRPORTS = {
    "SGN": ["Hồ Chí Minh", "Sài Gòn", "Tân Sơn Nhất", "TP HCM", "TP.HCM", "TPHCM", "HCM", "HCMC"],
    "HAN": ["Hà Nội", "Nội Bài"],
    "DAD": ["Đà Nẵng"],
    "HUI": ["Huế", "Phú Bài"],
    "VCA": ["Cần Thơ"],
    "DLI": ["Đà Lạt", "Liên Khương"],
    "UIH": ["Quy Nhơn", "Phù Cát"],
    "PQC": ["Phú Quốc"],
    "CXR": ["Nha Trang", "Cam Ranh"],
    "VDH": ["Đồng Hới", "Quảng Bình"],
    "HPH": ["Hải Phòng", "Cát Bi"],
    "VII": ["Vinh"],
    "THD": ["Thanh Hoá", "Thọ Xuân"],
    "VCL": ["Chu Lai", "Quảng Nam"],
    "TBB": ["Tuy Hoà", "Phú Yên"],
    "PXU": ["Pleiku", "Gia Lai"],
    "BMV": ["Buôn Ma Thuột", "Đắk Lắk"],
    "VCS": ["Côn Đảo"],
    "VKG": ["Rạch Giá"],
    "CAH": ["Cà Mau"],
    "DIN": ["Điện Biên"],
    "VDO": ["Vân Đồn", "Quảng Ninh"],
}
# each name also answers to its spelling without spaces ('Hanoi', 'Danang', 'Saigon', 'Nhatrang')
_NAMES = {code: sorted({v for n in names for v in (_fold(n), _fold(n).replace(" ", ""))}) for code, names in AIRPORTS.items()}


# words that may surround a city / airport name in a query without changing it ('thành phố Hồ Chí Minh', 'sân bay Nội Bài')
_GENERIC = {"thanh", "pho", "tp", "san", "bay", "tinh", "thanhpho", "sanbay", "ga", "city", "airport"}


def _place_match(stored, query):
    """True when `query` (code, city or airport name, any case/diacritics) designates the stored IATA code.
    A name must match whole words and whatever else the query says must be generic ('thành phố', 'sân bay'):
    'thành phố Hồ Chí Minh' -> SGN, but 'Vĩnh Long' is not Vinh (VII)."""
    if query is None:
        return True
    q, code = _fold(query) or "", str(stored or "").upper()
    if not q:
        return True
    if q == code.lower():
        return True
    q_words = q.split()
    for n in _NAMES.get(code, []):
        if n == q:
            return True
        n_words = n.split()
        for i in range(len(q_words) - len(n_words) + 1):
            if q_words[i:i + len(n_words)] == n_words and set(q_words[:i] + q_words[i + len(n_words):]) <= _GENERIC:
                return True
    return False


class Flights(App):
    name = "flights"

    @read
    def search(self, origin=None, destination=None, date=None, **_):
        """origin/destination: IATA code (SGN, HAN, DAD...) or city/airport name; date exact (YYYY-MM-DD)."""
        r = self.read("flights", eq={"date": date})
        r["flights"] = [f for f in r["flights"] if _place_match(f.get("origin"), origin) and _place_match(f.get("destination"), destination)]
        return r

    @write
    def book(self, flight_id=None, passengers=None, seat_class=None, **_):
        f = self.find("flights", flight_id)
        if f is None:
            return self.noop("không tìm thấy flight_id")
        b = {"id": self.new_id("bookings", "bk"), "flight_id": f["id"], "passengers": passengers if passengers is not None else 1,
             "seat_class": seat_class if seat_class is not None else "economy", "status": "confirmed"}
        self.state.setdefault("bookings", []).append(b)
        return {"ok": True, "booking": b}

    @read
    def my_bookings(self, **_):
        flights = {f["id"]: f for f in self.state.get("flights", [])}
        out = []
        for b in self.state.get("bookings", []):
            f = flights.get(b.get("flight_id"), {})
            out.append({**b, "flight": {k: f[k] for k in ("origin", "destination", "date", "depart", "arrive", "airline") if k in f}})
        return {"ok": True, "bookings": out}

    @write
    def cancel(self, booking_id=None, **_):
        return self.patch("bookings", "booking_id", booking_id, set={"status": "cancelled"})

    @write
    def check_in(self, booking_id=None, **_):
        b = self.find("bookings", booking_id)
        if b is None:
            return self.noop("không tìm thấy booking_id")
        if b.get("status") == "cancelled":
            return self.noop("vé đã huỷ")
        if b.get("checked_in"):
            return self.noop("vé đã làm thủ tục")
        b["checked_in"] = True
        return {"ok": True, "booking": b}
