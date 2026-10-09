import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

// Dil: Türkçe (kaynak) ve İngilizce. Metinler kodda Türkçe yazılır; t("Türkçe metin") İngilizce seçiliyse karşılığını verir.
// Karşılığı henüz yazılmamış metin Türkçe kalır (hata vermez). Değişkenler: t("{n} hisse", { n: 5 }).
// Seçim tarayıcıda saklanır; sistem sahibi için bota da iletilir (Telegram mesajları aynı dile geçer).
const KEY = "kapanis-lang";

const EN = {
  // menü grupları
  "Özet": "Overview", "Portföy": "Portfolio", "Sinyaller": "Signals", "Performans": "Performance", "Piyasa": "Markets", "Sistem": "System", "Hesap": "Account",
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
  let out = lang === "en" && Object.prototype.hasOwnProperty.call(EN, text) ? EN[text] : text;
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
export const LANGS = [{ value: "tr", label: "Türkçe" }, { value: "en", label: "English" }];
