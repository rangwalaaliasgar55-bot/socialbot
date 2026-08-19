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

### Mastodon
1. Log into your instance → **Preferences → Development → New application**
2. Scopes: `write:statuses`, `write:media`, `read:search`, `write:favourites`, `write:follows`
3. Copy the **access token**. Instance URL is e.g. `https://mastodon.social`.

### Bluesky
1. Settings → **App passwords** → create one (`xxxx-xxxx-xxxx-xxxx`)
2. Use your handle as identifier. PDS defaults to `https://bsky.social`.

### Reddit
1. `reddit.com/prefs/apps` → **create another app…** → choose **script**
2. `client_id` is under the app name, `client_secret` is labeled *secret*
3. Use your login username/password (the app acts as your account)

### X (Twitter)
1. `developer.x.com` → create a Project + App
2. Set up **User authentication settings** (OAuth 2.0, web, read/write)
3. Generate an OAuth 2.0 **user access token** with scopes `tweet.read tweet.write users.read like.write follows.write offline.access`
4. Paste the token (and refresh token + client id/secret for auto-refresh)

### Telegram
1. Chat with **@BotFather** → `/newbot` → copy the token
2. Add the bot to your channel/group as **admin**, or DM it and use your numeric id
3. Get chat ids from `https://api.telegram.org/bot<TOKEN>/getUpdates`

### Discord
Server Settings → **Integrations → Webhooks → New Webhook → Copy Webhook URL**

### Slack
`api.slack.com/messaging/webhooks` → create app → incoming webhook → copy URL

### LinkedIn
1. Create an app at `developer.linkedin.com` with the **Sign In with LinkedIn (OpenID Connect)** product
2. Generate a user token with scope `w_member_social`
3. `member_id` = the `sub` claim from your OpenIDConnect id token

### Facebook Page
1. `developers.facebook.com` → create app → add **Pages API**
2. Get a Page access token with `pages_manage_posts`, `pages_read_engagement`
3. Page id is visible in the Page's "About" section or via `/me/accounts`

### Instagram Business
1. Convert to a Business/Creator account linked to a Facebook Page
2. Token with `instagram_content_publish`
3. `user_id` = the IG Business account id (`/{page-id}?fields=instagram_business_account`)

### Threads
1. `developers.facebook.com` → Threads API app
2. Token with `threads_basic` + `threads_content_publish`
3. User id from `https://graph.threads.net/v1.0/me`

### Pinterest
1. `developers.pinterest.com` → create app → get token with `pins:write`, `boards:read`
2. Board id from `GET https://api.pinterest.com/v5/boards`
