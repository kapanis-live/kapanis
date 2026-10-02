# OpenBB staging test (not production)

Status 2026-10-02: **OpenBB is not in the production image.** `Dockerfile.prebuilt` builds with `WITH_OPENBB=0` unless told
otherwise, `OPENBB_PYTHON` / `OPENBB_URL` are unset on the VM, and the advisor's macro block is `UNAVAILABLE` there. The
technical advisor does not depend on it. This file is the plan for measuring OpenBB before it goes anywhere near the VM.
Nothing below has been run yet.

Why it is held back: the Docker layer was never built, it adds about 1 GB, the first read takes about 26 s, the effect
on a small VM's RAM and disk is unmeasured, and OpenBB needs FastAPI >= 0.137 while the backend pins 0.110.1 (so it can
only live in its own virtual environment or its own container).

## What to measure

| # | Measurement | How |
|---|---|---|
| 1 | Image size | `docker images kapanis:openbb-test --format '{{.Size}}'` against `kapanis:latest` |
| 2 | Build duration | `time docker build ...` (cold, then with the layer cache) |
| 3 | Idle RAM | `docker stats --no-stream` 2 minutes after start, before any macro call |
| 4 | First-request RAM peak | `docker stats` sampled every second during the first `/api/admin/advisor/macro` |
| 5 | First-request latency | `curl -w '%{time_total}'` on the first `/macro` (cold cache) |
| 6 | Cached latency | the same call again within 5 minutes |
| 7 | Worker restart latency | `docker compose restart web` (or the worker), then the first `/macro` |
| 8 | Backend startup latency | time from `docker compose up -d web` to the first `200` on `/api/` |
| 9 | Disk remaining | `df -h /` and `docker system df` before and after |
| 10 | Healthcheck | `/api/admin/advisor/health?deep=true` -> `openbb.status == "OK"`; with the worker stopped -> `UNAVAILABLE` and `/analyze` still 200 |

Accept only if, on a VM of the production size: the build finishes without swapping the machine to a halt, idle RAM grows
by a negligible amount (the subprocess exits after each read), the first-request peak leaves headroom for web + worker +
Caddy, and at least 2 GB of disk stays free after the image and one old image are both present. Otherwise use option B.

## Option A: OpenBB inside the web image (its own venv, called as a subprocess)

Run on a staging machine or a copy of the VM, never on the live one:

```bash
cd ~/kapanis
df -h / ; docker system df                                   # 9: before
time docker build -f kapanis/deploy/Dockerfile.prebuilt --build-arg WITH_OPENBB=1 -t kapanis:openbb-test .   # 2
docker images kapanis --format '{{.Tag}} {{.Size}}'          # 1
df -h / ; docker system df                                   # 9: after

# a throw-away web container on another port, with the staging env file plus OPENBB_PYTHON
cp deploy/web.env /tmp/web.openbb.env && echo 'OPENBB_PYTHON=/opt/openbb/bin/python' >> /tmp/web.openbb.env
START=$(date +%s.%N)
docker run -d --name web-openbb-test --env-file /tmp/web.openbb.env -p 127.0.0.1:8011:8001 kapanis:openbb-test /app/start.sh web
until curl -fs http://127.0.0.1:8011/api/ >/dev/null; do sleep 0.5; done
echo "startup: $(echo "$(date +%s.%N) - $START" | bc) s"     # 8
sleep 120 ; docker stats --no-stream web-openbb-test         # 3

# the macro endpoint needs an admin session: use a Clerk session token of the admin account (never paste it into a file)
read -s TOKEN
( while docker stats --no-stream --format '{{.MemUsage}}' web-openbb-test; do sleep 1; done ) > /tmp/mem.log &   # 4
curl -s -o /dev/null -w 'first: %{time_total}s\n'  -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8011/api/admin/advisor/macro   # 5
curl -s -o /dev/null -w 'cached: %{time_total}s\n' -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8011/api/admin/advisor/macro   # 6
kill %1 ; sort -h /tmp/mem.log | tail -1                     # 4: the peak
curl -s -H "Authorization: Bearer $TOKEN" 'http://127.0.0.1:8011/api/admin/advisor/health?deep=true'   # 10

docker restart web-openbb-test                               # 7
curl -s -o /dev/null -w 'after restart: %{time_total}s\n' -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8011/api/admin/advisor/macro

docker rm -f web-openbb-test ; docker rmi kapanis:openbb-test ; rm /tmp/web.openbb.env /tmp/mem.log
```

Known unknown in this option: OpenBB builds part of its own package on the first import. The Dockerfile runs that
import as root during the build; whether the unprivileged `kapanis` user can then import it without rebuilding is
exactly what step 5 will show (a failure appears as `macro_status: UNAVAILABLE` with the reason in `unavailable_fields`).

## Option B: a small OpenBB worker next to the web container

```
web / backend  --HTTP (internal Docker network)-->  openbb worker  (python openbb_worker.py serve 8010)
   OPENBB_URL=http://openbb:8010                     its own image: python:3.11-slim + pip install openbb
```

The backend already speaks this: when `OPENBB_URL` is set, `danisman_v2/macro.py` reads `GET {OPENBB_URL}/calendar`,
`/macro`, `/cross_asset`, `/health` instead of starting a process. The worker is `danisman_v2/openbb_worker.py serve`
(standard library HTTP server, no auth: it must stay on the internal network and never get a published port or a Caddy
route). Sketch, not added to `docker-compose.yml` yet:

```yaml
  openbb:
    build:
      context: .
      dockerfile_inline: |
        FROM python:3.11-slim
        RUN pip install --no-cache-dir openbb && python -c "from openbb import obb"
        COPY kriptografikbotu/danisman_v2/openbb_worker.py /app/openbb_worker.py
        CMD ["python", "/app/openbb_worker.py", "serve", "8010"]
    restart: unless-stopped
    mem_limit: 700m          # set from measurement 4
  web:
    environment:
      OPENBB_URL: http://openbb:8010
```

What changes against option A: the web image stays as small as it is now; OpenBB stays loaded (about 16 s of import is
paid once at container start, not on every cache miss), so its RAM is permanent instead of a peak; a crash or an OOM
kill of the worker cannot touch the web process. The same ten measurements apply, taken on the `openbb` container.

## Either way

- If OpenBB is down, slow or missing: `macro_status` is `DEGRADED` / `UNAVAILABLE`, the fields it could not read are
  listed with the reason, nothing is invented, and analysis, buy plan, protection plan and scan keep working. A coin
  analysis waits at most `ADVISOR_MACRO_WAIT_SECONDS` (40) for macro.
- No provider key is needed for what the advisor reads today (calendars, Treasury rates, EFFR, OECD CPI / unemployment,
  Cboe SPX / VIX, Nasdaq 100). FRED series would need `FRED_API_KEY` inside the OpenBB environment.
- Event importance stays unknown unless `ADVISOR_MACRO_HIGH_IMPACT_KEYWORDS` is set.
