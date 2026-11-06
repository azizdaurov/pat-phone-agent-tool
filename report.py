"""A bug report you can post in public: Pat's recent logs with phone numbers, names, callers' names and what was said taken out.

  .venv\\Scripts\\python.exe report.py            the last 3 calls
  .venv\\Scripts\\python.exe report.py --calls 10

It writes one text file in reports\\ and changes nothing else. What people said on a call is left out and only counted,
so the report shows timings, devices and errors. Read it before you post it: it can't know every private word.
"""
import argparse
import datetime
import glob
import json
import os
import platform
import re
import subprocess
import sys

from private_numbers import BOOK_NAME, DATE_FIRST, NUMBER_LIKE, split_caller
from phone_memory import FOLDER as CONTACTS

HERE = os.path.dirname(os.path.abspath(__file__))
CALLS = os.path.join(HERE, "calls")
REPORTS = os.path.join(HERE, "reports")
PHONE_DIGITS = 7  # fewer digits than this is a count or a time, not a phone number
CALL_ID = re.compile(r"\d{8}-\d{6}")  # the date and time at the start of a call's file name
SPOKEN = re.compile(r"^(\s*(?:\d\d:\d\d:\d\d \S+ )?)(Claude|Them): (.*)$")
# The call's brief, and what Haiku and Sonnet said to each other: what the call was about, so never in a report.
PRIVATE_PAT_LINES = re.compile(r"^((?:\d\d:\d\d:\d\d )?(?:Pat|Cicero): )(task|Haiku asks Sonnet|Sonnet answers|Sonnet \w+ \(|not spoken)")
SAFE_BRIEF_FIELDS = re.compile(r"^(language|confidence|time_zone|date_format): \S+$")
NEXT_ENTRY = re.compile(r"^(?:\d\d:\d\d:\d\d )?(?:(?:Pat|Cicero|Claude|Them|Status): |\[|Connected\.|Call over|No conversation)")
DIALING = re.compile(r"^(Dialing .*?\.) Claude's task: .*$")
# Where a caller's name can appear: the phone shows names from its own contacts, which Pat's contacts may not have.
# iphonecall writes "-- Incoming Name (+number): Talking, audio=..." and "call     : Incoming Name (+number): ...";
# pat.py writes "Incoming: Name (+number)".
CALLER_IN_STATUS = re.compile(r"((?:-- |call {5}: )\w+ )(.+?)(: \w+, audio=)")
CALLER_INCOMING = re.compile(r"^(\s*(?:\d\d:\d\d:\d\d\S* )?Incoming: )(.+)$")
PACKAGES = ("numpy", "sounddevice", "PyAudioWPatch", "onnx-asr", "piper-tts", "pocket-tts", "PySide6", "mcp")
SETUP_LOGS = os.path.join(HERE, "setup-logs")  # setup.ps1 writes one per run, so a failed setup can still be reported
SETUP_LOG_LINES = 150
PHONE_LINK_START = (r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData"
                    r"\Microsoft.YourPhone_8wekyb3d8bbwe\YourPhone.Start")
START_STATES = {0: "off", 1: "off (turned off by you or Pat's setup)", 2: "on", 3: "off (set by an administrator)",
                4: "on (set by an administrator)"}
BLUETOOTH_EVENTS_KEPT = 80  # a day of testing pairings made 113
BLUETOOTH_EVENT_WORDS = {8: "paired", 10: "pairing removed", 16: "authentication failed (it may hold an old pairing)",
                         37: "its connection was refused"}
# Pairings from the last day, with each device's name where Windows still has one. Reads only.
BLUETOOTH_EVENTS_SCRIPT = r"""
$names = @{}
Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -match 'DEV_([0-9A-F]{12})' } | ForEach-Object {
    if ($_.InstanceId -match 'DEV_([0-9A-F]{12})') { $names[$matches[1].ToLower()] = $_.FriendlyName } }
@(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='BTHUSB'; Id=8,10,16,37; StartTime=(Get-Date).AddDays(-1)} -ErrorAction SilentlyContinue |
    Sort-Object TimeCreated | ForEach-Object {
        $address = ''
        if ($_.Message -match '([0-9a-f]{2}(:[0-9a-f]{2}){5})') { $address = ($matches[1] -replace ':', '').ToLower() }
        [pscustomobject]@{ time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'); id = $_.Id; name = $names[$address]; device = $address }
    }) | ConvertTo-Json -Compress
"""
# A Bluetooth address names one phone or headset. They can appear in Windows device ids, as in
# "Bluetooth#Bluetooth38:00:25:aa:bb:cc-30:d7:a1:a4:fc:0b" or "BTHENUM\...\DEV_30D7A1A4FC0B".
# Six hex pairs joined by colons or dashes, or 12 hex characters between the separators Windows device ids use
# (& _ # \). The second form needs those separators, so the end of an audio device id such as "-a1ad32d2649a}" stays.
BLUETOOTH_ADDRESS = re.compile(r"(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
                               r"|(?<=[&_#\\])[0-9a-f]{12}(?=[&_#\\]|$)", re.IGNORECASE)


