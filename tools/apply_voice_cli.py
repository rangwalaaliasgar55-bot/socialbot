#!/usr/bin/env python3
from pathlib import Path

p = Path("socialbot/cli.py")
text = p.read_text(encoding="utf-8")
if "def voice_cmd" in text:
    print("voice cli already applied")
    raise SystemExit(0)
snippet = r'''
# ---------------------------------------------------------------- voice / desktop
@cli.command("voice")
@click.option("--once", is_flag=True, help="listen once and exit")
def voice_cmd(once: bool):
    """Voice listen → skill router (mic required)."""
    from .voice import VoiceEngine
    store = get_store()
    eng = VoiceEngine(store=store)
    caps = eng.capabilities()
    click.echo(f"voice caps: {caps}")
    if not caps.get("stt_local"):
        click.echo("install: pip install SpeechRecognition pyaudio pyttsx3")
        click.echo("or type commands via: socialbot skill \"system status\"")
        return
    try:
        text = eng.listen_once()
    except Exception as exc:
        raise click.ClickException(str(exc))
    click.echo(f"heard: {text}")
    result = eng.handle_command(text)
    eng.speak(str(result.get("result") or result.get("action") or "done"))
    echo_json(result)


@cli.command("skill")
@click.argument("text")
def skill_cmd(text: str):
    """Run a desktop/AI skill from text (no mic)."""
    from .desktop_skills import DesktopSkills
    result = DesktopSkills().run(text, store=get_store())
    echo_json(result)
'''
marker = "# ---------------------------------------------------------------- chatgpt"
if marker in text:
    text = text.replace(marker, snippet + "\n" + marker, 1)
else:
    marker2 = "# ----------------------------------------------------------------- generate"
    if marker2 not in text:
        raise SystemExit("no insert marker")
    text = text.replace(marker2, snippet + "\n" + marker2, 1)
p.write_text(text, encoding="utf-8")
print("voice/skill CLI applied")
