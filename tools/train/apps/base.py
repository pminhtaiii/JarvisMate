"""App base class and the @read / @write / @meta markers (meta = system tool, touches no state; same kinds as the catalog). One subclass per app lives in its own module of this package."""
from __future__ import annotations

from ..utils import _eq, _fold


def read(fn):
    fn.kind = "read"
    return fn


def write(fn):
    fn.kind = "write"
    return fn


def meta(fn):
    fn.kind = "meta"
    return fn


class App:
    """Base: generic operations on the app's collections. `self.state` is the app's part of state.json; `self.session` the whole sample."""
    name = ""

    def __init__(self, session, state: dict):
        self.session = session
        self.state = state

    # -- generic helpers ---------------------------------------------------------------------
    @staticmethod
    def noop(message):
        """A call that ran but had nothing to do (unknown ID, not enough balance, already cancelled...): not an error,
        state unchanged. Schema errors are the executor's job (zaic_tools.validate), never the app's."""
        return {"ok": True, "done": False, "message": message}

    def empty(self, collection):
        """Read result with nothing found."""
        return {"ok": True, collection: []}

    def find(self, collection, item_id):
        for it in self.state.get(collection, []):
            if it.get("id") == item_id:
                return it
        return None

    def new_id(self, collection, prefix, state=None):
        state = self.state if state is None else state
        existing = {it.get("id") for it in state.get(collection, [])}
        n = len(existing) + 1
        while f"{prefix}_{n:02d}" in existing:
            n += 1
        return f"{prefix}_{n:02d}"

    def read(self, collection, eq=None, where=None, contains=None, prefix=None, date_range=None, drop=()):
        """Filter a collection. eq: {field: value} (None values ignored, strings compared case-insensitively);
        where: {field: value} fixed; contains: {fields: query} substring after lower + strip diacritics;
        prefix: {field: value}; date_range: (field, from, to) on the first 10 chars; drop: fields removed from the output."""
        items = self.state.get(collection, [])
        if isinstance(items, dict):
            items = [items]
        out = []
        for it in items:
            ok = all(it.get(k) == v for k, v in (where or {}).items())
            for field, v in (eq or {}).items():
                if v is not None and not _eq(it.get(field), v):
                    ok = False
            for fields, q in (contains or {}).items():
                q = _fold(q)
                if q and q != "*":
                    ok = ok and any(q in _fold(str(it.get(f) or "")) for f in fields)  # plain substring after lower + strip diacritics
            for field, v in (prefix or {}).items():
                if v:
                    ok = ok and str(it.get(field, "")).startswith(v)
            if date_range:
                field, a_from, a_to = date_range
                v = str(it.get(field, ""))[:10]
                if a_from and v < a_from:
                    ok = False
                if a_to and v > a_to:
                    ok = False
            if ok:
                out.append({k: v for k, v in it.items() if k not in drop})
        return {"ok": True, collection: out}

    def create(self, collection, prefix, defaults=None, **fields):
        item = dict(defaults or {})
        item.update({k: v for k, v in fields.items() if v is not None})
        item = {"id": self.new_id(collection, prefix), **item}
        self.state.setdefault(collection, []).append(item)
        return {"ok": True, "id": item["id"], "item": item}

    def patch(self, collection, id_arg, item_id, nested=None, require=None, set=None, **fields):
        item = self.find(collection, item_id)
        if item is None:
            return self.noop(f"không tìm thấy {id_arg}={item_id!r}")
        for k, v in (require or {}).items():
            if item.get(k) != v:
                return self.noop(f"thiết bị {item['id']} không phải loại {v}")
        target = item.setdefault(nested, {}) if nested else item
        target.update(set or {})
        target.update({k: v for k, v in fields.items() if v is not None})
        return {"ok": True, "item": item}

    def contact_ref(self, contact_id=None, phone_number=None):
        """(contact_id, phone_number) completed from the contacts app when it is installed in the sample: a contact_id fills
        phone_number with that contact's phone; a phone_number equal to exactly one contact's phone (digits compared, +84 = 0)
        fills contact_id (and is stored as the contact's phone). Both given, or no contacts app: returned unchanged."""
        book = ((getattr(self.session, "states", None) or {}).get("contacts") or {}).get("contacts")
        if not isinstance(book, list) or (contact_id and phone_number):
            return contact_id, phone_number
        if contact_id:
            c = next((c for c in book if isinstance(c, dict) and c.get("id") == contact_id), None)
            return contact_id, (c or {}).get("phone") or phone_number
        if phone_number:
            def digits(v):
                d = "".join(ch for ch in str(v) if ch.isdigit())
                return "0" + d[2:] if d.startswith("84") and len(d) == 11 else d
            hits = [c for c in book if isinstance(c, dict) and c.get("phone") and digits(c["phone"]) == digits(phone_number)]
            if len(hits) == 1:
                return hits[0].get("id"), hits[0]["phone"]
        return contact_id, phone_number

    def delete(self, collection, id_arg, item_id):
        item = self.find(collection, item_id)
        if item is None:
            return self.noop(f"không tìm thấy {id_arg}={item_id!r}")
        self.state[collection].remove(item)
        return {"ok": True}
