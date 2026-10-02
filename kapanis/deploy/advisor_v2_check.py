"""Kripto Danışman V2: server-side check, run INSIDE the web container (it has the runtime environment):

    cd ~/kapanis && docker compose exec -T web python - < kapanis/deploy/advisor_v2_check.py

It prints facts only: whether a variable is set (never its value), what the image contains, whether the exchange and
the database answer, what the paper log and the audit log hold. One engine-only run is made (no AI call, nothing
logged). No order code exists to be run. Exit code 1 when something a deploy needs is missing.
"""
import asyncio
import glob
import importlib
import importlib.util
import os
import pathlib
import re
import sys
import time

BACKEND = pathlib.Path("/app/kapanis/backend") if pathlib.Path("/app/kapanis/backend").is_dir() else pathlib.Path(__file__).resolve().parents[1] / "backend"
BOT = BACKEND.parents[1] / "kriptografikbotu"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
problems = []


def show(label, value, ok=None):
    print(f"{label}: {value}" + ("" if ok is None else "   [OK]" if ok else "   [PROBLEM]"))
    if ok is False:
        problems.append(label)


def flag(name):
    return bool(os.environ.get(name, "").strip())


print("== environment (set or not; values are never printed)")
show("DEEPSEEK_API_KEY configured", flag("DEEPSEEK_API_KEY"), flag("DEEPSEEK_API_KEY"))
show("ADMIN_EMAILS configured", flag("ADMIN_EMAILS"), flag("ADMIN_EMAILS"))
show("OWNER_EMAIL configured", flag("OWNER_EMAIL"))
if flag("ADMIN_EMAILS") and flag("OWNER_EMAIL"):
    admins = {e.strip().lower() for e in os.environ["ADMIN_EMAILS"].split(",") if e.strip()}
    show("the owner's account is on the admin list", os.environ["OWNER_EMAIL"].strip().lower() in admins)
show("OPENBB_PYTHON set", flag("OPENBB_PYTHON"), not flag("OPENBB_PYTHON"))
show("OPENBB_URL set", flag("OPENBB_URL"), not flag("OPENBB_URL"))
show("AUTH_MODE", os.environ.get("AUTH_MODE", "legacy"))

print("== image")
show("openbb importable", importlib.util.find_spec("openbb") is not None, importlib.util.find_spec("openbb") is None)
show("/opt/openbb exists", os.path.exists("/opt/openbb"), not os.path.exists("/opt/openbb"))
found = [p for p in glob.glob("/app/**/.env", recursive=True) + glob.glob("/app/**/.env.*", recursive=True) if not p.endswith(".example")]
show(".env files in the image", found or "none", not found)
venvs = glob.glob("/app/**/.venv-openbb", recursive=True)
show(".venv-openbb in the image", venvs or "none", not venvs)

print("== no order code")
pattern = re.compile(r"/api/v3/order|/sapi/|X-MBX-APIKEY|create_order|market_order\(|limit_order\(|new_order|signature=|BINANCE_API_SECRET|api_secret")
hits = []
for root in (BOT, BACKEND):
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(p.startswith(".venv") or p in ("site-packages", "node_modules", "tests") for p in parts) or path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits += [f"{path.relative_to(root.parent)}:{n}" for n, line in enumerate(text.splitlines(), 1) if pattern.search(line)]
show("exchange order endpoints / signing in the source", hits or "none", not hits)
show("exchange trading key in the environment", [k for k in os.environ if re.search(r"BINANCE.*(SECRET|KEY)", k)] or "none",
     not [k for k in os.environ if re.search(r"BINANCE.*(SECRET|KEY)", k)])

print("== engine")
import advisor_v2_api as api  # noqa: E402

svc = api.engine()
versions = svc.versions()
show("advisor version / ruleset", f"{versions['advisor_version']} / {versions['ruleset_hash']}")
show("code", f"{(versions['git_commit'] or '?')[:10]}{' (dirty)' if versions['working_tree_dirty'] else ''}")
v1 = sys.modules["danisman"]
show("V1 advisor version / ruleset (unchanged engine)", f"{v1.ADVISOR_VERSION} / {v1.ruleset_hash()}")
agents = importlib.import_module("danisman_v2.agents")
clients = agents.build_clients()
show("analyst roles configured", {r: (c.provider + "/" + c.model if c else None) for r, c in clients.items()}, all(clients.values()))
div = agents.diversity(clients)
show("independent analyses / distinct models", f"{div['configured_roles']} / {div['distinct_models']}")
show("OpenBB mode", api.openbb().mode(), api.openbb().mode() in ("not_installed", "missing_python"))
cfg = importlib.import_module("danisman_v2.config")
show("timeouts", cfg.timeouts())


