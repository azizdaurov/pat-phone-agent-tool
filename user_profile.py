"""Local owner preferences and versioned first-run acceptance. No account or Git settings are changed."""
import datetime
import hashlib
import json
import os
from zoneinfo import ZoneInfo

with open(os.path.join(os.path.dirname(__file__), "TERMS.md"), encoding="utf-8") as _terms_file:
    TERMS_TEXT = _terms_file.read()
# Any edit to TERMS.md also requires a fresh acceptance, without a manual version bump.
TERMS_VERSION = hashlib.sha256(TERMS_TEXT.encode("utf-8")).hexdigest()
DATE_FORMATS = {"iso": "YYYY-MM-DD", "dmy": "DD-MM-YYYY", "mdy": "MM/DD/YYYY"}
SETUP_MESSAGE = "Open Pat and finish the name and Terms of Use setup before using the phone tool."


def local_zone():
    from tzlocal import get_localzone_name
    return get_localzone_name()


class UserProfile:
    def __init__(self, path=None):
        self.path = path or os.environ.get("PAT_PROFILE_PATH") or os.path.join(os.path.dirname(__file__), "contacts", "user-profile.json")
        try:
            with open(self.path, encoding="utf-8") as stream:
                self.values = json.load(stream)
            if not isinstance(self.values, dict):
                self.values = {}
        except (OSError, ValueError):
            self.values = {}

    @property
    def name(self):
        value = self.values.get("name", "")
        return value.strip() if isinstance(value, str) else ""

    @property
    def time_zone(self):
        return self.values.get("time_zone") or local_zone()

    @property
    def country(self):
        return self.values.get("country", "")

    @property
    def date_format(self):
        return self.values.get("date_format", "iso")

    @property
    def phone_device(self):
        return self.values.get("phone_device", "")

    @property
    def ready(self):
        if not self.name or self.values.get("accepted_terms") != TERMS_VERSION:
            return False
        try:
            ZoneInfo(self.time_zone)
            return self.date_format in DATE_FORMATS
        except (ValueError, KeyError, TypeError):
            return False

    def save(self, **values):
        updated = {**self.values, **values}
        name = updated.get("name", "").strip()
        if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
            raise ValueError("Enter your name, using 1 to 100 characters.")
        ZoneInfo(updated.get("time_zone") or local_zone())
        if updated.get("date_format", "iso") not in DATE_FORMATS:
            raise ValueError("Choose a date format from the list.")
        country = updated.get("country", "")
        if country:
            from phonenumbers import SUPPORTED_REGIONS
            if country not in SUPPORTED_REGIONS:
                raise ValueError("Choose a supported country for local numbers.")
        updated["name"] = name
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as stream:
            json.dump(updated, stream, ensure_ascii=False, indent=2)
        os.replace(self.path + ".tmp", self.path)
        self.values = updated

    def accept_terms(self):
        self.save(accepted_terms=TERMS_VERSION, accepted_at=datetime.datetime.now(datetime.timezone.utc).isoformat())


def setup_refusal():
    return None if UserProfile().ready else {"status": "setup_required", "reason": SETUP_MESSAGE}


def requires_setup(function):
    import functools
    import inspect
    if inspect.iscoroutinefunction(function):
        @functools.wraps(function)
        async def asynchronous(*args, **kwargs):
            return setup_refusal() or await function(*args, **kwargs)
        return asynchronous
    @functools.wraps(function)
    def synchronous(*args, **kwargs):
        return setup_refusal() or function(*args, **kwargs)
    return synchronous
