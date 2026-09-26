"""Bu oturumdaki gerçek sayılarla hazırlanmış sahte (mock) veri.
Bot web API'si eklendiğinde /api/ingest/{collection} ile bu koleksiyonlar
üzerine yazılır (upsert, id alanına göre)."""

from datetime import datetime, timezone, timedelta


def _iso(dt):
    return dt.isoformat()


NOW = datetime.now(timezone.utc)


ALERTS = [
    {
        "id": "alr_near_retest",
        "symbol": "NEAR/USDT",
        "side": "long",
        "entry": 5.42,
        "stop": 5.18,
        "target": 6.10,
        "rr": 2.83,
        "status": "armed",
        "note": "Retest planı: 5.42 bölgesinden dönüş teyidi bekleniyor.",
        "created_at": _iso(NOW - timedelta(hours=3)),
        "queued": False,
    },
    {
        "id": "alr_btc_break",
        "symbol": "BTC/USDT",
        "side": "long",
        "entry": 84350.0,
        "stop": 82900.0,
        "target": 88200.0,
        "rr": 2.66,
        "status": "triggered",
        "note": "84 350 kırılımı tetiklendi.",
        "created_at": _iso(NOW - timedelta(hours=6)),
        "queued": False,
    },
    {
        "id": "alr_eth_range",
        "symbol": "ETH/USDT",
        "side": "short",
        "entry": 3180.0,
        "stop": 3260.0,
        "target": 2980.0,
        "rr": 2.50,
        "status": "armed",
        "note": "Aralık üstünden reddedilme.",
        "created_at": _iso(NOW - timedelta(hours=1)),
        "queued": False,
    },
]

POSITIONS = [
    {
        "id": "pos_btc_1",
        "symbol": "BTC/USDT",
        "side": "long",
        "entry": 84350.0,
        "stop": 82900.0,
        "target": 88200.0,
        "current": 85120.0,
        "size": 0.15,
        "rr": 2.66,
        "pnl": 115.5,
        "pnl_pct": 0.91,
        "opened_at": _iso(NOW - timedelta(hours=6)),
        "status": "open",
    },
    {
        "id": "pos_sol_1",
        "symbol": "SOL/USDT",
        "side": "long",
        "entry": 142.30,
        "stop": 137.50,
        "target": 154.00,
        "current": 140.10,
        "size": 8.0,
        "rr": 2.44,
        "pnl": -17.6,
        "pnl_pct": -1.55,
        "opened_at": _iso(NOW - timedelta(hours=20)),
        "status": "open",
    },
]

DECISIONS = [
    {
        "id": "dec_near_1",
        "symbol": "NEAR/USDT",
        "kind": "KARAR",
        "verdict": None,
        "entry": 5.42,
        "stop": 5.18,
        "target": 6.10,
        "rr": 2.83,
        "chart_note": "1H retest, SMA20 üzerinde tutundu.",
        "status": "pending",
        "created_at": _iso(NOW - timedelta(minutes=12)),
        "queued": False,
    },
    {
        "id": "dec_btc_1",
        "symbol": "BTC/USDT",
        "kind": "KARAR",
        "verdict": "Aldım",
        "entry": 84350.0,
        "stop": 82900.0,
        "target": 88200.0,
        "rr": 2.66,
        "chart_note": "84 350 kırılımı, hacim teyidi mevcut.",
        "status": "resolved",
        "created_at": _iso(NOW - timedelta(hours=6)),
        "queued": False,
    },
    {
        "id": "dec_eth_1",
        "symbol": "ETH/USDT",
        "kind": "KARAR",
        "verdict": "Pas",
        "entry": 3180.0,
        "stop": 3260.0,
        "target": 2980.0,
        "rr": 2.50,
        "chart_note": "Sinyal zayıf, makro rejim nötr.",
        "status": "resolved",
        "created_at": _iso(NOW - timedelta(hours=9)),
        "queued": False,
    },
]

