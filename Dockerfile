# One image, two processes: "web" (FastAPI + React panel) and "worker" (Telegram bot + scheduled jobs).
# No secrets are baked in: every key comes from the platform's environment variables at runtime.

FROM node:20-bookworm-slim AS web
# small VMs (1-2 GB RAM + swap): cap the build's memory, skip source maps (also keeps source out of the site)
ENV NODE_OPTIONS=--max-old-space-size=1536 GENERATE_SOURCEMAP=false
WORKDIR /src
COPY kapanis/frontend/package.json kapanis/frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund
COPY kapanis/frontend/ ./
RUN npx craco build

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Europe/Istanbul
WORKDIR /app
COPY kapanis/backend/requirements.cloud.txt /tmp/web-req.txt
COPY kriptografikbotu/requirements.txt /tmp/bot-req.txt
RUN pip install -r /tmp/web-req.txt -r /tmp/bot-req.txt
COPY kapanis/backend/ kapanis/backend/
COPY kriptografikbotu/ kriptografikbotu/
COPY --from=web /src/build kapanis/frontend/build
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh && useradd --create-home kapanis && mkdir -p /app/kriptografikbotu/data && chown -R kapanis /app
USER kapanis
EXPOSE 8001
CMD ["/app/start.sh", "web"]
