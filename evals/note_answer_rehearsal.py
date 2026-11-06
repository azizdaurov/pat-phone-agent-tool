"""The whole answer path, as the sticky note drives it: real speech models and real Claude, but a pretend phone line.
Nothing rings or dials, and the default devices stay as they are. Claude's voice goes into the cable, and to the speaker during
the Listen and take-over steps, with no sound from a caller. Your real microphone goes into the cable for a few seconds. Run: .venv\\Scripts\\python.exe evals\\note_answer_rehearsal.py"""
import json
import os
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import live_call

CALLS = os.path.join(HERE, "..", "calls")
RING = "\n-- Incoming +998900000001: Incoming, audio=RemoteDevice, muted=False"
FAKE_LINE = r"""
import sys
log = open(sys.argv[1], "a", encoding="utf-8")
print("line     : pretend | canDial=True", flush=True)
print("commands: pretend", flush=True)
print(""" + repr(RING) + r""", flush=True)
for command in sys.stdin:
    command = command.strip()
    log.write(command + "\n"); log.flush()
    if command == "a":
        print("\n-- Incoming +998900000001: Talking, audio=LocalDevice, muted=False", flush=True)
    if command == "q":
        break
"""
RUNNER = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
import pat
pat.PhoneLine.__init__.__defaults__ = ((sys.executable, sys.argv[2], sys.argv[3]),) + pat.PhoneLine.__init__.__defaults__[1:]
pat.check_audio_setup = lambda audible=False: []
pat.use_call_devices = lambda devices, audible: None
sys.argv = ["pat.py", "answer", "--wait-for-go", "--no-memory", "--no-observer", "--lang", "ru", "--result-file", sys.argv[4]]
pat.main()
"""


def wait_for(condition, seconds, what):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.1)
    raise SystemExit(f"FAILED waiting for {what}")


def stage_is(stage):
    return lambda: (live_call.read_live(CALLS) or {}).get("stage") == stage


def start():
    folder = tempfile.mkdtemp()
    fake, runner = os.path.join(folder, "line.py"), os.path.join(folder, "run.py")
    for path, text in ((fake, FAKE_LINE), (runner, RUNNER)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    sent, result = os.path.join(folder, "sent.txt"), os.path.join(folder, "result.json")
    open(sent, "w").close()
    output = open(os.path.join(folder, "output.txt"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, runner, os.path.join(HERE, "..", "app"), fake, sent, result], stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return proc, sent, result, os.path.join(folder, "output.txt")


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


print("1. Rings, then Me takes it: Claude must step aside without touching the call", flush=True)
proc, sent, result, output = start()
started = time.time()
wait_for(stage_is("ringing"), 120, "ringing")
print(f"   ready to pick up after {time.time() - started:.1f} s", flush=True)
live_call.send_command(CALLS, "cancel")
proc.wait(20)
commands = read(sent).split()
print("   sent to the line:", commands, "| result:", json.loads(read(result))["reason"], flush=True)
assert "a" not in commands and "h" not in commands, read(output)
assert live_call.read_live(CALLS) is None

print("2. Told to go before it has even started: it must still pick up", flush=True)
proc, sent, result, output = start()
live_call.send_command(CALLS, "go")
started = time.time()
wait_for(stage_is("talking"), 120, "talking")
print(f"   on the call after {time.time() - started:.1f} s", flush=True)
assert "a" in read(sent).split()
state = wait_for(lambda: (lambda s: s if s and s.get("facts") else None)(live_call.read_live(CALLS)), 60, "the bullet points")
print("   bullet points:", state["facts"], "| summary:", repr(state["summary"]), flush=True)
levels = set()
wait_for(lambda: levels.add((live_call.read_live(CALLS) or {}).get("level", 0)) or len(levels) > 4, 30, "the mixer to follow Claude's voice")
print("   the mixer follows the sound. Levels seen:", sorted(levels), flush=True)
time.sleep(9)  # the opening line finishes
live_call.send_command(CALLS, "listen on")
wait_for(lambda: (live_call.read_live(CALLS) or {}).get("listening"), 10, "listening")
live_call.send_command(CALLS, "listen off")
wait_for(lambda: not (live_call.read_live(CALLS) or {}).get("listening"), 10, "listening to stop")
print("   Listen went on and off", flush=True)
live_call.send_command(CALLS, "take-over")
wait_for(stage_is("handed"), 20, "the take-over on the laptop")
print("   taken over on the laptop", flush=True)
time.sleep(6)  # Claude says it's passing them over
assert "p" not in read(sent).split() and proc.poll() is None, read(output)
live_call.send_command(CALLS, "to-phone")
proc.wait(60)
commands = read(sent).split()
print("   moved to the iPhone. Sent to the line:", commands, flush=True)
assert "p" in commands and "h" not in commands, read(output)
print("   transcript lines:", *[line for line in read(output).splitlines() if line.startswith("Claude:")], sep="\n     ", flush=True)
assert live_call.read_live(CALLS) is None
last = live_call.read_last_call(CALLS)
print("   left for the note:", last, flush=True)
assert last and last["facts"], "the end-of-call note should be there"
print("PASSED", flush=True)
