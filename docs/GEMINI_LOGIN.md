# Gemini login (Google account, no API key)

Same pattern as ChatGPT OAuth: browser sign-in, local tokens, your quotas.

## One-time Google Cloud setup (free)

1. [Google Cloud Console](https://console.cloud.google.com/) → create/select a project  
2. Enable **Generative Language API**  
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**  
   - Application type: **Desktop app**  
   - Copy **Client ID** (and Client secret if shown)  
4. **OAuth consent screen**: User type External → add your Google email as a **test user**

## Env

```bash
export SOCIALBOT_GEMINI_CLIENT_ID="123456789-xxxx.apps.googleusercontent.com"
export SOCIALBOT_GEMINI_CLIENT_SECRET="..."   # if provided
```

## Commands

```bash
git pull
python tools/apply_gemini_cli.py
pip install -e .

socialbot gemini login
socialbot gemini status
socialbot gemini generate "write a short product launch tweet"
socialbot gemini logout
```

Tokens are stored in SocialBot SQLite under platform `gemini`.  
Generation uses `Authorization: Bearer <access_token>` against Generative Language API — subject to **your** free-tier / plan limits.

Not supported: hijacking Gemini CLI subscription tokens or any third-party free bypass.
