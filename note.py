"""The sticky note: a small window that stays on top, shows the phone line, and decides who takes each incoming call.

  .venv\\Scripts\\pythonw.exe note.py

Its settings are on the right-click menu of its icon, in the hidden icons.

It watches the line with an iphonecall of its own, which never moves a call's audio. Each AI call is still a pat.py
process with its own iphonecall, so the note also shows calls an agent places, and a crash here can't end a call.
"""
import argparse
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
CALLS = os.path.join(HERE, "calls")
CONTACTS = os.path.join(HERE, "contacts")
ALWAYS_AI_FILE = os.path.join(CONTACTS, "always_ai.json")  # the older form of the rules: read once
CALL_RULES_FILE = os.path.join(CONTACTS, "call_rules.json")
ASK, AI, ME = "ask", "ai", "me"
ME_ROUTE_NAME = "note-me-route.txt"
CANCEL_SECONDS = 3  # how long a getting-ready call gets to step aside before Me answers
RETRY_SECONDS = 15
NOTICE_CHARS = 110
AGENT_MODEL = "claude-sonnet-5-5"
AGENT_TOOLS = ",".join(f"mcp__pat-phone__{tool}" for tool in ("place_call", "get_call", "contact_notes", "list_contacts"))
AGENT_REPLY_CHARS = 300  # only so a runaway reply can't fill the screen
WORKING = "Working on it..."
AGENT_PROMPT = ("The owner typed this into Pat's sticky note. Do it with the pat-phone tools, and wait for the call to finish. "
                "The note shows the call's report by itself, so don't show chat_summary or repeat the report: when the call is over, reply with only the word Done. "
                "If there was no call, or nobody answered, say so in one short plain sentence instead. "
                "To keep them private, phone numbers appear as #1, #2 and so on: pass those to the tools exactly as written. People may be "
                "named instead: list_contacts has the names. "
                "Nobody can answer questions here. If something essential is missing, such as the number, don't call: say what's "
                "missing in one short sentence.")
if sys.stdout is None:  # pythonw has no console
    os.makedirs(CALLS, exist_ok=True)
    sys.stdout = sys.stderr = open(os.path.join(CALLS, "note.log"), "a", encoding="utf-8", buffering=1)

from audio_defaults import CallDevices, headset_problem  # noqa: E402
from easter_eggs import EasterEggs, choose_next_style, split_style  # noqa: E402
from live_call import SoundMeter, read_last_call, read_live, send_command, take_commands  # noqa: E402
from note_settings import SETTINGS_NAME, NoteSettings  # noqa: E402
from phone_memory import number_key  # noqa: E402
from private_numbers import PrivateNumbers, split_caller  # noqa: E402
from phone_numbers import unambiguous_legacy_keys  # noqa: E402
from user_profile import UserProfile  # noqa: E402


class CallRules:
    """Who takes each number's calls without asking. A number with no rule follows `decide`."""

    def __init__(self, path=CALL_RULES_FILE, old_always_ai=None):
        self.path = path
        self.rules = self._read(path)
        if not self.rules and old_always_ai:
            self.rules = {key: AI for key in self._read(old_always_ai)}

    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def rule(self, number):
        key = number_key(number)
        if key in self.rules:
            return self.rules[key]
        previous = {self.rules[old] for old in unambiguous_legacy_keys(key, os.path.dirname(self.path)) if old in self.rules}
        return previous.pop() if len(previous) == 1 else None

    def has(self, number):
        return self.rule(number) == AI

    def set(self, number, rule):
        key = number_key(number)
        if not key:  # a hidden number has nothing to remember
            return
        for old in unambiguous_legacy_keys(key, os.path.dirname(self.path)):
            self.rules.pop(old, None)
        if rule in (AI, ME):
            self.rules[key] = rule
        else:
            self.rules.pop(key, None)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.rules, f, indent=1)
        os.replace(self.path + ".tmp", self.path)

    def add(self, number):
        self.set(number, AI)

    def decide(self, number, is_contact, for_unknown):
        """AI, ME or ASK for this call: its own rule, or else contacts get asked about and strangers follow the setting."""
        return self.rule(number) or (ASK if is_contact else for_unknown)