class Redactor:
    """Swaps numbers and names for stand-ins such as <number 1>. The same number always gets the same stand-in, so a
    report can still show that two lines are about the same call."""

    def __init__(self, names=(), home=None):
        self.numbers = {}
        self.callers = {}
        self.names = sorted({name.strip() for name in names if name and len(name.strip()) >= 3}, key=len, reverse=True)
        self.known = {name.casefold() for name in self.names}
        self.home = home

    def number(self, digits):
        return self.numbers.setdefault(digits, f"<number {len(self.numbers) + 1}>")

    def caller(self, name):
        return self.callers.setdefault(name.casefold(), f"<caller {len(self.callers) + 1}>")

    def _hide_caller(self, match):
        """The name part of a caller label. A saved contact's name is left for the name stand-ins, so it keeps its <name N>."""
        who = match.group(2)
        name, number = split_caller(who)
        if not name and re.search(r"[^\W\d_]", who) and not re.search(r"\d", who):
            name, number = who.strip(), ""  # a name with no number
        if not name or name.casefold() in self.known:
            return match.group(0)
        hidden = f"{self.caller(name)} ({number})" if number else self.caller(name)
        return match.group(1) + hidden + (match.group(3) if match.re is CALLER_IN_STATUS else "")

    def _swap(self, match):
        found = match.group(0)
        text, start = match.string, match.start()
        before = text[start - 1] if start else ""
        call_id = CALL_ID.match(found)
        if call_id:  # keep the call's date and time, hide what follows
            rest = found[call_id.end():]
            digits = re.sub(r"\D", "", rest)
            return call_id.group(0) + (rest[:1] + self.number(digits) if len(digits) >= PHONE_DIGITS else rest)
        digits = re.sub(r"\D", "", found)
        if len(digits) < PHONE_DIGITS or DATE_FIRST.match(found):
            return found
        if before == ":" or re.fullmatch(r"\d+\.\d+", found):  # 21:59:38.783689, or a measurement
            return found
        if before == "=" and not found.startswith("+"):  # frames=829440: a count
            return found
        return self.number(digits)

    def clean(self, text, numbers=True):
        if self.home:
            text = re.sub(re.escape(self.home), "%USERPROFILE%", text, flags=re.I)
        if BLUETOOTH_ADDRESS is not None:  # before numbers, whose rule would take the address's digits apart
            text = BLUETOOTH_ADDRESS.sub("<bluetooth address>", text)
        text = CALLER_IN_STATUS.sub(self._hide_caller, text)
        text = CALLER_INCOMING.sub(self._hide_caller, text)
        if numbers:
            text = NUMBER_LIKE.sub(self._swap, text)
        for index, name in enumerate(self.names, 1):
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", f"<name {index}>", text, flags=re.I)
        return text


def words(text):
    return len(re.findall(r"\w+", text))


def without_conversation(lines):
    """Each line, with what someone said, the brief and the AIs' notes to each other left out."""
    out = []
    in_brief = False  # the brief runs over several lines, until the next line someone or Pat wrote
    for line in lines:
        line = line.rstrip("\r\n")
        if in_brief:
            if NEXT_ENTRY.match(line):
                in_brief = False
            else:
                if SAFE_BRIEF_FIELDS.match(line):
                    out.append(line)  # language, time zone and date format help explain a call and say nothing private
                continue
        spoken = SPOKEN.match(line)
        if spoken:
            out.append(f"{spoken.group(1)}{spoken.group(2)}: <said {words(spoken.group(3))} words>")
            continue
        private = PRIVATE_PAT_LINES.match(line)
        if private:
            in_brief = private.group(2) == "task"
            out.append(f"{private.group(1)}{private.group(2).rstrip(' (')}: <left out>")
            continue
        dialing = DIALING.match(line)
        out.append(dialing.group(1) + " <task left out>" if dialing else line)
    return out


def private_names():
    names = []
    try:
        with open(os.path.join(CONTACTS, BOOK_NAME), encoding="utf-8") as f:
            names += list(json.load(f))
    except (OSError, ValueError):
        pass
    try:
        from user_profile import UserProfile
        profile = UserProfile()
        for spelling in {profile.name, *profile.names.values()}:  # every language's spelling of the owner's name
            names += [spelling, *spelling.split()]
        names.append(profile.phone_device)
    except Exception:
        pass
    names.append(os.environ.get("USERNAME", ""))
    names.append(os.environ.get("COMPUTERNAME", ""))  # the laptop's name: setup's log and phone prompts show it
    return names