SIGNALS = [
    {
        "id": "sig_near_1",
        "symbol": "NEAR/USDT",
        "timeframe": "1H",
        "type": "Retest",
        "score": 3,
        "summary": "Kırılım sonrası retest, SMA20 desteği korunuyor.",
        "created_at": _iso(NOW - timedelta(minutes=14)),
        "analysis": {
            "panels": [
                {"key": "trend", "title": "Trend (1D)", "value": "Yukarı", "detail": "SMA50 > SMA200, fiyat SMA20 üzerinde."},
                {"key": "momentum", "title": "Momentum (4H)", "value": "Pozitif", "detail": "RSI 58, yükselen."},
                {"key": "structure", "title": "Yapı (1H)", "value": "Retest", "detail": "5.42 seviyesi destek olarak test ediliyor."},
                {"key": "volume", "title": "Hacim", "value": "Ortalama üstü", "detail": "Kırılım mumunda hacim %38 arttı."},
            ],
            "bot_decision": {"verdict": "İzle", "confidence": 0.62, "reason": "Teyit mumu bekleniyor."},
        },
    },
    {
        "id": "sig_btc_1",
        "symbol": "BTC/USDT",
        "timeframe": "4H",
        "type": "Kırılım",
        "score": 4,
        "summary": "84 350 direnci kırıldı, hedef 88 200.",
        "created_at": _iso(NOW - timedelta(hours=6)),
        "analysis": {
            "panels": [
                {"key": "trend", "title": "Trend (1D)", "value": "Güçlü yukarı", "detail": "Tüm SMA'lar dizili."},
                {"key": "momentum", "title": "Momentum (4H)", "value": "Güçlü", "detail": "RSI 64."},
                {"key": "structure", "title": "Yapı (1H)", "value": "Kırılım", "detail": "84 350 üzerinde kapanış."},
                {"key": "volume", "title": "Hacim", "value": "Yüksek", "detail": "Kırılımda net alım."},
            ],
            "bot_decision": {"verdict": "Al", "confidence": 0.78, "reason": "Kırılım + hacim teyidi."},
        },
    },
    {
        "id": "sig_eth_1",
        "symbol": "ETH/USDT",
        "timeframe": "1H",
        "type": "Reddedilme",
        "score": -2,
        "summary": "Aralık üstünden reddedilme, kısa fırsatı.",
        "created_at": _iso(NOW - timedelta(hours=2)),
        "analysis": {
            "panels": [
                {"key": "trend", "title": "Trend (1D)", "value": "Nötr", "detail": "SMA20 ~ SMA50."},
                {"key": "momentum", "title": "Momentum (4H)", "value": "Zayıf", "detail": "RSI 46."},
                {"key": "structure", "title": "Yapı (1H)", "value": "Reddedilme", "detail": "3 180 üstünden fitil."},
                {"key": "volume", "title": "Hacim", "value": "Düşük", "detail": "Teyit zayıf."},
            ],
            "bot_decision": {"verdict": "Pas", "confidence": 0.41, "reason": "Hacim teyidi yok."},
        },
    },
]

MACRO = {
    "id": "macro_current",
    "regime_score": 2,
    "regime_label": "Hafif risk-iştahı",
    "dxy_alt": {"label": "klasik DXY değil", "value": 103.8, "score": -1},
    "stale": False,
    "updated_at": _iso(NOW - timedelta(minutes=25)),
    "components": [
        {"name": "Likidite", "value": "Genişleyen", "score": 2},
        {"name": "Faiz beklentisi", "value": "Sabit", "score": 0},
        {"name": "Risk (VIX benzeri)", "value": "Düşük", "score": 1},
        {"name": "Kredi spreadleri", "value": "Daralan", "score": 1},
        {"name": "Dolar (alt endeks)", "value": "Zayıf", "score": -1},
    ],
    "calendar": [
        {"time": _iso(NOW + timedelta(hours=2)), "title": "ABD TÜFE (Aylık)", "country": "US", "importance": "high", "actual": None, "forecast": "0.3%", "previous": "0.4%"},
        {"time": _iso(NOW + timedelta(hours=5)), "title": "Ham Petrol Stokları", "country": "US", "importance": "medium", "actual": None, "forecast": "-1.2M", "previous": "0.8M"},
        {"time": _iso(NOW + timedelta(days=1, hours=1)), "title": "Fed Konuşması", "country": "US", "importance": "high", "actual": None, "forecast": None, "previous": None},
        {"time": _iso(NOW - timedelta(hours=3)), "title": "Euro Bölgesi Sanayi Üretimi", "country": "EU", "importance": "low", "actual": "-0.1%", "forecast": "0.2%", "previous": "0.6%"},
    ],
    "note": "Rejim skalası -5…+5 arası. Alt dolar endeksi klasik DXY değildir; likidite ağırlıklı hesaplanır.",
}

DERIVATIVES = [
    {
        "id": "der_btc",
        "symbol": "BTC/USDT",
        "funding_rate": 0.0089,
        "open_interest": 18420000000.0,
        "long_short_ratio": 1.24,
        "cot_percentile": 94,
        "basis": 0.42,
        "updated_at": _iso(NOW - timedelta(minutes=8)),
    },
    {
        "id": "der_eth",
        "symbol": "ETH/USDT",
        "funding_rate": 0.0051,
        "open_interest": 7850000000.0,
        "long_short_ratio": 0.98,
        "cot_percentile": 61,
        "basis": 0.28,
        "updated_at": _iso(NOW - timedelta(minutes=8)),
    },
]

# 24 saatlik tarife şeridi + kullanım
_HOURLY = []
_TARIFF = []
for h in range(24):
    peak = 9 <= h <= 17
    _TARIFF.append({"hour": h, "rate": 0.018 if peak else 0.009, "tier": "yüksek" if peak else "düşük"})
    _HOURLY.append({"hour": h, "cost": round((0.42 if peak else 0.18) + (h % 5) * 0.03, 3), "calls": 40 + (h % 7) * 6})

USAGE = {
    "id": "usage_today",
    "date": _iso(NOW),
    "total_cost": 6.284,
    "tokens_in": 1284500,
    "tokens_out": 342100,
    "calls": 1180,
    "hourly": _HOURLY,
    "tariff": _TARIFF,
}

