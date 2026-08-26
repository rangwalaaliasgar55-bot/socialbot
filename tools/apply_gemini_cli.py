#!/usr/bin/env python3
"""Wire socialbot gemini login|status|logout|generate into cli.py"""
from pathlib import Path

p = Path("socialbot/cli.py")
text = p.read_text(encoding="utf-8")
if "def gemini_group" in text or '@cli.group("gemini")' in text:
    print("gemini cli already applied")
    raise SystemExit(0)

snippet = r'''
# ---------------------------------------------------------------- gemini
@cli.group("gemini")
def gemini_group():
    """Gemini / Google account sign-in (OAuth, no API key)."""


@gemini_group.command("login")
@click.option("--no-browser", is_flag=True)
def gemini_login(no_browser: bool):
    """Sign in with Google in the browser. Requires SOCIALBOT_GEMINI_CLIENT_ID."""
    from .gemini_oauth import GeminiOAuth
    store = get_store()
    status = GeminiOAuth(store=store).login(open_browser=not no_browser)
    echo_json(status)


@gemini_group.command("status")
def gemini_status():
    from .gemini_oauth import GeminiOAuth
    echo_json(GeminiOAuth(store=get_store()).status())


@gemini_group.command("logout")
def gemini_logout():
    from .gemini_oauth import GeminiOAuth
    GeminiOAuth(store=get_store()).logout()
    click.echo("gemini logged out")


@gemini_group.command("generate")
@click.argument("prompt")
@click.option("--model", default="gemini-2.0-flash")
@click.option("-n", default=1, type=int)
def gemini_generate(prompt: str, model: str, n: int):
    from .gemini_oauth import GeminiOAuth
    texts = GeminiOAuth(store=get_store()).generate(prompt, model=model, n=n)
    for t in texts:
        click.echo(t)
'''

marker = "# ---------------------------------------------------------------- chatgpt"
if marker in text:
    text = text.replace(marker, snippet + "\n" + marker, 1)
elif "# ---------------------------------------------------------------- voice" in text:
    text = text.replace("# ---------------------------------------------------------------- voice", snippet + "\n# ---------------------------------------------------------------- voice", 1)
else:
    marker2 = "# ----------------------------------------------------------------- generate"
    if marker2 not in text:
        raise SystemExit("no insert marker in cli.py")
    text = text.replace(marker2, snippet + "\n" + marker2, 1)

p.write_text(text, encoding="utf-8")
print("gemini CLI applied")
