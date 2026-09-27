#!/bin/sh
# web: panel + API on $PORT (Heroku/Render set it) · worker: Telegram bot, alarms, scheduled jobs
set -e
case "$1" in
  web)
    cd /app/kapanis/backend
    exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8001}" --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    cd /app/kriptografikbotu
    exec python main.py
    ;;
  *)
    echo "usage: start.sh web|worker" >&2
    exit 2
    ;;
esac
