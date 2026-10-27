"""tv: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class Tv(App):
    name = "tv"

    @read
    def guide(self, channel=None, **_):
        r = self.read("programs", eq={"channel": channel})
        if channel and not r.get("programs"):  # 'S+' also finds 'S+ Sport': fall back to a substring match on the channel name
            r = self.read("programs", contains={("channel",): channel})
        r["channels"] = list(self.state.get("channels", []))  # the channel list (tune only accepts these), so guide -> tune is the natural trajectory
        return r

    @write
    def tune(self, channel=None, **_):
        if channel not in self.state.get("channels", []):
            return self.noop(f"không có kênh {channel!r}")
        self.state["power"], self.state["channel"] = "on", channel
        return {"ok": True, "channel": channel}

    @write
    def control(self, action=None, volume=None, **_):
        if action in ("on", "off"):
            self.state["power"] = action
        elif action == "volume":
            self.state["volume"] = volume
        elif action == "mute":
            self.state["muted"] = True
        return {"ok": True, "power": self.state.get("power"), "volume": self.state.get("volume")}

    @write
    def record(self, program_id=None, **_):
        """recordings[]: {id, program_id, channel, start, status}"""
        prog = self.find("programs", program_id)
        if prog is None:
            return self.noop(f"không tìm thấy program_id={program_id!r}")
        if any(r.get("program_id") == program_id and r.get("status") == "scheduled" for r in self.state.get("recordings", [])):
            return self.noop("chương trình đã được đặt ghi")
        r = self.create("recordings", "rec", program_id=prog["id"], channel=prog.get("channel"), start=prog.get("start"), status="scheduled")
        return {"ok": True, "recording": r["item"]}
