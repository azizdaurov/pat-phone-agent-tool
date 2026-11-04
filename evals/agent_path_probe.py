"""Runs what place_call runs, the way phone_mcp.py starts it (no console window, stdin piped, output to a file), but places no call.

Windows-only risk this checks: iphonecall is launched through a package alias, which might behave differently with no console.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FLAGS = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def run(label, args, cwd):
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, cwd=cwd, text=True,
                                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}, **FLAGS)
        code = proc.wait(timeout=90)
        log.seek(0)
        print(f"--- {label} (exit {code})\n{log.read().strip()[-700:]}", flush=True)


pat_dir = os.path.join(HERE, "..")
run("pat.py check", [sys.executable, os.path.join(pat_dir, "pat.py"), "check"], pat_dir)
run("iphonecall status", ["iphonecall", "status"], pat_dir)

script = (
    "import pat, time\n"
    "line = pat.PhoneLine()\n"
    "print('shell ready:', line.wait_ready(40))\n"
    "print('last lines:', line.started[-3:])\n"
    "line.close()\n"
)
run("PhoneLine shell over pipes", [sys.executable, "-c", script], pat_dir)
