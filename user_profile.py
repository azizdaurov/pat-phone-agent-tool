"""Local owner preferences and versioned first-run acceptance. No account or Git settings are changed."""
import datetime
import hashlib
import json
import os
from zoneinfo import ZoneInfo

from languages import LANGUAGES, guess_language, system_language

with open(os.path.join(os.path.dirname(__file__), "TERMS.md"), encoding="utf-8") as _terms_file:
    TERMS_TEXT = _terms_file.read()
# Any edit to TERMS.md also requires a fresh acceptance, without a manual version bump.
TERMS_VERSION = hashlib.sha256(TERMS_TEXT.encode("utf-8")).hexdigest()
DATE_FORMATS = {"iso": "YYYY-MM-DD", "dmy": "DD-MM-YYYY", "mdy": "MM/DD/YYYY"}
# How Pat speaks about the owner on calls. Russian has no neutral pronoun, and its verbs show gender, so "they" means using the name.
PRONOUNS = {"they": "they/them", "he": "he/him", "she": "she/her"}
REFER_TO_OWNER = {
    "they": "When you speak about {owner}, use the name {owner} or they. In Russian, use the name and avoid word forms that show gender.",
    "he": "When you speak about {owner}, say he and him. In Russian, use masculine forms, such as он сказал.",
    "she": "When you speak about {owner}, say she and her. In Russian, use feminine forms, such as она сказала.",
}
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
    def name_language(self):
        """The language the owner typed their name in: the system's language at first run."""
        saved = self.values.get("name_language")
        return saved if saved in LANGUAGES else guess_language(self.name, system_language())

    @property
    def names(self):
        """The name written for each language Pat calls in, so each call's voice says it right. Missing ones use name."""
        saved = self.values.get("names")
        saved = saved if isinstance(saved, dict) else {}
        if isinstance(self.values.get("name_ru"), str):  # one test build saved only a Russian spelling
            saved = {"ru": self.values["name_ru"], **saved}
        names = {code: value.strip() for code, value in saved.items() if code in LANGUAGES and isinstance(value, str) and value.strip()}
        if self.name:
            names[self.name_language] = self.name
        return names

    def name_in(self, language):
        return self.names.get(language) or self.name

    @property
    def pronouns(self):
        value = self.values.get("pronouns", "they")
        return value if value in PRONOUNS else "they"

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
        names = updated.get("names") or {}
        if not isinstance(names, dict) or any(code not in LANGUAGES or not isinstance(value, str) for code, value in names.items()):
            raise ValueError("Names must be given per supported language.")
        for value in names.values():
            if len(value.strip()) > 100 or any(ord(char) < 32 for char in value):
                raise ValueError("Keep each spelling of your name to 100 characters or fewer.")
        updated["names"] = {code: value.strip() for code, value in names.items() if value.strip()}
        updated.pop("name_ru", None)
        if "name_language" in updated and updated["name_language"] not in LANGUAGES:
            raise ValueError("Choose a supported language for your name.")
        if updated.get("pronouns", "they") not in PRONOUNS:
            raise ValueError("Choose how Pat should refer to you from the list.")
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


def refer_to_owner(owner, pronouns=None):
    """The line that tells Haiku how to speak about the owner. Saved settings are used unless pronouns are given."""
    choice = pronouns if pronouns in PRONOUNS else UserProfile().pronouns
    return REFER_TO_OWNER[choice].format(owner=owner)


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
