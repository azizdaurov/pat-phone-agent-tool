"""How a running call and the sticky note talk to each other: a state file one way, a command file the other.
Files, because a call can be its own process started by anyone, including an agent through phone_mcp.py."""
import json
import math
import os
import threading
import time
import uuid

LIVE_NAME = "live.json"
LAST_CALL_NAME = "last-call.json"
COMMAND_NAME = "live-command"
STALE_SECONDS = 3  # a state older than this is from a call that was killed
PUBLISH_SECONDS = 0.05  # often enough for the mixer to follow speech
QUIETEST_DB = -50  # a phone line can be very quiet, so the mixer works in decibels: this shows as nothing...
LOUDEST_DB = -12  # ...and this as full height


def sound_level(samples):
    """How loud some audio is, from 0 to 1, the way an ear would judge it."""
    power = sum(float(s) * float(s) for s in samples) / max(len(samples), 1)
    if power <= 0:
        return 0.0
    level = (10 * math.log10(power) - QUIETEST_DB) / (LOUDEST_DB - QUIETEST_DB)
    return round(min(1.0, max(0.0, level)), 2)


class SoundMeter:
    """The loudest level since the mixer last asked."""

    def __init__(self):
        self.loudest = 0.0

    def feed(self, samples):
        self.loudest = max(self.loudest, sound_level(samples[::4]))

    def take(self):
        loudest, self.loudest = self.loudest, 0.0
        return loudest


def publish(folder, state):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, LIVE_NAME)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({**state, "updated": time.time()}, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:  # the note has it open for a moment; the next one gets through
        pass


def read_live(folder, now=None):
    """The running call's state, or None if there is none."""
    state = _read_json(os.path.join(folder, LIVE_NAME))
    return state if state and (now or time.time()) - state.get("updated", 0) < STALE_SECONDS else None


def _read_json(path):
    for _ in range(3):  # the call may be swapping the file in at this very moment
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.005)
    return None


def write_last_call(folder, **call):
    """What the note shows when a call is over. Unlike the live state, it stays until the next call replaces it."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, LAST_CALL_NAME)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(call, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def read_last_call(folder):
    return _read_json(os.path.join(folder, LAST_CALL_NAME))


def _sentence(text):
    """Sonnet writes details as fragments, which run together when joined: "Bring a passport Parking is behind"."""
    text = text.strip()
    return text if text[-1] in ".!?…" else text + "."


def final_note(report, facts, summary):
    """(bullet points, summary, contact question) for the end of a call, nothing cut. Sonnet's report if there is one, or else
    the live note. What they said to keep in mind and what to do next are the last bullet, Advice."""
    report = report if isinstance(report, dict) else {}
    answers = [item for item in report.get("answers") or [] if isinstance(item, dict)]
    if answers:
        facts = [{"label": str(item.get("label") or item.get("need") or "Answer"), "value": str(item["answer"]) if item.get("answer") else "not found"}
                 for item in answers]
    else:
        facts = [{"label": fact["label"], "value": fact["value"] or "not found"} for fact in facts]
    advice = [str(detail) for detail in report.get("important_details") or []] + ([str(report["follow_up"])] if report.get("follow_up") else [])
    if advice:
        facts = facts + [{"label": "Advice", "value": " ".join(_sentence(item) for item in advice if item.strip())}]
    return facts, str(report.get("summary") or summary or ""), str(report.get("contact") or "")


def send_command(folder, command):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, COMMAND_NAME), "a", encoding="utf-8") as f:
        f.write(command + "\n")


def take_commands(folder):
    path = os.path.join(folder, COMMAND_NAME)
    taken = path + f".{os.getpid()}"
    try:
        os.replace(path, taken)
        with open(taken, encoding="utf-8") as f:
            commands = f.read().split("\n")
        os.remove(taken)
    except OSError:
        return []
    return [command.strip() for command in commands if command.strip()]


def clear(folder):
    for name in (LIVE_NAME, COMMAND_NAME):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


class LiveCall:
    """Keeps the state file fresh while a call runs, and passes the note's commands to whoever handles them."""

    def __init__(self, folder, keep_commands=False, **fields):
        self.folder = folder
        self.fields = {"session_id": uuid.uuid4().hex, **fields}
        self.sources = {}  # field name -> function giving its current value
        self.handlers = {}
        self.closed = threading.Event()
        if not keep_commands:  # commands left by a call that was killed aren't for this one
            clear(folder)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def update(self, **fields):
        self.fields.update(fields)

    def _state(self):
        return {**self.fields, **{name: source() for name, source in list(self.sources.items())}}

    def _run(self):
        while not self.closed.wait(PUBLISH_SECONDS):
            publish(self.folder, self._state())
            for command in take_commands(self.folder):
                handler = self.handlers.get(command)
                if handler:
                    try:
                        handler()
                    except Exception as error:
                        print(f"[couldn't do '{command}': {error}]", flush=True)

    def close(self):
        self.closed.set()
        self.thread.join(1)
        clear(self.folder)
