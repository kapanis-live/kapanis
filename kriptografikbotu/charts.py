"""Candlestick PNG: price + SMA20/50/200, RSI, ATR, volume (TradingView-like panel order)."""
import threading
from io import BytesIO

import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)  # mplfinance asks for "semibold"
import pandas as pd  # noqa: E402

import config  # noqa: E402
from macro import TR  # noqa: E402

_lock = threading.Lock()  # matplotlib is not thread-safe

_style = mpf.make_mpf_style(base_mpf_style="nightclouds", gridstyle=":",
                            marketcolors=mpf.make_marketcolors(up="#26a69a", down="#ef5350",
                                                               wick="inherit", edge="inherit",
                                                               volume="in"))


def render(df: pd.DataFrame, title: str, levels: dict[str, float | None]) -> bytes:
    d = df.tail(config.CHART_CANDLES).copy()
    d.index = pd.to_datetime(d["open_time"], unit="ms", utc=True).dt.tz_convert(TR).dt.tz_localize(None)
    d = d.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})

    plots = [mpf.make_addplot(d[col], color=color, width=1.1)
             for col, color in (("sma20", "#f5c518"), ("sma50", "#2196f3"), ("sma200", "#e040fb"))
             if d[col].notna().any()]
    if d["rsi14"].notna().any():
        plots += [mpf.make_addplot(d["rsi14"], panel=1, color="#b388ff", ylabel="RSI 14", ylim=(0, 100)),
                  mpf.make_addplot(pd.Series(70.0, index=d.index), panel=1, color="#777", linestyle="--", width=0.7),
                  mpf.make_addplot(pd.Series(30.0, index=d.index), panel=1, color="#777", linestyle="--", width=0.7)]
    if d["atr14"].notna().any():
        plots.append(mpf.make_addplot(d["atr14"], panel=2, color="#ffab40", ylabel="ATR 14"))

    colors = {"tetik": "#ffffff", "iptal": "#ef5350", "hedef": "#26a69a"}
    # Levels further than 20% from price would squash the candles; leave them off the chart.
    last = d["Close"].iloc[-1]
    marked = {k: v for k, v in levels.items() if v is not None and abs(v / last - 1) <= 0.2}
    # Y range covers candles and alert levels, not far-away SMAs.
    lo, hi = min([d["Low"].min(), *marked.values()]), max([d["High"].max(), *marked.values()])
    pad = (hi - lo) * 0.04
    kwargs = {"ylim": (lo - pad, hi + pad)}
    if marked:
        kwargs["hlines"] = dict(hlines=list(marked.values()), colors=[colors[k] for k in marked],
                                linestyle="--", linewidths=0.9)

    with _lock:
        fig, _ = mpf.plot(d, type="candle", style=_style, addplot=plots, volume=True, volume_panel=3,
                          panel_ratios=(5, 1.4, 1.4, 1.4), figsize=(12, 10), title=title,
                          ylabel="Fiyat", ylabel_lower="Hacim", returnfig=True, tight_layout=True,
                          warn_too_much_data=10_000, **kwargs)
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=110)
        plt.close(fig)
    return buf.getvalue()


def portfolio(alloc: list[dict], history: list[dict], title: str = "Portföy") -> bytes:
    """Left: allocation donut (TL weights). Right: value vs. cost over time (TL)."""
    colors = ["#26a69a", "#2196f3", "#f5c518", "#e040fb", "#ff7043", "#8d6e63", "#78909c", "#66bb6a",
              "#ab47bc", "#29b6f6", "#ffa726", "#ec407a"]
    with _lock:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [1, 1.6]})
        fig.patch.set_facecolor("#131722")
        for ax in (ax1, ax2):
            ax.set_facecolor("#131722")
        top = alloc[:9]
        rest = sum(a["yuzde"] for a in alloc[9:])
        labels = [f"{a['ad']} %{a['yuzde']:g}" for a in top] + ([f"Diğer %{rest:.1f}"] if rest else [])
        sizes = [a["yuzde"] for a in top] + ([rest] if rest else [])
        if sizes:
            # Small slices get no label on the ring (they would overlap); the legend lists every slice.
            ring = [lbl if sz >= 5 else "" for lbl, sz in zip(labels, sizes)]
            wedges, _ = ax1.pie(sizes, labels=ring, colors=colors[:len(sizes)], startangle=90, counterclock=False,
                                wedgeprops={"width": 0.42, "edgecolor": "#131722"},
                                textprops={"color": "#d1d4dc", "fontsize": 9})
            ax1.legend(wedges, labels, loc="center", frameon=False, labelcolor="#d1d4dc", fontsize=8)
        ax1.set_title("Dağılım (TL)", color="#d1d4dc")
        if history:
            x = pd.to_datetime([h["tarih"] for h in history])
            ax2.plot(x, [h["deger_tl"] for h in history], color="#26a69a", linewidth=1.8, label="Değer")
            ax2.plot(x, [h["maliyet_tl"] for h in history], color="#f5c518", linewidth=1.2, linestyle="--", label="Maliyet")
            ax2.legend(facecolor="#131722", labelcolor="#d1d4dc", edgecolor="#333")
            ax2.tick_params(colors="#d1d4dc", labelsize=8)
            ax2.grid(color="#2a2e39", linestyle=":")
            for side in ax2.spines.values():
                side.set_color("#333")
            fig.autofmt_xdate()
        else:
            ax2.text(0.5, 0.5, "Geçmiş için veri yok", color="#d1d4dc", ha="center", va="center")
            ax2.set_axis_off()
        ax2.set_title("Değer ve maliyet (TL, günlük kapanış)", color="#d1d4dc")
        fig.suptitle(title, color="#ffffff")
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
        plt.close(fig)
    return buf.getvalue()
