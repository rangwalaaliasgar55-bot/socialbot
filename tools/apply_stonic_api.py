#!/usr/bin/env python3
"""Wire Stonic API routes into socialbot/api/app.py"""
from pathlib import Path

p = Path("socialbot/api/app.py")
text = p.read_text(encoding="utf-8")
if "register_stonic_routes" in text:
    print("already applied")
    raise SystemExit(0)
needle = "    return app\n"
inject = """    from ..stonic_api import register_stonic_routes
    register_stonic_routes(app, state)

    return app
"""
idx = text.rfind(needle)
if idx < 0:
    raise SystemExit("return app not found")
text = text[:idx] + inject + text[idx + len(needle):]
p.write_text(text, encoding="utf-8")
print("stonic API registered in app.py")
