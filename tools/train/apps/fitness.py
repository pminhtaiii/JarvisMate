"""fitness: one method per tool of the app.

State: {activity: {"YYYY-MM-DD": {steps, calories, distance_km}}, goal_steps: int, workouts: [{id, type, minutes, time}]}."""
from __future__ import annotations

from .base import App, read, write

WORKOUT_TYPES = ("walking", "running", "cycling", "swimming", "yoga", "gym", "football", "badminton", "other")


class Fitness(App):
    name = "fitness"

    @read
    def get_activity(self, date=None, **_):
        """One day's steps/calories; without `date`, the latest day on record. A day with no record has 0 steps."""
        days = self.state.get("activity") or {}
        if date:
            date = str(date)[:10]
        else:
            date = max(days) if days else None
        if date is None:
            return self.noop("chưa có dữ liệu hoạt động")
        day = days.get(date) or {"steps": 0, "calories": 0, "distance_km": 0}
        workouts = [w for w in self.state.get("workouts", []) if str(w.get("time") or "")[:10] == date]
        return {"ok": True, "activity": {"date": date, **day, "goal_steps": self.state.get("goal_steps"), "workouts": workouts}}

    @write
    def log_workout(self, type=None, minutes=None, time=None, **_):
        if time is None:
            time = getattr(self.session, "now", None)  # omitted: logged at current_time
        r = self.create("workouts", "wo", type=type, minutes=minutes, time=time)
        return {"ok": True, "workout": r["item"]}

    @write
    def set_goal(self, steps=None, **_):
        self.state["goal_steps"] = steps
        return {"ok": True, "goal_steps": steps}
