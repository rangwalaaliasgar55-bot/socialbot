#!/usr/bin/env python3
from pathlib import Path

p = Path("socialbot/api/app.py")
text = p.read_text(encoding="utf-8")
if "register_skills_routes" in text:
    print("already applied")
    raise SystemExit(0)
needle = "    return app\n"
inject = """    from ..skills_api import register_skills_routes
    register_skills_routes(app, state)

    return app
"""
if "register_stonic_routes(app, state)" in text:
    text = text.replace(
        "    register_stonic_routes(app, state)\n",
        "    register_stonic_routes(app, state)\n    from ..skills_api import register_skills_routes\n    register_skills_routes(app, state)\n",
        1,
    )
else:
    idx = text.rfind(needle)
    if idx < 0:
        raise SystemExit("return app not found")
    text = text[:idx] + inject + text[idx + len(needle):]
p.write_text(text, encoding="utf-8")
print("skills API registered")
