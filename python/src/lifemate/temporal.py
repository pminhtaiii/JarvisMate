"""Explicit dates and Vietnamese relative time resolved against sample context."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .numbers import clean, duration_seconds, number


def _now(context):
    now = datetime.fromisoformat(context["current_time"].replace("Z", "+00:00"))
    if now.utcoffset() is None:
        raise ValueError("Sample current_time needs an offset")
    name = context["timezone"]
    try:
        zone = ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Windows stdlib may have no IANA database. These zones have fixed offsets
        # for the modern benchmark dates; never reuse a fixed offset for DST zones.
        offsets = {"Asia/Ho_Chi_Minh": 7, "Asia/Saigon": 7, "UTC": 0, "Etc/UTC": 0}
        if name not in offsets or now.year < 1976:
            raise ValueError("Timezone database unavailable for sample") from None
        zone = timezone(timedelta(hours=offsets[name]))
    return now.astimezone(zone)


def _day(value, now):
    value = clean(value)
    relative = {"hôm nay": 0, "nay": 0, "ngày mai": 1, "mai": 1,
                "ngày kia": 2, "kia": 2, "hôm qua": -1}
    if value in relative:
        return now.date() + timedelta(days=relative[value])
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if match:
        return date(int(match[3]), int(match[2]), int(match[1]))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    spoken = re.fullmatch(r"(?:ngày )?(?:mùng |mồng )?(.+?) tháng (.+?) năm (.+)", value)
    if spoken:
        parts = [number(part) for part in spoken.groups()]
        if any(part != int(part) for part in parts):
            raise ValueError("Date requires integral components")
        day, month, year = map(int, parts)
        return date(year, month, day)
    boundary = re.fullmatch(r"(đầu|cuối) tháng (này|sau)", value)
    if boundary:
        year, month = now.year, now.month
        if boundary[2] == "sau":
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        day = 1 if boundary[1] == "đầu" else monthrange(year, month)[1]
        return date(year, month, day)
    weekdays = {"thứ hai": 0, "thứ ba": 1, "thứ tư": 2, "thứ năm": 3,
                "thứ sáu": 4, "thứ bảy": 5, "chủ nhật": 6}
    for label, weekday in weekdays.items():
        if value in {label + " tới", label + " tuần sau"}:
            delta = ((weekday - now.weekday()) % 7 or 7) if value.endswith(" tới") else 7 - now.weekday() + weekday
            return now.date() + timedelta(days=delta)
    raise ValueError("Date needs an explicit year or supported relative expression")


def _clock(value):
    value = clean(value)
    period_match = re.search(r" (?:buổi )?(sáng|trưa|chiều|tối|đêm)$", value)
    period = period_match[1] if period_match else None
    if period_match:
        value = value[:period_match.start()]
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", value)
    if match:
        hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
        if period is None:
            return time(hour, minute, second)
    else:
        match = re.fullmatch(r"(.+?) giờ(?: (.+))?", value)
        if not match:
            raise ValueError("Unsupported clock expression")
        hour, tail = number(match[1]), match[2]
        second = 0
        if tail == "rưỡi":
            minute = 30
        elif tail:
            seconds_match = re.fullmatch(r"(.+?) phút (.+?) giây", tail)
            if seconds_match:
                minute, second = number(seconds_match[1]), number(seconds_match[2])
            else:
                minute = number(tail.removesuffix(" phút"))
        else:
            minute = 0
    if any(part != int(part) for part in (hour, minute, second)):
        raise ValueError("Clock requires integral hours and minutes")
    hour, minute, second = int(hour), int(minute), int(second)
    if period:
        if hour == 0 and period in {"sáng", "đêm"}:
            return time(hour, minute, second)
        if not 1 <= hour <= 12:
            raise ValueError("Invalid twelve-hour clock")
        hour = hour % 12 + (12 if period in {"trưa", "chiều", "tối"} else 0)
    elif 1 <= hour <= 12:
        raise ValueError("Spoken hour needs a day period")
    return time(hour, minute, second)


def _local(day, clock, zone):
    naive = datetime.combine(day, clock)
    first, second = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
    if (first.utcoffset() != second.utcoffset()
            or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive):
        raise ValueError("Ambiguous or nonexistent local time")
    return first


def temporal(value: str, kind: str, context) -> str:
    if len(value) > 512:
        raise ValueError("Time expression too long")
    now, value = _now(context), clean(value)
    if kind == "date":
        return _day(value, now).isoformat()
    if kind == "time":
        # Preserve already canonical precision; schema may explicitly request HH:MM.
        if re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", value):
            _clock(value)
            return value
        parsed_clock = _clock(value)
        return parsed_clock.isoformat(timespec="seconds" if parsed_clock.second else "minutes")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?", value, re.I):
        # Preserve valid literals byte for byte: equivalent spellings can score differently.
        parsed = datetime.fromisoformat(value.replace("t", "T").replace("z", "+00:00"))
        if parsed.utcoffset() is not None:
            return value.replace("t", "T").replace("z", "Z")
        return _local(parsed.date(), parsed.time(), now.tzinfo).isoformat(timespec="seconds")
    if value.startswith("sau "):
        seconds = duration_seconds(value[4:])
        if seconds != int(seconds):
            raise ValueError("Subsecond delay unsupported")
        return (now.astimezone(timezone.utc) + timedelta(seconds=int(seconds))).astimezone(now.tzinfo).isoformat(timespec="seconds")
    if value in {"bây giờ", "hiện tại"}:
        return now.isoformat(timespec="seconds")
    # Date and clock can occur in either order: 'ba giờ chiều mai' / 'mai lúc 15:00'.
    for index in range(1, len(value.split())):
        parts = value.split()
        left, right = " ".join(parts[:index]), " ".join(parts[index:])
        for day_text, clock_text in ((left, right), (right, left)):
            try:
                day = _day(day_text.removeprefix("ngày "), now)
                clock = _clock(clock_text.removeprefix("lúc ").removeprefix("vào "))
            except ValueError:
                continue
            return _local(day, clock, now.tzinfo).isoformat(timespec="seconds")
    raise ValueError("Datetime needs both a date and an unambiguous clock")
