"""Pat's tests. The code is in app/, which goes first on the import path: pat.py, note.py, report.py and
phone_mcp.py in the main folder are only launchers with the same names."""
import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if APP not in sys.path:
    sys.path.insert(0, APP)
