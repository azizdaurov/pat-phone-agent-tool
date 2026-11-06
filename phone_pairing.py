"""Runs `iphonecall pair --json` for the note's "Set up the phone for Pat's calls" window.

The helper deletes the phone's old pairing, ends Phone Link, finds the phone, pairs and registers Pat on the new pairing
before any other app can. It reports each step as one JSON object per line and reads answers on stdin: a number, y or n,
an empty line to go on, or q to stop. Lines that aren't JSON (the connection steps) are only logged.
"""
import json
import subprocess
import threading

COMMAND = ("iphonecall", "pair", "--json")


def parse_event(line):
    """The helper's JSON line as a dict with an "event", or None for any other line."""
    try:
        data = json.loads(line)
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("event"), str) else None


class PairingRun:
    """One run of the helper. on_event is called from a reader thread, last with {"event": "closed"}."""

    def __init__(self, on_event, command=COMMAND):
        self.on_event = on_event
        self.proc = subprocess.Popen(list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            event = parse_event(line.strip())
            if event:
                self.on_event(event)
        self.proc.wait()
        self.on_event({"event": "closed", "code": self.proc.returncode})

    def answer(self, text):
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):  # the helper has already finished
            pass

    def stop(self):
        """Leaves the helper. Asked to stop between steps, it changes nothing more; mid-pairing, it's ended."""
        if self.proc.poll() is not None:
            return
        self.answer("q")
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
