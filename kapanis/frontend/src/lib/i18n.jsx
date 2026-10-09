import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

// Dil: Türkçe (kaynak) ve İngilizce. Metinler kodda Türkçe yazılır; t("Türkçe metin") İngilizce seçiliyse karşılığını verir.
// Karşılığı henüz yazılmamış metin Türkçe kalır (hata vermez). Değişkenler: t("{n} hisse", { n: 5 }).
// Aynı Türkçe sözün iki İngilizce karşılığı varsa bağlam eklenir: t("Kapat§off"); "§" ve sonrası ekranda görünmez.
// Seçim tarayıcıda saklanır; sistem sahibi için bota da iletilir (Telegram mesajları aynı dile geçer).
const KEY = "kapanis-lang";

const EN = {
  // menü grupları
  "Özet": "Overview", "Portföy": "Portfolio", "Sinyaller": "Signals", "Performans": "Performance", "Piyasa": "Market", "Sistem": "System", "Hesap": "Account",
  // menü
  "Genel Bakış": "Overview", "Takip Listem": "Watchlist", "Pozisyonlar": "Positions", "Sinyaller & Analiz": "Signals & Analysis",
  "Son Analizlerim": "My Analyses", "Strateji Kurucu": "Strategy Builder", "Kriz Planı": "Crisis Plan", "Planlar & Fırsatlar": "Plans & Opportunities",
  "Kripto Danışman V2": "Crypto Advisor V2", "Kontrol & Karşılaştır": "Check & Compare", "Alarmlar": "Alerts", "Grafik alarmlarım": "My Chart Alerts",
  "Disiplin & Günlük": "Discipline & Journal", "Rapor & Kural Karnesi": "Report & Rule Scorecard", "Grafik": "Chart", "Makro": "Macro", "Vadeli": "Futures",
  "Hisse tablosu": "Stock Table", "Hisse kartı": "Stock Card", "Şirket takvimi": "Company Calendar", "Yapay zekâ maliyeti": "AI Cost", "Ayarlar": "Settings",
  "Kullanıcılar": "Users", "Hesap & Telegram": "Account & Telegram", "Portföyüm": "My Portfolio", "Portföy sağlığı": "Portfolio Health", "Karnem": "My Scorecard",
  "Karnem & aylık rapor": "Scorecard & Monthly Report", "Alarmlarım": "My Alerts", "Grafik & Analiz": "Chart & Analysis", "Alarm": "Alerts", "Takip": "Watch",
  "Sinyal": "Signals", "Bot ayarları": "Bot settings", "Çıkış yap": "Sign out", "Dil": "Language",
  // üst şerit
  "Bot çevrimiçi": "Bot online", "Bot yanıt vermiyor": "Bot not responding", "son veri": "last data", "Son veri": "Last data",
  "Bot henüz veri göndermedi": "The bot has not sent data yet", "açık": "open", "kapalı": "closed", "kapalı · son seans Cuma": "closed · last session Friday",
  "Kripto 7/24": "Crypto 24/7", "işlem bota iletildi": "actions sent to the bot", "bekleyen karar": "pending decisions", "Temayı değiştir": "Switch theme",
  "Menü": "Menu", "Kapat": "Close", "Ana sekmeler": "Main tabs",
  "Bu panel fikir üretir; karar senindir.": "This panel gives you information; the decision is yours.", "Bot işlem yapmaz.": "The bot never trades.",
  "Yatırım tavsiyesi değildir. Bot işlem yapmaz.": "Not investment advice. The bot never trades.",
  "Defansif mod açık": "Defensive mode on", "risk hedefi": "risk target", "Planı gör": "See the plan",
  // etiketler (bottan gelen değerler)
  "GÜÇLÜ": "STRONG", "ZAYIF": "WEAK", "NÖTR": "NEUTRAL", "PAHALI": "EXPENSIVE", "UCUZ": "CHEAP", "MAKUL": "FAIR", "BİLİNMİYOR": "UNKNOWN",
  "YÜKSEK": "HIGH", "ORTA": "MEDIUM", "DÜŞÜK": "LOW", "YUKARI": "UP", "AŞAĞI": "DOWN", "YATAY": "FLAT",
  "↗ güçlü": "↗ strong", "↘ zayıf": "↘ weak", "→ karışık": "→ mixed", "az veri": "little data",
  // ayarlar: bildirimler ve dil
  "Bildirimler": "Notifications", "bildirimleri": "notifications", "AÇ": "ON", "KP": "OFF",
  "Kapalı piyasadan otomatik mesaj gelmez (alarm, sinyal, seviye özeti, çıkış uyarısı). Yazdığın komutlar yine cevaplanır, kayıtlı alarmlar silinmez; kapalıyken oluşan bildirimler sonradan gönderilmez. Telegram: /bildirimler":
    "A market that is switched off sends no automatic messages (alerts, signals, level digest, exit warnings). Commands you type are still answered and saved alerts are kept; messages suppressed while it was off are not sent later. Telegram: /bildirimler",
  "Site ve Telegram dili": "Language of the site and Telegram",
  "Seçim bu tarayıcıda saklanır ve bota iletilir: Telegram mesajları da aynı dile geçer. Çeviri aşamalı ilerliyor; henüz çevrilmemiş yerler Türkçe görünür.":
    "The choice is stored in this browser and sent to the bot, so Telegram messages switch too. Translation is in progress; parts not translated yet stay in Turkish.",
  // hisse tablosu
  "Bir evrenin bütün hisseleri tek tabloda: trend, endekse göre güç, bilanço günü, temel puan, değerleme. Bakmak ve sıralamak için; öneri listesi değil.":
    "Every stock of a universe in one table: trend, strength against the index, earnings day, fundamental score, valuation. For looking up and sorting; not a list of suggestions.",
  "Şimdi yenile": "Refresh now", "Hazırlanıyor…": "Preparing…", "Sıralama": "Sort", "Temel puan: yüksekten düşüğe": "Fundamental score: high to low",
  "Endekse göre en güçlü": "Strongest against the index", "Günlük: en çok yükselen": "Daily: biggest gainers", "Haftalık: en çok yükselen": "Weekly: biggest gainers",
  "Bilançosu en yakın": "Earnings soonest", "RSI: düşükten yükseğe": "RSI: low to high", "Kod (A–Z)": "Ticker (A–Z)",
  "↗ Güçlü trend": "↗ Strong trend", "Endeksten güçlü": "Stronger than the index", "Temel puan 70+": "Fundamental score 70+", "Pahalı değil": "Not expensive",
  "Bilanço 14 günden uzak": "Earnings more than 14 days away", "Bilanço 14 gün içinde": "Earnings within 14 days",
  "Kod": "Ticker", "Fiyat": "Price", "Günlük": "Day", "Haftalık": "Week", "Trend": "Trend", "Güç": "Strength", "Bilanço": "Earnings", "Temel puan": "Fund. score",
  "Değerleme": "Valuation", "bugün": "today", "yarın": "tomorrow", "gün": "days", "hisse": "stocks", "güncelleme": "updated",
  "hissenin bilançosu 5 gün içinde": "stocks report earnings within 5 days", "hissenin temel verisi alınamadı": "stocks have no fundamentals data",
  "Tablo henüz hazırlanmadı": "The table has not been built yet", "Eşleşen hisse yok": "No matching stocks", "Bu filtrelere uyan hisse yok.": "No stock matches these filters.",
  "Bot her işlem günü kapanıştan sonra bu tabloyu yeniler. Beklemeden görmek için \"Şimdi yenile\"ye bas ya da Telegram'da": "The bot rebuilds this table after the close of each trading day. To see it now press \"Refresh now\" or type in Telegram",
  "yaz.": ".",
  "Satıra basınca hisse kartı açılır. Güç: 6 aylık getirinin {b} getirisinden farkı. Değerleme kaba yön göstergesidir, adil değer hesabı değildir. Temel puan getiri tahmini değildir: hisselerde test edilen zamanlama kurallarının hiçbiri elde tutmayı geçemedi.":
    "Tap a row to open the stock card. Strength: the 6-month return minus the {b} return. Valuation is a coarse pointer, not a fair-value estimate. The fundamental score is not a return forecast: no timing rule tested on stocks beat holding them.",
  "Kaynaklar": "Sources", "puan": "score", "güç": "strength", "bilanço": "earnings", "Gün": "Day",
  // şirket takvimi
  "Portföyündeki ve takip listendeki hisselerin bilanço ve temettü günleri. Bilanço günü fiyat açılışta sıçrayabilir.":
    "Earnings and dividend days of the stocks you hold or watch. On an earnings day the price can gap at the open.",
  "Takvim yükleniyor...": "Loading the calendar...", "Hepsi": "All", "Yalnız bilanço": "Earnings only",
  "hissede bilanço 5 gün içinde": "stocks report earnings within 5 days",
  "Açılış boşluğu (gap) riski yüksek: stop seviyesi atlanabilir. Bu bir uyarıdır, öneri değildir.": "Gap risk at the open is high: a stop level can be jumped. This is a warning, not a suggestion.",
  "Yaklaşan olay yok": "No upcoming events", "Bu filtreye uyan olay yok.": "No event matches this filter.",
  "Önümüzdeki günlerde bilanço ya da temettü tarihi görünmüyor. Takip listene hisse ekleyince burada çıkar.": "No earnings or dividend date in the coming days. Stocks you add to the watchlist appear here.",
  "portföyünde": "held", "takipte": "watched", "boşluk riski": "gap risk", "Önümüzdeki 7 gün": "Next 7 days",
  "Tarihler Yahoo'dan, günde bir kez yenilenir; kesin tarih için KAP ya da şirketin yatırımcı sayfası. Bilançoya 5 gün ve daha az kala risk YÜKSEK, 14 güne kadar ORTA sayılır. Bir gün önce Telegram'dan hatırlatma gelir. Telegram: /olaylar":
    "Dates come from Yahoo and are refreshed once a day; for the exact date check KAP or the company's investor page. Risk is HIGH with 5 days or fewer to the report and MEDIUM up to 14 days. A reminder arrives on Telegram the day before. Telegram: /olaylar",
  "Temettü hak kullanım": "Ex-dividend", "Temettü ödeme": "Dividend payment",
  // ortak
  "ABD": "US", "Kripto": "Crypto", "KRIPTO": "CRYPTO", "Kripto (BTC)": "Crypto (BTC)", "ABD (S&P 500)": "US (S&P 500)", "Altın/Döviz": "Gold/FX",
  "Açık": "On", "Kapalı": "Off", "Kapat§off": "Turn off", "Aç": "Turn on", "Kaydet": "Save", "Vazgeç": "Cancel", "Değiştir": "Edit", "Ekle": "Add",
  "Hesapla": "Calculate", "Hesaplanıyor…": "Calculating…", "Yenile": "Refresh", "yok": "none", "Yok.": "None.", "{n} gün": "{n} days",
  "{n} dikkat noktası": "Points to note: {n}", "bilinmiyor": "unknown", " puan": " points", "toplam": "total", "Bugün": "Today", "Dün": "Yesterday",
  "birazdan": "soon", "az önce": "just now", "dk": "min", "sa": "h", "↓ Yenilemek için bırak": "↓ Release to refresh",
  // hisse kartı
  "Sonraki bilanço": "Next earnings", "açıklanmadı": "not reported yet", "Değerleme (kaba)": "Valuation (coarse)",
  "ileri F/K {a} · PEG {b}": "forward P/E {a} · PEG {b}", "F/K {a} · PD/DD {b}": "P/E {a} · P/B {b}", "Trend ve güç": "Trend and strength",
  "Günlük / haftalık / aylık": "Daily / weekly / monthly", "Günlük / haftalık": "Daily / weekly", "Ortalamalar": "Moving averages",
  "52 hafta zirvesine uzaklık": "Distance to the 52-week high", "S&P 500'e göre (6 ay)": "Against the S&P 500 (6 months)",
  "Nasdaq-100'e göre (6 ay)": "Against the Nasdaq-100 (6 months)", "Sektöre göre ({etf}, 6 ay)": "Against the sector ({etf}, 6 months)",
  "BIST 100'e göre (6 ay)": "Against the BIST 100 (6 months)", "Haftalık evre": "Weekly stage",
  "Güç: 6 aylık getirinin endeksten farkı. 10 puan üstü GÜÇLÜ, 10 puan altı ZAYIF.":
    "Strength: the 6-month return minus the index return. More than 10 points above is STRONG, more than 10 points below is WEAK.",
  "Bilanço ve temettü": "Earnings and dividends", "{n} gün sonra": "in {n} days", "tarih geçmiş": "date has passed", "Tarihin kaynağı": "Source of the date",
  "Son açıklama": "Last release", "İlk seans tepkisi": "First-session reaction", "(S&P 500'e göre {x})": "({x} against the S&P 500)",
  "O günden beri": "Since that day", "{n} seans önce": "{n} sessions ago", "SEC kaydında bulunamadı": "Not found in SEC filings",
  "EPS sürprizi ({q})": "EPS surprise ({q})", "açıklanmış tarih yok": "no announced date",
  "Bağlamdır, sinyal değildir.": "This is context, not a signal.",
  "Geçmiş testte iyi bilanço tepkisinden sonra piyasanın üstünde getiri çıkmadı. Bilançoya 5 gün ve daha az kala açılış boşluğu (gap) riski yüksektir.":
    "In the history test a good earnings reaction was not followed by a return above the market. With 5 days or fewer to the report, gap risk at the open is high.",
  "Bilançoya 5 gün ve daha az kala açılış boşluğu riski yüksektir. Tarihler Yahoo'dan; kesin tarih için KAP. Geçmiş bilanço tepkisi ve analist tahmin revizyonu BIST için ücretsiz kaynakta yok.":
    "With 5 days or fewer to the report, gap risk at the open is high. Dates come from Yahoo; for the exact date check KAP. Past earnings reactions and analyst estimate revisions are not available for BIST in a free source.",
  "Analist tahminleri": "Analyst estimates", "Kâr tahmini yönü (30 gün)": "Earnings estimate direction (30 days)", "EPS tahmini değişimi": "EPS estimate change",
  "30 gün {a} · 90 gün {b}": "30 days {a} · 90 days {b}", "Revizyon sayısı (30 gün)": "Revisions (30 days)", "yukarı {a} · aşağı {b}": "up {a} · down {b}",
  "Analistlerin gelecek yıl kâr tahminindeki değişim. Tahmin yönü fiyat yönü demek değildir.":
    "The change in analysts' earnings estimate for next year. The direction of estimates is not the direction of the price.",
  "Etiket": "Label", "İleri F/K": "Forward P/E", "F/K": "P/E", "PD/DD": "P/B", "FD/FAVÖK": "EV/EBITDA", "Serbest nakit akışı verimi": "Free cash flow yield",
  "Kaba yön göstergesidir, adil değer hesabı değildir.": "A coarse pointer, not a fair-value estimate.",
  "Sabit eşikler: ileri F/K 35 üstü ya da PEG 2,5 üstü PAHALI; ileri F/K 15 altı (PEG 1,5 altı) UCUZ.":
    "Fixed thresholds: forward P/E above 35 or PEG above 2.5 is EXPENSIVE; forward P/E below 15 (PEG below 1.5) is CHEAP.",
  "Sabit eşikler: F/K 25 üstü ya da PD/DD 6 üstü PAHALI; F/K 8 altı (PD/DD 1,5 altı) UCUZ. Enflasyon muhasebesinde F/K dönemden döneme çok oynar.":
    "Fixed thresholds: P/E above 25 or P/B above 6 is EXPENSIVE; P/E below 8 (P/B below 1.5) is CHEAP. Under inflation accounting the P/E moves a lot from period to period.",
  "Kaynaklar ve denetim izi": "Sources and audit trail", "Veri": "Data", "Kaynak": "Source", "Tarih / dönem": "Date / period",
  "Üretildi {z}": "Generated {z}", "kod sürümü {k}": "code version {k}",
  "Her kart sunucuda denetim kaydına yazılır. Karar desteğidir; AL/SAT önerisi değildir. Hisselerde test edilen zamanlama kurallarının hiçbiri hisseyi elde tutmayı geçemedi.":
    "Every card is written to the audit log on the server. It is decision support, not a BUY/SELL suggestion. No timing rule tested on stocks beat holding the stock.",
  "ABD hisse kodu yaz (ör. NVDA).": "Type a US ticker (e.g. NVDA).", "BIST hisse kodu yaz (ör. THYAO).": "Type a BIST ticker (e.g. THYAO).",
  "{k} kartı hazırlanıyor.": "Preparing the {k} card.",
  "Tek ekranda bir hisse: trend, endekse göre güç, bilanço riski, temel puan, değerleme. Karar desteği; sinyal değil.":
    "One stock on one screen: trend, strength against the index, earnings risk, fundamental score, valuation. Decision support; not a signal.",
  "Hisse seç": "Choose a stock", "Kartı getir": "Get the card",
  "Veriler istek anında çekilir. ABD: SEC (resmi bilanço ve açıklama zamanı), Yahoo (analist tahminleri, takvim). BIST: İş Yatırım mali tabloları, Yahoo (fiyat ~15 dk gecikmeli, takvim). Hazırlanması 10–40 saniye sürer.":
    "Data is fetched at the time of the request. US: SEC (official statements and release time), Yahoo (analyst estimates, calendar). BIST: İş Yatırım financial statements, Yahoo (price delayed ~15 min, calendar). It takes 10–40 seconds.",
  "Bot verileri topluyor…": "The bot is collecting the data…", "Kart hazırlanamadı": "The card could not be prepared", "Henüz kart yok": "No card yet",
  "Piyasayı seç, kodu yaz, \"Kartı getir\"e bas. Son istenen kart burada kalır.": "Choose the market, type the ticker, press \"Get the card\". The last card you asked for stays here.",
  // ABD portföyü
  "ABD portföyü hesaplanıyor.": "Calculating the US portfolio.", "1 = endeks kadar oynar": "1 = moves as much as the index",
  "ABD hisseleri: ortak risk": "US stocks: shared risk",
  "Yedi ayrı hisse, aynı hikâyeye bağlıysa tek pozisyon gibi davranır. Bu bölüm botun portföyündeki ABD hisselerini sektör, tema, birlikte hareket ve dört senaryo üzerinden gösterir. Öneri içermez.":
    "Seven different stocks behave like one position when they depend on the same story. This section shows the US stocks in the bot's portfolio by sector, theme, co-movement and four scenarios. It contains no suggestion.",
  "Bot bir yıllık fiyatları ve sektörleri topluyor (10–40 sn)…": "The bot is collecting one year of prices and the sectors (10–40 s)…",
  "Hesaplanamadı": "Could not be calculated", "Botta açık ABD pozisyonu yok.": "The bot has no open US position.",
  "Henüz hesaplanmadı. \"Hesapla\"ya bas; sonuç burada kalır.": "Not calculated yet. Press \"Calculate\"; the result stays here.",
  "ABD toplamı": "US total", "Ortalama korelasyon": "Average correlation", "1 yıl, günlük; 1'e yakın = birlikte hareket": "1 year, daily; close to 1 = moving together",
  "{n} yoğunlaşma notu": "Concentration notes: {n}", "Hisse ağırlıkları": "Stock weights", "Sektör dağılımı": "Sector breakdown", "Tema dağılımı": "Theme breakdown",
  "Tanımlı temalarda hisse yok.": "No stock in the defined themes.",
  "Bir hisse birden çok temada olabilir, toplam %100'ü geçer. Temalar elle tanımlı listelerdir: mega teknoloji, yarı iletken, yapay zekâ, yapay zekâ enerjisi, banka/finans, savunmacı.":
    "A stock can be in more than one theme, so the total exceeds 100%. Themes are hand-made lists: mega tech, semiconductors, AI, AI energy, banks/finance, defensive.",
  "Mega teknoloji": "Mega tech", "Yarı iletken": "Semiconductors", "Yapay zekâ (çip, bulut, yazılım)": "AI (chips, cloud, software)",
  "Yapay zekâ enerjisi / altyapı": "AI energy / infrastructure", "Banka / finans": "Banks / finance", "Savunmacı (temel tüketim, sağlık)": "Defensive (staples, health care)",
  "Birlikte hareket": "Co-movement", "en bağlı": "most linked", "en bağımsız": "most independent", "Çift": "Pair", "Korelasyon": "Correlation",
  "Senaryolar": "Scenarios", "Senaryo": "Scenario", "Senaryo cetvelidir, tahmin değildir.": "A scenario ruler, not a forecast.", "Tutar": "Amount",
  "En çok etkilenen": "Most affected", "S&P 500 %10 düşerse": "If the S&P 500 falls 10%", "Nasdaq-100 %10 düşerse": "If the Nasdaq-100 falls 10%",
  "10 yıllık faiz 0,50 puan artarsa": "If the 10-year yield rises 0.50 points", "VIX 30'a çıkarsa": "If the VIX rises to 30",
  "BTC %20 düşerse": "If BTC falls 20%", "BIST 100 %15 düşerse": "If the BIST 100 falls 15%", "Dolar/TL %10 yükselirse": "If USD/TRY rises 10%",
  "Tek etkenli hesap: son bir yılın günlük birlikte hareketinden. Şu an VIX {vix}, 10 yıllık faiz %{tnx}. Gerçek bir satışta etkenler birlikte hareket eder ve duyarlılıklar değişir; satırlar toplanmaz.":
    "Single-factor arithmetic from the daily co-movement of the last year. Now: VIX {vix}, 10-year yield {tnx}%. In a real sell-off the factors move together and the sensitivities change; do not add the rows.",
  "beta ve senaryolar portföyün %{n}'ini kapsar": "beta and scenarios cover {n}% of the portfolio",
  // portföy sağlığı
  "Piyasa durumu": "Market state", "yükseliş trendi": "uptrend", "düşüş trendi": "downtrend", "yatay / kararsız": "sideways / undecided",
  "oynaklık yüksek": "high volatility", "panik / sert düşüş": "panic / sharp fall", "veri yetersiz": "not enough data",
  "Bilgi amaçlı piyasa durumu (kapanmış günlük mumlardan). Strateji seçmek için kullanılmaz: rejime göre strateji seçmenin işe yaradığı henüz kanıtlanmadı.":
    "Market state for information (from closed daily candles). It is not used to pick a strategy: picking a strategy by regime has not been shown to work.",
  "Kod yaz.": "Type a ticker.", "Kaç adet alayım? (risk hesabı)": "How many should I buy? (risk arithmetic)", "boşsa 2 × ATR": "empty = 2 × ATR", "boşsa %1": "empty = 1%",
  "En fazla": "At most", "adet": "units", "stop kırılırsa kayıp": "loss if the stop breaks", "Stres testi: şu olursa?": "Stress test: what if?",
  "Tahmin değil: her varlığın son 1 yılda o piyasanın günlük hareketine ne kadar eşlik ettiği (beta) ile hesaplandı. Gerçek düşüşlerde varlıklar genelde birlikte daha sert düşer; dolar senaryosu yalnız kur etkisi.":
    "Not a forecast: computed from how much each asset followed the daily move of that market over the last year (beta). In real sell-offs assets usually fall harder together; the dollar scenario is the currency effect only.",
  "Tek ekranda: neye ne kadar bağlısın, tepeden ne kadar düştün, hangileri aslında aynı pozisyon.":
    "On one screen: what you depend on and how much, how far you are below the peak, which holdings are really the same position.",
  "Açık pozisyon yok": "No open position", "Portföyüm'e pozisyon ekleyince burada sağlık özeti çıkar.": "Add a position in My Portfolio and the health summary appears here.",
  "Belirgin sorun yok": "No obvious problem", "Yoğunlaşma, birlikte hareket eden çift ya da stopsuz pozisyon görünmüyor.": "No concentration, no co-moving pair and no position without a stop.",
  "Ağırlık": "Weight", "Maliyete göre": "Against cost", "Tepeden": "From the peak", "Trend kuralı": "Trend rule", "yalnız kripto": "crypto only",
  "trendde · çıkış {p}": "in trend · exit {p}", "dışarıda (10 gün dibi {p})": "out (10-day low {p})",
  "Ağırlık TL karşılığıyla (USD/TRY {fx}). \"Tepeden\": aldığından beri görülen en yüksek günlük kapanışa göre. Trend kuralı geçmiş testte işe yarayan tek kural; yalnız kriptoda test edildi. Kapanış fiyatları, oluşmakta olan mum sayılmaz.":
    "Weights are in TL terms (USD/TRY {fx}). \"From the peak\": against the highest daily close since you bought. The trend rule is the only rule that worked in the history test; it was tested on crypto only. Closing prices; the candle still forming is not counted.",
  "Birlikte hareket edenler": "Moving together",
  "90 günlük korelasyon {r}. Biri düşerken diğeri de düşer; risk hesabında tek pozisyon say.": "90-day correlation {r}. When one falls the other falls too; count them as one position for risk.",
  // karnem ve aylık rapor
  "ort. {n} gün tuttun": "held {n} days on average",
  "Kapattığın işlemlerden: ne kadar isabetli, ne kadar tuttun, stopa uydun mu, erken mi sattın.": "From your closed trades: how often you were right, how long you held, whether you kept your stop, whether you sold early.",
  "Henüz kapalı işlem yok": "No closed trade yet",
  "Portföyüm'de bir pozisyonu \"Sattım\" ile kapattığında karnen burada oluşur.": "When you close a position with \"Sold\" in My Portfolio, your scorecard appears here.",
  "Az veri": "Little data", "Kapalı işlem": "Closed trades", "{w} kazanç · {l} kayıp": "{w} wins · {l} losses", "İsabet": "Hit rate",
  "kârla kapanan işlem oranı": "share of trades closed at a profit", "Ortalama kazanç": "Average win", "Ortalama kayıp": "Average loss",
  "Gerçekleşen ({c})": "Realized ({c})", "kapattıkların toplamı": "total of your closed trades", "Davranışın": "Your behaviour",
  "⚠️ Kaybedenleri kazananlardan uzun tutuyorsun ({a} gün vs {b} gün): en yaygın hata \"kârı erken al, zararı bekle\".":
    "⚠️ You hold losers longer than winners ({a} days vs {b} days): the most common mistake is \"take profit early, wait on a loss\".",
  "✅ Kaybedenleri kazananlardan uzun tutmuyorsun.": "✅ You do not hold losers longer than winners.",
  "⚠️ {n} işlemi stopunun altından sattın (ortalama {p}): stop kapanışla kırıldığında beklemek kaybı büyüttü.":
    "⚠️ You sold {n} trades below your stop (average {p}): waiting after the stop broke on a close made the loss bigger.",
  "✅ Stopunun altına inmeden sattın.": "✅ You sold without going below your stop.",
  "ℹ️ {n} kârlı satıştan sonra fiyat %10'dan fazla daha yükseldi. Bu kesin bir hata değil; çıkışı kurala (ör. trend kuralı) bağlarsan duyguya bağlı kalmaz.":
    "ℹ️ After {n} profitable sales the price rose more than 10% further. This is not necessarily a mistake; an exit tied to a rule (e.g. the trend rule) does not depend on emotion.",
  "ℹ️ Sattıktan sonra %10'dan fazla yükselen olmadı.": "ℹ️ Nothing rose more than 10% after you sold.",
  "Son satışların": "Your latest sales", "Satış": "Sale", "Maliyet → satış": "Cost → sale", "Sonuç": "Result", "stop altı": "below stop", "Satıştan sonra": "After the sale",
  "\"Satıştan sonra\": sattığın fiyattan son günlük kapanışa değişim.": "\"After the sale\": the change from your sale price to the latest daily close.",
  "Aylık rapor": "Monthly report",
  "Henüz rapor yok. Bot her ayın ilk günü geçen ayın raporunu hazırlar; beklemeden görmek için Telegram'da /aylik yaz.":
    "No report yet. The bot prepares last month's report on the first day of each month; to see it now type /aylik in Telegram.",
  "Ay": "Month", "Bu ay içinde izlenen pozisyon yok.": "No position was tracked in this month.", "Getiri (TL)": "Return (TL)", "Getiri (USD)": "Return (USD)",
  "İşlemler": "Trades", "{a} alım · {s} satım": "{a} buys · {s} sells", "gerçekleşen": "realized", "satış yok": "no sales", "En büyük pozisyon": "Largest position",
  "ay başı": "month start", "ay sonunda pozisyon yok": "no position at month end", "Aynı ay endeksler": "Indexes in the same month", "Endeks": "Index",
  "Aynı ay": "Same month", "Senin farkın (puan)": "Your difference (points)", "Altın": "Gold",
  "BIST 100 ile TL getirin, diğerleriyle USD getirin karşılaştırılır. USD/TRY aynı ay {x}.": "Your TL return is compared with the BIST 100, your USD return with the others. USD/TRY in the same month: {x}.",
  "En çok kazandıran": "Biggest gainers", "En çok kaybettiren": "Biggest losers", "Alınan": "Bought", "Satılan": "Sold",
  "Fiyat geçmişi alınamadığı için dışarıda kalan": "Left out because the price history was not available",
  "Ölçüm: her pozisyon yalnız elde tutulduğu günler için sayılır ({a} kapanışı → {b} kapanışı; ay içinde alınan alış fiyatından, satılan satış fiyatından). Yeni giren para getiri sayılmaz. Geçmişin özetidir; tahmin ya da öneri içermez.":
    "Measurement: each position counts only for the days it was held (close of {a} → close of {b}; bought within the month from the buy price, sold from the sale price). New money is not counted as return. It is a summary of the past; it contains no forecast or suggestion.",
  // uygulama bildirimleri
  "Bu cihazda uygulama bildirimleri açık.": "App notifications are on for this device.", "Bildirim açılamadı. Tarayıcı izinlerini kontrol et.": "Could not turn notifications on. Check the browser permissions.",
  "Bu cihazda uygulama bildirimleri kapatıldı.": "App notifications are off for this device.", "Test bildirimi gönderildi.": "Test notification sent.", "Gönderilemedi.": "Could not send.",
  "Uygulama bildirimleri": "App notifications",
  "Botun Telegram'a attığı otomatik mesajlar (alarm, seviye özeti, çıkış uyarısı) bu cihaza da bildirim olarak gelir. Telegram bildirimleri aynen sürer. Her cihazda ayrı açılır.":
    "The automatic messages the bot sends to Telegram (alerts, level digest, exit warnings) also arrive on this device as notifications. Telegram notifications continue as before. Turn it on separately on each device.",
  "Kontrol ediliyor…": "Checking…", "Bu tarayıcı uygulama bildirimini desteklemiyor. Android'de Kapanış uygulaması ya da Chrome kullan.": "This browser does not support app notifications. On Android use the Kapanış app or Chrome.",
  "Bildirim izni bu cihazda engellenmiş. Telefon ayarları → Uygulamalar → Kapanış (ya da Chrome) → Bildirimler'den izin ver.":
    "Notification permission is blocked on this device. Allow it in Phone settings → Apps → Kapanış (or Chrome) → Notifications.",
  "Açılıyor…": "Turning on…", "Bu cihazda aç": "Turn on for this device", "Test bildirimi gönder": "Send a test notification",
  "Hangi piyasadan bildirim geleceğini Telegram'da /bildirimler ile ya da Ayarlar'dan seçersin; kapalı piyasa buraya da gelmez.":
    "Choose which markets send notifications with /bildirimler in Telegram or in Settings; a market that is off sends nothing here either.",
  // takip listesi
  "Desteğe yaklaşınca (%)": "Near support (%)", "RSI altına inince": "RSI falls below", "RSI üstüne çıkınca": "RSI rises above", "Hacim ortalamanın kaç katı": "Volume, times the average",
  "Değerler sayı olmalı (0 = o kural kapalı).": "Values must be numbers (0 = that rule is off).", "Takip kuralları kaydediliyor.": "Saving the watch rules.",
  "Takip uyarıları kapatılıyor.": "Turning watch alerts off.", "Takip uyarıları açılıyor.": "Turning watch alerts on.", "Takip uyarıları": "Watch alerts",
  "Bot 30 dakikada bir listeni kontrol eder; bir koşul olursa Telegram'a yazar (her kod ve kural için günde en fazla bir kez). Bu bir AL sinyali değildir.":
    "The bot checks your list every 30 minutes and writes to Telegram when a condition is met (at most once a day per ticker and rule). This is not a BUY signal.",
  "Liste sırası": "List order", "Günlük: en çok düşen": "Daily: biggest losers", "Haftalık: en çok düşen": "Weekly: biggest losers", "RSI: yüksekten düşüğe": "RSI: high to low",
  "Desteğe en yakın": "Closest to support", "↘ Zayıf": "↘ Weak", "Isınmış (RSI > 70)": "Overbought (RSI > 70)", "Çok satılmış (RSI < 30)": "Oversold (RSI < 30)",
  "Desteğe %2'den yakın": "Within 2% of support", "Portföyümde": "In my portfolio", "Portföyde": "Held",
  "Eklenecek kodu yaz.": "Type the ticker to add.", "{k} takip listesine ekleniyor.": "Adding {k} to the watchlist.", "{k} listeden çıkarılıyor.": "Removing {k} from the list.",
  "Takip listesi": "Watchlist", "İzlediğin kodların kodla hesaplanmış hızlı durumu. Satıra tıkla, grafiği açılsın.": "A quick computed status of the tickers you watch. Click a row to open its chart.",
  "kod ekle": "add a ticker", "Takip listesine eklenecek kod": "Ticker to add to the watchlist", "Takip listesi yükleniyor...": "Loading the watchlist...",
  "Bot takip listesi verisini henüz göndermedi (30 dakikada bir yeniler). Yukarıdan kod ekleyebilirsin.": "The bot has not sent the watchlist data yet (it refreshes every 30 minutes). You can add tickers above.",
  "yükselişte": "rising", "günlük = 24 saatlik değişim": "daily = 24-hour change", "günlük = son seans": "daily = last session", "veri ~15 dk gecikmeli": "data delayed ~15 min",
  "30 dakikada bir": "every 30 minutes",
  "Güç: 6 aylık getirinin {b} getirisinden farkı (puan); 10 puan üstü GÜÇLÜ, altı ZAYIF.": "Strength: the 6-month return minus the {b} return (points); more than 10 above is STRONG, more than 10 below is WEAK.",
  "Bilanço: sıradaki bilançoya kalan gün (5 gün ve altı kırmızı). Temel puan: bilanço verisinden 100 üzerinden, günde bir kez.":
    "Earnings: days to the next report (5 days or fewer in red). Fundamental score: out of 100 from financial statements, once a day.",
  "Açıklamadır, öneri değildir.": "A description, not a suggestion.", "Bu filtrelere uyan kod yok.": "No ticker matches these filters.", "Destek → Direnç": "Support → Resistance",
  "veri alınamadı": "no data", "Hafta": "Week", "kod seçili": "tickers selected", "Temizle": "Clear", "Listeden çıkar": "Remove from the list",
  "En fazla 10 kod": "At most 10 tickers", "Yapay zekâ analizi": "AI analysis", "{k} seç": "Select {k}",
};

