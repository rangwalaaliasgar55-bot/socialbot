# Environment variables reference

SocialBot reads settings in this order: **account config in the database**
(`socialbot accounts add …`) → `PLATFORM_FIELD` env var → `.env` file.

## Core

| Variable | Default | Purpose |
|---|---|---|
| `SOCIALBOT_DB` | `./socialbot.db` | SQLite database path |
| `SOCIALBOT_WEBHOOK_URL` | — | Global webhook fired on every publish |
| `SOCIALBOT_AI_API_KEY` | — | Enables LLM drafts |
| `SOCIALBOT_AI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible endpoint |
| `SOCIALBOT_AI_MODEL` | `gpt-4o-mini` | Model name |

## How to get platform credentials

### LinkedIn
1. Create an app at `developer.linkedin.com` with the **Sign In with LinkedIn (OpenID Connect)** product
2. Generate a user token with scope `w_member_social`
3. `member_id` = the `sub` claim from your OpenIDConnect id token

### X (Twitter)
1. `developer.x.com` → create a Project + App
2. Set up **User authentication settings** (OAuth 2.0, web, read/write)
3. Generate an OAuth 2.0 **user access token** with scopes `tweet.read tweet.write users.read like.write follows.write offline.access`
4. Paste the token (and refresh token + client id/secret for auto-refresh)

### YouTube
1. Google Cloud Console → create a project → enable **YouTube Data API v3**
2. Create an **OAuth 2.0 Client ID** (Desktop application)
3. Run the OAuth flow to obtain `access_token` + `refresh_token` (paste `client_id`/`client_secret` and they auto-refresh)
4. Optional: `privacy` (`public`/`unlisted`/`private`, default `public`), `category_id`

### Telegram
1. Chat with **@BotFather** → `/newbot` → copy the token
2. Add the bot to your channel/group as **admin**, or DM it and use your numeric id
3. Get chat ids from `https://api.telegram.org/bot<TOKEN>/getUpdates`