class CallLevel:
    """Whether anyone is talking while the owner is on the laptop and no Pat call is running: what's playing, or their microphone."""

    def __init__(self):
        import numpy as np
        import pyaudiowpatch
        self.np = np
        self.sound = SoundMeter()
        self.pa = pyaudiowpatch.PyAudio()
        self.done = pyaudiowpatch.paContinue
        self.format = pyaudiowpatch.paFloat32
        self.streams = [self._open(self.pa.get_default_wasapi_loopback()),
                        self._open(self.pa.get_device_info_by_index(self.pa.get_host_api_info_by_type(pyaudiowpatch.paWASAPI)["defaultInputDevice"]))]

    def _open(self, device):
        return self.pa.open(format=self.format, channels=device["maxInputChannels"], rate=int(device["defaultSampleRate"]), input=True,
                            input_device_index=device["index"], frames_per_buffer=1024, stream_callback=self._on_audio)

    def _on_audio(self, data, count, when, status):
        self.sound.feed(self.np.frombuffer(data, dtype=self.np.float32))
        return None, self.done

    def take(self):
        return self.sound.take()

    def close(self):
        for stream in self.streams:
            stream.stop_stream()
            stream.close()
        self.pa.terminate()


def agent_words(reply):
    """The last thing the agent wrote that's meant to be read: never the code fence closing a card."""
    lines = [line.strip() for line in reply.splitlines() if line.strip() and not line.strip().startswith("```")]
    return lines[-1][:AGENT_REPLY_CHARS] if lines else ""


def terminate_call_process(process):
    """A Windows venv launcher can have a real Python child; stop the whole cancelled request."""
    if os.name == "nt" and getattr(process, "pid", None):
        try:
            result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=5,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    process.kill()


