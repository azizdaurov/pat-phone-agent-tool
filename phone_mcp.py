"""The pat-phone MCP server that Claude Code agents place calls through. setup.ps1 registers it.

The code is in app/phone_mcp.py; this file only starts it, so commands stay the same.
"""
import os
import runpy
import sys

if __name__ == "__main__":
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
    sys.path.insert(0, app)
    runpy.run_path(os.path.join(app, "phone_mcp.py"), run_name="__main__")
