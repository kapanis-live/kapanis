"""The language of a chat: Turkish (the source) or English. /dil tr | en, or the language switch on the site.

The bot's texts are written in Turkish. A text that has an English version is chosen with pick(); everything else
stays Turkish until it is translated, so switching to English never breaks a message. Numbers, tickers and dates are
the same in both languages: they come from code, never from a translation step.

Translated so far: the notification switches, the monthly report, the stock table, the command menu, the stock cards
(US and BIST), the US portfolio report and the level digest. Notes a card stores (warnings, source names) stay Turkish.
Stored per chat in settings.json under "dil" (kept in MongoDB in the cloud).
"""
import alerts_store

KEY = "dil"
LANGS = {"tr": "Türkçe", "en": "English"}
WORDS = {"tr": "tr", "turkce": "tr", "türkçe": "tr", "turkish": "tr", "en": "en", "ingilizce": "en", "i̇ngilizce": "en", "english": "en", "eng": "en"}

# labels that travel inside data (cards, tables): Turkish in storage, translated when shown
LABELS = {"GÜÇLÜ": "STRONG", "ZAYIF": "WEAK", "NÖTR": "NEUTRAL", "PAHALI": "EXPENSIVE", "UCUZ": "CHEAP", "MAKUL": "FAIR",
          "BİLİNMİYOR": "UNKNOWN", "YÜKSEK": "HIGH", "ORTA": "MEDIUM", "DÜŞÜK": "LOW", "YUKARI": "UP", "AŞAĞI": "DOWN", "YATAY": "FLAT",
          "↗ güçlü": "↗ strong", "↘ zayıf": "↘ weak", "→ karışık": "→ mixed"}
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

MENU_EN = {
    "komutlar": "All commands with examples", "portfoy": "Portfolio: quantity, value, day / total %, verdicts",
    "bakiye": "Balance (assets + cash), P/L today / week / total", "aldim": "Record a buy: /aldim HYPE/USDT 92.7 60",
    "plan": "Plans of the coins / stocks you chose (/plan ekle BTC THYAO)", "firsat": "Is any triggered coin / stock within the rules now?",
    "takip": "Watchlist: crypto / BIST / US", "hedef": "Target allocation and drift: /hedef BIST 50 KRIPTO 20 ...",
    "sanal": "Paper trade (no real money): /sanal al THYAO 290 5000", "kontrol": "Pre-buy check: /kontrol THYAO 290 280 310",
    "galarm": "Indicator alert: /galarm THYAO sma50 ustu 1d", "karsilastir": "Compare stocks: /karsilastir THYAO PGSUS",
    "olaylar": "Earnings and dividend dates (holdings + watchlist)", "kap": "KAP filings of the stocks you hold",
    "ders": "Lesson of the week: which rule helped", "tara": "Opportunity scan: crypto + BIST",
    "analiz": "🪙 Crypto analysis: /analiz BTC", "danis": "🪙 Advisor: is it a setup, where is the stop-limit? /danis HYPE",
    "haber": "🪙 Crypto news: /haber BTC", "vadeli": "🪙 Funding / open interest: /vadeli BTC", "duygu": "🪙 Fear & Greed, BTC dominance",
    "new_alert": "🪙 Create a close-based alert", "backtest": "🪙 Try a rule on history",
    "incele": "🇹🇷 BIST stock analysis: /incele THYAO", "bist": "🇹🇷 BIST: index, budget, /bist kart THYAO, /bist tara",
    "guc": "🇹🇷 Weekly strength ranking + sector rotation", "temel": "🇹🇷🇺🇸 Fundamentals: /temel THYAO · /temel AAPL",
    "abd": "🇺🇸 US: market, /abd kart AAPL, /abd tara, /abd portfoy", "gunsonu": "🇹🇷 BIST end-of-day report",
    "temettu": "🇹🇷 Dividends and bonus shares: /temettu THYAO",
    "grafik": "Portfolio chart (allocation + 90 days)", "risk": "Concentration and correlation",
    "kiyas": "Portfolio vs BIST 100, BTC, gold, deposits", "palarm": "Portfolio alert: /palarm kripto %-10", "birikim": "Monthly accumulation plan",
    "hesap": "Before a buy: quantity, risk, R/R", "pozisyonlar": "Open positions and P/L", "sat": "Record a sale: /sat ID PRICE",
    "duzelt": "Fix a record: /duzelt ID giris=X miktar=Y tarih=...", "kayitsil": "Delete a record you never bought: /kayitsil ID",
    "view_alerts": "List alerts", "cancel_alert": "Delete an alert: /cancel_alert PAIR ID",
    "rapor": "Performance report", "haftalik": "Weekly summary", "golge": "Shadow portfolio: if you had taken the signals",
    "karne": "Rule + model scorecard", "gunluk": "Trade journal scorecard", "disiplin": "Tilt protection status",
    "makro": "US macro dashboard", "takvim": "US + Türkiye data calendar",
    "model": "Model order: Kimi K3 / DeepSeek Flash / GLM 5.3", "maliyet": "AI spending", "durum": "Data freshness",
    "sessizlik": "Quiet hours: /sessizlik hafta içi 12.00-14.30", "sessiz": "No notifications at all (/plan turns them back on)",
    "midas": "Coins Midas does not offer (left out of scans)", "seviye": "Support / resistance scan (every 30 min; kapat/ac)",
    "bildirimler": "Market notifications: /kripto /bist /abd ac|kapat", "aylik": "Monthly report: return, vs indexes, trades",
    "dil": "Language: /dil tr · /dil en",
    "ne": "Plan for something you hold: /ne ASTOR", "pozisyon": "Mark a plan as held: /pozisyon BTC acik", "sil": "Delete a plan: /sil BTC",
    "sifirla": "Clear the chat history", "set_config": "Quiet-hours setting", "get_logs": "Latest error log", "start": "Start / chat id",
}


def get(chat_id) -> str:
    return (alerts_store.load_settings().get(KEY) or {}).get(str(chat_id), "tr")


def set_lang(chat_id, value: str) -> str:
    code = WORDS.get(str(value).casefold().strip())
    if code is None:
        raise ValueError("dil tr ya da en olmalı / the language must be tr or en")
    s = alerts_store.load_settings()
    s.setdefault(KEY, {})[str(chat_id)] = code
    alerts_store.save_settings(s)
    return code


def pick(chat_id_or_lang, tr: str, en: str) -> str:
    """The English text for a chat (or a language code) set to English, else the Turkish one."""
    code = chat_id_or_lang if chat_id_or_lang in LANGS else get(chat_id_or_lang)
    return en if code == "en" else tr


def label(code: str, value):
    """A stored Turkish label (GÜÇLÜ, PAHALI, ↗ güçlü ...) in the chat's language."""
    return LABELS.get(value, value) if code == "en" and value is not None else value


def status(chat_id) -> str:
    code = get(chat_id)
    return pick(code, f"🌐 Dil: {LANGS[code]}\nDeğiştir: /dil tr · /dil en\nÇeviri aşamalı ilerliyor: bildirim tercihleri, aylık rapor, hisse tablosu, hisse kartları, "
                      "ABD portföyü, seviye özeti ve komut menüsü İngilizce; diğer mesajlar şimdilik Türkçe.",
                f"🌐 Language: {LANGS[code]}\nChange: /dil tr · /dil en\nTranslation is in progress: notification settings, the monthly report, "
                "the stock table, the stock cards, the US portfolio, the level digest and the command menu are in English; other messages are still Turkish for now.")
