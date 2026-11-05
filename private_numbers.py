"""Keeps real phone numbers on this laptop. The AI sees a contact's name or a placeholder such as #1, and the phone tool turns
those back into the number. A file you can edit, and a command for the same:

  .venv\\Scripts\\python.exe private_numbers.py add "Alex" "+COUNTRY_CODE_NUMBER"
  .venv\\Scripts\\python.exe private_numbers.py list
  .venv\\Scripts\\python.exe private_numbers.py remove "Рустам"
"""
import json
import os
import re
import sys

from phone_memory import FOLDER, number_key
from phone_numbers import international_number, unambiguous_legacy_keys

BOOK_NAME = "book.json"  # {name: number}
PLACEHOLDERS_NAME = "private_numbers.json"  # {"#1": number}
# Country metadata decides the length, including short international numbers. Colons are valid delimiters.
NUMBER_LIKE = re.compile(r"(?<![\w#])\+?\d(?:[ \t().-]*\d){2,14}(?![\w])")
DATE_FIRST = re.compile(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}")
PLACEHOLDER = re.compile(r"#\d+")


def digit_count(text):
    return len(re.sub(r"\D", "", text))


def split_caller(who):
    """Separate a caller label while keeping parentheses inside the phone number."""
    who = (who or "").strip()
    match = re.fullmatch(r"(.*?)\s+\((\+?[\d\s().-]+)\)", who)
    return (match.group(1).strip(), match.group(2).strip()) if match else ("", who)


class PrivateNumbers:
    def __init__(self, folder=FOLDER):
        self.book_path = os.path.join(folder, BOOK_NAME)
        self.placeholders_path = os.path.join(folder, PLACEHOLDERS_NAME)

    def _load(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)

    def contacts(self):
        return self._load(self.book_path)

    def add_contact(self, name, number):
        number = international_number(number)
        book = self.contacts()
        book[name.strip()] = number
        self._save(self.book_path, book)

    def remove_contact(self, name):
        book = self.contacts()
        removed = book.pop(name.strip(), None)
        self._save(self.book_path, book)
        return removed is not None

    def name_for(self, number):
        """The contact with this number, or ""."""
        key = number_key(number)
        return next((name for name, theirs in self.contacts().items() if key and number_key(theirs) == key), "")

    def display_name(self, caller):
        """Display metadata only. A saved name or caller ID does not verify who is speaking."""
        supplied_name, number = split_caller(caller)
        if not re.search(r"[^\W\d_]", supplied_name):  # with no contact, the phone sends the number itself as the name
            supplied_name = ""
        return self.name_for(number) or supplied_name

    def label_for(self, number, allow_unresolved=False):
        """What the AI calls this number: the contact's name, or a placeholder that stays the same for this number."""
        written = number.strip()
        try:
            number = international_number(number)
            key = number_key(number)
            name = self.name_for(number)
        except ValueError:
            # Hide an ambiguous typed number without guessing its country. resolve() still refuses to dial it.
            if not allow_unresolved or not 7 <= digit_count(written) <= 15:
                raise
            key = "raw:" + re.sub(r"\D", "", written)
            name = ""
        if name:
            return name
        placeholders = self._load(self.placeholders_path)
        for label, theirs in placeholders.items():
            theirs_key = number_key(theirs) or "raw:" + re.sub(r"\D", "", theirs)
            if theirs_key == key:
                return label
        label = f"#{len(placeholders) + 1}"
        placeholders[label] = written  # The owner sees the spelling they entered; resolve() still returns E.164.
        self._save(self.placeholders_path, placeholders)
        return label

    def resolve(self, target):
        """(number, contact's name) for a name, a placeholder or a number. Raises LookupError if it can't tell which."""
        target = (target or "").strip()
        if PLACEHOLDER.fullmatch(target):
            number = self._load(self.placeholders_path).get(target)
            if not number:
                raise LookupError(f"There's no {target} on this laptop. Ask for the number or a contact's name again.")
            try:
                return international_number(number), self.name_for(number)
            except ValueError as error:
                raise LookupError(str(error)) from error
        if digit_count(target) and re.fullmatch(r"\+?[\d\s().-]+", target):
            try:
                number = international_number(target)
            except ValueError as error:
                raise LookupError(str(error)) from error
            return number, self.name_for(number)
        wanted = target.casefold()
        book = self.contacts()
        exact = [name for name in book if name.casefold() == wanted]
        matches = exact or ([name for name in book if wanted and wanted in name.casefold()])
        if len(matches) == 1:
            try:
                return international_number(book[matches[0]]), matches[0]
            except ValueError as error:
                raise LookupError(str(error)) from error
        if matches:
            raise LookupError(f"More than one contact fits '{target}': {', '.join(matches)}. Say which one.")
        raise LookupError(f"No contact called '{target}'. Give a contact's name, a placeholder such as #1, or a full phone number.")

    def protect(self, text):
        """Swaps every number in what someone typed for its label, before it leaves the laptop."""
        def swap(match):
            found = match.group(0)
            if DATE_FIRST.match(found):
                return found
            try:
                return self.label_for(found, allow_unresolved=True)
            except ValueError:
                return found
        return NUMBER_LIKE.sub(swap, text)

    def reveal(self, text):
        """Placeholders back to numbers, for showing to the owner."""
        placeholders = self._load(self.placeholders_path)
        return PLACEHOLDER.sub(lambda match: placeholders.get(match.group(0), match.group(0)), text)

    def _known(self):
        known = {}
        for number in self._load(self.placeholders_path).values():
            known[number_key(number)] = None
        for number in self.contacts().values():
            known[number_key(number)] = None
        labels = {key: self.label_for("+" + key) for key in known if key}
        for key, label in list(labels.items()):
            for old in unambiguous_legacy_keys(key, os.path.dirname(self.book_path)):
                labels[old] = label  # Redact old transcript paths too; never use these keys to match a person.
        return labels

    def hide(self, value):
        """Copies a result with each number this laptop knows swapped for its label: as written, and as the digits in a file name.
        Numbers it doesn't know stay, as one may be what the call was for."""
        known = self._known()

        def clean(text):
            def swap(match):
                return known.get(number_key(match.group(0)), match.group(0))
            text = NUMBER_LIKE.sub(swap, text)
            for key in sorted(known, key=len, reverse=True):
                text = re.sub(rf"(?<!\d){re.escape(key)}(?!\d)", lambda _: known[key], text)
            return text

        def walk(item):
            if isinstance(item, str):
                return clean(item)
            if isinstance(item, list):
                return [walk(part) for part in item]
            if isinstance(item, dict):
                return {key: walk(part) for key, part in item.items()}
            return item

        return walk(value)


def main():
    private = PrivateNumbers()
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if command == "add" and len(sys.argv) == 4:
        private.add_contact(sys.argv[2], sys.argv[3])
        print(f"Added {sys.argv[2]}.")
    elif command == "remove" and len(sys.argv) == 3:
        print(f"Removed {sys.argv[2]}." if private.remove_contact(sys.argv[2]) else f"No contact called {sys.argv[2]}.")
    elif command == "list":
        for name, number in private.contacts().items():
            print(f"{name}: {number}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
