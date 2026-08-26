"""Desktop automation skills — operator's own machine only.

Safe actions: open URL/app, list files, system stats, AI draft via linked ChatGPT.
No remote control of third-party accounts. No credential theft.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict

ALLOWED_APPS = {
    "chrome", "google-chrome", "chromium", "firefox", "code", "notepad",
    "gedit", "nautilus", "explorer", "calc", "gnome-calculator",
}


class DesktopSkills:
    def run(self, text: str, store=None) -> Dict[str, Any]:
        t = (text or "").strip().lower()
        if not t:
            return {"ok": False, "error": "empty command"}

        if t.startswith("open ") or t.startswith("launch "):
            target = re.sub(r"^(open|launch)\s+", "", t, flags=re.I).strip()
            return self.open_thing(target)

        if "system" in t and any(w in t for w in ("status", "health", "info", "stats")):
            return {"ok": True, "action": "system_info", "result": self.system_info()}

        if t.startswith("list ") or t.startswith("ls "):
            path = re.sub(r"^(list|ls)\s+", "", t, flags=re.I).strip() or "."
            return self.list_dir(path)

        if "generate" in t or "draft" in t:
            topic = re.sub(r".*?(generate|draft)\s+(about\s+)?", "", t, flags=re.I).strip() or "product"
            if store is not None:
                from . import ai as ai_mod
                drafts = ai_mod.generate(topic, n=2, store=store)
                return {"ok": True, "action": "generate", "drafts": drafts}
            return {"ok": False, "error": "no store for AI"}

        return {
            "ok": True,
            "action": "echo",
            "result": f"heard: {text}",
            "hint": "try: open youtube.com | system status | list ~/Downloads | draft about launch",
        }

    def open_thing(self, target: str) -> Dict[str, Any]:
        if target.startswith("http://") or target.startswith("https://") or ("." in target and " " not in target):
            url = target if target.startswith("http") else f"https://{target}"
            webbrowser.open(url)
            return {"ok": True, "action": "open_url", "url": url}
        base = Path(target).name.lower().replace(".exe", "")
        if base not in ALLOWED_APPS and target not in ALLOWED_APPS:
            return {"ok": False, "error": f"app not allowlisted: {target}", "allowed": sorted(ALLOWED_APPS)}
        exe = shutil.which(target) or shutil.which(base)
        if not exe:
            return {"ok": False, "error": f"not found on PATH: {target}"}
        subprocess.Popen([exe], start_new_session=True)
        return {"ok": True, "action": "open_app", "exe": exe}

    def list_dir(self, path: str) -> Dict[str, Any]:
        p = Path(path).expanduser()
        if not p.is_dir():
            return {"ok": False, "error": f"not a directory: {path}"}
        names = sorted([x.name for x in p.iterdir()])[:100]
        return {"ok": True, "action": "list_dir", "path": str(p), "entries": names}

    def system_info(self) -> Dict[str, Any]:
        return {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cwd": os.getcwd(),
            "home": str(Path.home()),
        }
