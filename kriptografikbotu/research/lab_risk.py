"""Is a trend exit a real risk tool, or does any 'be out 60% of the time' look as good?
Per coin (77 incl. dead) and BIST (40): rule vs buy&hold vs random in/out with the same exposure and
the same average holding length. Median max drawdown and yearly return per half."""
import asyncio, json, random
import numpy as np, httpx
import lab, lab_xs2

def random_pos(n, exposure, avg_len, rng):
    pos, hold, i = np.zeros(n), 0, 201
    p_exit = 1 / max(avg_len, 1)
    p_enter = p_exit * exposure / max(1 - exposure, 1e-9)
    for i in range(201, n):
        hold = (rng.random() > p_exit) if hold else (rng.random() < p_enter)
        pos[i] = hold
    return pos

def half_stats(df, pos, cost, dpy, half):
    d = df.iloc[201:].reset_index(drop=True); p = pos[201:]
    cut = len(d) // 2
    d, p = (d.iloc[:cut], p[:cut]) if half == 0 else (d.iloc[cut:].reset_index(drop=True), p[cut:])
    if len(d) < 120: return None
    eq, held, tr = lab.equity(d.reset_index(drop=True), p, cost)
    return lab.stats(eq, held, tr, len(d) / dpy)

async def main():
    rng = random.Random(3)
    async with httpx.AsyncClient() as c:
        cr = []
        for coin in lab_xs2.WIDE + [x for x in lab_xs2.DEAD if x != "BTT"]:
            try:
                df = await lab.crypto_daily(c, coin)
                if len(df) > 400: cr.append(lab.ind(df))
            except Exception: pass
        bi = [lab.ind(await lab.bist_daily(c, x)) for x in lab.BIST]
    for market, frames, dpy in (("KRIPTO", cr, 365), ("BIST", bi, 250)):
        for rule in ("donchian_20_10_trend", "sma200"):
            res = {}
            for half in (0, 1):
                rows = {"kural": [], "al_tut": [], "rastgele": []}
                for df in frames:
                    pos = lab.rule_positions(df, rule)
                    exp = pos[201:].mean()
                    runs = np.diff(np.flatnonzero(np.diff(np.concatenate([[0], pos[201:], [0]])))) if pos[201:].any() else [1]
                    avg_len = float(np.mean(runs[::2])) if len(runs) else 1
                    rp = random_pos(len(df), exp, avg_len, rng)
                    for key, p in (("kural", pos), ("al_tut", np.ones(len(df))), ("rastgele", rp)):
                        s = half_stats(df, p, lab.COST[market], dpy, half)
                        if s: rows[key].append(s)
                res[f"{half + 1}. yarı"] = {k: {m: round(float(np.median([r[m] for r in v])), 1) for m in ("yillik_%", "max_dusus_%", "piyasada_%")}
                                            for k, v in rows.items()} | {"varlik": len(rows["kural"])}
            print(market, rule, json.dumps(res, ensure_ascii=False), flush=True)
asyncio.run(main())
