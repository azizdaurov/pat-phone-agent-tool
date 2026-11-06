"""Pat's sticky note. Start it with pythonw, so it opens no terminal.

The code is in app/note.py; this file only starts it, so commands stay the same.
"""
import os
import runpy
import sys

if __name__ == "__main__":
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
    sys.path.insert(0, app)
    runpy.run_path(os.path.join(app, "note.py"), run_name="__main__")