class Desk:
    """Everything the note knows and does, apart from drawing it. `line` is the note's own PhoneLine."""

    def __init__(self, line, start_call, devices=None, always=None, settings=None, folder=CALLS, real_devices=None, headsets=None, make_level=CallLevel, cancel_seconds=CANCEL_SECONDS, private=None, eggs=None, speech_ready=lambda: True):
        self.line = line
        self.private = private or PrivateNumbers()
        self.eggs = eggs or EasterEggs(os.path.dirname(self.private.book_path), folder)
        self._set_panel(self.eggs.first_open_panel())
        self.panel_style = ""
        self.start_call = start_call  # takes a result file; returns a process getting ready to pick up
        self.speech_ready = speech_ready
        self.prepare_requested = False
        self.ai_requested = False
        self.devices = devices or CallDevices(folder)
        self.always = always or CallRules()
        self.settings = settings or NoteSettings(folder)
        self.folder = folder
        self.real_devices = real_devices
        self.headsets = headsets  # Bluetooth headsets on the laptop, which keep a call's audio on the phone
        self.headset_check = None
        self.route_moves = 0  # counts each move, so a late headset check only acts on the move it was made for
        self.make_level = make_level
        self.cancel_seconds = cancel_seconds
        self.lock = threading.RLock()
        self.screen = "idle"
        self.finished_session = None
        self.number = ""
        self.name = ""
        self.route = "iphone"
        self.me_route = self._load_me_route()
        self.showing_last = None
        self.forwarding = False  # the call's own process has the owner on the laptop, after Take over or F9
        self.notice = ""
        self.ready_call = None
        self.result_file = None
        self.chosen_ai = False
        self.ai_since = 0.0
        self.level = None
        last = read_last_call(folder)
        self.dismissed = last.get("id") if last else None  # a call from before the note opened isn't news

    def _load_me_route(self):
        try:
            with open(os.path.join(self.folder, ME_ROUTE_NAME), encoding="utf-8") as f:
                return "laptop" if f.read().strip() == "laptop" else "iphone"
        except OSError:
            return "iphone"

    # What the line reports

    def on_event(self, event):
        status, who, direction = event
        with self.lock:
            if status == "Incoming" and self.screen in ("idle", "ending"):
                self._ring(who)
            elif status == "Talking" and direction == "Incoming" and self.screen == "ringing":
                # Picked up on the phone itself. Nothing here moves it.
                self._cancel_ready_call()
                self.screen = "me"
                self.route = "laptop" if self.line.audio == "LocalDevice" else "iphone"
            elif status in ("Ended", "Closed"):
                self._back_to_idle()
            elif status == "RingingStopped" and self.screen in ("ringing", "ai"):
                live = read_live(self.folder) or {}
                if live.get("stage") not in ("talking", "handed", "wrapping"):
                    self._back_to_idle()

    def _ring(self, who):
        self.finished_session = None
        self.name, self.number = split_caller(who)
        self.name = self.name or self.private.name_for(self.number)
        self.notice = ""
        self._set_panel(None)
        take_commands(self.folder)  # from a call that was killed
        self.screen = "ringing"
        rule = self.always.decide(self.number, bool(self.private.name_for(self.number)), self.settings.unknown)
        self.prepare_requested = rule != ME
        if rule != ME:  # Me never answers by itself: nobody may be at the laptop. The phone just rings as usual.
            self._get_claude_ready()
        if rule == AI:
            self._pick_up_with_ai()

    def _get_claude_ready(self):
        if not self.speech_ready():
            self.notice = "Speech is getting ready. You can answer on your phone meanwhile."
            return
        self.notice = ""
        self.result_file = os.path.join(self.folder, f"answer-{int(time.time())}.result.json")
        self.ready_call = self.start_call(self.result_file)

    def _back_to_idle(self):
        self._stop_level()
        self.devices.restore()
        live = read_live(self.folder) or {}
        if live:
            self.finished_session = self._session_key(live)
        self._cancel_ready_call(force=live.get("stage") not in ("talking", "handed", "wrapping"))
        self.screen = "idle"
        self.chosen_ai = False
        self.forwarding = False
        self.route = "iphone"
        self.prepare_requested = False
        self.ai_requested = False
        if self.notice == "Ending call…":
            self.notice = ""

    @staticmethod
    def _session_key(live):
        return live.get("session_id") or (live.get("number", ""), live.get("name", ""))

    def _stop_level(self):
        if self.level:
            self.level.close()
            self.level = None

    def _cancel_ready_call(self, call=None, force=False):
        call = call or self.ready_call
        self.ready_call = None
        if call is None or call.poll() is not None or (self.chosen_ai and not force):
            return
        send_command(self.folder, "cancel")
        try:
            call.wait(self.cancel_seconds)
        except subprocess.TimeoutExpired:
            terminate_call_process(call)

    def _pick_up_with_ai(self):
        self.ai_requested = True
        if self.ready_call is None:
            self._get_claude_ready()
        if self.ready_call is None:
            return
        self.ai_requested = False
        self.chosen_ai = True
        self.ai_since = time.monotonic()
        self.screen = "ai"
        send_command(self.folder, "go")

    # What the buttons do

    def answer_ai(self, always=False):
        with self.lock:
            if self.screen != "ringing":
                return
            if always:
                self.always.add(self.number)
            self.prepare_requested = True
            if self.ready_call is None:
                self._get_claude_ready()
            self._pick_up_with_ai()

    def choose_route(self, route):
        """The arrow's choice, which Me keeps using until the next choice, across restarts too."""
        with self.lock:
            self.me_route = "laptop" if route == "laptop" else "iphone"
            try:
                os.makedirs(self.folder, exist_ok=True)
                with open(os.path.join(self.folder, ME_ROUTE_NAME), "w", encoding="utf-8") as f:
                    f.write(self.me_route)
            except OSError as error:
                print(f"[couldn't remember where Me answers: {error}]", flush=True)

    def answer_me(self, route="iphone"):
        with self.lock:
            if self.screen != "ringing":
                return
            self.screen = "me"
            self.route = route
            self.prepare_requested = False
            self.ai_requested = False
            call = self.ready_call
        # Not holding the lock: the note keeps drawing while this waits.
        self._cancel_ready_call(call)  # its iphonecall would pull the audio to the laptop
        self.line.answer()
        self.set_route(route)

    def set_route(self, route):
        with self.lock:
            self.route_moves += 1
            self.route = route
            if self.screen != "me":
                return
            if self.forwarding:
                if route == "laptop":
                    return
                # The call's process moves it, then leaves, and puts the default devices back itself.
                send_command(self.folder, "to-phone")
                self.forwarding = False
                self._stop_level()
            elif route == "laptop":
                self.line.to_laptop()
                self._use_real_devices()
                if self.headsets:  # asking Windows takes a couple of seconds, so the call moves first
                    self.headset_check = threading.Thread(target=self._back_if_headset, args=(self.route_moves,), daemon=True)
                    self.headset_check.start()
            else:
                self.line.to_phone()
                self._stop_level()
                self.devices.restore()

    def _back_if_headset(self, move):
        """With a Bluetooth headset on the laptop, Windows says the call moved here while its sound stays on the phone.
        Then the phone is where it really is, so the note says so and puts it back there properly."""
        try:
            blocked = headset_problem(self.headsets())
        except OSError as error:
            blocked = str(error)
        with self.lock:
            if not blocked or move != self.route_moves or self.screen != "me" or self.route != "laptop" or self.forwarding:
                return
            self.route = "iphone"
            self.line.to_phone()
            self._stop_level()
            self.devices.restore()
            self.notice = blocked

    def _use_real_devices(self):
        speaker, microphone = self.real_devices() if self.real_devices else (None, None)
        try:
            self.devices.use(speaker=speaker, mic=microphone)
            self.level = self.level or self.make_level()
        except (LookupError, OSError) as error:
            self.notice = f"Couldn't set up the laptop's audio: {error}"

    def _start_forwarded_level(self):
        """The mixer while the call's process forwards the audio. The defaults stay on the silent speaker and the cable, which carry both voices."""
        try:
            self.level = self.level or self.make_level()
        except OSError as error:
            print(f"[no mixer during this call: {error}]", flush=True)

    def listen(self, on):
        send_command(self.folder, "listen on" if on else "listen off")

    def take_over(self):
        """To the laptop: the call's process says it's passing them over, and forwards the audio from then on."""
        with self.lock:
            send_command(self.folder, "take-over")
            self._now_forwarded()

    def _now_forwarded(self):
        live = read_live(self.folder)
        if self.screen == "idle" and live:  # a call an agent placed: only the call knows who it's with
            self.number, self.name = live.get("number", ""), live.get("name", "")
        self.chosen_ai = False
        self.ready_call = None
        self.prepare_requested = False
        self.screen = "me"
        self.route = "laptop"
        self.forwarding = True
        self._start_forwarded_level()

    def end_call(self):
        with self.lock:
            self.prepare_requested = False
            self.ai_requested = False
            self.screen = "ending"
            self.notice = "Ending call…"
            send_command(self.folder, "hang-up")
            send_command(self.folder, "cancel")
        self.line.hang_up()

    def _set_panel(self, panel):
        self.panel = panel
        delay = panel.get("dismiss_after", 0) if panel else 0
        self.panel_deadline = time.monotonic() + delay if delay else None
        if panel is None:
            self.eggs.pending = None

    def _expire_panel(self):
        if self.panel_deadline is not None and time.monotonic() >= self.panel_deadline:
            self._set_panel(None)

    def submit(self, text):
        """Hands what was typed to an agent, which places the call through the phone tool like any other agent. Easter eggs are
        answered here first, so a joke needs no Claude, and a joke number can't reach the phone tool from here."""
        text, style = split_style(text)
        with self.lock:
            self._set_panel(None)
            self.notice = ""
            panel = self.eggs.respond(text, self.private) if text else None
            if panel:
                self._set_panel(panel)
                self.panel_style = style
                return
            if not text:
                self.notice = "Say who to call, then the flag: call the dentist --haiku"
                return
        self._send_to_agent(text, style)

    def _send_to_agent(self, text, style):
        with self.lock:
            self.notice = WORKING
        # The number never leaves the laptop: what Claude gets has a name or a placeholder in its place.
        threading.Thread(target=self._run_agent, args=(self.private.protect(text), style), daemon=True).start()

    def press(self, button):
        """A button on the open panel."""
        with self.lock:
            self._expire_panel()
            if self.panel is None:
                return
            panel, target = self.eggs.press(button)
            self._set_panel(panel)
            style = self.panel_style
        if target:
            self._send_to_agent(f"Call {target}. Say hello from the owner and ask how they are, then say goodbye.", style)

    def show_stats(self):
        with self.lock:
            self._set_panel(self.eggs.stats_panel())

    def show_facts(self):
        with self.lock:
            self._set_panel(self.eggs.found_panel())

    def quit(self):
        """The note is closing for good. A call Claude is on carries on by itself."""
        with self.lock:
            self._stop_level()
            self._cancel_ready_call()
            if self.screen == "me":
                self.devices.restore()
        self.line.close()

    def _run_agent(self, text, style=""):
        from voice_loop import find_claude
        before = self._last_call_id()
        try:
            choose_next_style(self.folder, style)  # the phone tool takes this for the call it places
            done = subprocess.run([find_claude(), "-p", text, "--model", AGENT_MODEL, "--allowedTools", AGENT_TOOLS, "--append-system-prompt", AGENT_PROMPT],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                                  creationflags=subprocess.CREATE_NO_WINDOW, cwd=HERE)
            reply = done.stdout.strip() or done.stderr.strip()
        except (OSError, SystemExit) as error:
            reply = f"Couldn't start Claude: {error}"
        choose_next_style(self.folder, "")  # if the agent didn't call, the flag isn't for some later call
        with self.lock:
            # If a call happened, the note has its report on screen already, and the agent's words are only a repeat of it.
            self.notice = "" if self._last_call_id() != before else self.private.reveal(agent_words(reply))

    def _last_call_id(self):
        return (read_last_call(self.folder) or {}).get("id")

    # What the note draws

    def _read_failure(self):
        """Why the call that was asked to pick up couldn't, so the note doesn't just sit there."""
        call = self.ready_call
        if call is None or call.poll() is None:
            return
        self.ready_call = None
        self.prepare_requested = False
        self.ai_requested = False
        reason = "Claude couldn't start."
        try:
            with open(self.result_file, encoding="utf-8") as f:
                reason = json.load(f).get("reason") or reason
        except (OSError, ValueError, TypeError):
            pass
        self.notice = reason[:NOTICE_CHARS]
        if self.screen == "ai":
            self.screen = "ringing"
            self.chosen_ai = False

    def state(self):
        with self.lock:
            self._expire_panel()
            if self.screen == "ringing" and self.prepare_requested and self.ready_call is None and self.speech_ready():
                self._get_claude_ready()
                if self.ai_requested:
                    self._pick_up_with_ai()
            live = read_live(self.folder)
            if live and live.get("stage") == "wrapping" and self.screen in ("ai", "me", "ending"):
                self._back_to_idle()
            if live and (self._session_key(live) == self.finished_session or live.get("stage") == "wrapping"):
                live = None
            if self.screen == "ending" and not self.line.in_call:
                self._back_to_idle()
                live = None
            if self.screen == "ai" and not live and time.monotonic() - self.ai_since > 2:
                if self.ready_call is not None:
                    self._read_failure()
                elif not self.line.in_call:
                    self._back_to_idle()
            elif self.screen == "ringing":
                self._read_failure()
            if live and live.get("stage") == "handed" and self.screen in ("ai", "idle") and not self.forwarding:  # F9
                self._now_forwarded()
            if live and live.get("notice"):  # such as why the call went to the phone instead
                self.notice = live["notice"]
            # A call an agent placed shows up with no button pressed here.
            screen = self.screen
            if screen == "idle" and live and live.get("stage") != "ringing":
                screen = "ai"
            last = read_last_call(self.folder) if screen == "idle" and not live else None
            if last and last.get("id") != self.dismissed:
                screen = "done"
            # Under a running call or its report, "working on it" has nothing left to say.
            notice = "" if screen != "idle" and self.notice == WORKING else self.notice
            state = {"screen": screen, "level": 0, "number": self.number, "name": self.name, "route": self.route, "me_route": self.me_route, "notice": notice,
                     "always": self.always.has(self.number), "talking": False, "listening": False, "facts": [], "summary": "",
                     "panel": self.panel if screen == "idle" else None}
            if screen == "ai" and live:
                state.update(talking=live.get("talking", False), level=live.get("level", 0), listening=live.get("listening", False), facts=live.get("facts", []),
                             summary=live.get("summary", ""))
                if self.screen == "idle":
                    state.update(number=live.get("number", ""), name=live.get("name", ""), always=False)
            elif screen == "me" and self.level:
                state["level"] = self.level.take()
                state["talking"] = state["level"] > 0
            elif screen == "done":
                state.update(number=last.get("number", ""), name=last.get("name", ""), facts=last.get("facts", []), summary=last.get("summary", ""),
                             next_step=last.get("next_step", ""), always=False, flair=last.get("flair", []), pat_facts=last.get("pat_facts", []), poem=last.get("poem", ""),
                             poem_style=last.get("poem_style", ""), poem_pending=last.get("poem_pending", False))
                self.showing_last = last.get("id")
            supplied_name, number = split_caller(state.get("number", ""))
            state["name"] = state.get("name") or self.private.name_for(number) or supplied_name
            state["number"] = number
            return state

    def dismiss(self):
        """The end-of-call summary stays until this."""
        with self.lock:
            self.dismissed = self.showing_last
            if self.notice == WORKING:  # the agent is only winding down now
                self.notice = ""


