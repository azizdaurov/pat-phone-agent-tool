"""Writes a bug report you can post, with numbers, names and what was said taken out.

The code is in app/report.py; this file only starts it, so commands stay the same.
"""
import os
import runpy
import sys

if __name__ == "__main__":
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
    sys.path.insert(0, app)
    runpy.run_path(os.path.join(app, "report.py"), run_name="__main__")
