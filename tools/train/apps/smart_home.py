"""smart_home: one method per tool of the app."""
from __future__ import annotations

from .base import App, read, write


class SmartHome(App):
    name = "smart_home"

    @read
    def get_status(self, room=None, floor=None, type=None, **_):
        r = self.read("devices", eq={"room": room, "floor": floor, "type": type})
        if room is None and floor is None and type is None and self.state.get("scenes"):  # unfiltered status also lists the saved scenes (id, name)
            r["scenes"] = [{"id": sc.get("id"), "name": sc.get("name")} for sc in self.state["scenes"]]
        return r

    @write
    def light_set(self, device_id=None, power=None, brightness=None, color=None, **_):
        return self.patch("devices", "device_id", device_id, nested="state", require={"type": "light"}, power=power, brightness=brightness, color=color)

    @write
    def fan_set(self, device_id=None, power=None, speed=None, **_):
        return self.patch("devices", "device_id", device_id, nested="state", require={"type": "fan"}, power=power, speed=speed)

    @write
    def climate_set(self, device_id=None, mode=None, temperature=None, **_):
        return self.patch("devices", "device_id", device_id, nested="state", require={"type": "climate"}, mode=mode, temperature=temperature)

    @write
    def switch_set(self, device_id=None, power=None, **_):
        return self.patch("devices", "device_id", device_id, nested="state", power=power)

    @write
    def scene_run(self, scene_id=None, **_):
        """scenes[]: {id, name, actions: [{device_id, state: {...}}]}; every action is applied to its device's state"""
        scene = self.find("scenes", scene_id)
        if scene is None:
            return self.noop(f"không tìm thấy scene_id={scene_id!r}")
        for a in scene.get("actions", []):
            if self.find("devices", a.get("device_id")) is None:
                return self.noop(f"ngữ cảnh {scene['id']} trỏ tới thiết bị không tồn tại {a.get('device_id')!r}")
        for a in scene.get("actions", []):
            self.find("devices", a["device_id"]).setdefault("state", {}).update(a.get("state", {}))
        self.state["active_scene"] = scene["id"]
        return {"ok": True, "scene_id": scene["id"], "devices": [self.find("devices", a["device_id"]) for a in scene.get("actions", [])]}