async def engine_only():
    started = time.monotonic()
    run = await svc.analyze("BTC", None, macro=api.openbb(), with_ai=False, log_paper=False, source="deploy-check")
    s = run["snapshot"]
    show("Binance reachable (BTC snapshot)", f"{s['market_timestamp']}, age {s['data_age_seconds']} s, stale {s['stale']}", not s["stale"])
    show("snapshot hash / engine status", f"{run['snapshot_hash']} / {run['engine']['status']} ({run['engine']['setup']})")
    show("order rules read from the exchange", s["execution"], bool(s["execution"]))
    show("macro without OpenBB", s["macro"]["macro_status"], s["macro"]["macro_status"] in ("UNAVAILABLE", "DEGRADED"))
    show("no analysts asked -> consensus / buy plan", f"{run['consensus']['consensus']} / {run['buy_plan']}",
         run["consensus"]["consensus"] == "DEGRADED_CONSENSUS" and run["buy_plan"] is None)
    show("order_sent / auto_trading", f"{run['order_sent']} / {run['auto_trading']}", run["order_sent"] is False and run["auto_trading"] is False)
    show("engine-only request", f"{int((time.monotonic() - started) * 1000)} ms (market {run['latency'].get('market_ms')} ms)")

try:
    asyncio.run(engine_only())
except Exception as e:
    show("engine-only run", f"FAILED: {type(e).__name__}: {str(e)[:160]}", False)

print("== database")
try:
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL") or os.environ["STATE_MONGO_URL"]
    db = MongoClient(url, serverSelectionTimeoutMS=10000)[os.environ.get("DB_NAME") or os.environ.get("STATE_DB_NAME") or "kapanis"]
    show("MongoDB reachable", db.command("ping").get("ok") == 1.0, True)
    # the admin as the server knows them: the database identity of a Clerk-verified session (the e-mail is not printed)
    owners = list(db["users"].find({"role": "owner", "clerk_id": {"$exists": True, "$ne": None}, "email_verified": True}, {"email": 1}))
    show("Clerk-verified owner accounts in the database", len(owners), len(owners) == 1)
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    show("that account's verified e-mail is on ADMIN_EMAILS", any((o.get("email") or "").lower() in admins for o in owners),
         any((o.get("email") or "").lower() in admins for o in owners))
    show("ADMIN_EMAILS entries that are not a verified owner (they open nothing)",
         len(admins - {(o.get("email") or "").lower() for o in owners}))
    paper = db["advisor_paper"]
    v2 = {"engine": "v2"}
    show("paper records V2 (LIVE / REPLAY / TEST)", " / ".join(str(paper.count_documents({**v2, "data_origin": o})) for o in ("LIVE", "REPLAY", "TEST")))
    show("paper records V1 (not V2)", paper.count_documents({"engine": {"$ne": "v2"}}))
    hashes = paper.distinct("ruleset_hash", v2)
    show("V2 ruleset hashes in the paper log", hashes or "none yet", not hashes or v1.ruleset_hash() not in hashes)
    last = paper.find_one(v2, {"_id": 0, "symbol": 1, "data_origin": 1, "advisor_version": 1, "ruleset_hash": 1, "snapshot_hash": 1,
                               "source": 1, "timestamp": 1}, sort=[("close_ms", -1)])
    show("last V2 paper record", last or "none yet")
    runs = db["advisor_consensus_runs"]
    show("audit runs stored", runs.count_documents({}))
    show("audit runs with order_sent true", runs.count_documents({"order_sent": True}), runs.count_documents({"order_sent": True}) == 0)
    doc = runs.find_one({}, {"_id": 0, "symbol": 1, "final": 1, "final_consensus": 1, "plan_released": 1, "generated_at": 1,
                             "ruleset_hash": 1, "admin_user_hash": 1}, sort=[("generated_at", -1)])
    show("last audit run", doc or "none yet")
    show("position states / released plans", f"{db['advisor_positions'].count_documents({})} / {db['advisor_plans'].count_documents({})}")
except Exception as e:
    show("MongoDB", f"FAILED: {type(e).__name__}: {str(e)[:160]}", False)

print("== result:", "READY" if not problems else "NOT READY: " + "; ".join(problems))
sys.exit(1 if problems else 0)
