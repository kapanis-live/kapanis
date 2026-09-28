"""Cross-sectional momentum: every 21 trading days hold the top K by 90-day return (equal weight), vs holding all."""
import asyncio, json, pathlib
import numpy as np, pandas as pd, httpx
import lab

def panel(frames):
    s = {i: pd.Series(f.c.values, index=pd.to_datetime(f.t, unit="ms").dt.normalize()) for i, f in enumerate(frames)}
    return pd.DataFrame(s).sort_index().ffill(limit=3)

def run(px, k, cost, step, half):
    rets = px.pct_change()
    mom = px / px.shift(90) - 1
    idx = px.index[200:]
    cut = len(idx) // 2
    idx = idx[:cut] if half == 0 else idx[cut:]
    eq_m, eq_a, w_prev = [1.0], [1.0], None
    w = None
    for n, d in enumerate(idx[:-1]):
        if n % step == 0:
            m = mom.loc[d].dropna()
            top = m.nlargest(k).index if len(m) >= k else m.index
            w_new = pd.Series(1 / len(top), index=top)
            turn = (w_new.reindex(px.columns, fill_value=0) - (w.reindex(px.columns, fill_value=0) if w is not None else 0)).abs().sum()
            eq_m[-1] *= 1 - turn * cost
            w = w_new
        nxt = idx[n + 1]
        r = rets.loc[nxt]
        eq_m.append(eq_m[-1] * (1 + (w * r.reindex(w.index).fillna(0)).sum()))
        avail = r.dropna()
        eq_a.append(eq_a[-1] * (1 + avail.mean() if len(avail) else 1))
    def st(eq, days_per_year):
        eq = np.array(eq); yrs = len(eq) / days_per_year
        return {"yillik_%": round(((eq[-1] / eq[0]) ** (1 / yrs) - 1) * 100, 1),
                "max_dusus_%": round((eq / np.maximum.accumulate(eq) - 1).min() * 100, 1)}
    dpy = 365 if cost == lab.COST["KRIPTO"] else 250
    return {"momentum_top": st(eq_m, dpy), "hepsi_esit": st(eq_a, dpy)}

async def main():
    out = {}
    async with httpx.AsyncClient() as c:
        cr = [await lab.crypto_daily(c, x) for x in lab.CRYPTO]
        bi = [await lab.bist_daily(c, x) for x in lab.BIST]
    for name, fr, k, cost, step in (("KRIPTO top3", cr, 3, lab.COST["KRIPTO"], 30), ("BIST top8", bi, 8, lab.COST["BIST"], 21)):
        px = panel(fr)
        out[name] = {f"{h + 1}. yarı": run(px, k, cost, step, h) for h in (0, 1)}
        print(name, json.dumps(out[name], ensure_ascii=False), flush=True)
if __name__ == "__main__":
    asyncio.run(main())
