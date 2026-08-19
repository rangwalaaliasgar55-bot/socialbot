#!/usr/bin/env bash
# Example: drive SocialBot from scripts / n8n / cron via the REST API.
# Start the server first:  socialbot dashboard
set -euo pipefail
BASE=${1:-http://localhost:8000}

echo "== health =="
curl -s "$BASE/api/health" | head -c 300; echo

echo "== connect the mock platform =="
curl -s -X POST "$BASE/api/accounts" -H 'Content-Type: application/json' \
  -d '{"platform":"mock","label":"demo","config":{"username":"demo"}}' | head -c 300; echo

echo "== publish immediately =="
curl -s -X POST "$BASE/api/posts" -H 'Content-Type: application/json' \
  -d '{"text":"Automated via the SocialBot API 🤖","platforms":["mock"],"publish_now":true}' \
  | head -c 400; echo

echo "== schedule tomorrow 09:00 UTC =="
curl -s -X POST "$BASE/api/posts" -H 'Content-Type: application/json' \
  -d '{"text":"Scheduled by cron","platforms":["mock"],"tag":"automation",
       "scheduled_at":"'"$(date -u -d '+1 day 09:00' +%Y-%m-%dT%H:%M:%SZ)"'"}' \
  | head -c 400; echo

echo "== create + dry-run a bot rule =="
RULE=$(curl -s -X POST "$BASE/api/bot/rules" -H 'Content-Type: application/json' \
  -d '{"name":"engage","platform":"mock","action":"like","trigger_type":"hashtag",
       "trigger_value":"opensource","dry_run":true}')
echo "$RULE" | head -c 300; echo
RID=$(echo "$RULE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -X POST "$BASE/api/bot/rules/$RID/run" | head -c 300; echo

echo "== analytics =="
curl -s "$BASE/api/analytics/summary" | head -c 400; echo
