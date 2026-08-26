# SocialBot Command Center (Stonic-style)

SocialBot is a **self-hosted social automation stack**. This layer adds a **Stonic Gen 2–style command center** on top:

| Stonic concept | SocialBot implementation |
|----------------|--------------------------|
| Sign in with ChatGPT (no API key) | `socialbot chatgpt login` + `socialbot/chatgpt_oauth.py` |
| HUD themes (Cyan / Crimson / Emerald) | Dashboard theme pills · `stonic.css` |
| Agent Town (Alice, Bob, Carol, Dave) | `socialbot/agent_town.py` + `/api/stonic/agents` |
| System Core (Memory / Skills / Soul / Settings) | `/api/stonic/core` |
| Living operators | Map to drafts, growth rules, trends, inbox |

## Quick start

```bash
git pull
python tools/apply_chatgpt_cli.py   # once — wires CLI chatgpt commands
pip install -e .
socialbot chatgpt login             # browser OAuth, no API key
socialbot dashboard                 # open http://localhost:8000
```

Open **◆ Command** for System Core + ChatGPT status. Open **🏢 Agent Town** for resident agents.

## Themes

Top bar theme pills persist in `localStorage` (`sb_theme`). CSS variables recolour the full HUD.

## API

- `GET /api/stonic/core` — circuits + ChatGPT link state  
- `GET /api/stonic/agents` — Agent Town roster + live tasks  
- `POST /api/stonic/agents/{id}/assign` — `{ "task": "…" }`

Social posting / scheduling / growth bot remain the product core. The Stonic layer is the **experience shell** and AI connectivity path.
