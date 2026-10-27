"""music: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Music(App):
    name = "music"

    @read
    def list_tracks(self, **_):
        """the library: tracks and, when the user has any, their playlists (the catalog's "bài hát và playlist")"""
        r = self.read("tracks")
        if self.state.get("playlists"):
            r["playlists"] = self.read("playlists")["playlists"]
        return r

    @write
    def play(self, track_id=None, playlist_id=None, **_):
        if track_id:
            t = self.find("tracks", track_id)
            if t is None:
                return self.noop("không tìm thấy track_id")
            self.state["now_playing"] = {"track_id": t["id"], "title": t.get("title"), "status": "playing"}
        elif playlist_id:
            p = self.find("playlists", playlist_id)
            if p is None:
                return self.noop("không tìm thấy playlist_id")
            self.state["now_playing"] = {"playlist_id": p["id"], "name": p.get("name"), "status": "playing"}
        else:  # x-one-of in the catalog; kept only so the method cannot crash
            return self.noop("cần track_id hoặc playlist_id")
        return {"ok": True, "now_playing": self.state["now_playing"]}

    @write
    def control(self, action=None, volume=None, **_):
        np_ = self.state.get("now_playing")
        if action == "volume":
            self.state["volume"] = volume
            return {"ok": True, "volume": self.state["volume"]}
        if np_ is None:
            return self.noop("không có gì đang phát")
        np_["status"] = {"pause": "paused", "resume": "playing"}.get(action, np_.get("status"))
        return {"ok": True, "now_playing": np_}

    @write
    def add_to_playlist(self, track_id=None, playlist_id=None, **_):
        if self.find("tracks", track_id) is None:
            return self.noop("không tìm thấy track_id")
        pl = self.find("playlists", playlist_id)
        if pl is None:
            return self.noop("không tìm thấy playlist_id")
        ids = pl.setdefault("track_ids", [])
        if track_id in ids:
            return self.noop("bài đã có trong playlist")
        ids.append(track_id)
        return {"ok": True, "playlist": pl}
