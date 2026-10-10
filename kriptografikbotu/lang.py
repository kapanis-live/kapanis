"""The language of a chat: Turkish (the source) or English. /dil tr | en, or the language switch on the site.

The bot's texts are written in Turkish. A text that has an English version is chosen with pick(); everything else
stays Turkish until it is translated, so switching to English never breaks a message. Numbers, tickers and dates are
the same in both languages: they come from code, never from a translation step.

Translated so far: the notification switches, the monthly report, the stock table, the command menu, the stock cards
(US and BIST) with their notes and source rows (data()), the US portfolio report and the level digest.
Stored per chat in settings.json under "dil" (kept in MongoDB in the cloud).
"""
import re

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


# ---- sentences the cards store in Turkish (notes, source rows, labels), for the English texts ----
# The same texts are translated on the site by frontend/src/lib/i18n.jsx (EN + PATTERNS): when a producer's sentence
# changes, change it in both places. A text that is not known here stays as written.
DATA_EN = {
    "fiyat > 50G > 200G (güçlü)": "price > 50D > 200D (strong)", "fiyat < 50G < 200G (zayıf)": "price < 50D < 200D (weak)", "karışık": "mixed",
    "Stage 2 — yükseliş (30h ortalama üstünde ve yükseliyor)": "Stage 2 — advance (above the 30-week average, which is rising)",
    "Stage 4 — düşüş (30h ortalama altında ve düşüyor): biriktirme için erken": "Stage 4 — decline (below the 30-week average, which is falling): early for accumulating",
    "yatay; tepe sonrası ise Stage 3 (dağıtım), dip sonrası Stage 1 (taban)": "sideways; Stage 3 (distribution) if after a top, Stage 1 (base) if after a bottom",
    "Stage 1 — taban oluşumu ihtimali (30h ortalama yatay)": "Stage 1 — a base may be forming (30-week average flat)",
    "şirket takvimi (Yahoo)": "company calendar (Yahoo)", "tahmin: önceki açıklamaların aralığı (SEC)": "estimate: the interval of earlier announcements (SEC)",
    "Sonraki bilanço tarihi bilinmiyor: şirketin yatırımcı sayfasından teyit et.": "The next earnings date is unknown: confirm it on the company's investor page.",
    "Sonraki bilanço tarihi bilinmiyor: KAP ya da şirketin yatırımcı sayfasından teyit et.": "The next earnings date is unknown: confirm it on KAP or the company's investor page.",
    "Fiyat 50 ve 200 günlük ortalamaların altında (zayıf yapı).": "Price is below the 50- and 200-day averages (weak structure).",
    "Analist kâr tahminleri son 30 günde aşağı çekildi.": "Analyst earnings estimates were cut in the last 30 days.",
    "Değerleme kaba ölçüyle pahalı: beklentinin altında bir bilanço daha sert düşürür.": "Valuation is expensive by a coarse measure: earnings below expectations would hit harder.",
    "Değerleme kaba ölçüyle pahalı.": "Valuation is expensive by a coarse measure.",
    "esas faaliyet zararı (TTM)": "operating loss (TTM)", "özkaynak negatif": "negative equity",
    "net kâr var ama serbest nakit akımı negatif": "net profit is positive but free cash flow is negative",
    "bilanço, marjlar, nakit akışı": "financial statements, margins, cash flow", "SEC EDGAR (10-K / 10-Q, resmi)": "SEC EDGAR (10-K / 10-Q, official)",
    "fiyat, ortalamalar, göreli güç": "price, averages, relative strength",
    "analist tahminleri, revizyonlar, sürprizler, bilanço takvimi": "analyst estimates, revisions, surprises, earnings calendar",
    "alınamadı": "not available", "son bilanço açıklama zamanı": "time of the last earnings release",
    "SEC EDGAR (8-K madde 2.02, resmi)": "SEC EDGAR (8-K item 2.02, official)", "bulunamadı": "not found",
    "mali tablolar, marjlar, borç, temel puan": "financial statements, margins, debt, fundamental score",
    "İş Yatırım (şirketin KAP'a bildirdiği tablolar)": "İş Yatırım (the statements the company filed with KAP)",
    "fiyat, ortalamalar, BIST 100'e göre güç": "price, averages, strength against BIST 100", "Yahoo Finance (~15 dk gecikmeli)": "Yahoo Finance (~15 min delayed)",
    "bilanço ve temettü takvimi": "earnings and dividend calendar", "kesin tarih için KAP": "KAP for the exact date",
    "günlük kapanışlar (1 yıl), SPY, QQQ, 10Y faiz, VIX": "daily closes (1 year), SPY, QQQ, 10Y yield, VIX", "sektör": "sector",
    "Yahoo Finance şirket profili": "Yahoo Finance company profile", "6 saatlik önbellek": "6-hour cache", "temalar": "themes",
    "koddaki sabit listeler (us_portfolio.THEMES)": "fixed lists in the code (us_portfolio.THEMES)", "elle güncellenir": "updated by hand",
    "Hisseler birbirine çok bağlı hareket ediyor: çeşitlendirme göründüğünden az.": "The stocks move very closely together: there is less diversification than it looks.",
}
_T = lambda m, i: data("en", m.group(i))
DATA_PATTERNS = [
    (r"Bilanço (-?\d+) gün sonra: açılış boşluğu (?:\(gap\) )?riski yüksek\. Yeni pozisyon bilanço sonrasına bırakılabilir ya da küçük tutulabilir\.",
     lambda m: f"Earnings in {m.group(1)} days: the risk of an opening gap is high. A new position can wait until after earnings or be kept small."),
    (r"Kırmızı bayrak: (.*)", lambda m: f"Red flag: {_T(m, 1)}"),
    (r"vergi öncesi kârın %(\S+)'i yatırım faaliyeti geliri \(tek seferlik olabilir\)", lambda m: f"{m.group(1)}% of pre-tax profit is investment income (may be one-off)"),
    (r"ticari alacaklar \(%(\S+)\) satıştan \(%(\S+)\) çok hızlı büyüyor", lambda m: f"trade receivables ({m.group(1)}%) are growing much faster than sales ({m.group(2)}%)"),
    (r"stoklar \(%(\S+)\) satıştan \(%(\S+)\) çok hızlı büyüyor", lambda m: f"inventories ({m.group(1)}%) are growing much faster than sales ({m.group(2)}%)"),
    (r"finansal borç yılda %(\S+) arttı", lambda m: f"financial debt rose {m.group(1)}% in a year"),
    (r"faaliyet marjı düşüyor \(%(\S+) → %(\S+)\)", lambda m: f"operating margin is falling ({m.group(1)}% → {m.group(2)}%)"),
    (r"net borç/FAVÖK (\S+) \(yüksek\)", lambda m: f"net debt/EBITDA {m.group(1)} (high)"),
    (r"faaliyet kârı finansman giderini ancak (\S+) kat karşılıyor", lambda m: f"operating profit covers finance costs only {m.group(1)} times"),
    (r"kredi/mevduat (\S+) \(fonlama baskısı\)", lambda m: f"loans/deposits {m.group(1)} (funding pressure)"),
    (r"risk maliyeti %(\S+) \(karşılık yükü\)", lambda m: f"cost of risk {m.group(1)}% (provision burden)"),
    (r"(.*) \(tarih geçmiş, yenisi açıklanmamış\)", lambda m: f"{_T(m, 1)} (the date has passed; the new one is not announced)"),
    (r"son çeyrek (.*)", lambda m: f"latest quarter {m.group(1)}"), (r"son dönem (.*)", lambda m: f"latest period {m.group(1)}"),
    (r"son kapanan gün (.*)", lambda m: f"last closed day {m.group(1)}"), (r"son gün (.*)", lambda m: f"last day {m.group(1)}"),
    (r"(\S+) portföyün %(\S+)'i: tek hisse riski yüksek\.", lambda m: f"{m.group(1)} is {m.group(2)}% of the portfolio: single-stock risk is high."),
    (r"(.+) sektörü portföyün %(\S+)'i\.", lambda m: f"The {m.group(1)} sector is {m.group(2)}% of the portfolio."),
    (r"'(.+)' temasında %(\S+) \((.*)\): bu hisseler aynı habere birlikte tepki verir\.",
     lambda m: f"{m.group(2)}% in the '{_T(m, 1)}' theme ({m.group(3)}): these stocks react together to the same news."),
]
_DATA_RE = None


def data(code: str, text):
    """A sentence, source row or label a card stores in Turkish, in English for an English chat; unknown text as written."""
    global _DATA_RE
    if code != "en" or not isinstance(text, str) or not text:
        return text
    if text in DATA_EN:
        return DATA_EN[text]
    if _DATA_RE is None:
        _DATA_RE = [(re.compile(p), fn) for p, fn in DATA_PATTERNS]
    for rx, fn in _DATA_RE:
        m = rx.fullmatch(text)
        if m:
            return fn(m)
    return text
