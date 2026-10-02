#!/usr/bin/env bash
# Kripto Danışman V2: is the web container's environment ready? Run on the server, before the deploy:
#
#   bash ~/kapanis/kapanis/deploy/advisor_v2_env.sh          report only
#   bash ~/kapanis/kapanis/deploy/advisor_v2_env.sh --fix    fill what is missing, then report
# Before the server has pulled this file (run in ~/kapanis):
#   git fetch -q origin && git show origin/main:kapanis/deploy/advisor_v2_env.sh | bash -s -- --fix
#
# It prints configured=true/false and nothing else: no key, no e-mail, no line of an env file is ever shown.
# --fix does two things, both from data that is already on the server:
#   DEEPSEEK_API_KEY  copied from deploy/bot.env (the bot's own key) when deploy/web.env has none
#   ADMIN_EMAILS      the owner's Clerk-verified e-mail as the DATABASE holds it (users: role owner or admin, clerk_id,
#                     email_verified). Nothing typed here and nothing a browser sent is used.
# OpenBB variables are only reported; this script never sets them. Exit code 1 = not ready, do not deploy.
set -euo pipefail
case "$0" in */advisor_v2_env.sh) cd "$(dirname "$0")/../.." ;; esac     # piped into bash: the current directory is the clone
WEB=deploy/web.env
BOT=deploy/bot.env
FIX=${1:-}
[ -f "$WEB" ] || { echo "$WEB not found (run this in the server's clone)"; exit 1; }

has() { grep -qE "^$1=.+" "$2" 2>/dev/null; }
flag() { if has "$1" "$2"; then echo true; else echo false; fi; }
newline() { [ -z "$(tail -c1 "$WEB")" ] || echo >> "$WEB"; }
saved=0
backup() {   # once, outside the repository, readable by the owner only
  [ "$saved" = 1 ] && return
  ( umask 077; cp "$WEB" "$HOME/web.env.before-advisor-v2" )
  saved=1
}

if [ "$FIX" = "--fix" ]; then
  if ! has DEEPSEEK_API_KEY "$WEB"; then
    if has DEEPSEEK_API_KEY "$BOT"; then
      backup; sed -i '/^DEEPSEEK_API_KEY=/d' "$WEB"; newline
      grep -E '^DEEPSEEK_API_KEY=.+' "$BOT" | tail -1 >> "$WEB"
      echo "DEEPSEEK_API_KEY: copied from $BOT"
    else
      echo "DEEPSEEK_API_KEY: not in $BOT either; add it to $WEB by hand (nano $WEB)"
    fi
  fi
  if ! has ADMIN_EMAILS "$WEB"; then
    # read inside the running web container: it has the database address; the e-mail goes into a variable, not onto the screen
    owner=$(docker compose exec -T web python -c '
import os
from pymongo import MongoClient
db = MongoClient(os.environ.get("MONGO_URL") or os.environ["STATE_MONGO_URL"], serverSelectionTimeoutMS=10000)[
    os.environ.get("DB_NAME") or os.environ.get("STATE_DB_NAME") or "kapanis"]
rows = list(db.users.find({"role": {"$in": ["owner", "admin"]}, "clerk_id": {"$exists": True, "$ne": None}, "email_verified": True}, {"email": 1}))
print(rows[0]["email"].strip().lower() if len(rows) == 1 and rows[0].get("email") else "")
' 2>/dev/null | tr -d '\r\n' || true)
    if printf '%s' "$owner" | grep -qE '^[^@[:space:],]+@[^@[:space:],]+\.[^@[:space:],]+$'; then
      backup; sed -i '/^ADMIN_EMAILS=/d' "$WEB"; newline
      printf 'ADMIN_EMAILS=%s\n' "$owner" >> "$WEB"
      echo "ADMIN_EMAILS: set from the database (the owner's Clerk-verified e-mail)"
    else
      echo "ADMIN_EMAILS: the database has no single Clerk-verified owner account."
      echo "  Sign in to the site once with the owner's account (OWNER_EMAIL must be that address), then run this again."
    fi
  fi
  [ "$saved" = 1 ] && echo "previous $WEB saved as ~/web.env.before-advisor-v2 (delete it when the deploy is confirmed)"
fi

echo "== $WEB (values are never shown)"
echo "DEEPSEEK_API_KEY configured=$(flag DEEPSEEK_API_KEY "$WEB")"
echo "ADMIN_EMAILS configured=$(flag ADMIN_EMAILS "$WEB")"
echo "OWNER_EMAIL configured=$(flag OWNER_EMAIL "$WEB")"
echo "AUTH_MODE=$(grep -E '^AUTH_MODE=' "$WEB" | tail -1 | cut -d= -f2 | tr -d '\r' || true)"
echo "OPENBB_PYTHON set=$(flag OPENBB_PYTHON "$WEB")   (must be false)"
echo "OPENBB_URL set=$(flag OPENBB_URL "$WEB")   (must be false)"
echo "exchange trading keys in $WEB or $BOT: $(grep -cE '^(BINANCE|MIDAS)[A-Z_]*(SECRET|API_KEY)=.+' "$WEB" "$BOT" 2>/dev/null | awk -F: '{s+=$2} END {print s+0}')   (must be 0)"

missing=""
has DEEPSEEK_API_KEY "$WEB" || missing="$missing DEEPSEEK_API_KEY"
has ADMIN_EMAILS "$WEB" || missing="$missing ADMIN_EMAILS"
if has OPENBB_PYTHON "$WEB" || has OPENBB_URL "$WEB"; then missing="$missing OPENBB_must_be_unset"; fi
if [ -n "$missing" ]; then
  echo "NOT READY, missing:$missing"
  echo "Do not deploy. Run with --fix, or edit $WEB by hand."
  exit 1
fi
echo "READY: deploy with  bash ~/guncelle.sh  (the containers are recreated, so the new variables are read)"
