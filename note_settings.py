"""What the tray menu sets. Stays through restarts. Calls read it too, so an agent's call uses the same voice unless the agent names one."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_NAME = "note-settings.json"


class NoteSettings:
    DEFAULTS = {"zoom": 1.0, "language": "en", "unknown": "ask", "voice_en": "charles", "voice_ru": "irina"}

    def __init__(self, folder=os.path.join(HERE, "calls")):
        self.path = os.path.join(folder, SETTINGS_NAME)
        self.values = dict(self.DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
            self.values.update({name: saved[name] for name in self.DEFAULTS if name in saved})
        except (OSError, ValueError, TypeError):
            pass

    def __getattr__(self, name):
        try:
            return self.__dict__["values"][name]
        except KeyError:
            raise AttributeError(name) from None

    def voice_for(self, language):
        return self.values["voice_ru" if language == "ru" else "voice_en"]

    def change(self, name, value):
        self.values[name] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.values, f, indent=1)
        os.replace(self.path + ".tmp", self.path)
