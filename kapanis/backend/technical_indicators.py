"""Chart-only technical indicators. Values are aligned to the input candles.

These plots do not participate in the bot's trading gate or AI prompt.
"""
from math import sqrt


def sma(values, period):
    out, total = [], 0.0
    for i, value in enumerate(values):
        total += value
        if i >= period:
            total -= values[i - period]
        out.append(total / period if i >= period - 1 else None)
    return out


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    value = sum(values[:period]) / period
    out[period - 1] = value
    weight = 2 / (period + 1)
    for i in range(period, len(values)):
        value += weight * (values[i] - value)
        out[i] = value
    return out


def _ema_optional(values, period):
    first = next((i for i, value in enumerate(values) if value is not None), len(values))
    if first == len(values):
        return [None] * len(values)
    return [None] * first + ema(values[first:], period)


def _rma(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    value = sum(values[:period]) / period
    out[period - 1] = value
    for i in range(period, len(values)):
        value = (value * (period - 1) + values[i]) / period
        out[i] = value
    return out


def calculate(rows):
    """Standard chart defaults; no look-ahead values are used."""
    closes = [r["c"] for r in rows]
    highs = [r["h"] for r in rows]
    lows = [r["l"] for r in rows]
    volumes = [r["v"] for r in rows]
    count = len(rows)
    out = {f"ema{n}": ema(closes, n) for n in (5, 9, 10, 20, 21, 50, 100, 200)}

    mid = sma(closes, 20)
    deviation = [None if i < 19 else sqrt(sum((x - mid[i]) ** 2 for x in closes[i - 19:i + 1]) / 20)
                 for i in range(count)]
    out.update(bb_mid=mid,
               bb_upper=[None if x is None else x + 2 * d for x, d in zip(mid, deviation)],
               bb_lower=[None if x is None else x - 2 * d for x, d in zip(mid, deviation)])

    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [a - b if a is not None and b is not None else None for a, b in zip(fast, slow)]
    signal = _ema_optional(macd, 9)
    out.update(macd=macd, macd_signal=signal,
               macd_hist=[a - b if a is not None and b is not None else None for a, b in zip(macd, signal)])

    true_ranges = [highs[0] - lows[0]]
    for i in range(1, count):
        true_ranges.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    out["atr"] = _rma(true_ranges, 14)

    plus_dm, minus_dm = [0.0], [0.0]
    for i in range(1, count):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    plus_smooth, minus_smooth = _rma(plus_dm, 14), _rma(minus_dm, 14)
    dx = [None] * count
    for i in range(13, count):
        atr = out["atr"][i]
        plus = 100 * plus_smooth[i] / atr if atr else 0
        minus = 100 * minus_smooth[i] / atr if atr else 0
        dx[i] = 100 * abs(plus - minus) / (plus + minus) if plus + minus else 0.0
    out["adx"] = [None] * min(count, 13) + _rma(dx[13:], 14)

    ema13 = ema(closes, 13)
    out["bull_power"] = [None if e is None else h - e for h, e in zip(highs, ema13)]
    out["bear_power"] = [None if e is None else l - e for l, e in zip(lows, ema13)]

    k = [None] * count
    for i in range(13, count):
        low, high = min(lows[i - 13:i + 1]), max(highs[i - 13:i + 1])
        k[i] = 100 * (closes[i] - low) / (high - low) if high > low else 50.0
    out["stoch_k"] = k
    out["stoch_d"] = [None if i < 15 else sum(k[i - 2:i + 1]) / 3 for i in range(count)]

    gains = [0.0] + [max(closes[i] - closes[i - 1], 0) for i in range(1, count)]
    losses = [0.0] + [max(closes[i - 1] - closes[i], 0) for i in range(1, count)]
    avg_gains = [None] + _rma(gains[1:], 14)
    avg_losses = [None] + _rma(losses[1:], 14)
    rsi = [None] * count
    for i in range(14, count):
        g, loss = avg_gains[i], avg_losses[i]
        rsi[i] = 100 * g / (g + loss) if g + loss else 50.0
    stoch_rsi = [None] * count
    for i in range(27, count):
        window = rsi[i - 13:i + 1]
        low, high = min(window), max(window)
        stoch_rsi[i] = 100 * (rsi[i] - low) / (high - low) if high > low else 50.0
    out["stoch_rsi"] = stoch_rsi

    buying_pressure, ultimate_tr = [], []
    for i in range(count):
        previous = closes[i - 1] if i else closes[i]
        low, high = min(lows[i], previous), max(highs[i], previous)
        buying_pressure.append(closes[i] - low)
        ultimate_tr.append(high - low)
    ultimate = [None] * count
    for i in range(27, count):
        averages = []
        for period in (7, 14, 28):
            tr_total = sum(ultimate_tr[i - period + 1:i + 1])
            averages.append(sum(buying_pressure[i - period + 1:i + 1]) / tr_total if tr_total else .5)
        ultimate[i] = 100 * (4 * averages[0] + 2 * averages[1] + averages[2]) / 7
    out["ultimate"] = ultimate

    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    cci = [None] * count
    for i in range(19, count):
        avg = sum(typical[i - 19:i + 1]) / 20
        dev = sum(abs(x - avg) for x in typical[i - 19:i + 1]) / 20
        cci[i] = (typical[i] - avg) / (0.015 * dev) if dev else 0.0
    out["cci"] = cci

    out["roc"] = [None if i < 12 or closes[i - 12] == 0 else 100 * (closes[i] / closes[i - 12] - 1)
                  for i in range(count)]
    out["williams_r"] = [None if i < 13 else (
        -100 * (max(highs[i - 13:i + 1]) - closes[i]) /
        (max(highs[i - 13:i + 1]) - min(lows[i - 13:i + 1]))
        if max(highs[i - 13:i + 1]) > min(lows[i - 13:i + 1]) else -50.0)
        for i in range(count)]

    obv = [0.0] * count
    for i in range(1, count):
        obv[i] = obv[i - 1] + (volumes[i] if closes[i] > closes[i - 1] else
                               -volumes[i] if closes[i] < closes[i - 1] else 0)
    out["obv"] = obv

    flows = [typical[i] * volumes[i] for i in range(count)]
    mfi = [None] * count
    for i in range(14, count):
        positive = sum(flows[j] for j in range(i - 13, i + 1) if typical[j] > typical[j - 1])
        negative = sum(flows[j] for j in range(i - 13, i + 1) if typical[j] < typical[j - 1])
        mfi[i] = 100 * positive / (positive + negative) if positive + negative else 50.0
    out["mfi"] = mfi
    return out