def newest(pattern, count):
    return sorted(glob.glob(os.path.join(CALLS, pattern)), key=os.path.getmtime)[-count:]


def read_lines(path, last=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as error:
        return [f"<couldn't read: {error}>"]
    return lines[-last:] if last else lines


def environment():
    lines = [f"Windows: {platform.platform()}", f"Python: {sys.version.split()[0]}"]
    try:
        commit = subprocess.run(["git", "describe", "--always", "--dirty"], cwd=HERE, capture_output=True, text=True, timeout=10).stdout.strip()
        lines.append(f"Pat: {commit or 'unknown'}")
    except (OSError, subprocess.TimeoutExpired):
        lines.append("Pat: unknown")
    from importlib import metadata
    for package in PACKAGES:
        try:
            lines.append(f"{package}: {metadata.version(package)}")
        except metadata.PackageNotFoundError:
            lines.append(f"{package}: not installed")
    try:
        import sounddevice as sd
        lines.append("Audio devices (WASAPI: inputs, outputs, rate):")
        for index, device in enumerate(sd.query_devices()):
            if "WASAPI" in sd.query_hostapis(device["hostapi"])["name"]:
                lines.append(f"  {index}: {device['name']} | in {device['max_input_channels']}, out {device['max_output_channels']}, "
                             f"{int(device['default_samplerate'])} Hz")
        from audio_defaults import chosen_devices
        speakers, microphones = chosen_devices(CALLS)
        lines.append(f"Picked in Windows: speakers {list(speakers)}, microphones {list(microphones)}")
    except Exception as error:
        lines.append(f"Audio devices: couldn't list them ({error})")
    return lines


def _registry(hive, path, name):
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, hive), path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except (OSError, ImportError):
        return None


def _on_off(value):
    return "on" if value == 1 else "off" if value is not None else "unknown"


def laptop_state(run=subprocess.run, headsets=None, registry=_registry):
    """The Windows settings and helpers behind every setup problem so far. Reads only. A check that can't tell says unknown."""
    def ask(command, seconds=30):
        try:
            done = run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=seconds)
            return done.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return None
    lines = [
        "Developer Mode: " + _on_off(registry("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock",
                                              "AllowDevelopmentWithoutDevLicense")),
        "Allow this PC to access your mobile devices: " + _on_off(registry("HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\Mobility",
                                                                           "CrossDeviceEnabled")),
    ]
    version = ask(["powershell", "-NoProfile", "-Command", "(Get-AppxPackage OasisTeam.PatPhone).Version"])
    lines.append("Phone helper: " + ("unknown" if version is None else f"installed, version {version}" if version else "not installed"))
    tasks = ask(["tasklist", "/FI", "IMAGENAME eq PhoneExperienceHost.exe", "/NH"])
    lines.append("Phone Link running: " + ("unknown" if tasks is None else "yes" if "PhoneExperienceHost" in tasks else "no"))
    installed = ask(["powershell", "-NoProfile", "-Command", "(Get-AppxPackage Microsoft.YourPhone).Version"])
    lines.append("Phone Link installed: " + ("unknown" if installed is None else f"yes, version {installed}" if installed else "no"))
    lines.append("Phone Link starts at sign-in: " + START_STATES.get(registry("HKEY_CURRENT_USER", PHONE_LINK_START, "State"), "unknown"))
    lines.append("Phone Link option on the Mobile devices page: " + _on_off(registry("HKEY_CURRENT_USER", r"Software\Microsoft\Windows\CurrentVersion\Mobility",
                                                                                     "PhoneLinkEnabled")))
    try:
        found = (headsets or _connected_headsets)()
        lines.append(f"Bluetooth headsets with calls on: {', '.join(found) if found else 'none'}")
    except Exception as error:
        lines.append(f"Bluetooth headsets with calls on: unknown ({type(error).__name__})")
    phones = ask(["iphonecall", "phones"], 60)
    lines += ["Paired phones:", *[f"  {line}" for line in phones.splitlines()]] if phones else ["Paired phones: the phone helper didn't answer"]
    claude = _claude_path()
    status = ask([claude, "auth", "status"]) if claude else None
    # Only whether it's logged in: the full answer has the account's email address.
    lines.append("Claude Code: " + ("not found" if not claude else "unknown" if status is None else
                                    "logged in" if re.search(r'"loggedIn":\s*true', status) else "not logged in"))
    return lines


