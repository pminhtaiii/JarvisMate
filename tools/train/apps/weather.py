"""weather: one method per tool of the app."""
from __future__ import annotations

from .base import App, read


class Weather(App):
    name = "weather"

    @read
    def get_current(self, location=None, **_):
        r = self.read("current", eq={"location": location})
        return r if r["current"] or not location else self.read("current")  # unknown/sub-city location: the user's city

    @read
    def get_forecast(self, location=None, date=None, **_):
        r = self.read("forecast", eq={"location": location, "date": date})
        return r if r["forecast"] or not location else self.read("forecast", eq={"date": date})
