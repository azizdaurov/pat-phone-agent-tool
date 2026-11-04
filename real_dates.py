"""Notes and reports are read days later, when "tomorrow" means something else, so what's kept names the real date.
The models are told, and code catches what they still write. What people said on a call stays word for word in its transcript."""
import datetime
import re
from zoneinfo import ZoneInfo

# Longest first, so "the day after tomorrow" isn't read as "tomorrow".
RELATIVE = (
    (r"(?:the\s+)?day\s+after\s+tomorrow(?:'s)?|послезавтра(?:шн\w+)?", 2),
    (r"(?:the\s+)?day\s+before\s+yesterday(?:'s)?|позавчера(?:шн\w+)?", -2),
    (r"tomorrow(?:'s)?|завтра(?:шн\w+)?", 1),
    (r"yesterday(?:'s)?|вчера(?:шн\w+)?", -1),
    (r"today(?:'s)?|tonight(?:'s)?|сегодня(?:шн\w+)?", 0),
)
ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
WRITE_REAL_DATES = ("Write full calendar dates in the format named in the date table. Name the time zone with appointment times. Never write tomorrow, today, yesterday, next Friday or anything else "
                    "that only makes sense on the day it was written, in any language: this is read later.")
SAY_DATES = ("The date format above is for writing. When you say a date aloud, say it the way people do: the weekday, then the day and month in words, "
             'such as "Friday, the sixth of November", or in Russian "в пятницу, шестого ноября". Say the year only if it isn\'t this year, '
             "and never read a date out in the written format, with its dashes or slashes.")


_time_zone = None
_date_format = None


def preferences(time_zone=None, date_format=None):
    from user_profile import UserProfile
    profile = UserProfile()
    zone = time_zone or _time_zone or profile.time_zone
    form = date_format or _date_format or profile.date_format
    ZoneInfo(zone)
    if form not in ("iso", "dmy", "mdy"):
        raise ValueError("Unknown date format.")
    return zone, form


def configure(time_zone=None, date_format=None):
    """Each call has its own process; its speech and report threads share these choices."""
    global _time_zone, _date_format
    _time_zone, _date_format = preferences(time_zone, date_format)


def current_time(time_zone=None, now=None):
    zone, _ = preferences(time_zone)
    instant = now or datetime.datetime.now(datetime.timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("Supply an aware timestamp when converting a time zone.")
    return instant.astimezone(ZoneInfo(zone))


def written(day, date_format=None):
    _, form = preferences(date_format=date_format)
    if form == "dmy":
        return f"{day.day}-{day.month}-{day.year}"
    if form == "mdy":
        return f"{day.month:02}/{day.day:02}/{day.year}"
    return day.isoformat()


def date_lines(today=None, time_zone=None, date_format=None, now=None):
    """What a model needs to get dates right: working them out by itself is where they go wrong."""
    zone, form = preferences(time_zone, date_format)
    current = current_time(zone, now)
    today = today or current.date()
    def show(day):
        return written(day, form)
    days = [today + datetime.timedelta(days=offset) for offset in range(1, 8)]
    coming = ", ".join(f"{day:%A} {show(day)}" for day in days)
    next_monday = today + datetime.timedelta(days=7 - today.weekday())
    from user_profile import DATE_FORMATS
    return (f"Time zone: {zone}; current local time {current:%H:%M %z}. Date format: {DATE_FORMATS[form]}. "
            f"Today is {today:%A}, {show(today)}. Yesterday was {show(today - datetime.timedelta(days=1))}. "
            f"Tomorrow is {show(days[0])}. The coming days: {coming}. Next week starts on {show(next_monday)}. "
            "Times on this call are in this time zone. If the other person means a different zone, ask and name it explicitly.")


def day_of(when):
    """The date in a "2026-11-03 13:42" timestamp. Today if it can't be read."""
    try:
        return datetime.date.fromisoformat(str(when)[:10])
    except ValueError:
        return current_time().date()


def real_dates(value, today=None):
    """Copies text, or a report made of lists and dicts, with relative dates swapped for real ones, written the same way throughout."""
    today = today or current_time().date()
    if isinstance(value, list):
        return [real_dates(item, today) for item in value]
    if isinstance(value, dict):
        return {key: real_dates(item, today) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    for words, offset in RELATIVE:
        day = written(today + datetime.timedelta(days=offset))
        value = re.sub(rf"(?<!\w)(?:{words})(?!\w)", day, value, flags=re.IGNORECASE)
    def convert(match):
        try:
            return written(datetime.date(*map(int, match.groups())))
        except ValueError:
            return match.group(0)
    return ISO_DATE.sub(convert, value)


# Pat fact #27: Pat doesn't know how it got here.
#fisheggs
