"""Pat's command line: dial, answer, check and the other set-up steps. Run with --help.

The code is in app/pat.py; this file only starts it, so commands stay the same.
"""
import os
import runpy
import sys

if __name__ == "__main__":
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
    sys.path.insert(0, app)
    runpy.run_path(os.path.join(app, "pat.py"), run_name="__main__")
