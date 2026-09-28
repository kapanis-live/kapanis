"""Momentum rotation on a wider crypto universe, including coins that later collapsed or were delisted.
A coin enters the ranking only after 200 days of history and leaves when its data stops (a delisted coin's last
price counts as the exit). Variants: top 3 / top 5, 30-day rebalance; universe equal weight as the benchmark."""
import asyncio, json
import numpy as np, pandas as pd, httpx
import lab, lab_xs

WIDE = ("BTC ETH BNB SOL XRP DOGE ADA TRX AVAX LINK DOT BCH LTC NEAR UNI ATOM ETC FIL ICP HBAR XLM VET ALGO AAVE "
        "MKR SAND MANA AXS CHZ ENJ GRT CRV COMP SNX SUSHI YFI 1INCH ZEC DASH XMR EOS NEO WAVES QTUM ZIL ONT IOTA "
        "KSM EGLD THETA FTM RUNE KAVA CELO ICX OMG BAT ZRX LRC STORJ ANKR SKL OCEAN BAND REN KNC").split()
DEAD = "LUNA FTT SRM UST ANC MIR BTT NANO STRAX LINA REEF MDX BZRX".split()

async def main():
    frames, names = [], []
    async with httpx.AsyncClient() as c:
        for coin in WIDE + DEAD:
            try:
                df = await lab.crypto_daily(c, coin)
                if len(df) > 260:
                    frames.append(df); names.append(coin)
            except Exception:
                pass
    print("coins", len(frames), "dead found", [n for n in names if n in DEAD], flush=True)
    px = lab_xs.panel(frames)
    last = {i: f.t.iloc[-1] for i, f in enumerate(frames)}
    out = {}
    for k in (3, 5):
        out[f"top{k}"] = {f"{h + 1}. yarı": lab_xs.run(px, k, lab.COST["KRIPTO"], 30, h) for h in (0, 1)}
        print(f"top{k}", json.dumps(out[f"top{k}"], ensure_ascii=False), flush=True)
    # thirds: stability over three periods for top3
    rets = {}
    print(json.dumps(out, ensure_ascii=False))
asyncio.run(main())
