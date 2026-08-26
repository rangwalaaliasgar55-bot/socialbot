#!/usr/bin/env python3
"""Apply ChatGPT CLI commands to socialbot/cli.py

Run from repo root after pulling main:
  python tools/apply_chatgpt_cli.py
"""
from pathlib import Path

snippet = r'''
# ---------------------------------------------------------------- chatgpt
@cli.group("chatgpt")
def chatgpt_group():
    """Sign in with ChatGPT account (no API key) — Stonic-style AI."""


@chatgpt_group.command("login")
@click.option("--port", default=1455, show_default=True, help="local OAuth callback port")
@click.option("--no-browser", is_flag=True, help="print URL only (headless/SSH)")
def chatgpt_login(port: int, no_browser: bool):
    """Open browser, sign in with ChatGPT, save tokens locally."""
    from .chatgpt_oauth import ChatGPTOAuth
    store = get_store()
    client = ChatGPTOAuth(store=store)
    click.echo("🔗 Opening ChatGPT sign-in…")
    click.echo(f"   callback: http://127.0.0.1:{port}/auth/callback")
    try:
        status = client.login(port=port, open_browser=not no_browser)
    except Exception as exc:
        raise click.ClickException(str(exc))
    click.echo(f"✅ ChatGPT connected. account_id={status.get('account_id') or '—'}")
    click.echo("   drafts will use your ChatGPT plan (no API key).")
    click.echo("   try: socialbot generate \"product launch\"")


@chatgpt_group.command("status")
def chatgpt_status():
    """Show ChatGPT sign-in status."""
    from .chatgpt_oauth import ChatGPTOAuth
    store = get_store()
    st = ChatGPTOAuth(store=store).status()
    if st["authenticated"]:
        click.echo(f"✅ signed in  account_id={st.get('account_id') or '—'}  expires={st.get('expires')}")
    else:
        click.echo("— not signed in. Run: socialbot chatgpt login")


@chatgpt_group.command("logout")
@click.confirmation_option(prompt="Sign out of ChatGPT?")
def chatgpt_logout():
    """Remove stored ChatGPT tokens."""
    from .chatgpt_oauth import ChatGPTOAuth
    ChatGPTOAuth(store=get_store()).logout()
    click.echo("signed out")
'''

def main():
    p = Path("socialbot/cli.py")
    text = p.read_text(encoding="utf-8")
    marker = "# ----------------------------------------------------------------- generate"
    if "chatgpt_group" in text:
        print("already applied")
    else:
        if marker not in text:
            raise SystemExit("marker not found in socialbot/cli.py")
        text = text.replace(marker, snippet + "\n" + marker)
    old = "    drafts = ai_mod.generate(topic, n, tone)"
    new = "    drafts = ai_mod.generate(topic, n, tone, store=get_store())"
    if old in text:
        text = text.replace(old, new)
    text = text.replace(
        '"""AI-generate post drafts about TOPIC (templates offline, LLM if key set)."""',
        '"""AI-generate post drafts about TOPIC (ChatGPT sign-in preferred, else API key, else templates)."""',
    )
    p.write_text(text, encoding="utf-8")
    print("cli.py patched — run: pip install -e . && socialbot chatgpt login")

if __name__ == "__main__":
    main()