const DAYS = { tr: ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"], en: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"] };
const MONTHS = {
  tr: ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

function read() {
  try { return localStorage.getItem(KEY) === "en" ? "en" : "tr"; } catch { return "tr"; }
}

export function translate(lang, text, vars) {
  if (typeof text !== "string") return text;
  let out = lang === "en" && Object.prototype.hasOwnProperty.call(EN, text) ? EN[text] : text.split("§")[0];
  if (vars) Object.entries(vars).forEach(([k, v]) => { out = out.split(`{${k}}`).join(String(v)); });
  return out;
}

const LangContext = createContext({ lang: "tr", setLang: () => {}, t: (s) => s, dayName: (i) => DAYS.tr[i], monthName: (i) => MONTHS.tr[i] });

export function LangProvider({ children }) {
  const [lang, setState] = useState(read);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  const setLang = useCallback((next) => {
    const value = next === "en" ? "en" : "tr";
    try { localStorage.setItem(KEY, value); } catch { /* depolama kapalıysa yalnız bu oturum */ }
    setState(value);
  }, []);
  const value = useMemo(() => ({
    lang, setLang, t: (text, vars) => translate(lang, text, vars),
    dayName: (i) => DAYS[lang][i], monthName: (i) => MONTHS[lang][i],
  }), [lang, setLang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export const useLang = () => useContext(LangContext);
// React dışındaki yardımcılar için (tarih biçimleri): seçili dil
export const currentLang = read;
export const LANGS = [{ value: "tr", label: "Türkçe" }, { value: "en", label: "English" }];
