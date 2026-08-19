# Security

- Credentials are stored **locally in your SQLite database** and masked in the
  API/dashboard responses. Never commit `socialbot.db` or `.env` (both gitignored).
- SocialBot never proxies tokens through third parties and makes outbound calls
  only to the official API endpoints of the platforms you configure.
- The dashboard/API server binds `0.0.0.0` by default for containers — restrict
  with `socialbot dashboard --host 127.0.0.1` or put it behind a reverse proxy
  with auth before exposing it publicly.
- Report vulnerabilities privately via GitHub Security Advisories.
