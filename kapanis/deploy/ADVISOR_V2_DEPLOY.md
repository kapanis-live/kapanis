# Kripto Danışman V2: production deploy without OpenBB

Decision support only. Nothing here sends an order; there is no order code and no exchange trading key.
OpenBB stays out: `WITH_OPENBB=0` (the Dockerfile default), `OPENBB_PYTHON` and `OPENBB_URL` unset. Macro is `UNAVAILABLE`.

Every step runs on the server (GCP console, SSH button) unless it says "browser". No command below prints a secret.
Stop at the first step that reports a problem.

## 1. Code and environment

```bash
cd ~/kapanis && git fetch -q origin && git log -1 --format='%h %s' origin/main
# the script is read straight from the fetched commit: the working tree is not touched before guncelle.sh pulls
git show origin/main:kapanis/deploy/advisor_v2_env.sh | bash -s                # report: configured=true/false
git show origin/main:kapanis/deploy/advisor_v2_env.sh | bash -s -- --fix       # only when something is missing
```

`--fix` copies `DEEPSEEK_API_KEY` from `deploy/bot.env` and writes `ADMIN_EMAILS` from the database: the owner's
Clerk-verified account (`users`: role owner or admin, `clerk_id`, `email_verified`). Nothing typed and nothing a browser sent is
used. If it says there is no verified owner, sign in to the site once with the owner's account and run it again.
`NOT READY` means: do not deploy.

## 2. Deploy

Upload `build-new.tgz` (SSH window, "Upload file"), then:

```bash
bash ~/guncelle.sh
```

It builds `kapanis:latest` from `kapanis/deploy/Dockerfile.prebuilt` with no build argument, so `WITH_OPENBB` is 0.

## 3. Image and services

```bash
cd ~/kapanis
docker images kapanis:latest --format 'size {{.Size}}  created {{.CreatedSince}}'
docker history --no-trunc --format '{{.CreatedBy}}' kapanis:latest | grep -ciE 'openbb.*pip install|API_KEY=|SECRET=|PASSWORD='   # 0
docker history --format '{{.CreatedBy}}' kapanis:latest | grep -c 'WITH_OPENBB=0'                                                  # 1 or more
docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
docker compose logs --since 10m web worker 2>&1 | grep -ciE 'traceback|error'       # look at the lines when it is not 0
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
df -h / | tail -1
```

## 4. Server-side check (inside the web container)

```bash
cd ~/kapanis && docker compose exec -T web python - < kapanis/deploy/advisor_v2_check.py
```

It reports: variables set or not, no OpenBB / no `.env` / no `.venv-openbb` in the image, no order endpoint or signing
code in the source, the engine and ruleset versions, Binance and MongoDB reachable, the Clerk-verified owner on the admin
list (true/false), one engine-only BTC run (no AI call, nothing logged), and what the paper log and the audit log hold.
The last line is `READY` or `NOT READY: ...`.

## 5. Smoke test with the real session (browser)

1. Open the site, sign in as the admin, open `/admin/advisor`. All nine tabs must load.
2. F12 -> Console, paste the content of `kapanis/deploy/advisor_v2_smoke.js`, Enter. It takes up to two minutes.
3. Copy the JSON it prints. Expected: `health.deepseek_configured` true, `health.session.auth` "clerk" with
   `email_verified` and `on_admin_list` true, `openbb_mode` "not_installed", three analysts `OK`, `parallel` true,
   `engine_only.levels_identical` true, `engine_only.paper_logged_again` 0, `protection_unknown_stop.r_basis`
   `ESTIMATED_R`, `protection_known_stop.r_basis` `RECORDED_INITIAL_STOP`, `macro.macro_status` `UNAVAILABLE`,
   `order_sent` false everywhere, `history.last.has_email` false.
4. Sign out, sign in with any other account, paste the same snippet: `verdict` must be
   `REFUSED_AS_EXPECTED_FOR_NON_ADMIN`, and the menu must not show "Kripto Danışman V2". Signed out: the page asks for a login.

## 6. Analyst timeout (temporary, restored at the end)

```bash
cd ~/kapanis
echo 'ADVISOR_AI_TOTAL_TIMEOUT_SECONDS=1' >> deploy/web.env && docker compose up -d --force-recreate web
```

Browser: run one BTC analysis. Expected: the three analysts `CEVAP YOK`, `EKSİK KONSENSÜS — AL yok`, no buy plan.

```bash
sed -i '/^ADVISOR_AI_TOTAL_TIMEOUT_SECONDS=1$/d' deploy/web.env && docker compose up -d --force-recreate web
bash kapanis/deploy/advisor_v2_env.sh && docker compose exec -T web python - < kapanis/deploy/advisor_v2_check.py | grep -E 'timeouts|result'
```

`timeouts` must show `AI_TOTAL_TIMEOUT_SECONDS: 100` again.

## Roll back

`~/guncelle.sh` keeps a backup before it updates. The V2 pages are additive: V1 (`/app/danisman`, Telegram `/danis`) does
not read any V2 variable. Removing `DEEPSEEK_API_KEY` from `deploy/web.env` leaves V2 in `DEGRADED_CONSENSUS` (no buy plan);
`~/web.env.before-advisor-v2` is the file as it was before `--fix`.