def watch_line(make_line, desk_box, on_problem):
    """Keeps a line open for as long as the note runs, and passes on what it reports."""
    while True:
        try:
            line = make_line()
        except OSError as error:
            on_problem(f"iphonecall won't start, so run setup.ps1: {error}"[:NOTICE_CHARS])
            time.sleep(RETRY_SECONDS)
            continue
        desk = desk_box(line)
        if not line.wait_ready():
            line.close()
            on_problem("Your phone isn't connected.")
            time.sleep(RETRY_SECONDS)
            continue
        on_problem("")
        while True:
            try:
                event = line.events.get(timeout=1)
            except queue.Empty:
                continue
            try:
                desk.on_event(event)
            except Exception as error:
                on_problem(f"Couldn't update the call screen: {error}"[:NOTICE_CHARS])
                print(f"[call screen event error: {error}]", flush=True)
            if event[0] == "Closed":
                break
        line.close()
        time.sleep(RETRY_SECONDS)


class LateDesk:
    """Lets the page ask for its state before the phone line is up."""

    def __init__(self, speech=None):
        self.desk = None
        self.notice = ""
        self.speech = speech

    def state(self):
        if self.desk:
            state = self.desk.state()
            if self.notice and not state["notice"]:
                state["notice"] = self.notice
        else:
            state = {"screen": "idle", "notice": self.notice}
        if self.speech:
            from speech_service import public_notice
            state["speech_status"] = public_notice(self.speech.status())
        return state

    def submit(self, text):
        if self.desk:
            self.desk.submit(text)
        else:
            self.notice = self.notice or "The phone line isn't ready yet."

    def show_stats(self):
        if self.desk:
            self.desk.show_stats()

    def show_facts(self):
        if self.desk:
            self.desk.show_facts()

    def __getattr__(self, name):
        return getattr(self.desk, name)


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    from note_window import claim_single_copy, show  # slow: loads the window library
    if not claim_single_copy():  # before anything starts watching the line
        return
    from onboarding import ensure_onboarding
    if not ensure_onboarding():
        return

    settings = NoteSettings()
    rules = CallRules(CALL_RULES_FILE, ALWAYS_AI_FILE)
    private = PrivateNumbers()

    # sys.executable would be pythonw, whose children can't print.
    python = os.path.join(os.path.dirname(sys.executable), "python.exe")

    def start_call(result_file):
        log = open(result_file.replace(".result.json", ".log"), "w", encoding="utf-8")
        return subprocess.Popen([python, os.path.join(HERE, "pat.py"), "answer", "--wait-for-go", "--lang", settings.language, "--result-file", result_file],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, cwd=HERE, creationflags=subprocess.CREATE_NO_WINDOW)

    from speech_service import ResidentSpeech
    speech = ResidentSpeech()
    speech.start()
    late = LateDesk(speech)

    def make_line():
        import pat  # slow: loads the audio libraries, so the window opens first
        return pat.PhoneLine(command=pat.phone_command(stay_on_phone=True, follow_phone=True), log_path=os.path.join(CALLS, "note-phone.log"))

    def desk_for(line):
        import pat

        def real_names():
            speaker, microphone = pat.real_devices()
            return (pat.sd.query_devices(speaker)["name"] if speaker is not None else None,
                    pat.sd.query_devices(microphone)["name"] if microphone is not None else None)

        late.desk = Desk(line, start_call, always=rules, settings=settings, private=private, real_devices=real_names, headsets=pat.connected_headsets, speech_ready=speech.is_ready)
        return late.desk

    def on_problem(text):
        late.notice = text

    os.makedirs(CALLS, exist_ok=True)
    threading.Thread(target=watch_line, args=(make_line, desk_for, on_problem), daemon=True).start()
    try:
        show(late, on_quit=lambda: late.desk and late.desk.quit(), options=types.SimpleNamespace(settings=settings, rules=rules, private=private, eggs=EasterEggs()))
    finally:
        speech.close()


if __name__ == "__main__":
    main()
