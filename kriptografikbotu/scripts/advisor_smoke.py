"""Deploy check of the Kripto Danışman's paper log, run INSIDE a container. Prints no secret; exits 1 on a failure.

    docker compose exec worker python scripts/advisor_smoke.py            # read-only checks
    docker compose exec web python /app/kriptografikbotu/scripts/advisor_smoke.py
    docker compose exec worker python scripts/advisor_smoke.py --write    # also: one live BTC report, logged twice

--write makes a real (LIVE) advisor report for BTC from public candles and logs it twice: the first must be stored,
the second must be refused as a duplicate. It reads the exchange's public data only; nothing here can send an order.
"""
import asyncio
import collections
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import danisman as d  # noqa: E402
import danisman_paper as p  # noqa: E402

failed = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""))
    if not ok:
        failed.append(name)


def main() -> int:
    check("STATE_MONGO_URL reaches this process", bool(os.getenv("STATE_MONGO_URL")), "set" if os.getenv("STATE_MONGO_URL") else "missing")
    check("no test or forced origin in this environment", not os.getenv("ADVISOR_DATA_ORIGIN") and not os.getenv("ADVISOR_PAPER_FILE"))
    st = p.store()
    mongo = isinstance(st, p.MongoStore)
    check("paper log is stored in MongoDB (survives a deploy)", mongo,
          f"{st.c.database.name}.{st.c.name}" if mongo else f"file {getattr(st, 'path', '?')}: NOT persistent")
    code = d.code_version()
    check("git_commit is known", bool(code["git_commit"]), str(code["git_commit"]))
    check("working_tree_dirty is false", code["working_tree_dirty"] is False, str(code["working_tree_dirty"]))
    print(f"      advisor_version {d.ADVISOR_VERSION} · ruleset_hash {d.ruleset_hash()}")
    if mongo:
        check("unique index on symbol + setup + candle + ruleset + origin",
              "setup_at_close_by_ruleset_and_origin" in st.c.index_information())

    if "--write" in sys.argv:
        report = asyncio.run(d.advise("BTC"))
        check("live BTC report", report["live"] and report["decision"] in d.DECISION_TR, report["decision"])
        first, second = d.paper_log([report], "smoke"), d.paper_log([report], "smoke")
        row = d.paper_row(report, "smoke")
        already = any(p.key(r) == p.key(row) for r in st.all())
        check("the report is in the log", already, f"first write stored {first} new record(s)")
        check("the same setup at the same candle is not written twice", second == 0, f"second write stored {second}")

    rows = st.all()
    by_origin = collections.Counter(r["data_origin"] for r in rows)
    print(f"      records: {dict(by_origin)}")
    dup = [k for k, n in collections.Counter(p.key(r) for r in rows).items() if n > 1]
    check("no duplicate records", not dup, f"{len(dup)} duplicated keys")
    live = sorted((r for r in rows if r["data_origin"] == "LIVE"), key=lambda r: r["generated_at"] or "")
    check("there is at least one LIVE record", bool(live), str(len(live)))
    if live:
        r = live[0]
        short = {k: r.get(k) for k in ("symbol", "decision", "setup_class", "data_origin", "advisor_version", "ruleset_hash",
                                       "git_commit", "working_tree_dirty", "generated_at", "market_timestamp", "source",
                                       "outcome_done")}
        print("      first LIVE record: " + json.dumps(short, ensure_ascii=False))
        newest = live[-1]
        check("LIVE record: advisor_version", newest["advisor_version"] == d.ADVISOR_VERSION, str(newest["advisor_version"]))
        check("LIVE record: ruleset_hash is the current one", newest["ruleset_hash"] == d.ruleset_hash(), str(newest["ruleset_hash"]))
        check("LIVE record: git_commit is the deployed commit", bool(newest.get("git_commit")) and newest["git_commit"] == code["git_commit"],
              str(newest.get("git_commit")))
        check("LIVE record: working_tree_dirty is false", newest.get("working_tree_dirty") is False, str(newest.get("working_tree_dirty")))
        check("LIVE record: generated_at and market_timestamp", bool(newest.get("generated_at")) and bool(newest.get("market_timestamp")))
    s = d.paper_stats(rows)
    current_live = sum(r["data_origin"] == "LIVE" and r.get("ruleset_hash") == d.ruleset_hash() for r in rows)
    check("default stats count LIVE records of the current ruleset only", s["records"] == current_live,
          f"{s['records']} counted, {s['excluded_other_origins']} of other origins and {s['excluded_other_versions']} of other "
          "versions left out")
    due = [r for r in live if p._due(r, int(__import__('time').time() * 1000))]
    moved = sum(bool(r.get("outcome_done")) for r in live)
    print(f"      outcome tracker: {moved} LIVE record(s) have an outcome, {len(due)} are due and waiting "
          "(the bot fills them every 30 minutes; /danis stats does it at once)")
    print("\nRESULT: " + ("FAILED: " + "; ".join(failed) if failed else "all checks passed"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
