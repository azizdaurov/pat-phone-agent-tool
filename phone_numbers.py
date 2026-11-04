"""One international representation for dialing, contacts and private placeholders."""
import re
import unicodedata

import phonenumbers


def international_number(text, country=None):
    """Accept international numbers, or local ones only when a home country is set."""
    text = unicodedata.normalize("NFKC", str(text or "")).strip()
    text = "".join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)
    # Caller ID can be 'Name (+1 (415) 555-0101)'. Do not mistake an area code for the whole number.
    if "+" in text:
        text = text[text.rindex("+"):]
    elif not re.fullmatch(r"[\d\s().-]+", text):
        match = re.search(r"\(([\d\s().-]+)\)\s*$", text)
        if not match:
            raise ValueError("Use a full international number starting with + and the country code.")
        text = match.group(1)
    if not re.fullmatch(r"\+?[\d\s().-]+", text):
        raise ValueError("Use a phone number, without an extension. Put extensions in the call brief.")
    if country is None:
        from user_profile import UserProfile
        country = UserProfile().country
    if not text.startswith("+") and not country:
        raise ValueError("Use + and the country code, or choose the country for local numbers in Pat's settings.")
    try:
        parsed = phonenumbers.parse(text, country or None)
    except phonenumbers.NumberParseException as error:
        raise ValueError("Use a full international number starting with + and the country code.") from error
    if parsed.extension or not phonenumbers.is_possible_number(parsed):
        raise ValueError("That number has the wrong length for its country. Include the country code.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def full_number_key(text, country=None):
    try:
        return international_number(text, country).lstrip("+")
    except (ValueError, TypeError):
        return None


def legacy_key(text):
    """Old keys are only for migration, never for deciding whether two people are the same."""
    groups = re.findall(r"\(([^()]*)\)", text or "")
    digits = re.sub(r"\D", "", groups[-1] if groups else text or "")
    return digits[-9:] or None


def unambiguous_legacy_keys(key, folder):
    """Only carry over a legacy record when the saved number book gives it a single owner."""
    import json
    import os
    owners = {}
    for filename in ("book.json", "private_numbers.json"):
        try:
            with open(os.path.join(folder, filename), encoding="utf-8") as stream:
                book = json.load(stream)
            if not isinstance(book, dict):
                continue
        except (OSError, ValueError):
            continue
        for number in book.values():
            full = full_number_key(number)
            old = legacy_key(number)
            if full and old:
                owners.setdefault(old, set()).add(full)
    return [old for old, full in owners.items() if full == {key} and old != key]
