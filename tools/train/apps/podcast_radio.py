"""podcast_radio: one method per tool of the app.

State: {shows: [{id, name, host, category}], episodes: [{id, show_id, title, number, duration_min, published}],
stations: [{id, name, frequency}], subscriptions: [show_id], queue: [episode_id], now_playing: {...} | null}."""
from __future__ import annotations

from ..utils import _fold
from .base import App, read, write


class PodcastRadio(App):
    name = "podcast_radio"

    @read
    def search(self, query=None, **_):
        """Shows matching by name/host/category, plus every episode of those shows and episodes whose own title matches; stations by name."""
        shows = self.read("shows", contains={("name", "host", "category"): query})["shows"]
        eps = self.read("episodes", contains={("title",): query})["episodes"]
        hit = {s["id"] for s in shows} | {e.get("show_id") for e in eps}
        shows = [s for s in self.state.get("shows", []) if s.get("id") in hit]
        episodes = [e for e in self.state.get("episodes", []) if e.get("show_id") in {s["id"] for s in shows}]
        stations = self.read("stations", contains={("name", "frequency"): query})["stations"]
        return {"ok": True, "shows": shows, "episodes": episodes, "stations": stations}

    def _station(self, station):
        q = _fold(station)
        stations = self.state.get("stations") or []
        if not stations:
            return {"name": station}
        exact = [s for s in stations if _fold(s.get("name")) == q or _fold(s.get("frequency")) == q]
        hits = exact or [s for s in stations if q and (q in _fold(s.get("name")) or q in _fold(s.get("frequency")))]
        return hits[0] if len(hits) == 1 else None

    @write
    def play(self, episode_id=None, station=None, **_):
        if episode_id:
            e = self.find("episodes", episode_id)
            if e is None:
                return self.noop("không tìm thấy episode_id")
            self.state["now_playing"] = {"episode_id": e["id"], "show_id": e.get("show_id"), "status": "playing"}
            q = self.state.get("queue") or []
            if e["id"] in q:  # playing a queued episode takes it off the queue
                q.remove(e["id"])
        elif station:
            s = self._station(station)
            if s is None:
                return self.noop(f"không tìm thấy kênh radio {station!r}")
            self.state["now_playing"] = {"station_id": s.get("id"), "station": s.get("name"), "status": "playing"}
        else:
            return self.noop("cần episode_id hoặc station")
        return {"ok": True, "now_playing": self.state["now_playing"]}

    @write
    def subscribe(self, show_id=None, **_):
        if self.find("shows", show_id) is None:
            return self.noop("không tìm thấy show_id")
        subs = self.state.setdefault("subscriptions", [])
        if show_id in subs:
            return self.noop("đã theo dõi kênh này")
        subs.append(show_id)
        return {"ok": True, "subscriptions": subs}

    @write
    def queue(self, episode_id=None, **_):
        if self.find("episodes", episode_id) is None:
            return self.noop("không tìm thấy episode_id")
        q = self.state.setdefault("queue", [])
        if episode_id in q:
            return self.noop("tập này đã có trong hàng đợi")
        q.append(episode_id)
        return {"ok": True, "queue": q}