REPORT = {
    "id": "report_current",
    "performance": {
        "count": 42,
        "win_rate": 0.643,
        "avg_rr": 1.87,
        "total_r": 18.4,
        "best": 4.2,
        "worst": -1.1,
    },
    "trades": [
        {"id": "t1", "symbol": "BTC/USDT", "side": "long", "entry": 81200, "exit": 84350, "r": 2.1, "result": "win", "closed_at": _iso(NOW - timedelta(days=1))},
        {"id": "t2", "symbol": "SOL/USDT", "side": "long", "entry": 138.0, "exit": 133.0, "r": -1.0, "result": "loss", "closed_at": _iso(NOW - timedelta(days=2))},
        {"id": "t3", "symbol": "NEAR/USDT", "side": "long", "entry": 4.9, "exit": 5.6, "r": 2.8, "result": "win", "closed_at": _iso(NOW - timedelta(days=3))},
        {"id": "t4", "symbol": "ETH/USDT", "side": "short", "entry": 3320, "exit": 3180, "r": 1.6, "result": "win", "closed_at": _iso(NOW - timedelta(days=4))},
        {"id": "t5", "symbol": "AVAX/USDT", "side": "long", "entry": 34.2, "exit": 33.1, "r": -0.9, "result": "loss", "closed_at": _iso(NOW - timedelta(days=5))},
    ],
}

BACKTEST = {
    "id": "bt_current",
    "strategy": "Kırılım + Retest (SMA20 filtreli)",
    "period": "2025-01-01 → 2026-06-01",
    "metrics": {
        "trades": 214,
        "win_rate": 0.58,
        "profit_factor": 1.72,
        "max_drawdown_r": -6.4,
        "expectancy_r": 0.42,
        "sharpe": 1.31,
    },
    "equity_curve": [round(i * 0.42 + (i % 9) * 0.6 - (i % 13) * 0.3, 2) for i in range(60)],
    "note": "Sonuçlar geçmişe dönük simülasyondur; gelecekteki performans için gösterge değildir.",
}


def _candles(base, count=60, step=1):
    out = []
    price = base
    t0 = NOW - timedelta(hours=count)
    for i in range(count):
        o = price
        c = price + ((i % 7) - 3) * (base * 0.004)
        h = max(o, c) + base * 0.003
        l = min(o, c) - base * 0.003
        out.append({
            "t": _iso(t0 + timedelta(hours=i)),
            "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2),
            "v": 1000 + (i % 11) * 120,
        })
        price = c
    return out


CANDLES = {
    "BTC-USDT": {
        "id": "BTC-USDT",
        "symbol": "BTC/USDT",
        "timeframe": "1H",
        "candles": _candles(84350.0),
        "sma20": 84180.0,
        "sma50": 83420.0,
        "sma200": 79850.0,
    },
    "NEAR-USDT": {
        "id": "NEAR-USDT",
        "symbol": "NEAR/USDT",
        "timeframe": "1H",
        "candles": _candles(5.42),
        "sma20": 5.38,
        "sma50": 5.21,
        "sma200": 4.75,
    },
}

OVERVIEW = {
    "id": "overview_current",
    "updated_at": _iso(NOW - timedelta(minutes=2)),
    "open_positions": 2,
    "armed_alerts": 2,
    "pending_decisions": 1,
    "day_pnl": 97.9,
    "day_pnl_pct": 0.71,
    "open_r": 1.4,
    "regime_score": 2,
    "regime_label": "Hafif risk-iştahı",
    "highlights": [
        {"text": "BTC 84 350 kırılımı çalıştı, açık pozisyon +0.91%.", "tone": "up"},
        {"text": "NEAR retest planı beklemede — teyit mumu izleniyor.", "tone": "info"},
        {"text": "ABD TÜFE verisi 2 saat içinde; volatilite artabilir.", "tone": "wait"},
    ],
}

SETTINGS = {
    "id": "settings_current",
    "risk_per_trade_pct": 1.0,
    "max_open_positions": 4,
    "default_rr_min": 2.0,
    "timezone": "Europe/Istanbul",
    "notifications": {"telegram": True, "email": False},
    "rules_readonly": [
        "Her işlemde risk hesabın %1'ini geçmez.",
        "Açık pozisyonda stop yukarı çekilebilir, aşağı çekilemez (goalpost kuralı).",
        "R/R oranı 2.0 altındaki kurulumlar otomatik pas geçilir.",
        "Bayat (stale) veriyle karar verilmez.",
        "'Kesin kazanç' yoktur; her işlem risklidir.",
    ],
}


SEED = {
    "alerts": ALERTS,
    "positions": POSITIONS,
    "decisions": DECISIONS,
    "signals": SIGNALS,
    "derivatives": DERIVATIVES,
    "candles": list(CANDLES.values()),
    "macro": [MACRO],
    "usage": [USAGE],
    "report": [REPORT],
    "backtest": [BACKTEST],
    "overview": [OVERVIEW],
    "settings": [SETTINGS],
}