def bluetooth_events(run=subprocess.run):
    """Windows' own record of pairings from the last day, by device name. It showed, for one, Phone Link's setup screen
    deleting a phone's pairing (6 Nov 2026). Addresses stay inside this function: a device that is no longer paired, so
    has no name to look up, is "device 1", "device 2"..."""
    try:
        done = run(["powershell", "-NoProfile", "-Command", BLUETOOTH_EVENTS_SCRIPT], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=60)
        found = json.loads(done.stdout) if done.stdout.strip() else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ["Couldn't read Windows' Bluetooth events."]
    if isinstance(found, dict):  # PowerShell writes a single event as an object, not a list
        found = [found]
    unnamed = {}
    lines = []
    for event in found:
        if not isinstance(event, dict):
            continue
        name = event.get("name") or unnamed.setdefault(event.get("device") or "?", f"device {len(unnamed) + 1} (not paired now)")
        lines.append(f"{event.get('time', '?')}  {BLUETOOTH_EVENT_WORDS.get(event.get('id'), 'event ' + str(event.get('id')))}: {name}")
    if len(lines) > BLUETOOTH_EVENTS_KEPT:
        lines = [f"({len(lines) - BLUETOOTH_EVENTS_KEPT} earlier ones left out)", *lines[-BLUETOOTH_EVENTS_KEPT:]]
    return lines or ["None in the last day."]


def pair_log_lines(path):
    """A set-up run's steps as plain lines; the note's runs write them as JSON."""
    lines = []
    for line in read_lines(path):
        try:
            step = json.loads(line)
        except ValueError:
            lines.append(line.rstrip("\r\n"))
            continue
        if isinstance(step, dict) and step.get("event") != "log":
            lines.append(f"{step.get('event')}: {str(step.get('text', '')).strip()}")
    return lines


def _connected_headsets():
    import pat
    return pat.connected_headsets()


def _claude_path():
    sys.path.insert(0, os.path.join(HERE, "voice-loop"))
    try:
        from voice_loop import find_claude
        return find_claude()
    except (ImportError, SystemExit):  # find_claude exits when there's no claude.exe
        return None


def newest_setup_log():
    logs = sorted(glob.glob(os.path.join(SETUP_LOGS, "setup-*.txt")), key=os.path.getmtime)
    return logs[-1] if logs else None


def result_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            result = json.load(f)
    except (OSError, ValueError):
        return None
    keep = {key: result.get(key) for key in ("status", "reason", "seconds", "outcome") if key in result}
    return f"Result: {json.dumps(keep, ensure_ascii=False)}"


def build(calls=3, redactor=None):
    redactor = redactor or Redactor(private_names(), os.path.expanduser("~"))
    sections = [("About this laptop", environment(), False),  # version numbers, not phone numbers
                ("Laptop settings", laptop_state(), True),
                ("Bluetooth pairings in the last day", bluetooth_events(), False)]  # times, not phone numbers
    setup_log = newest_setup_log()
    if setup_log:
        sections.append((f"Setup log {os.path.basename(setup_log)} (last {SETUP_LOG_LINES} lines)", read_lines(setup_log, SETUP_LOG_LINES), True))
    call_logs = set(newest("[0-9]*-[0-9]*-*.log", calls) + newest("answer-*.log", calls))
    for path in sorted(call_logs, key=os.path.getmtime)[-calls:]:
        body = without_conversation(read_lines(path))
        result = result_line(path[:-len(".log")] + ".result.json")
        sections.append((f"Call {os.path.basename(path)}", body + ([result] if result else []), True))
    for path in newest("phone-*.log", calls):
        sections.append((f"Phone line {os.path.basename(path)}", read_lines(path), True))
    for path in newest("pair-*.log", 2):
        sections.append((f"Phone set-up {os.path.basename(path)}", pair_log_lines(path), True))
    for name, last in (("note-phone.log", 200), ("note.log", 100), ("speech-service.log", 100)):
        path = os.path.join(CALLS, name)
        if os.path.exists(path):
            sections.append((f"{name} (last {last} lines)", without_conversation(read_lines(path, last)), True))
    out = [f"Pat bug report, {datetime.datetime.now():%Y-%m-%d %H:%M}",
           "Phone numbers, names and what was said on calls are left out. Read this before posting it.", ""]
    for title, lines, numbers in sections:
        out += [f"===== {redactor.clean(title)}", *(redactor.clean(line.rstrip("\r\n"), numbers) for line in lines), ""]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calls", type=int, default=3, help="how many recent calls to include (default 3)")
    args = parser.parse_args()
    text = build(max(1, args.calls))
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"pat-report-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Report written: {path}")
    print("Read it before posting. Numbers, names and what was said are left out, but check for anything else private.")


if __name__ == "__main__":
    main()
