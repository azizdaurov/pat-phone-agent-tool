"""Notes and reports are read days later, when "tomorrow" means something else, so what's kept names the real date.
The models are told, and code catches what they still write. What people said on a call stays word for word in its transcript."""
import datetime
import re

# Longest first, so "the day after tomorrow" isn't read as "tomorrow".
RELATIVE = (
    (r"(?:the\s+)?day\s+after\s+tomorrow(?:'s)?|послезавтра(?:шн\w+)?", 2),
    (r"(?:the\s+)?day\s+before\s+yesterday(?:'s)?|позавчера(?:шн\w+)?", -2),
    (r"tomorrow(?:'s)?|завтра(?:шн\w+)?", 1),
    (r"yesterday(?:'s)?|вчера(?:шн\w+)?", -1),
    (r"today(?:'s)?|tonight(?:'s)?|сегодня(?:шн\w+)?", 0),
)
ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
WRITE_REAL_DATES = ("Write every date as day-month-year, such as 4-11-2026. Never write tomorrow, today, yesterday, next Friday or anything else "
                    "that only makes sense on the day it was written, in any language: this is read later.")


def written(day):
    return f"{day.day}-{day.month}-{day.year}"


def date_lines(today=None):
    """What a model needs to get dates right: working them out by itself is where they go wrong."""
    today = today or datetime.date.today()
    days = [today + datetime.timedelta(days=offset) for offset in range(1, 8)]
    coming = ", ".join(f"{day:%A} {written(day)}" for day in days)
    next_monday = today + datetime.timedelta(days=7 - today.weekday())
    return (f"Today is {today:%A}, {written(today)}. Yesterday was {written(today - datetime.timedelta(days=1))}. "
            f"Tomorrow is {written(days[0])}. The coming days: {coming}. Next week starts on {written(next_monday)}.")


def day_of(when):
    """The date in a "2026-11-03 13:42" timestamp. Today if it can't be read."""
    try:
        return datetime.date.fromisoformat(str(when)[:10])
    except ValueError:
        return datetime.date.today()


def real_dates(value, today=None):
    """Copies text, or a report made of lists and dicts, with relative dates swapped for real ones, written the same way throughout."""
    today = today or datetime.date.today()
    if isinstance(value, list):
        return [real_dates(item, today) for item in value]
    if isinstance(value, dict):
        return {key: real_dates(item, today) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    for words, offset in RELATIVE:
        day = written(today + datetime.timedelta(days=offset))
        value = re.sub(rf"(?<!\w)(?:{words})(?!\w)", day, value, flags=re.IGNORECASE)
    return ISO_DATE.sub(lambda match: f"{int(match.group(3))}-{int(match.group(2))}-{match.group(1)}", value)


# Pat fact #27: Pat doesn't know how it got here.
#fisheggs
