"""The languages Pat can hold calls in, kept in one place so another can be added later.

Adding a language takes an entry here, plus its speech recognition and voice in pat.py, its speaking rules in
voice_loop.SYSTEM_PROMPTS and its openings in pat.OPENINGS. The owner's name table and the AI that fills it in
read this list, so they need no change.
"""
import locale
import re

# letters: what a name written for this language must contain, so a reply in the wrong script is refused.
LANGUAGES = {
    "en": {"title": "English", "native": "English", "letters": re.compile(r"[A-Za-z]")},
    "ru": {"title": "Russian", "native": "Русский", "letters": re.compile(r"[А-Яа-яЁё]")},
}
FALLBACK = "en"


def system_language():
    """The Windows display language, if Pat can call in it; otherwise English."""
    code = ""
    try:
        import ctypes
        code = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    except (AttributeError, OSError):
        code = (locale.getlocale()[0] or "")
    code = code.split("_")[0].lower()
    return code if code in LANGUAGES else FALLBACK


def written_in(name, language):
    """True when the name uses the letters of this language."""
    return bool(LANGUAGES[language]["letters"].search(name))


def guess_language(name, preferred=None):
    """For a name saved before languages were recorded: the language whose letters it uses, preferring the given one."""
    order = [preferred] if preferred in LANGUAGES else []
    order += [code for code in LANGUAGES if code not in order]
    return next((code for code in order if written_in(name, code)), order[0])
