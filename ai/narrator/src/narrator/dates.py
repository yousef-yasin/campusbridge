"""Dates, times and remaining time said naturally (Levantine month names in Arabic)."""
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional, Tuple, Union

from .errors import InputError
from .words import count

MONTHS_AR = ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول",
             "تشرين الأول", "تشرين الثاني", "كانون الأول"]
DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

When = Union[str, datetime, date]


def parse(value: When, tz: tzinfo, field: str = "date") -> Tuple[datetime, bool]:
    """(aware datetime in tz, has_time). ISO strings: '2026-11-15', '2026-11-15T10:00+03:00', 'Z'.

    A value without a zone is taken as local time in tz.
    """
    if isinstance(value, datetime):
        dt, has_time = value, True
    elif isinstance(value, date):
        dt, has_time = datetime.combine(value, time()), False
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise InputError(f"{field}: not an ISO date or date-time: {value!r}") from None
        has_time = "T" in text or " " in text
    else:
        raise InputError(f"{field}: expected an ISO date or date-time, got {value!r}")
    dt = dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
    return dt, has_time


def say_date(dt: datetime, lang: str, now: Optional[datetime] = None) -> str:
    """'الأحد 15 تشرين الثاني' (+ year when it is not this year) / 'Sunday 15 November'."""
    year = "" if now is not None and now.year == dt.year else f" {dt.year}"
    if lang == "en":
        return f"{DAYS_EN[dt.weekday()]} {dt.day} {MONTHS_EN[dt.month - 1]}{year}"
    return f"{DAYS_AR[dt.weekday()]} {dt.day} {MONTHS_AR[dt.month - 1]}{year}"


def _period_ar(hour: int) -> str:
    if hour < 12:
        return "صباحاً"
    if hour == 12:
        return "ظهراً"
    return "بعد الظهر" if hour < 17 else "مساءً"


def say_time(dt: datetime, lang: str) -> str:
    """'الساعة 9 ونصف صباحاً', 'الساعة 11 و59 دقيقة مساءً' / '9:30 AM', 'midnight'."""
    h, m = dt.hour, dt.minute
    if lang == "en":
        if (h, m) == (0, 0):
            return "midnight"
        if (h, m) == (12, 0):
            return "noon"
        clock = f"{h % 12 or 12}" + (f":{m:02d}" if m else "")
        return f"{clock} {'AM' if h < 12 else 'PM'}"
    if (h, m) == (0, 0):
        return "الساعة 12 منتصف الليل"
    if m == 45 and h != 23:
        nxt = h + 1
        return f"الساعة {nxt % 12 or 12} إلا ربع {_period_ar(nxt)}"
    minutes = {0: "", 15: " وربع", 30: " ونصف"}.get(m, f" و{count(m, 'minute', 'ar')}")
    return f"الساعة {h % 12 or 12}{minutes} {_period_ar(h)}"


def say_when(value: When, lang: str, tz: tzinfo, now: datetime, field: str = "date") -> str:
    """Date and time: 'اليوم الساعة 10 صباحاً', 'غداً الساعة ...', 'الخميس 26 تشرين الثاني الساعة ...'."""
    dt, has_time = parse(value, tz, field)
    days = (dt.date() - now.astimezone(tz).date()).days
    relative = {0: ("اليوم", "today"), 1: ("غداً", "tomorrow"), -1: ("أمس", "yesterday")}.get(days)
    day = (relative[1] if lang == "en" else relative[0]) if relative else say_date(dt, lang, now)
    if not has_time:
        return day
    return f"{day} at {say_time(dt, lang)}" if lang == "en" else f"{day} {say_time(dt, lang)}"


def say_duration(delta: timedelta, lang: str) -> str:
    """'3 أيام', 'يوم و5 ساعات', 'ساعتين', 'أقل من دقيقة' / '1 day and 5 hours'."""
    minutes = int(abs(delta.total_seconds()) // 60)
    days, hours, mins = minutes // 1440, minutes % 1440 // 60, minutes % 60
    if days:
        units = [(days, "day")] + ([(hours, "hour")] if days < 3 and hours else [])
    elif hours:
        units = [(hours, "hour")] + ([(mins, "minute")] if hours < 3 and mins else [])
    elif mins:
        units = [(mins, "minute")]
    else:
        return "less than a minute" if lang == "en" else "أقل من دقيقة"
    parts = [count(n, noun, lang, one=len(units) == 1) for n, noun in units]
    return " and ".join(parts) if lang == "en" else " و".join(parts)


def say_remaining(deadline: When, lang: str, tz: tzinfo, now: datetime, field: str = "deadline") -> str:
    """'باقي 3 أيام' / '3 days left'; 'انتهى الموعد منذ يومين' / 'the deadline passed 2 days ago'."""
    dt, _ = parse(deadline, tz, field)
    delta = dt - now
    span = say_duration(delta, lang)
    if delta.total_seconds() >= 0:
        return f"{span} left" if lang == "en" else f"باقي {span}"
    return f"the deadline passed {span} ago" if lang == "en" else f"انتهى الموعد منذ {span}"


def say_until(value: When, lang: str, tz: tzinfo, now: datetime, field: str = "date") -> str:
    """'بعد 30 دقيقة' / 'in 30 minutes'; 'قبل 3 أيام' / '3 days ago' for past times."""
    dt, _ = parse(value, tz, field)
    delta = dt - now
    span = say_duration(delta, lang)
    if delta.total_seconds() >= 0:
        return f"in {span}" if lang == "en" else f"بعد {span}"
    return f"{span} ago" if lang == "en" else f"قبل {span}"
