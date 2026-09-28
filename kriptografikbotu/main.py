import asyncio
import contextvars
import types
import functools
import logging
import math
import re
import time
import tempfile
from collections import deque
from datetime import datetime, time as dtime, timedelta
from logging.handlers import RotatingFileHandler

import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, ExtBot, TypeHandler,
                          MessageHandler, filters)
from telegram.request import HTTPXRequest

import alerts_store
import assets
import balance
import backtest
import benchmark
import bist
import bist_signals
import charts
import corporate
import costs
import dca
import derivatives
import discipline
import eod
import freshness
import fundamentals
import exits
import gate
import journal
import pf_alarm
import positions
import quant_scan
import risk
import risk_news
import scanner
import sentiment
import shadow
import strength
import universe
import us
import us_fund
import us_signals
import watchlist
import features
import tools
import cloud_store
import db_backup
import config
import conversation_store as store
import llm
import macro
import model_score
import news
import opportunities
import market
import watcher
import web_sync
import voice_quant
import quiet
import signal_life
import advisor
from alert_engine import AlertEngine

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO,
                    handlers=[logging.StreamHandler(),
                              RotatingFileHandler(config.LOG_FILE, maxBytes=1_000_000, backupCount=3,
                                                  encoding="utf-8")])
# httpx logs full request URLs, which contain the Telegram bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

QUIET_NOTE = "🔕 Bu sinyal sessiz saatlerde tetiklendi, güncel fiyatla tekrar teyit et."
engine: AlertEngine | None = None

# One analysis at a time keeps history.json in order.
analysis_lock = asyncio.Lock()

HELP = """📋 KOMUTLAR (menü: mesaj kutusundaki / tuşu)

⭐ TEMEL
/firsat — "şu an alabileceğim tetiklenen hisse ya da coin var mı?" (düz yazıyla da sorabilirsin)
/takip — takip listem (16 coin, 35 BIST, 53 ABD). 30 dk'da bir sessizce sorar; tek/çoklu seç → 📊 durum (kod) / 🧠 analiz
  /takip THYAO BTC — direkt durum · /takip ekle X · /takip cikar X · /takip liste · /takip kapat|ac · /takip aralik 60
  /takip kural destek=1.5 rsi_alti=30 rsi_ustu=75 hacim=2 — son kapanışa göre koşullu uyarılar
/portfoy — portföy: adet, değer, günlük/toplam %, TUT/SAT (➕ Ekle butonu, çoklu seçim)
/portfoy detay — satış/tepe analizi · /portfoy analiz — yapay zekâ yorumu
/ne ASTOR — elindeki bir varlık için adım adım plan (düz yazı: "ASTOR çok arttı ne yapayım")
/portföy astordan 4 tane var 260 tl iken almıştım, europower 5 adet 70 tl — doğal yazıyla ekle (onay sorar)
/bakiye — bakiye (varlık + nakit), bugün / bu hafta / toplam K/Z · /bakiye bist · /bakiye kripto
/bakiye nakit 5000 tl · /bakiye nakit 120 usdt — nakdini gir
/aldim HYPE/USDT 92.7 60 — alım kaydı (alış fiyatı, kaç USDT'lik) · /aldim THYAO 285 10 (adet)
/plan — seçtiğin varlıkların planı, 15 dk'da bir takip · /plan ekle BTC THYAO · /plan cikar BTC · /plan hepsi · /plan dur
/tara — kripto + BIST fırsat taraması · /tara kripto · /tara bist

🪙 KRİPTO
/analiz BTC — analiz (birden fazla: /analiz ETH SOL)
/haber [BTC] — haberler · /vadeli BTC — funding, açık pozisyon · /duygu — Korku & Açgözlülük
/new_alert BTC/USDT KAPANIS ABOVE 85000 15m 1h iptal=83850 hedef=85500 — kapanış alarmı
/backtest BTC/USDT ABOVE 85000 15m — kuralı geçmişte dene

🇹🇷 BIST (orta/uzun vade · veri ~15 dk gecikmeli)
/incele THYAO — hisse analizi (teknik + temel + haber)
/temel THYAO — bilanço: USD büyüme, marj, nakit akışı, borç, ROE, F/K, FD/FAVÖK, kırmızı bayrak, skor
/bist — endeks kapısı, USD/TRY, bütçe, adaylar · /bist butce 5000 — BIST bütçen
/bist makro — TCMB/TÜİK takvimi · /bist haber [THYAO] — haberler
/bist alarm THYAO ABOVE 300 1d iptal=285 hedef=330 — kapanış alarmı
/bist aldim THYAO 320 4 stop=300 hedef=360 · /bist backtest THYAO 320 stop=300 hedef=360
/bist kapat · /bist ac — otomatik tarama (18:35)
/guc — haftalık güç sıralaması + sektör rotasyonu (cuma 19:00)
/gunsonu — gün sonu raporu (18:45) · /temettu [THYAO] — temettü ve bedelsiz
/kap — portföyündeki hisselerin KAP bildirimleri · /olaylar — bilanço ve temettü takvimi

🇺🇸 ABD HİSSELERİ (orta/uzun vade · Tiingo/Yahoo fiyat + SEC bilanço + analist tahminleri)
/abd — S&P 500/Nasdaq kapısı, VIX, 10Y faiz, dolar endeksi, bütçe · /abd butce 1000 (USD)
/abd AAPL — analiz (yapay zekâ) · /temel AAPL — büyüme, marj, FCF, SBC/seyreltme, ROIC, değerleme, tahmin revizyonu, skor
/abd guc — S&P 100 güç sıralaması + temel skor (cumartesi 10:00 otomatik)
/aldim AAPL 180 5 (hisse) · /aldim AAPL 180 500$ (tutar) · /bakiye nakit abd 1000 · "AAPL 200 üstünde kapanırsa haber ver"

💼 PORTFÖY ARAÇLARI
/grafik — dağılım + 90 gün · /risk — yoğunlaşma, korelasyon · /kiyas — BIST 100/BTC/altın/mevduat kıyası (/kiyas faiz 45)
/palarm kripto %-10 · /palarm bist 20000 — portföy alarmı · /palarm sil ID
/birikim ekle BTC 50 gun=5 — aylık düzenli alım · /birikim · /birikim sil ID
/hedef BIST 50 KRIPTO 20 ABD 20 NAKIT 10 — hedef dağılım (akşam sapma uyarısı)
/sanal al THYAO 290 5000 · /sanal sat ID [FIYAT] — gerçek para olmadan işlem takibi
/kontrol THYAO 290 280 310 — alım öncesi kontrol: kod kapısı, adet, risk (stop/hedef yazmazsan bölgelerden önerir)
/galarm THYAO sma50 ustu 1d · /galarm BTC rsi alti 30 4h · /galarm NVDA hacim 2 1d — gösterge alarmı (yalnız kapanış)
/karsilastir THYAO PGSUS EREGL — 2-4 hisse yan yana (BIST ya da ABD)
/temettu gelir — portföyün yıllık tahmini temettü geliri, ay ay
/hesap THYAO 320 stop=300 hedef=360 — kaç adet, risk, R/R
/pozisyonlar · /sat ID FIYAT [adet=N | yuzde=50]
/duzelt ID giris=X miktar=Y adet=N stop=X hedef=Y tarih=2025-03-01
/kayitsil ID — hiç almadığın kaydı sil (satış sayılmaz)
📸 Aracı kurum/borsa ekran görüntüsü at → varlıkları okur, onaylarsan ekler (Kimi K3)
🥇 Altın/döviz: /portfoy → Ekle → Altın/Döviz (gram altın, dolar, euro)

⏰ ALARMLAR
/view_alerts — liste · /cancel_alert PAIR ID — sil
Düz yazı: "THYAO 300 üstünde kapanırsa haber ver", "kripto portföyüm %10 düşerse haber ver"

📊 TAKİP VE KARNE
/rapor [gün] — performans · /haftalik — haftalık özet (pazar 20:00)
/golge — her ŞİMDİ AL'ı alsaydın · /karne — kural + model karnesi
/gunluk — neden aldım/sattım · /disiplin — tilt koruması (/disiplin sifirla)
/ders — haftanın kural ve işlem dersi (pazar 20:10 otomatik)

🌍 MAKRO
/makro — ABD makro pano · /takvim — ABD + Türkiye veri takvimi

🧠 YAPAY ZEKÂ VE SİSTEM
/model — Kimi K3 → DeepSeek V4.1 Flash → GLM 5.3 (15 dk'da bir sırayla) · /model kimi|deepseek|glm|sira
/maliyet — harcama · /durum — veri güncelliği
/sessizlik — bildirim gelmeyecek saatler, düz yazıyla: /sessizlik hafta içi 12.00-14.30 (/sessizlik sil 1)
/sessiz — hiç bildirim gelmez, açmak için /plan · /plan 45dk — plan güncellemesi aralığı
/pozisyon BTC acik|kapali · /sil BTC — plan · /sifirla — sohbet geçmişi · /get_logs — hatalar

💬 Düz yazı da olur: "BTC ne durumda", "THYAO ne durumda", "hype'a 60 dolar yatırdım", "portföy"."""


BOT_MENU = [
    # temel
    ("komutlar", "Tüm komutlar ve örnekler"),
    ("portfoy", "Portföy: adet, değer, günlük/toplam %, TUT/SAT"),
    ("bakiye", "Bakiye (varlık + nakit), bugün/hafta/toplam K/Z"),
    ("aldim", "Alım kaydı: /aldim HYPE/USDT 92.7 60"),
    ("plan", "Seçtiğin coin/hisselerin planı (/plan ekle BTC THYAO)"),
    ("firsat", "Şu an alabileceğim tetiklenen coin/hisse var mı?"),
    ("takip", "Takip listem: kripto/BIST/ABD, tek/çoklu seç, bak"),
    ("hedef", "Hedef dağılım ve sapma: /hedef BIST 50 KRIPTO 20 ..."),
    ("sanal", "Sanal işlem (gerçek para yok): /sanal al THYAO 290 5000"),
    ("kontrol", "Alım öncesi kontrol: /kontrol THYAO 290 280 310"),
    ("galarm", "Gösterge alarmı: /galarm THYAO sma50 ustu 1d"),
    ("karsilastir", "Hisse karşılaştır: /karsilastir THYAO PGSUS"),
    ("olaylar", "Bilanço ve temettü tarihleri (portföy + takip)"),
    ("kap", "Portföyündeki hisselerin KAP bildirimleri"),
    ("ders", "Haftanın dersi: hangi kural işe yaradı"),
    ("tara", "Fırsat taraması: kripto + BIST"),
    # kripto
    ("analiz", "🪙 Kripto analizi: /analiz BTC"),
    ("haber", "🪙 Kripto haberleri: /haber BTC"),
    ("vadeli", "🪙 Funding / açık pozisyon: /vadeli BTC"),
    ("duygu", "🪙 Korku & Açgözlülük, BTC dominansı"),
    ("new_alert", "🪙 Kapanış alarmı kur"),
    ("backtest", "🪙 Kuralı geçmişte dene"),
    # BIST
    ("incele", "🇹🇷 BIST hisse analizi: /incele THYAO"),
    ("bist", "🇹🇷 BIST: endeks, bütçe, makro, alarm, haber"),
    ("guc", "🇹🇷 Haftalık güç sıralaması + sektör rotasyonu"),
    ("temel", "🇹🇷🇺🇸 Temel analiz: /temel THYAO · /temel AAPL"),
    ("abd", "🇺🇸 ABD: piyasa, /abd AAPL analiz, /abd guc"),
    ("gunsonu", "🇹🇷 BIST gün sonu raporu"),
    ("temettu", "🇹🇷 Temettü ve bedelsiz: /temettu THYAO"),
    # portföy araçları
    ("grafik", "Portföy grafiği (dağılım + 90 gün)"),
    ("risk", "Yoğunlaşma ve korelasyon"),
    ("kiyas", "Portföy vs BIST 100, BTC, altın, mevduat"),
    ("palarm", "Portföy alarmı: /palarm kripto %-10"),
    ("birikim", "Aylık düzenli alım planı"),
    ("hesap", "Alım öncesi: adet, risk, R/R"),
    ("pozisyonlar", "Açık pozisyonlar ve K/Z"),
    ("sat", "Satış kaydı: /sat ID FIYAT"),
    ("duzelt", "Kaydı düzelt: /duzelt ID giris=X miktar=Y tarih=..."),
    ("kayitsil", "Hiç almadığın kaydı sil: /kayitsil ID"),
    # alarmlar
    ("view_alerts", "Alarmları listele"),
    ("cancel_alert", "Alarm sil: /cancel_alert PAIR ID"),
    # takip ve karne
    ("rapor", "Performans raporu"),
    ("haftalik", "Haftalık özet"),
    ("golge", "Gölge portföy: sinyalleri alsaydın"),
    ("karne", "Kural + model karnesi"),
    ("gunluk", "İşlem günlüğü karnesi"),
    ("disiplin", "Tilt koruması durumu"),
    # makro
    ("makro", "ABD makro pano"),
    ("takvim", "ABD + Türkiye veri takvimi"),
    # yapay zekâ ve sistem
    ("model", "Kimi K3 / DeepSeek Flash / GLM 5.3 sırası"),
    ("maliyet", "Yapay zekâ harcaması"),
    ("durum", "Veri güncelliği"),
    ("sessizlik", "Bildirim gelmeyecek saatler: /sessizlik hafta içi 12.00-14.30"),
    ("sessiz", "Hiç bildirim gelmesin (açmak için /plan)"),
    ("ne", "Elindeki bir varlık için plan: /ne ASTOR"),
    ("pozisyon", "Plan için pozisyon işareti: /pozisyon BTC acik"),
    ("sil", "Plan sil: /sil BTC"),
    ("sifirla", "Sohbet geçmişini temizle"),
    ("set_config", "Sessiz saat ayarı"),
    ("get_logs", "Son hata kayıtları"),
    ("start", "Başlat / chat id"),
]


SEND_ATTEMPTS = 6


async def _retry_send(send, *args, **kwargs):
    """Telegram send with retries when the connection itself failed (the message never left).
    BadRequest and timeouts are not retried: a timeout may have been delivered, a retry would duplicate it."""
    for attempt in range(SEND_ATTEMPTS):
        try:
            return await send(*args, **kwargs)
        except NetworkError as e:
            if attempt == SEND_ATTEMPTS - 1 or isinstance(e, (BadRequest, TimedOut)) or "ConnectError" not in str(e):
                raise
            log.warning("Telegram connection failed, retrying (%d): %s", attempt + 1, e)
            await asyncio.sleep(min(3 * 2 ** attempt, 30))  # 3, 6, 12, 24, 30 s: rides out a ~75 s outage


# True while the bot handles something the owner just did (command, message, button): those replies always
# arrive. Background jobs run outside it, so their messages follow /sessiz and /sessizlik.
USER_TURN: contextvars.ContextVar[bool] = contextvars.ContextVar("user_turn", default=False)


class HeldMessage:
    """Stands in for a message held back while quiet, so callers can still .edit_text() / .delete() it."""
    message_id = 0

    def __getattr__(self, name):
        async def noop(*args, **kwargs):
            return None
        return noop


def _held(chat_id) -> bool:
    return bool(config.ALLOWED_CHAT_ID) and chat_id == config.ALLOWED_CHAT_ID and not USER_TURN.get() and quiet.muted()


async def mark_user_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs first for every update (group -1)."""
    USER_TURN.set(bool(update.effective_chat) and update.effective_chat.id == config.ALLOWED_CHAT_ID)


class RetryBot(ExtBot):
    """Every send in the bot (also message.reply_text) goes through here."""

    async def send_message(self, *args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else None)
        if _held(chat_id):
            quiet.hold(kwargs.get("text", args[1] if len(args) > 1 else ""))
            return HeldMessage()
        return await _retry_send(super().send_message, *args, **kwargs)

    async def send_photo(self, *args, **kwargs):
        chat_id = kwargs.get("chat_id", args[0] if args else None)
        if _held(chat_id):
            quiet.hold(kwargs.get("caption") or "", "foto")
            return HeldMessage()
        return await _retry_send(super().send_photo, *args, **kwargs)

    async def edit_message_text(self, *args, **kwargs):
        return await _retry_send(super().edit_message_text, *args, **kwargs)

    async def edit_message_reply_markup(self, *args, **kwargs):
        return await _retry_send(super().edit_message_reply_markup, *args, **kwargs)

    async def delete_message(self, *args, **kwargs):
        return await _retry_send(super().delete_message, *args, **kwargs)

    async def answer_callback_query(self, *args, **kwargs):
        return await _retry_send(super().answer_callback_query, *args, **kwargs)


async def send_help(message):
    """HELP split on section breaks so no part exceeds Telegram's 4096-character limit."""
    part = ""
    for block in HELP.split("\n\n"):
        if len(part) + len(block) + 2 > 3800:
            await message.reply_text(part)
            part = ""
        part = f"{part}\n\n{block}" if part else block
    if part:
        await message.reply_text(part)


def authorized(handler):
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not config.ALLOWED_CHAT_ID or update.effective_chat.id != config.ALLOWED_CHAT_ID:
            log.warning("Refused chat %s", update.effective_chat.id)
            return
        return await handler(update, context)
    return wrapper


def silent() -> bool:
    """Inside a quiet window replies to the owner's own commands still arrive, but without sound."""
    return quiet.muted()


async def send_long(bot, chat_id: int, text: str, reply_markup=None):
    """Split at Telegram's limit; returns the last message (the one with the buttons)."""
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)] or [""]
    last = None
    for i, chunk in enumerate(chunks):
        last = await bot.send_message(chat_id, chunk, reply_markup=reply_markup if i == len(chunks) - 1 else None,
                                      disable_notification=silent())
    return last


def plan_alarm_buttons(reply: str, plan_coins: list[str]):
    """Under a normal analysis: one button per coin whose plan this reply set."""
    if not plan_coins:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"⏰ {c} planıyla alarm kur", callback_data=f"plan|{c}")]
                                 for c in plan_coins[:5]])


async def build_market_data(coins: list[str]) -> tuple[dict, list[str]]:
    coins = ["BTC"] + [c for c in dict.fromkeys(coins) if c != "BTC"]
    data, missing = {}, []
    async with httpx.AsyncClient() as client:
        for coin in coins:
            try:
                data[coin] = await market.snapshot(client, coin)
            except market.SymbolNotFound:
                missing.append(coin)
    try:
        data["DUYGU"] = await sentiment.summary()
    except Exception as e:
        data["DUYGU"] = {"hata": str(e)[:80]}
    btc15 = (data.get("BTC") or {}).get("zaman_dilimleri", {}).get("15m") or {}
    if btc15.get("kapanis") is not None and btc15.get("sma50") is not None:
        # The gate's own definition, so the model never reads an old note as the current gate state.
        data["BTC_KAPI"] = {"durum": "AÇIK" if btc15["kapanis"] > btc15["sma50"] else "KAPALI",
                            "kural": "BTC son 15m kapanış > 15m SMA50", "kapanis": btc15["kapanis"], "sma50": btc15["sma50"]}
    return data, missing


async def run_analysis(bot, chat_id: int | None, user_text: str, coins: list[str],
                       data: dict | None = None, footer: str = "", buttons=plan_alarm_buttons,
                       allow_state_update: bool = True, personal: bool = True, keys: dict | None = None,
                       on_sent=None) -> str | None:
    """DeepSeek analysis. Pass `data` to send prepared market data instead of coin snapshots.

    `buttons(reply, plan_coins)` returns the inline keyboard for the reply, or None.
    """
    async with analysis_lock:
        # chat_id None: the answer only goes to the panel (a site user without a Telegram link)
        status = await bot.send_message(chat_id, "⏳ veri çekiliyor, analiz ediliyor...", disable_notification=True) if chat_id else None
        try:
            if data is None:
                data, missing = await build_market_data(coins)
                if missing:
                    user_text += f"\n(Not: {', '.join(missing)} için Binance'te {config.QUOTE} paritesi bulunamadı.)"
            reply, warnings, plan_coins = await llm.analyze(user_text, data,
                                                            allow_state_update=allow_state_update, personal=personal,
                                                            keys=keys)
        except Exception as e:
            log.exception("Analysis failed")
            if status:
                await status.edit_text(f"❌ Hata: {e}")
            return None
        if status:
            await status.delete()
        if chat_id:
            msg = await send_long(bot, chat_id, "\n\n".join([reply, *warnings, *([footer] if footer else [])]),
                                  reply_markup=buttons(reply, plan_coins) if buttons else None)
            if on_sent and msg is not None:
                on_sent(msg)
        return reply


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not config.ALLOWED_CHAT_ID:
        await update.message.reply_text(
            f"Chat id: {chat_id}\n.env dosyasına ALLOWED_CHAT_ID={chat_id} yaz ve botu yeniden başlat.")
        return
    if chat_id != config.ALLOWED_CHAT_ID:
        if web_sync.enabled():  # a site user: the only thing this chat can do is link their account
            await update.message.reply_text("Kapanış'a hoş geldin. Hesabını bağlamak için sitede Hesap → "
                                            "Telegram'ı bağla'ya bas, çıkan kodu buraya yaz: /bagla KP-XXXXXXXX")
        return
    await update.message.reply_text("Hazırım knk.\n\n" + HELP)


_link_tries: dict[int, list[float]] = {}
_chat_hits: dict[str, list[float]] = {}


def chat_rate_ok(chat_id: int, bucket: str, limit: int, window: float) -> bool:
    """Per-chat budget for commands any Telegram user can send (the owner's chat is never limited)."""
    if chat_id == config.ALLOWED_CHAT_ID:
        return True
    key, now = f"{bucket}:{chat_id}", time.time()
    hits = [t for t in _chat_hits.get(key, []) if now - t < window]
    if len(hits) >= limit:
        _chat_hits[key] = hits
        return False
    _chat_hits[key] = hits + [now]
    if len(_chat_hits) > 20000:
        for k in [k for k, v in _chat_hits.items() if not v or now - v[-1] > 3600][:5000]:
            _chat_hits.pop(k, None)
    return True


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "***@" + domain) if domain else ""


async def bagla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bagla KP-XXXXXXXX: open to any chat (not @authorized). Binds this chat to a site account so that
    account's panel analyses also arrive here. Gives this chat no access to the owner's bot."""
    chat_id = update.effective_chat.id
    if not web_sync.enabled():
        return
    now = time.time()
    tries = [t for t in _link_tries.get(chat_id, []) if now - t < 3600]
    if len(tries) >= 5:
        await update.message.reply_text("Çok fazla deneme. Bir saat sonra tekrar dene.")
        return
    _link_tries[chat_id] = tries + [now]
    if len(context.args) != 1:
        await update.message.reply_text("Kullanım: /bagla KP-XXXXXXXX (kodu sitede Hesap → Telegram'ı bağla'dan al)")
        return
    try:
        ok, info = await web_sync.link_telegram(context.args[0].strip(), chat_id, update.effective_user.username if update.effective_user else None)
    except Exception as e:
        log.warning("Telegram link failed: %s", e)
        await update.message.reply_text("Şu an bağlanamadı, biraz sonra tekrar dene.")
        return
    if ok:
        _link_tries.pop(chat_id, None)
        web_sync._linked_cache.pop(chat_id, None)
        await update.message.reply_text(f"✅ Bağlandı: {_mask_email(info)}\nSiteden istediğin analizler buraya da gelecek. "
                                        "Bağlantıyı kaldırmak için sitede Hesap → Bağlantıyı kaldır.")
    else:
        await update.message.reply_text(f"❌ {info}")


async def web_ekle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ekle THYAO 10 300: add to the linked site's portfolio, never place an order."""
    if update.effective_chat.type != "private" or not web_sync.enabled():
        return
    if not chat_rate_ok(update.effective_chat.id, "public", 30, 600):
        await update.message.reply_text("Çok sık mesaj gönderdin; birkaç dakika sonra tekrar dene.")
        return
    args = context.args or []
    if len(args) == 3 and args[2].upper() == "TL":
        code, price = args[0].upper(), args[1].replace(",", ".")
        try:
            if not re.fullmatch(r"[A-Z0-9.]{2,12}", code) or float(price) <= 0:
                raise ValueError()
            context.user_data["site_ekle"] = (code, float(price))
            await update.message.reply_text(f"{code} için alış fiyatı {price} TL. Kaç adet aldın? Yalnız sayıyı yaz.")
        except ValueError:
            await update.message.reply_text("Kullanım: /ekle THYAO 10 300 (kod, adet, alış fiyatı)")
        return
    if len(args) != 3:
        await update.message.reply_text("Kullanım: /ekle THYAO 10 300 (kod, adet, alış fiyatı). /ekle THYAO 300 TL yazarsan adedi sorarım.")
        return
    code = args[0].upper()
    try:
        qty, price = float(args[1].replace(",", ".")), float(args[2].replace(",", "."))
        if not re.fullmatch(r"[A-Z0-9.]{2,12}", code) or qty <= 0 or price <= 0:
            raise ValueError()
        row = await web_sync.telegram_add_position(update.effective_chat.id, code, qty, price)
        account = f" (hesap: {row['hesap']})" if row.get("hesap") else ""
        await update.message.reply_text(f"✅ {row['kod']} {row['adet']:g} adet × {row['maliyet']:g} TL portföyüne eklendi{account}.\n"
                                        f"📊 {config.PUBLIC_URL}/app/portfoyum\nGerçek borsa emri gönderilmedi.")
    except ValueError as e:
        await update.message.reply_text(f"❌ {e or 'Kod, adet ve fiyatı kontrol et.'}")
    except Exception:
        log.exception("Telegram portfolio add failed")
        await update.message.reply_text("Şu an portföye eklenemedi; biraz sonra tekrar dene.")


async def site_or_owner_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not chat_rate_ok(update.effective_chat.id, "public", 30, 600):
        return  # silent: answering every message of a flood is the flood's goal
    pending = context.user_data.get("site_ekle")
    if pending:
        try:
            qty = float(update.message.text.strip().replace(",", "."))
            if qty <= 0:
                raise ValueError()
            code, price = pending
            row = await web_sync.telegram_add_position(update.effective_chat.id, code, qty, price)
            context.user_data.pop("site_ekle", None)
            account = f" (hesap: {row['hesap']})" if row.get("hesap") else ""
            await update.message.reply_text(f"✅ {row['kod']} {row['adet']:g} adet portföyüne eklendi{account}. "
                                            f"{config.PUBLIC_URL}/app/portfoyum")
        except ValueError as e:
            await update.message.reply_text(f"❌ {e or 'Kaç adet aldığını sayı olarak yaz.'}")
        except Exception:
            log.exception("Telegram portfolio add failed")
            await update.message.reply_text("Şu an eklenemedi; biraz sonra tekrar dene.")
        return
    n = voice_quant.top_n(update.message.text)
    if n is not None and update.effective_chat.type == "private" and web_sync.enabled():
        return await quant_confirm_prompt(update.message, context, update.message.text, n)
    if update.effective_chat.id == config.ALLOWED_CHAT_ID:
        return await text_message(update, context)
    await update.message.reply_text("Hesabını /bagla ile bağlayıp /ekle KOD ADET FİYAT yazabilirsin. "
                                    "Analiz için web panelinde Grafik → Analiz et bölümünü kullan.")


async def quant_confirm_prompt(message, context, heard: str, n: int):
    context.user_data["quant_pending"] = {"n": n, "at": time.time()}
    await message.reply_text(
        f"Şunu anladım: “{heard[:400]}”\nBIST 100 içinden kalite + 3 aylık göreli momentumla ilk {n} hisseyi tara. "
        "Doğruysa onayla; analiz biraz sürebilir. Gerçek emir verilmez.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Taramayı başlat", callback_data="quant|confirm"),
            InlineKeyboardButton("Vazgeç", callback_data="quant|cancel")]]))


async def quant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not web_sync.enabled():
        return
    if not chat_rate_ok(update.effective_chat.id, "public", 30, 600):
        await update.message.reply_text("Çok sık mesaj gönderdin; birkaç dakika sonra tekrar dene.")
        return
    raw = " ".join(context.args or [])
    n = voice_quant.top_n(raw)
    if n is None:
        await update.message.reply_text("Örnek: /quant BIST 100 kalite ve momentum en yüksek 3 hisse")
        return
    await quant_confirm_prompt(update.message, context, raw, n)


async def quant_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop("quant_pending", None)
    await query.edit_message_reply_markup(None)
    if query.data == "quant|cancel":
        await query.message.reply_text("Tarama başlatılmadı.")
        return
    if not pending or time.time() - pending["at"] > 300:
        await query.message.reply_text("Onay süresi doldu; sorguyu tekrar gönder.")
        return
    try:
        await web_sync.telegram_quant_run(update.effective_chat.id, pending["n"])
        await query.message.reply_text("🔎 BIST 100 taraması sıraya alındı. Sonuç Telegram'a ve Son Analizlerim'e gelecek.")
    except ValueError as e:
        await query.message.reply_text(f"❌ {e}")
    except Exception:
        log.exception("Quant scan request failed")
        await query.message.reply_text("Tarama şu an başlatılamadı; biraz sonra tekrar dene.")


@authorized
async def komutlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_help(update.message)


@authorized
async def analiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /analiz COIN (örn. /analiz AAVE)")
        return
    coins = [a.upper().removesuffix("/USDT") for a in context.args]
    stocks = [c for c in coins if c.endswith(".IS") or c in bist.watchlist()]
    if stocks:
        await update.message.reply_text(f"ℹ️ {', '.join(bist.ticker(x) for x in stocks)} BIST hissesi; "
                                        f"BIST için komut /incele {bist.ticker(stocks[0])}. Oradan analiz ediyorum.")
        await incele_ticker(update, context, bist.ticker(stocks[0]))
        coins = [c for c in coins if c not in stocks]
        if not coins:
            return
    await run_analysis(context.bot, update.effective_chat.id, f"{' '.join(coins)} analiz et.", coins)


async def incele_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE, tick: str):
    """BIST stock analysis: the BIST twin of /analiz."""
    async with httpx.AsyncClient() as client:
        try:
            data = await bist_market_data(client, tick)
        except market.SymbolNotFound:
            await update.message.reply_text(f"❌ {tick} BIST'te bulunamadı (Yahoo: {bist.yahoo_symbol(tick)}).")
            return
    await run_analysis(context.bot, update.effective_chat.id, f"[BIST] {tick} analiz et.", [], data=data,
                       buttons=None, footer="BIST planı kaydedildiyse 1 saatlik kapanışlarla otomatik izlenir. "
                                            "Fiyat Yahoo'dan, ~15 dk gecikmeli.")


@authorized
async def incele(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /incele THYAO (BIST hissesi). Kripto için: /analiz BTC")
        return
    tick = bist.ticker(context.args[0])
    if not re.fullmatch(r"[A-Z0-9]{3,6}", tick):
        await update.message.reply_text("Hisse kodu harf/rakam olmalı (ör. THYAO).")
        return
    if tick in config.WATCHLIST:
        await update.message.reply_text(f"ℹ️ {tick} bir kripto; kripto için /analiz {tick}. Oradan analiz ediyorum.")
        await run_analysis(context.bot, update.effective_chat.id, f"{tick} analiz et.", [tick])
        return
    await incele_ticker(update, context, tick)


PLAN_FOLLOW_JOB = "plan_takip"
PLAN_FOLLOW_MINUTES = (5, 240)  # allowed range for /plan 45dk


def plan_follow_minutes() -> int:
    return int(alerts_store.load_settings().get("plan_aralik_dk") or 15)


def _pct(a: float, b: float) -> str:
    return f"{(a / b - 1) * 100:+.2f}%"


def plan_list() -> list[str]:
    """Assets the user picked for /plan: "BTC" for crypto, "THYAO.IS" for BIST. Empty = show every plan."""
    return alerts_store.load_settings().get("plan_listesi") or []


def save_plan_list(keys: list[str]):
    s = alerts_store.load_settings()
    s["plan_listesi"] = list(dict.fromkeys(keys))
    alerts_store.save_settings(s)


def plan_key_name(key: str) -> str:
    return bist.ticker(key) if bist_signals.is_bist_plan(key) else us.ticker(key) if key.endswith(".US") else key


async def plan_key(code: str) -> str | None:
    """User text -> plan key. BIST if it's a BIST name (or ends with .IS), else a Binance coin."""
    t = code.strip().upper().removesuffix("/USDT").removesuffix("USDT")
    if not re.fullmatch(r"[A-Z0-9\-]{1,10}(\.IS|\.US)?", t):
        return None
    if t.endswith(".IS") or t in bist.watchlist():
        return bist.yahoo_symbol(t)
    mkt = await _detect_market(t)
    if mkt == assets.MARKET:
        return None
    return None if mkt is None else bist.yahoo_symbol(t) if mkt == "BIST" else us.key(t) if mkt == "ABD" else t


def plan_view(show_all: bool = False) -> tuple[list[str], list[str]]:
    """(keys to show, saved plans hidden by the user's list)."""
    state = store.load_state()
    chosen = [] if show_all else plan_list()
    if not chosen:
        return list(state["planlar"]), []
    return chosen, [k for k in state["planlar"] if k not in chosen]


async def _no_plan_lines(client, key: str) -> str:
    """An asset on the list without a saved plan: price and the nearest zones, from code."""
    is_bist = bist_signals.is_bist_plan(key)
    is_us = key.endswith(".US")
    symbol = key if is_bist or is_us else key + config.QUOTE
    try:
        if is_bist:
            q = await bist.day_quote(client, symbol)
        elif is_us:
            q = await us.day_quote(client, symbol)
        else:
            q = await market.ticker_24h(client, symbol)
        stop, target, why = await _suggest_levels({"piyasa": "BIST" if is_bist else "ABD" if is_us else "KRIPTO", "symbol": symbol})
    except Exception as e:
        return f"\n{'🇹🇷 ' if is_bist else ''}{plan_key_name(key)}: veri alınamadı ({str(e)[:60]})"
    price, prev = q["fiyat"], q.get("onceki_kapanis")
    day = f" ({'bugün' if is_bist else '24s'} {(price / prev - 1) * 100:+.2f}%)" if prev else ""
    cmd = f"/incele {plan_key_name(key)}" if is_bist else f"/abd {plan_key_name(key)}" if is_us else f"/analiz {key}"
    return (f"\n{'🇹🇷 ' if is_bist else ''}{plan_key_name(key)}: {_g(price)}{day}\n"
            f"  plan yok · destek altı {_g(stop)} ({_pct(stop, price)}) · direnç {_g(target)} ({_pct(target, price)})\n"
            f"  Tetik/teyit/iptal için: {cmd} ya da aşağıdaki butona bas")


async def plan_status_text(show_all: bool = False) -> str | None:
    """Live status of the user's chosen assets (or every saved plan), computed in code. None if empty."""
    state = store.load_state()
    keys, hidden = plan_view(show_all)
    if not keys:
        return None
    lines = [f"🎯 PLAN DURUMU — {alerts_store.now_tr().strftime('%H:%M')}"]
    async with httpx.AsyncClient() as client:
        for coin in keys:
            p = state["planlar"].get(coin)
            if p is None:
                lines.append(await _no_plan_lines(client, coin))
                continue
            tetik, teyit, iptal, hedef = (p.get(k) for k in ("tetik", "teyit", "iptal", "hedef"))
            try:
                if bist_signals.is_bist_plan(coin):
                    df = await bist.fetch(client, coin, "1h")
                    price = await bist.last_price(client, coin)
                elif coin.endswith(".US"):
                    df = await us.fetch(client, coin, "1d")
                    price = await us.last_price(client, coin)
                else:
                    df = await market.fetch_klines(client, coin + config.QUOTE, "15m", limit=3)
                    price = await market.last_price(client, coin + config.QUOTE)
            except Exception as e:
                lines.append(f"\n{coin}: veri alınamadı ({e})")
                continue
            close = float(df.close.iloc[-1])
            if p.get("pozisyon"):
                status = "💼 POZİSYON AÇIK — stop/hedef izleniyor"
            elif p.get("sinyal_verildi"):
                status = "🟢 ŞİMDİ AL verildi — alım yaptıysan Aldım'a bas, yapmadıysan kovalama"
            elif p.get("bekleyen_teyit"):
                status = f"⏳ TETİK kapandı, teyit mumu bekleniyor (teyit {_g(teyit)} altında kapanmamalı)"
            elif iptal is not None and close < iptal:
                status = "❌ İPTAL altında kapanış — plan bozuk, yeni plan için /analiz"
            elif hedef is not None and close >= hedef:
                status = "🎯 HEDEF üstünde — tetiksiz koşu, kovalama yok"
            elif tetik is not None and close > tetik:
                status = "📈 Tetik üstünde (teyitsiz) — kovalama yok, geri çekilmeyi bekle"
            elif tetik is not None:
                status = f"👀 BEKLE — tetiğe {_pct(tetik, price)} kaldı"
            else:
                status = "BEKLE"
            # Close-only rule: a live price through the stop is a warning, not yet a broken plan.
            if iptal is not None and price < iptal <= close and not p.get("pozisyon"):
                tf = "1s" if bist_signals.is_bist_plan(coin) else "15m"
                status += f"\n  ⚠️ Canlı fiyat iptalin ({_g(iptal)}) altında; {tf} mum böyle kapanırsa plan bozulur"
            elif iptal is not None and price < iptal <= close and p.get("pozisyon"):
                tf = "1s" if bist_signals.is_bist_plan(coin) else "15m"
                status += f"\n  ⚠️ Canlı fiyat stopun ({_g(iptal)}) altında; {tf} kapanış altında olursa kural: sat"
            lines.append(
                f"\n{'🤖 ' if p.get('otomatik') else ''}{'🇹🇷 ' if bist_signals.is_bist_plan(coin) else '🇺🇸 ' if coin.endswith('.US') else ''}"
                f"{plan_key_name(coin)}: {_g(price)} "
                f"(son {'1s' if bist_signals.is_bist_plan(coin) else 'günlük' if coin.endswith('.US') else '15m'} kapanış {_g(close)})\n"
                f"  tetik {_g(tetik)}" + (f" ({_pct(tetik, price)})" if tetik else "") +
                f" | iptal {_g(iptal)}" + (f" ({_pct(iptal, price)})" if iptal else "") +
                f" | hedef {_g(hedef)}" + (f" ({_pct(hedef, price)})" if hedef else "") +
                f"\n  {status}")
        try:
            btc = market.add_indicators(await market.fetch_klines(client, "BTC" + config.QUOTE, "15m"))
            b = btc.iloc[-1]
            gate = "AÇIK" if b.close > b.sma50 else "KAPALI"
            lines.append(f"\nBTC kapı: {gate} (15m kapanış {_g(float(b.close))}, SMA50 {_g(float(b.sma50))})")
        except Exception:
            pass
    if hidden:
        lines.append(f"\n(+{len(hidden)} plan listende değil: {', '.join(plan_key_name(k) for k in hidden[:6])} — "
                     "görmek için /plan hepsi)")
    return "\n".join(lines)


def plan_buttons() -> InlineKeyboardMarkup | None:
    """One "set up a plan" button per listed asset that has no saved plan (DeepSeek analysis)."""
    state = store.load_state()
    missing = [k for k in plan_view()[0] if k not in state["planlar"]]
    if not missing:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"🎯 {plan_key_name(k)} için plan kur", callback_data=f"plkur|{k}")]
                                 for k in missing[:6]])


async def plan_add(update, context, codes: list[str]):
    added, bad = [], []
    for c in codes:
        key = await plan_key(c)
        (added if key else bad).append(key or c.upper())
    if added:
        save_plan_list(plan_list() + added)
    msg = []
    if added:
        msg.append("✅ Plan listesine eklendi: " + ", ".join(plan_key_name(k) for k in added))
    if bad:
        msg.append("❌ Bulunamadı (ne Binance ne BIST): " + ", ".join(bad))
    msg.append("Listen: " + (", ".join(plan_key_name(k) for k in plan_list()) or "boş"))
    await update.message.reply_text("\n".join(msg) + "\nDurum için: /plan")


async def plan_follow_job(context: ContextTypes.DEFAULT_TYPE):
    text = await plan_status_text()
    if text is None:
        context.job.schedule_removal()
        await context.bot.send_message(config.ALLOWED_CHAT_ID, "Gösterilecek plan kalmadı, plan takibi durdu.",
                                       disable_notification=silent())
        return
    await context.bot.send_message(config.ALLOWED_CHAT_ID, text + "\n\nDurdurmak için: /plan dur",
                                   disable_notification=silent())


def start_plan_follow(app: Application):
    for job in app.job_queue.get_jobs_by_name(PLAN_FOLLOW_JOB):
        job.schedule_removal()
    seconds = plan_follow_minutes() * 60
    app.job_queue.run_repeating(plan_follow_job, interval=seconds, first=seconds, name=PLAN_FOLLOW_JOB)


@authorized
async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unmuted = ""
    if quiet.is_muted_all():  # /plan is also how the user turns /sessiz off
        quiet.set_muted_all(False)
        unmuted = "🔔 Sessiz mod kapandı, bildirimler yeniden geliyor.\n\n"
        await send_held(context.bot)
    s = alerts_store.load_settings()
    m = re.fullmatch(r"(?:aral[ıi]k\s*)?(\d{1,3})\s*(?:dk|dakika|m|min)?", " ".join(context.args).lower()) if context.args else None
    if m:
        minutes = int(m[1])
        lo, hi = PLAN_FOLLOW_MINUTES
        if not lo <= minutes <= hi:
            await update.message.reply_text(f"Aralık {lo}-{hi} dakika arasında olmalı. Örnek: /plan 45dk")
            return
        s["plan_aralik_dk"] = minutes
        s["plan_takip"] = True
        alerts_store.save_settings(s)
        start_plan_follow(context.application)
        await update.message.reply_text(f"{unmuted}🔁 Plan güncellemesi artık {minutes} dk'da bir gelecek. Durdurmak için: /plan dur")
        return
    if context.args and context.args[0].lower() in ("dur", "kapat", "durdur", "stop"):
        for job in context.application.job_queue.get_jobs_by_name(PLAN_FOLLOW_JOB):
            job.schedule_removal()
        s["plan_takip"] = False
        alerts_store.save_settings(s)
        await update.message.reply_text(f"{unmuted}⏹ Plan takibi durdu. Tetik/teyit/ŞİMDİ AL uyarıları yine gelir.")
        return
    sub = context.args[0].lower() if context.args else ""
    if sub == "ekle":
        if len(context.args) > 1:
            await plan_add(update, context, context.args[1:])
        else:
            context.user_data["bekleyen"] = "plan_ekle"
            await update.message.reply_text("Hangi coin/hisseler? Boşlukla yaz (adet gerekmez), ör: BTC ETH THYAO ASELS")
        return
    if sub in ("cikar", "çıkar", "sil"):
        drop = {bist.ticker(a.upper()) for a in context.args[1:]} | {a.upper() for a in context.args[1:]}
        left = [k for k in plan_list() if k not in drop and plan_key_name(k) not in drop]
        save_plan_list(left)
        await update.message.reply_text("🗑 Çıkarıldı. Listen: " + (", ".join(plan_key_name(k) for k in left)
                                                                  or "boş (tüm kayıtlı planlar gösterilir)"))
        return
    if sub == "temizle":
        save_plan_list([])
        await update.message.reply_text("Plan listesi temizlendi: /plan artık tüm kayıtlı planları gösterir.")
        return
    if sub == "liste":
        await update.message.reply_text("Plan listen: " + (", ".join(plan_key_name(k) for k in plan_list())
                                                           or "boş (tüm kayıtlı planlar gösteriliyor)")
                                        + "\nEkle: /plan ekle BTC THYAO · Çıkar: /plan cikar BTC")
        return
    text = await plan_status_text(show_all=sub == "hepsi")
    if text is None:
        await update.message.reply_text("Plan listen boş ve kayıtlı plan yok.\n"
                                        "İzlemek istediklerini ekle (adet gerekmez): /plan ekle BTC ETH THYAO")
        return
    state = store.load_state()
    shown = set(plan_view(show_all=sub == "hepsi")[0])
    notes = [f"{plan_key_name(c)}: {p['not']}" for c, p in state["planlar"].items() if p.get("not") and c in shown]
    if notes:
        text += "\n\n📝 " + "\n📝 ".join(notes)
    if state.get("btc_not"):
        text += f"\n🧭 BTC kapı notu: {state['btc_not']}"
    start_plan_follow(context.application)
    s["plan_takip"] = True
    alerts_store.save_settings(s)
    minutes = plan_follow_minutes()
    next_at = (alerts_store.now_tr() + timedelta(minutes=minutes)).strftime("%H:%M")
    await send_long(context.bot, update.effective_chat.id,
                    unmuted + text + f"\n\n🔁 Takip açık: {minutes} dk'da bir güncelleme (sıradaki {next_at}). "
                    "Aralığı değiştir: /plan 45dk · durdur: /plan dur\n"
                    "Liste: /plan ekle BTC THYAO · /plan cikar BTC · /plan hepsi",
                    reply_markup=plan_buttons())


@authorized
async def pozisyon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2 or context.args[1].lower() not in ("acik", "açık", "kapali", "kapalı"):
        await update.message.reply_text("Kullanım: /pozisyon COIN acik|kapali")
        return
    coin, is_open = context.args[0].upper(), context.args[1].lower() in ("acik", "açık")
    state = store.load_state()
    if coin not in state["planlar"]:
        await update.message.reply_text(f"{coin} için kayıtlı plan yok. Önce /analiz {coin}.")
        return
    state["planlar"][coin]["pozisyon"] = is_open
    store.save_state(state)
    await update.message.reply_text(f"{coin}: pozisyon {'açık' if is_open else 'kapalı'} olarak işaretlendi.")


@authorized
async def sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /sil COIN")
        return
    coin = context.args[0].upper()
    state = store.load_state()
    if state["planlar"].pop(coin, None) is None:
        await update.message.reply_text(f"{coin} için plan yok.")
        return
    store.save_state(state)
    await update.message.reply_text(f"{coin} planı silindi.")


@authorized
async def sifirla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store.clear_history()
    await update.message.reply_text("Konuşma geçmişi temizlendi. Planlar duruyor (/plan).")


@authorized
async def makro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await update.message.reply_text("⏳ makro veri çekiliyor...")
    m = await macro.summary(force="yenile" in context.args)
    await status.delete()
    await send_long(context.bot, update.effective_chat.id, macro.dashboard(m))


@authorized
async def takvim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tr = "\n".join(f"{datetime.fromisoformat(e['tr_zaman']).strftime('%a %d.%m %H:%M')} TR  {e['olay']} (BIST)"
                   for e in bist.tr_events(14)) or "yok"
    await update.message.reply_text("🇺🇸 ABD (kripto kapısı)\n" + macro.calendar_text(await macro.calendar())
                                    + "\n\n🇹🇷 Türkiye (BIST kapısı)\n" + tr)


@authorized
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.strip().lower() in ("komutlar", "komut", "yardım", "yardim"):
        await send_help(update.message)
        return
    if (await journal_text(update, context, text) or await wizard_text(update, context, text)
            or await sell_text(update, context, text)):
        return
    pending = context.user_data.get("bekleyen")
    if pending == "plan_ekle":
        context.user_data.pop("bekleyen", None)
        codes = [c for c in re.findall(r"[A-Za-z0-9.]{2,12}", text) if c.upper() not in FILLER_WORDS]
        if codes:
            await plan_add(update, context, codes)
            return
    if pending == "ekle" and await add_holdings(update, context, text):
        return
    if pending and pending.startswith("sat|"):
        _, mkt, sym = pending.split("|", 2)
        if await sell_holding(update, context, mkt, sym, text):
            return
    if re.search(r"bildirim\w*\s+(atma|gönderme|gonderme|yollama|gelmesin|istemiyorum)|sessizlik", text.lower()) \
            and await add_quiet_window(update, text):
        return
    if re.search(r"ne yap|sat(ay)?[ıi]m m[ıi]|tutay[ıi]m m[ıi]|kâr m[ıi] alay|kar m[ıi] alay|ne öneri", text.lower()):
        held_code = next((w for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]{2,10}", text) if advisor.holdings(w)), None)
        if held_code:
            await advice_reply(context.bot, update.effective_chat.id, held_code, text)
            return
    if wants_opportunities(text):
        await opportunity_report(update, context)
        return
    if re.search(r"takip list", text.lower()):
        await update.message.reply_text(takip_prompt_text(), reply_markup=takip_menu())
        return
    if ("portföy" in text.lower() or "portfoy" in text.lower() or "bakiye" in text.lower()) and \
            any(w in text.lower() for w in ALARM_TRIGGERS) and await add_portfolio_alarm(update, text):
        return
    if await natural_alarm(update, context, text):
        return
    if looks_like_holdings(text) and not any(w in text.lower() for w in ALARM_TRIGGERS):
        if await natural_holdings(update, context, text):
            return
    if await amount_intent(update, context, text):
        return
    low = text.strip().lower()
    if (low.startswith(("ekle ", "aldım ", "aldim ", "portföye ekle", "portfoye ekle"))
            and await add_holdings(update, context, re.sub(r"^\S+\s+(ekle\s+)?", "", text.strip()))):
        return
    if text.strip().lower() in ("portföy", "portfoy", "portföyüm", "portfoyum"):
        await portfolio_summary(update, context)
        return
    if text.strip().lower() in ("bakiye", "bakiyem", "bakiyem ne", "bakiyem ne kadar", "kâr zarar", "kar zarar"):
        await balance_report(update, context)
        return
    if text.strip().lower() in ("okul", "okul modu", "okuldayım", "okuldayim"):
        await update.message.reply_text(OKUL_MOVED)
        return
    words = {w.upper() for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2,6}", text)}
    coins = [c for c in config.WATCHLIST if c in words]
    held = {bist.ticker(p["symbol"]) for p in positions.open_positions() if p.get("piyasa") == "BIST"}
    stocks = [t for t in dict.fromkeys([*bist.watchlist(), *held,
                                        *(bist.ticker(k) for k in store.load_state()["planlar"] if k.endswith(".IS"))])
              if t in words]
    if stocks and not coins:
        tick = stocks[0]
        async with httpx.AsyncClient() as client:
            data = await bist_market_data(client, tick)
        await run_analysis(context.bot, update.effective_chat.id, f"[BIST] {text}", [], data=data)
        return
    await run_analysis(context.bot, update.effective_chat.id, text, coins)


@authorized
async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A brokerage/exchange screenshot: Kimi K3 reads the holdings, the user confirms before anything is saved."""
    msg = update.message
    if msg.photo:
        tg_file, mime = await msg.photo[-1].get_file(), "image/jpeg"
    else:
        tg_file, mime = await msg.document.get_file(), msg.document.mime_type or "image/png"
    status = await msg.reply_text("⏳ Ekran görüntüsü okunuyor (Kimi K3)...")
    try:
        found = await llm.read_holdings(bytes(await tg_file.download_as_bytearray()), mime)
    except Exception as e:
        await status.edit_text(f"❌ Görsel okunamadı: {str(e)[:150]}")
        return
    rows = await validate_holdings(found.get("varliklar") or [])
    if not rows:
        await status.edit_text("Görselde portföy satırı bulamadım. Aracı kurumun 'Portföyüm' ekranının görüntüsünü at "
                               "(kod, adet ve maliyet görünsün)." + (f"\nNot: {found.get('not')}" if found.get("not") else ""))
        return
    await show_holdings_confirm(status.edit_text, context, rows, f"📸 Ekranda {len(rows)} varlık okudum (Kimi K3):")


async def validate_holdings(items: list[dict]) -> list[dict]:
    """AI-extracted rows -> checked rows: real ticker (Yahoo/Binance), positive quantity, market decided in code."""
    rows = []
    held = {bist.ticker(p["symbol"]) if p.get("piyasa") == "BIST" else
            p["symbol"] if assets.is_other(p) else p["pair"].split("/")[0] for p in positions.open_positions()}
    for v in items:
        code = str(v.get("kod") or "").upper().replace("/USDT", "").removesuffix("USDT").removesuffix(".IS").strip()
        num = lambda x: float(str(x).replace(",", ".")) if x not in (None, "") else None
        try:
            qty, cost, amount = num(v.get("adet")), num(v.get("maliyet")), num(v.get("tutar"))
        except ValueError:
            continue
        if qty is None and amount and cost:
            qty = amount / cost
        hint = str(v.get("piyasa") or "").upper()
        other = assets.normalize(code)
        if other and (hint in ("ALTIN_DOVIZ", "DIGER") or code in ("GRAM_ALTIN", "USD", "EUR")):
            code, mkt = other, assets.MARKET
        elif re.fullmatch(r"[A-Z0-9]{2,10}", code):
            mkt = ("BIST" if hint == "BIST" and (code in universe.bist_names() or await _detect_market(code) == "BIST")
                   else "ABD" if hint in ("ABD", "US", "USA") else
                   "BIST" if code in bist.watchlist() or code in universe.bist_names() else await _detect_market(code))
        else:
            continue
        if mkt not in ("BIST", "KRIPTO", "ABD", assets.MARKET) or not qty or qty <= 0:
            continue
        if mkt == "BIST":
            qty = float(int(qty))
            if qty < 1:
                continue
        rows.append({"kod": code, "adet": qty, "maliyet": cost, "piyasa": mkt, "var": code in held})
    return rows


async def show_holdings_confirm(send, context, rows: list[dict], title: str):
    context.user_data["ekran"] = rows
    lines = [title]
    for r in rows:
        unit = assets.ASSETS[r["kod"]]["birim"] if r["piyasa"] == assets.MARKET else "adet"
        name = assets.name(r["kod"]) if r["piyasa"] == assets.MARKET else r["kod"]
        cost = f"alış {r['maliyet']:g}" if r["maliyet"] else "alış fiyatı yok → şu anki fiyat"
        lines.append(f"{_icon(r['piyasa'])} {name} — {r['adet']:g} {unit} · {cost}"
                     + (" · ⚠️ portföyde zaten var" if r["var"] else ""))
    lines.append("\nDoğru mu? Yanlış olan varsa ekledikten sonra /duzelt ID ile düzeltebilirsin.")
    new = [r for r in rows if not r["var"]]
    kb = []
    if new and len(new) < len(rows):
        kb.append([InlineKeyboardButton(f"✅ Sadece yenileri ekle ({len(new)})", callback_data="ekr|yeni")])
    kb.append([InlineKeyboardButton(f"✅ Ekle ({len(rows)})", callback_data="ekr|hepsi")])
    kb.append([InlineKeyboardButton("❌ Vazgeç", callback_data="ekr|iptal")])
    await send("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))


HOLDING_WORDS = ("tane", "adet", "lot", "almıştım", "almistim", "aldım", "aldim", "maliyet", "iken", "elimde",
                 "portföy", "portfoy", "gram", "var ", " var")


def looks_like_holdings(text: str) -> bool:
    """"astordan 4 tane var 260 tl iken almıştım": a quantity word and at least two numbers (qty + price)."""
    low = text.lower()
    return len(re.findall(r"\d+(?:[.,]\d+)?", low)) >= 2 and any(w in low for w in HOLDING_WORDS)


async def natural_holdings(update, context, text: str) -> bool:
    """Free-text portfolio entry. The AI only extracts; tickers are checked in code; nothing is saved without a tap."""
    status = await update.message.reply_text("⏳ yazdıklarını portföy satırlarına çeviriyorum...")
    try:
        found = await llm.parse_holdings_text(text, universe.bist_names())
    except Exception as e:
        await status.edit_text(f"❌ Anlayamadım ({str(e)[:100]}). Örnek: astor 4 adet 260 tl, europower 5 adet 70 tl")
        return True
    rows = await validate_holdings(found.get("varliklar") or [])
    if not rows:
        await status.edit_text("Bir varlık çıkaramadım. Şöyle yaz: \"astor 4 adet 260 tl, europower 5 adet 70 tl\" "
                               "ya da /portfoy → ➕ Ekle.")
        return True
    await show_holdings_confirm(status.edit_text, context, rows, f"📝 {len(rows)} varlık anladım:")
    return True


async def screenshot_confirm(update, context, which: str):
    rows = context.user_data.pop("ekran", None)
    msg = _shim(update)
    if which == "iptal" or not rows:
        await msg.message.reply_text("❌ Eklenmedi." if which == "iptal" else "Bu onayın süresi geçti, tekrar gönder.")
        return
    for r in rows:
        if which == "yeni" and r["var"]:
            continue
        cost = r["maliyet"] or await _price(bist.yahoo_symbol(r["kod"]) if r["piyasa"] == "BIST" else us.key(r["kod"])
                                            if r["piyasa"] == "ABD" else r["kod"] if r["piyasa"] == assets.MARKET else r["kod"] + config.QUOTE)
        await portfolio_add(msg, [r["kod"], repr(float(r["adet"])), repr(float(cost))], market_name=r["piyasa"])
    await msg.message.reply_text("📅 Alış tarihlerini bilmiyorum; dolar bazlı getiri ve /kiyas için: /duzelt ID tarih=2025-03-01",
                                 reply_markup=PORTFOLIO_BUTTONS)


async def watch_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        alerts = await watcher.check_plans()
    except Exception:
        log.exception("Watcher failed")
        return
    auto_plans = {c for c, p in store.load_state()["planlar"].items() if p.get("otomatik")}
    for coin, event, is_close_event, buy in alerts:
        if not is_close_event and alerts_store.is_quiet():
            log.info("Quiet/school hours, suppressed pre-alert %s: %s", coin, event)
            continue
        log.info("Alert %s: %s", coin, event)
        if coin in auto_plans:
            # Scanner plans stay cheap: no DeepSeek for intermediate events, only when ŞİMDİ AL passes.
            if buy is None:
                continue
            await send_buy_signal(context.bot, coin, buy)
            if buy["ok"] and config.BUY_SIGNALS:
                await run_analysis(context.bot, config.ALLOWED_CHAT_ID,
                                   f"[OTOMATİK UYARI] {coin}: tarayıcı kırılımı teyit edildi, kod kapısı GEÇTİ. {event}",
                                   [coin])
            else:
                state = store.load_state()
                state["planlar"].pop(coin, None)  # confirmation failed the gate: drop the auto plan
                store.save_state(state)
            continue
        if buy is not None:
            await send_buy_signal(context.bot, coin, buy)
        await run_analysis(context.bot, config.ALLOWED_CHAT_ID,
                           f"[OTOMATİK UYARI] {coin}: {event}", [coin])

    if scanner.enabled() and config.BUY_SIGNALS:
        await run_scanner(context.bot)


async def run_scanner(bot, announce_empty_to: int | None = None):
    """Look for new setups across the watchlist and announce candidates (silently)."""
    try:
        dropped = scanner.expire_auto_plans()
        if dropped:
            log.info("Expired automatic plans: %s", dropped)
        found = await scanner.scan()
    except Exception:
        log.exception("Scanner failed")
        return
    for c in found:
        text = (f"👀 ADAY — {c['coin']}/{config.QUOTE}\n"
                f"15m kapanış {_g(c['kapanis'])} ile 4h/1d direnç bölgesi ({c['dokunma']} dokunma) hacimle kırıldı "
                f"(hacim x{c['hacim_orani']:.2f}).\n"
                f"Otomatik plan: tetik/teyit {_g(c['tetik'])} | iptal {_g(c['iptal'])} | hedef {_g(c['hedef'])}\n"
                "Henüz AL değil: sonraki 15m mum direncin üstünde kalırsa kod kapısı kontrol eder, "
                "geçerse 🟢 ŞİMDİ AL gelir.")
        await bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=True)
    if announce_empty_to and not found:
        await bot.send_message(announce_empty_to, "Tarama bitti: son kapanan 15m mumda yeni kırılım adayı yok.")


async def brief_job(context: ContextTypes.DEFAULT_TYPE):
    m = await macro.summary(force=True)
    await send_long(context.bot, config.ALLOWED_CHAT_ID, "☀️ MAKRO PANO\n\n" + macro.dashboard(m))
    data, _ = await build_market_data([])
    try:
        async with httpx.AsyncClient() as client:
            data["BIST100_KAPI"] = await bist.index_gate(client)
        data["BIST_HABERLER"] = await news.bist_for_model(None, hours=24, limit=6)
    except Exception as e:
        data["BIST100_KAPI"] = {"hata": str(e)[:80]}
    await run_analysis(context.bot, config.ALLOWED_CHAT_ID,
                       "[GÜNLÜK MAKRO BRİF] Bugünün makro çerçevesi, BTC durumu ve BIST 100 kapısı.", [], data=data)
    await schedule_events(context.application)


async def schedule_events(app: Application):
    """Queue a warning before and a reaction check after each release in the next 36 hours."""
    now = datetime.now(macro.TR)
    bls_period = (await macro.summary()).get("bls", {}).get("enflasyon", {}).get("donem")
    for e in macro.upcoming(await macro.calendar(), 36):
        t = datetime.fromisoformat(e["tr_zaman"])
        for kind, when in (("uyari", t - timedelta(minutes=config.EVENT_WARN_MINUTES)),
                           ("sonrasi", t + timedelta(minutes=20))):
            name = f"{kind}|{e['olay']}|{e['tr_zaman']}"
            if when <= now or app.job_queue.get_jobs_by_name(name):
                continue
            app.job_queue.run_once(event_job, when=when, name=name,
                                   data={"tur": kind, "onceki_bls_donem": bls_period, **e})
            log.info("Scheduled %s", name)


async def event_job(context: ContextTypes.DEFAULT_TYPE):
    e = context.job.data
    hhmm = datetime.fromisoformat(e["tr_zaman"]).strftime("%H:%M")
    plans = store.load_state()["planlar"]

    if e["tur"] == "uyari":
        lines = [f"⚠️ {config.EVENT_WARN_MINUTES} dk sonra {e['olay']} ({hhmm} TR).",
                 "Yeni giriş yok; veri sonrası ilk 15dk kapanışını bekle."]
        open_pos = [f"  {c}: iptal {p.get('iptal')}" for c, p in plans.items() if p.get("pozisyon")]
        if open_pos:
            lines += ["Açık pozisyonlar, iptal seviyeleri:", *open_pos]
        await context.bot.send_message(config.ALLOWED_CHAT_ID, "\n".join(lines), disable_notification=silent())
        return

    note = ""
    if e["olay"] in macro.BLS_RELEASES:
        bls = await macro.refresh_bls()
        if bls.get("enflasyon", {}).get("donem") == e["onceki_bls_donem"] and e["olay"] == "CPI":
            note = " (BLS API henüz yeni ayı yayınlamadı; [MAKRO] içindeki CPI eski ay olabilir.)"
    await run_analysis(context.bot, config.ALLOWED_CHAT_ID,
                       f"[OTOMATİK UYARI] {e['olay']} {hhmm} TR'de açıklandı, 20 dk geçti.{note} "
                       "Veriyi ve BTC'nin veri sonrası 15dk kapanışlarını değerlendir; planlara etkisi ne?",
                       list(plans))


# --- close-only price alerts -----------------------------------------------------

def _num(x):
    return None if x != x else float(f"{float(x):.6g}")  # NaN -> None


def _alert_line(pair: str, a: dict) -> str:
    last = a["son_tetik_zamani"][:16].replace("T", " ") if a["son_tetik_zamani"] else "-"
    return (f"{pair} #{a['id']} [{a['durum']}] KAPANIŞ {a['yon']} {a['tetik']:g} {a['timeframe']} "
            f"cd {a['cooldown']}\n  iptal {a.get('iptal')} | hedef {a.get('hedef')} | "
            f"hacim şartı {'evet' if a['hacim_sart'] else 'hayır'} | son tetik {last}")


async def on_alert_trigger(bot, pair: str, alert: dict, df, candle: dict, warns: list[str]):
    """Stage 1: chart + facts only. Stage 2: DeepSeek analysis as a separate message."""
    chat, tf = config.ALLOWED_CHAT_ID, alert["timeframe"]
    close = candle["kapanis"]
    op = ">" if alert["yon"] == "ABOVE" else "<"
    caption = "\n".join([f"🔔 {pair} {tf} KAPANIŞ {alert['yon']}",
                         f"Tetik: {alert['tetik']:g}  |  Kapanış: {close:g} ({op} tetik)",
                         *[f"⚠️ {w}" for w in warns]])
    levels = {k: alert.get(k) for k in ("tetik", "iptal", "hedef")}
    try:
        png = await asyncio.to_thread(charts.render, df, f"{pair} {tf}", levels)
        await bot.send_photo(chat, photo=png, caption=caption, disable_notification=silent())
    except Exception:
        log.exception("Chart failed for %s", pair)
        await bot.send_message(chat, caption + "\n(grafik üretilemedi, /get_logs)")

    cols = ["open", "high", "low", "close", "volume", "sma20", "sma50", "sma200", "rsi14", "atr14", "vol_avg20", "vwap"]
    rows = [{"utc": market._ts(r["open_time"]),
             **{c: _num(r[c]) for c in cols}}
            for r in df.tail(config.ALERT_ANALYSIS_CANDLES).to_dict("records")]
    # The shared decision gate decides; the model must use these numbers as given.
    iptal, hedef = alert.get("iptal"), alert.get("hedef")
    async with httpx.AsyncClient() as client:
        g = await gate.evaluate(client, pair=pair, direction=alert["yon"], entry=close, iptal=iptal, hedef=hedef,
                                timeframe=tf, candle=df.iloc[-1])
    data = {"alarm": {"pair": pair, "zaman_dilimi": tf, "yon": alert["yon"], "tetik": alert["tetik"],
                      "iptal": iptal, "hedef": hedef, "kapanis": close, "rr": g["rr"],
                      "kademe_usd": g["kademe_usd"], "kademe_notlari": g["kademe_notlari"],
                      "kapi": {"gecti": g["ok"], "kurallar": g["maddeler"]},
                      "uyarilar": warns},
            f"son_{config.ALERT_ANALYSIS_CANDLES}_mum_{tf}": rows}
    try:
        async with httpx.AsyncClient() as client:
            symbol = alerts_store.pair_to_symbol(pair)
            df4h = market.add_indicators(await market.fetch_klines(client, symbol, "4h"))
            df1d = market.add_indicators(await market.fetch_klines(client, symbol, "1d"))
        data["destek_direnc"] = market.sr_zones(df4h, df1d, close, float(df4h.atr14.iloc[-1]))
    except Exception as e:
        data["destek_direnc"] = {"hata": str(e)}
    base = pair.split("/")[0]
    if base != "BTC":
        try:
            async with httpx.AsyncClient() as client:
                data["BTC"] = await market.snapshot(client, "BTC")
        except Exception as e:
            data["BTC"] = {"hata": str(e)}
    footer = "\n".join(x for x in (gate.summary_line(g), QUIET_NOTE if alerts_store.is_quiet() else "") if x)
    last_row = df.iloc[-1]

    alarm_analysis_id = f"alarm_{pair.replace('/', '')}_{alert['id']}_{int(time.time())}"

    card = {}

    def decision_buttons(reply: str, _plan_coins):
        verdict = re.search(r"KARAR:\s*\**\s*(AL|BEKLE|PAS)", reply)
        d = positions.log_decision({
            "pair": pair, "symbol": alerts_store.pair_to_symbol(pair), "timeframe": tf, "yon": alert["yon"],
            "alarm_id": alert["id"], "kapanis": close, "mum_ms": candle["acilis_zamani"],
            "iptal": alert.get("iptal"), "hedef": alert.get("hedef"),
            "karar": verdict[1] if verdict else "BELİRSİZ",
            "model": llm.model_of(reply),  # for the model scorecard
            "kademe_usd": g["kademe_usd"],  # from the gate; the reply's wording is not parsed
            "kapi": {k: g[k] for k in ("ok", "rr", "kademe_usd", "kademe_notlari", "risk_off", "hacim_ok", "acgozluluk",
                                       "kurallar", "kalan", "mum", "veri")},
            "analiz": reply,
            "uyarilar": warns,
            "gostergeler": {c: _num(last_row[c]) for c in
                            ("close", "sma20", "sma50", "sma200", "rsi14", "atr14", "volume", "vol_avg20", "vwap")},
            "kart": {"alarm": [pair, alert["id"]],
                     "link": f"{config.PUBLIC_URL}/app/analizlerim?id={alarm_analysis_id}" if web_sync.enabled() else None}})
        card["id"] = d["id"]
        if not config.BUY_SIGNALS:
            rows = [[InlineKeyboardButton("🗑 Alarmı sil", callback_data=f"asil|{pair}|{alert['id']}")]]
            if web_sync.enabled():
                rows.append([InlineKeyboardButton("📊 Analizi ve grafiği panelde aç",
                                                  url=f"{config.PUBLIC_URL}/app/analizlerim?id={alarm_analysis_id}")])
            return InlineKeyboardMarkup(rows)
        if d["karar"] == "AL" and g["ok"]:
            return signal_markup(d, None)
        rows = [[InlineKeyboardButton("✅ Aldım", callback_data=f"al|{d['id']}"),
                 InlineKeyboardButton("⏭ Pas", callback_data=f"pas|{d['id']}")],
                [InlineKeyboardButton("🗑 Alarmı sil", callback_data=f"asil|{pair}|{alert['id']}")]]
        if web_sync.enabled():  # opens this very analysis; the page needs the owner's session
            rows.append([InlineKeyboardButton("📊 Analizi ve grafiği panelde aç",
                                              url=f"{config.PUBLIC_URL}/app/analizlerim?id={alarm_analysis_id}")])
        return InlineKeyboardMarkup(rows)

    if not config.BUY_SIGNALS:
        footer = config.NO_SIGNAL_NOTE
    reply = await run_analysis(bot, chat, f"[ALARM TETİKLENDİ] {pair} {tf} kapanış {close:g} {op} tetik {alert['tetik']:g}."
                               + ("" if config.BUY_SIGNALS else " Otomatik AL önerisi kapalı: KARAR satırında AL yazma, "
                                  "BEKLE ya da PAS kullan; durumu, riskleri ve kapanışla geçersiz olma şartını anlat."),
                               [], data=data, footer=footer, buttons=decision_buttons,
                               on_sent=lambda m: card.get("id") and not isinstance(m, HeldMessage)
                               and positions.update_decision(card["id"], mesaj_id=m.message_id))
    if reply and web_sync.enabled():  # the owner's panel keeps the alarm analysis next to its chart
        try:
            await web_sync.push_docs("analyses", [{
                "id": alarm_analysis_id, "kodlar": [pair.split("/")[0]], "piyasa": "KRIPTO", "tur": "alarm",
                "zaman": alerts_store.now_tr().isoformat(), "timeframe": tf,
                "metin": "\n\n".join([reply, footer]) if footer else reply}])
        except Exception as e:
            log.warning("Alarm analysis not saved to the panel: %s", e)


async def on_alert_notice(bot, pair: str, alert: dict, text: str):
    await bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())


@authorized
async def new_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usage = ("Kullanım: /new_alert BTC/USDT KAPANIS ABOVE 84280 15m 1h iptal=83750 hedef=85500 [hacim=hayir]\n"
             f"Zaman dilimleri: {', '.join(config.ALERT_TIMEFRAMES)}. Cooldown: 30m, 1h, 1d gibi.")
    args = context.args
    if len(args) < 6:
        await update.message.reply_text(usage)
        return
    pair, mode, direction, trigger, tf, cooldown, *opts = args
    pair, direction = pair.upper(), direction.upper()
    if mode.upper() not in ("KAPANIS", "KAPANIŞ"):
        await update.message.reply_text("Sadece KAPANIS alarmı var: mum içi dokunma (high/low) asla tetiklemez.\n\n" + usage)
        return
    errors = []
    if not re.fullmatch(r"[A-Z0-9]+/[A-Z0-9]+", pair):
        errors.append("PAIR formatı BTC/USDT gibi olmalı")
    if direction not in ("ABOVE", "BELOW"):
        errors.append("yön ABOVE veya BELOW olmalı")
    try:
        trigger = float(trigger)
    except ValueError:
        errors.append("tetik sayı olmalı")
    if tf not in config.ALERT_TIMEFRAMES:
        errors.append(f"zaman dilimi {', '.join(config.ALERT_TIMEFRAMES)} olmalı")
    if not alerts_store.parse_duration(cooldown):
        errors.append("cooldown 30m / 1h / 1d formatında olmalı")
    extra = {"iptal": None, "hedef": None, "hacim_sart": True}
    for opt in opts:
        key, _, val = opt.partition("=")
        key = key.lower()
        if key in ("iptal", "hedef"):
            try:
                extra[key] = float(val)
            except ValueError:
                errors.append(f"{key} sayı olmalı")
        elif key == "hacim":
            extra["hacim_sart"] = val.lower() not in ("hayir", "hayır", "no", "false", "0")
        else:
            errors.append(f"bilinmeyen seçenek: {opt}")
    if not errors:
        above = direction == "ABOVE"
        if extra["iptal"] is not None and (extra["iptal"] >= trigger if above else extra["iptal"] <= trigger):
            errors.append(f"{direction} alarmında iptal tetiğin {'altında' if above else 'üstünde'} olmalı")
        if extra["hedef"] is not None and (extra["hedef"] <= trigger if above else extra["hedef"] >= trigger):
            errors.append(f"{direction} alarmında hedef tetiğin {'üstünde' if above else 'altında'} olmalı")
    if errors:
        await update.message.reply_text("❌ " + "\n❌ ".join(errors) + "\n\n" + usage)
        return

    try:
        async with httpx.AsyncClient() as client:
            df = market.add_indicators(await market.fetch_klines(client, alerts_store.pair_to_symbol(pair), tf))
    except market.SymbolNotFound:
        await update.message.reply_text(f"❌ Binance'te {pair} paritesi yok.")
        return

    alert = alerts_store.add_alert(pair, {"tetik": trigger, "yon": direction, "timeframe": tf,
                                          "cooldown": cooldown.lower(), **extra})
    engine.refresh()
    last = df.iloc[-1]
    lines = ["✅ Alarm kuruldu:", _alert_line(pair, alert), f"Son kapanmış {tf} mum: {last.close:g}"]
    if (last.close > trigger) if direction == "ABOVE" else (last.close < trigger):
        lines.append("⚠️ Şart şu an zaten sağlanıyor: bir sonraki kapanış da öyleyse hemen tetiklenir.")
    if extra["iptal"] is not None and last.atr14 == last.atr14 and abs(trigger - extra["iptal"]) < last.atr14:
        lines.append(f"⚠️ tetik-iptal mesafesi 1×ATR ({last.atr14:.6g}) altında: gürültüye takılma riski yüksek.")
    await update.message.reply_text("\n".join(lines))


@authorized
async def view_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    only = context.args[0].upper() if context.args else None
    lines = [_alert_line(pair, a) for pair, items in alerts_store.load_alerts().items()
             if not only or pair == only for a in items if a["durum"] in alerts_store.ACTIVE_STATES]
    await send_long(context.bot, update.effective_chat.id,
                    "\n\n".join(lines) if lines else "Aktif alarm yok.")


@authorized
async def cancel_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2 or not context.args[1].isdigit():
        await update.message.reply_text("Kullanım: /cancel_alert BTC/USDT 1")
        return
    pair, alert_id = context.args[0].upper(), int(context.args[1])
    alerts = alerts_store.load_alerts()
    for a in alerts.get(pair, []):
        if a["id"] == alert_id:
            a["durum"], a["iptal_nedeni"] = "iptal", "kullanici"
            alerts_store.save_alerts(alerts)
            engine.refresh()
            await update.message.reply_text(f"{pair} #{alert_id} iptal edildi.")
            return
    await update.message.reply_text(f"{pair} #{alert_id} bulunamadı. /view_alerts")


@authorized
async def get_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = int(context.args[0]) if context.args and context.args[0].isdigit() else 50
    n = min(n, 500)
    try:
        with open(config.LOG_FILE, encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=n)
    except FileNotFoundError:
        lines = []
    await send_long(context.bot, update.effective_chat.id, "".join(lines) or "Log boş.")


@authorized
async def set_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = alerts_store.load_settings()
    if not context.args:
        await update.message.reply_text(f"quiet_hours={s['quiet_hours'] or 'off'} "
                                        f"quiet_days={','.join(s['quiet_days']) or 'her gün'}\n"
                                        "Değiştir: /set_config quiet_hours=09:00-16:00 quiet_days=Mon,Tue,Wed,Thu,Fri")
        return
    for arg in context.args:
        key, _, val = arg.partition("=")
        if key == "quiet_hours":
            if val.lower() == "off":
                s["quiet_hours"] = None
            elif hours := alerts_store.parse_quiet_hours(val):
                s["quiet_hours"] = "-".join(hours)
            else:
                await update.message.reply_text("quiet_hours HH:MM-HH:MM olmalı (örn. 09:00-16:00) veya off.")
                return
        elif key == "quiet_days":
            days = alerts_store.parse_days(val)
            if days is None:
                await update.message.reply_text("quiet_days Mon,Tue,Wed,Thu,Fri,Sat,Sun formatında olmalı.")
                return
            s["quiet_days"] = days
        else:
            await update.message.reply_text(f"Bilinmeyen ayar: {key}")
            return
    alerts_store.save_settings(s)
    schedule_quiet_summary(context.application)
    await update.message.reply_text(
        f"✅ quiet_hours={s['quiet_hours'] or 'off'} quiet_days={','.join(s['quiet_days']) or 'her gün'}\n"
        "Sessiz saatte sadece 'yaklaşıyor' ön-uyarıları susar; kapanış onaylı tetikler her zaman gelir.")


def schedule_quiet_summary(app: Application):
    for job in app.job_queue.get_jobs_by_name("quiet_summary"):
        job.schedule_removal()
    s = alerts_store.load_settings()
    if not s["quiet_hours"]:
        return
    end = datetime.strptime(s["quiet_hours"].split("-")[1], "%H:%M") + timedelta(minutes=5)
    app.job_queue.run_daily(quiet_summary_job, dtime(end.hour, end.minute, tzinfo=macro.TR), name="quiet_summary")
    log.info("Quiet-hours summary scheduled at %s TR", end.strftime("%H:%M"))


async def quiet_summary_job(context: ContextTypes.DEFAULT_TYPE):
    s = alerts_store.load_settings()
    today = alerts_store.now_tr()
    if s["quiet_days"] and today.strftime("%a") not in s["quiet_days"]:
        return
    status_text = {"aktif": "geçerli", "tetiklendi": "geçerli (cooldown)", "pasif": "hedef görüldü"}
    lines = []
    for pair, items in alerts_store.load_alerts().items():
        for a in items:
            for t in a.get("tetikler", []):
                if t[:10] == today.date().isoformat():
                    state = ("iptal oldu (kapanış)" if a.get("iptal_nedeni") == "kapanis" else "iptal edildi (elle)") \
                        if a["durum"] == "iptal" else status_text[a["durum"]]
                    lines.append(f"{t[11:16]}  {pair} #{a['id']} {a['yon']} {a['tetik']:g} {a['timeframe']} → {state}")
    body = "\n".join(sorted(lines)) if lines else "Bugün tetiklenen alarm yok."
    await context.bot.send_message(config.ALLOWED_CHAT_ID, "📋 Günlük alarm özeti\n\n" + body)


# --- positions, buttons, report, backtest, derivatives ----------------------------

def _opts(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split ['BTC/USDT', '84000', 'stop=83000'] into positional args and key=value options."""
    pos, kv = [], {}
    for a in args:
        if "=" in a:
            k, _, v = a.partition("=")
            kv[k.lower()] = v
        else:
            pos.append(a)
    return pos, kv


def _float(text: str | None) -> float | None:
    return None if text is None else float(text.replace(",", "."))


async def _price(symbol: str) -> float:
    async with httpx.AsyncClient() as client:
        if symbol in assets.ASSETS:
            return await assets.last_price(client, symbol)
        if symbol.upper().endswith(".US"):
            return await us.last_price(client, symbol)
        if symbol.upper().endswith(".IS"):
            return await bist.last_price(client, symbol)
        return await market.last_price(client, symbol)


def _position_line(p: dict, price: float | None = None) -> str:
    cur = p.get("para", "USD")
    lots = f" ({_qty(p['adet'])} adet)" if p.get("adet") else ""
    if assets.is_other(p):
        lots = f" ({p['adet']:g} {assets.ASSETS[p['symbol']]['birim']})"
    name = assets.name(p["symbol"]) if assets.is_other(p) else p["pair"]
    stop = "yok" if p.get("stop") is None else _px(p["stop"])
    target = "yok" if p.get("hedef") is None else _px(p["hedef"])
    line = (f"#{p['id']} {name} {p['miktar_usd']:,.2f} {cur}{lots} @ {_px(p['giris'])} | stop {stop} | "
            f"hedef {target} | {p['timeframe']}")
    if price is not None:
        r = positions.pnl(p, price)
        line += f"\n   şimdi {_px(price)} → {r['pnl_usd']:+.2f} {cur} ({r['pnl_yuzde']:+.2f}%)" + \
                (f", {r['R']:+.2f}R" if r["R"] is not None else "")
    return line


def _undo_button(pos: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Almadım, kaydı sil", callback_data=f"psil|{pos['id']}")]])


async def _open_from_decision(query, dec_id: int):
    d = positions.get_decision(dec_id)
    if not d:
        await query.message.reply_text("Karar kaydı bulunamadı.")
        return
    if d.get("piyasa") == "BIST" and d.get("aksiyon"):
        await query.message.reply_text("Bu BIST kararı zaten işlendi.")
        return
    pos, warning = await gate.record_purchase(d)
    if d.get("piyasa") == "BIST":
        await query.message.reply_text(
            f"✅ BIST pozisyonu kaydedildi:\n{_position_line(pos)}\n"
            + (f"{warning}\n" if warning else "")
            + f"Yahoo fiyatı gecikmeli. Gerçek işlem fiyatı ve adet farklıysa: /duzelt {pos['id']} giris=FIYAT adet=N\n"
            "Stop/hedef 1s kapanışla izleniyor.")
        await ask_buy_reason(query.message, pos)
        await query.message.reply_text("Yanlışlıkla mı bastın?", reply_markup=_undo_button(pos))
        return
    await query.message.reply_text(
        f"✅ Pozisyon kaydedildi:\n{_position_line(pos)}\n"
        + (f"{warning}\n" if warning else "")
        + f"Giriş şu anki fiyat. Farklıysa: /duzelt {pos['id']} giris=FIYAT miktar=USD\n"
        "Stop/hedef kapanışla izleniyor.")
    await ask_buy_reason(query.message, pos)
    await query.message.reply_text("Yanlışlıkla mı bastın?", reply_markup=_undo_button(pos))


def signal_markup(d: dict, life: dict | None) -> InlineKeyboardMarkup:
    """Buy-signal card buttons: live status on top (tap = refresh), Aldım/Pas while it is still worth acting on."""
    status = signal_life.status_text(life) if life else "🟢 Aktif · yeni · dokun: güncelle"
    rows = [[InlineKeyboardButton(status, callback_data=f"omur|{d['id']}")]]
    if not life or life["durum"] not in signal_life.FINAL:
        rows.append([InlineKeyboardButton("✅ Aldım", callback_data=f"al|{d['id']}"),
                     InlineKeyboardButton("⏭ Pas", callback_data=f"pas|{d['id']}")])
    kart = d.get("kart") or {}
    if kart.get("alarm"):
        rows.append([InlineKeyboardButton("🗑 Alarmı sil", callback_data=f"asil|{kart['alarm'][0]}|{kart['alarm'][1]}")])
    if kart.get("link"):
        rows.append([InlineKeyboardButton("📊 Panelde aç", url=kart["link"])])
    return InlineKeyboardMarkup(rows)


async def _signal_life_or_none(d: dict | None) -> dict | None:
    if not d or d.get("karar") != "AL" or (d.get("piyasa") or "KRIPTO") != "KRIPTO" or not d.get("kapanis"):
        return None
    try:
        async with httpx.AsyncClient() as client:
            return await signal_life.evaluate(client, d)
    except Exception as e:
        log.warning("Signal life for decision %s failed: %s", d.get("id"), e)
        return None


async def signal_life_job(context: ContextTypes.DEFAULT_TYPE):
    """Keeps the status button of recent buy-signal cards current (age, live price, valid/late/expired)."""
    now = alerts_store.now_tr()
    cards = [d for d in positions.load_decisions()[-40:]
             if d.get("mesaj_id") and d.get("karar") == "AL" and not d.get("aksiyon")
             and (d.get("omur") or {}).get("durum") not in signal_life.FINAL
             and now - datetime.fromisoformat(d["zaman"]) < timedelta(hours=signal_life.WATCH_HOURS)]
    for d in cards:
        life = await _signal_life_or_none(d)
        if not life:
            continue
        positions.update_decision(d["id"], omur={"durum": life["durum"], "ts": now.isoformat()})
        try:
            await context.bot.edit_message_reply_markup(config.ALLOWED_CHAT_ID, d["mesaj_id"], reply_markup=signal_markup(d, life))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                log.warning("Signal card %s not updated: %s", d["id"], e)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_chat.id != config.ALLOWED_CHAT_ID:
        await query.answer()
        return
    await query.answer()
    kind, *rest = query.data.split("|")
    try:
        if kind == "al":
            decision = positions.get_decision(int(rest[0]))
            life = await _signal_life_or_none(decision)
            if life and life["durum"] != "aktif" and rest[1:] != ["onay"]:
                await query.message.reply_text(
                    f"⚠️ Bu sinyal artık {life['etiket']}: giriş {decision['kapanis']:g}, şimdi {life['fiyat']:.6g} "
                    f"({life['fark_yuzde']:+.2f}%), {life['yas_dk']} dk önce verildi. Eski sinyalin peşinden girmiş olursun.\n"
                    "Gerçekten aldıysan kaydederim ve 'geç giriş' notu düşerim.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Evet, aldım", callback_data=f"al|{rest[0]}|onay"),
                        InlineKeyboardButton("❌ Hayır", callback_data="alno")]]))
                return
            if decision and decision.get("karar") != "AL" and rest[1:] != ["onay"]:
                await query.message.reply_text(
                    f"⚠️ Bot bu alarmda {decision.get('karar')} dedi. Gerçekten aldın mı? (yanlışlıkla bastıysan Hayır)",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Evet, aldım", callback_data=f"al|{rest[0]}|onay"),
                        InlineKeyboardButton("❌ Hayır", callback_data="alno")]]))
                return
            if decision and decision.get("piyasa") == "BIST":
                await _open_from_decision(query, int(rest[0]))
                await query.edit_message_reply_markup(None)
            else:
                await query.edit_message_reply_markup(None)
                await _open_from_decision(query, int(rest[0]))
            if life and life["durum"] != "aktif":
                pos = next((p for p in reversed(positions.open_positions()) if p.get("karar_id") == int(rest[0])), None)
                if pos:
                    positions.add_violation(pos["id"], f"{life['etiket']} sinyalden giriş ({life['fark_yuzde']:+.2f}%)", "gec_giris")
        elif kind == "omur":
            d = positions.get_decision(int(rest[0]))
            life = await _signal_life_or_none(d)
            if d and life and not d.get("aksiyon"):
                positions.update_decision(d["id"], omur={"durum": life["durum"], "ts": alerts_store.now_tr().isoformat()})
                try:
                    await query.edit_message_reply_markup(signal_markup(d, life))
                except BadRequest:
                    pass
        elif kind == "ne":
            await query.edit_message_reply_markup(None)
            await advice_reply(context.bot, update.effective_chat.id, rest[0], f"{rest[0]} için ne yapayım?")
        elif kind == "alno":
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("👍 Kayıt açılmadı.")
        elif kind == "psil":
            await query.edit_message_reply_markup(None)
            pos = positions.get(int(rest[0]))
            if not pos:
                await query.message.reply_text("Bu kayıt zaten yok.")
            elif rest[1:] != ["onay"]:
                await query.message.reply_text(
                    f"🗑 #{pos['id']} {pos['pair']} kaydı tamamen silinsin mi? (satış sayılmaz, K/Z ve günlüğe girmez)",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Evet, sil", callback_data=f"psil|{pos['id']}|onay"),
                                                        InlineKeyboardButton("❌ Vazgeç", callback_data="alno")]]))
            else:
                positions.delete_position(pos["id"])
                await query.message.reply_text(f"🗑 #{pos['id']} {pos['pair']} kaydı silindi. Stop/hedef uyarısı artık gelmez.")
        elif kind == "pas":
            decision = positions.get_decision(int(rest[0]))
            if decision and decision.get("piyasa") == "BIST":
                if decision.get("aksiyon"):
                    await query.message.reply_text("Bu BIST kararı zaten işlendi.")
                    return
                bist_signals.discard_candidate(decision["symbol"])
            positions.set_decision_action(int(rest[0]), "pas")
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⏭ Pas geçildi, karar günlüğe yazıldı.")
        elif kind == "asil":
            pair, alert_id = rest[0], int(rest[1])
            alerts = alerts_store.load_alerts()
            for a in alerts.get(pair, []):
                if a["id"] == alert_id:
                    a["durum"], a["iptal_nedeni"] = "iptal", "kullanici"
            alerts_store.save_alerts(alerts)
            engine.refresh()
            await query.message.reply_text(f"🗑 {pair} #{alert_id} alarmı silindi.")
        elif kind == "plan":
            coin = rest[0]
            if bist_signals.is_bist_plan(coin):
                await query.message.reply_text("BIST planı otomatik olarak 1 saatlik kapanışlarla izlenir; ayrıca alarm kurmana gerek yok.")
                return
            if coin.endswith(".US"):
                await query.message.reply_text("ABD planı New York kapanışından sonra günlük kapanışla otomatik izlenir; ayrıca alarm gerekmez.")
                return
            p = store.load_state()["planlar"].get(coin)
            if not p or p.get("tetik") is None:
                await query.message.reply_text(f"{coin} için tetikli plan yok.")
                return
            pair = f"{coin}/{config.QUOTE}"
            alert = alerts_store.add_alert(pair, {"tetik": p["tetik"], "yon": "ABOVE", "timeframe": "15m",
                                                  "cooldown": "1h", "iptal": p.get("iptal"),
                                                  "hedef": p.get("hedef"), "hacim_sart": True})
            engine.refresh()
            state = store.load_state()
            state["planlar"][coin]["alarm_id"] = alert["id"]  # watcher leaves this plan to the alarm engine
            store.save_state(state)
            await query.message.reply_text("⏰ Alarm kuruldu:\n" + _alert_line(pair, alert))
        elif kind == "sat" and query.message.date and \
                (datetime.now(query.message.date.tzinfo) - query.message.date).total_seconds() > STALE_SELL_BUTTON_S:
            p = positions.get(int(rest[0]))
            if not p or p["durum"] != "acik":
                await query.message.reply_text("Bu pozisyon zaten kapalı.")
                return
            now_price = await _price(p["symbol"])
            age_h = (datetime.now(query.message.date.tzinfo) - query.message.date).total_seconds() / 3600
            await query.message.reply_text(
                f"Bu mesaj {age_h:.1f} saat önce geldi; içindeki {float(rest[1]):g} artık satış fiyatın olmayabilir.\n"
                f"Gerçek satışını yaz: /sat {p['id']} FİYAT [TARİH] (ör. /sat {p['id']} 11,04 dün ya da 25.09 14:30)\n"
                "ya da seç:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"Mesajdaki fiyat {float(rest[1]):g}", callback_data=f"satk|{rest[0]}|{rest[1]}|{rest[2]}")],
                    [InlineKeyboardButton(f"Şu anki fiyat {now_price:g}", callback_data=f"satk|{rest[0]}|{now_price}|{rest[2]}")]]))
        elif kind in ("sat", "satk"):
            pos = positions.close_position(int(rest[0]), float(rest[1]), rest[2])
            await query.edit_message_reply_markup(None)
            if pos:
                r = positions.pnl(pos, pos["kapanis_fiyat"])
                await query.message.reply_text(f"💰 #{pos['id']} {pos['pair']} kapatıldı @ {pos['kapanis_fiyat']:g}: "
                                               f"{r['pnl_usd']:+.2f} {pos.get('para', 'USD')}" + (f", {r['R']:+.2f}R" if r["R"] is not None else ""))
                await ask_sell_reason(query.message, [pos["id"]])
        elif kind == "yari":
            p = positions.get(int(rest[0]))
            qty = p["adet"] / 2
            if p.get("piyasa") == "BIST":
                qty = max(int(p["adet"] // 2), 1)
            part, remain = positions.partial_close(p["id"], qty, float(rest[1]), "kısmi (tepe/çıkış işareti)")
            await query.edit_message_reply_markup(None)
            r = positions.pnl(part, float(rest[1]))
            await query.message.reply_text(
                f"½ #{p['id']} {p['pair']}: {qty:g} satıldı @ {float(rest[1]):g} → {r['pnl_usd']:+.2f} {p.get('para', 'USD')}"
                + (f"\nKalan {remain['adet']:g}. Stopu yukarı çekmeyi unutma." if remain else " (tamamen kapandı)")
                + "\nGerçek fiyat farklıysa kaydı /duzelt ile düzelt.")
            await ask_sell_reason(query.message, [part["id"]])
        elif kind == "stopcek":
            pos, err = positions.update(int(rest[0]), stop=float(rest[1]))
            await query.edit_message_reply_markup(None)
            await query.message.reply_text(err or f"🔒 #{pos['id']} {pos['pair']} stop {pos['stop']:g} yapıldı "
                                                  "(sadece yukarı; aracı kurumda/borsada da güncelle).")
        elif kind == "pf":
            await query.edit_message_reply_markup(None)
            action = rest[0]
            if action == "ekle":
                await wizard_start(query.message, context)
            elif action == "sat":
                await ask_sell(query, context)
            elif action == "detay":
                await portfolio_show(_shim(update), context)
            elif action == "grafik":
                await portfolio_chart(_shim(update), context)
            elif action == "risk":
                await risk_report(_shim(update), context)
            elif action == "bakiye":
                await balance_report(_shim(update), context)
            elif action == "ne":
                await ask_advice(query.message)
            else:
                await portfolio_summary(_shim(update), context)
        elif kind == "pfsat":
            mkt, sym = rest[0], rest[1]
            await query.edit_message_reply_markup(None)
            total = sum(p["adet"] for p in positions.open_positions() if p["symbol"] == sym)
            half = int(total // 2) if mkt == "BIST" else total / 2
            context.user_data.pop("sihirbaz", None)
            context.user_data["satis"] = {"mkt": mkt, "sym": sym, "toplam": total, "adim": "adet"}
            unit = "adet"
            await query.message.reply_text(
                f"{bist.ticker(sym) if mkt == 'BIST' else sym}: elinde {_qty(total)} {unit}. Kaç {unit} sattın?\n(butona bas ya da sayı yaz)",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"Hepsi ({_qty(total)})", callback_data=f"st|adet|{total!r}")]
                    + ([InlineKeyboardButton(f"Yarısı ({_qty(half)})", callback_data=f"st|adet|{half!r}")] if half > 0 else []),
                    [InlineKeyboardButton("❌ İptal", callback_data="st|iptal")]]))
        elif kind == "st":
            s = context.user_data.get("satis")
            await query.edit_message_reply_markup(None)
            if not s or rest[0] == "iptal":
                context.user_data.pop("satis", None)
                await query.message.reply_text("❌ Satış iptal.")
            elif rest[0] == "adet":
                s["adet"] = float(rest[1])
                await sell_ask_price(query.message, context)
            elif rest[0] == "fiyat":
                s["satis_fiyati"] = s["fiyat"]
                await sell_ask_when(query.message, context)
            elif rest[0] == "zaman":
                context.user_data.pop("satis", None)
                when = parse_when(rest[1])
                await sell_holding(_shim(update), context, s["mkt"], s["sym"], when=when,
                                   qty=s["adet"], price=s["satis_fiyati"])
        elif kind == "wz" and rest[0] in ("sec", "sayfa", "yok", "devam"):
            w = context.user_data.get("sihirbaz")
            if not w or w.get("adim") != "kod":
                await query.message.reply_text("Bu seçim ekranı eskidi. /portfoy → Ekle ile yeniden başla.")
                return
            if rest[0] == "sec":
                chosen = w.setdefault("secili", [])
                chosen.remove(rest[1]) if rest[1] in chosen else chosen.append(rest[1])
                await query.edit_message_reply_markup(_pick_keyboard(w))
            elif rest[0] == "sayfa":
                w["sayfa"] = int(rest[1])
                await query.edit_message_reply_markup(_pick_keyboard(w))
            elif rest[0] == "devam":
                if not w.get("secili"):
                    await query.message.reply_text("Önce en az bir tane seç (butona bas, ✅ olur).")
                    return
                await query.edit_message_reply_markup(None)
                await wizard_start_queue(query.message, context, w["secili"])
        elif kind == "wz":
            await query.edit_message_reply_markup(None)
            w = context.user_data.get("sihirbaz")
            step = rest[0]
            if step == "iptal":
                context.user_data.pop("sihirbaz", None)
                await query.message.reply_text("❌ İptal edildi.", reply_markup=PORTFOLIO_BUTTONS)
            elif step == "piyasa":
                context.user_data["sihirbaz"] = {"adim": "kod", "piyasa": rest[1]}
                await wizard_ask_asset(query.message, context)
            elif not w:
                await query.message.reply_text("Bu işlem zaman aşımına uğradı. /portfoy ile yeniden başla.")
            elif step == "kod":
                await wizard_set_asset(query.message, context, rest[1])
            elif step == "maliyet":
                await wizard_set_cost(query.message, context, rest[1])
            elif step == "kaydet":
                await wizard_save(update, context, today=rest[1:2] == ["bugun"])
        elif kind == "ekr":
            await query.edit_message_reply_markup(None)
            await screenshot_confirm(update, context, rest[0])
        elif kind == "nal":
            await query.edit_message_reply_markup(None)
            await natural_alarm_confirm(update, context, rest[0] == "kur")
        elif kind == "guc":
            await query.edit_message_reply_markup(None)
            top = [r["hisse"] for r in strength.load().get("sirali", [])[:5]]
            await plan_add(_shim(update), context, top)
        elif kind == "tk":
            await takip_button(update, context, rest)
        elif kind == "firsat":
            await query.edit_message_reply_markup(None)
            if rest[0] == "yorum":
                await opportunity_ai(update, context)
            else:
                await opportunity_report(_shim(update), context)
        elif kind == "temel":
            await query.edit_message_reply_markup(None)
            await fundamentals_ai(update, context, rest[0])
        elif kind == "abdtez":
            await query.edit_message_reply_markup(None)
            await us_thesis(update, context, rest[0])
        elif kind == "abdguc":
            await query.edit_message_reply_markup(None)
            await plan_add(_shim(update), context, [us.key(t) for t in alerts_store.load_settings().get("abd_guc_son", [])[:5]])
        elif kind == "plkur":
            await query.edit_message_reply_markup(None)
            key = rest[0]
            if bist_signals.is_bist_plan(key):
                await incele_ticker(_shim(update), context, bist.ticker(key))
            elif key.endswith(".US"):
                await us_analysis(_shim(update), context, us.ticker(key))
            else:
                await run_analysis(context.bot, update.effective_chat.id,
                                   f"{key} analiz et ve tetik/teyit/iptal/hedef planı kur.", [key])
        elif kind == "gn":
            await journal_button(query, context, rest[0], rest[1], rest[2])
        elif kind == "dca":
            await dca_button(query, rest)
        elif kind == "tutk":
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("✋ Tutuluyor. Trend bozulursa (SMA50/iz süren stop altı kapanış) SAT uyarısı gelir.")
        elif kind == "tut":
            if rest[1:] == ["cikis"]:
                positions.add_violation(int(rest[0]), "SAT kararına rağmen tutuldu", "sat_tut")
            else:
                positions.add_violation(int(rest[0]), "stop kapanışla kırıldı, pozisyon tutuldu", "stop_tut")
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⚠️ Tutuluyor. Kural ihlali olarak günlüğe yazıldı (/rapor'da görünür).")
        elif kind == "be":
            pos, err = positions.update(int(rest[0]), stop=positions.get(int(rest[0]))["giris"])
            await query.edit_message_reply_markup(None)
            await query.message.reply_text(err or f"🔒 #{pos['id']} stop girişe ({pos['stop']:g}) çekildi, risk sıfır.")
    except Exception as e:
        log.exception("Button %s failed", query.data)
        await query.message.reply_text(f"❌ Hata: {e}")


@authorized
async def aldim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Record a buy: asset, buy price, how much. Shows the change right away. No stop, no rules."""
    usage = ("Kullanım: /aldim COIN ALIŞ_FİYATI KAÇ_USDT'LİK\n"
             "Örnek: /aldim HYPE/USDT 92.7 60 → 60 USDT'lik HYPE, 92.7'den alındı\n"
             "       /aldim THYAO 285 10 → BIST: 10 adet (ya da 5000tl yaz)\n"
             "Bot şu anki fiyatı, yüzde artış/düşüşü ve K/Z'yi gösterir; sonra /portfoy.")
    args, kv = _opts(context.args)
    if len(args) != 3:
        await update.message.reply_text(usage)
        return
    code = args[0].upper()
    if not code.endswith(".IS"):
        code = code.replace("/", "").removesuffix(config.QUOTE)
    amount_txt = args[2].replace("$", "").lower()
    in_tl = amount_txt.endswith(("tl", "₺"))
    for suffix in ("tl", "₺", "usdt", "usd"):
        amount_txt = amount_txt.removesuffix(suffix)
    try:
        entry, amount = _float(args[1]), _float(amount_txt)
    except ValueError:
        await update.message.reply_text(usage)
        return
    if not entry or entry <= 0 or not amount or amount <= 0:
        await update.message.reply_text("❌ Fiyat ve tutar pozitif sayı olmalı.\n\n" + usage)
        return
    mkt = "BIST" if code.endswith(".IS") or code in bist.watchlist() else await _detect_market(code)
    if mkt not in ("KRIPTO", "BIST", "ABD"):
        await update.message.reply_text(f"❌ {code} ne Binance'te, ne BIST'te, ne ABD borsalarında bulundu.")
        return
    if mkt == "ABD":
        usd_amount = "$" in args[2] or "usd" in args[2].lower()
        qty = amount / entry if usd_amount else amount
        symbol = us.key(code)
        pair, value, tf, cur = symbol, qty * entry, "1d", "USD"
    elif mkt == "BIST":
        qty = int(amount // entry) if in_tl else amount
        if qty < 1 or qty != int(qty):
            await update.message.reply_text("BIST'te adet tam sayı olmalı (ör. 10) ya da TL tutar yaz (ör. 5000tl).")
            return
        symbol = bist.yahoo_symbol(code)
        pair, value, tf, cur = symbol, qty * entry, "1d", "TL"
    else:
        if in_tl:
            async with httpx.AsyncClient() as client:
                amount = amount / await bist.last_price(client, bist.FX)
        pair = f"{code}/{config.QUOTE}"
        symbol = alerts_store.pair_to_symbol(pair)
        value, tf, cur = amount, "4h", "USDT"
    # A plain holding: no stop, not counted against the bot's short-term 25 USD first-tranche cap.
    pos = positions.open_position(pair, entry, value, None, None, tf, source="portföy", market_name=mkt, symbol=symbol)
    positions.update(pos["id"], tarih_girildi=True)  # bought now: the date is known
    pos = positions.get(pos["id"])
    name = bist.ticker(symbol) if mkt == "BIST" else us.ticker(symbol) if mkt == "ABD" else code
    lines = [f"✅ Kaydedildi: #{pos['id']} {name} — "
             + (f"{pos['adet']:.0f} adet × {entry:g} = {value:,.2f} TL" if mkt == "BIST" else
                f"{pos['adet']:.6g} hisse × {entry:g} = {value:,.2f} USD" if mkt == "ABD"
                else f"{value:,.2f} USDT'lik, {entry:g}'den → {pos['adet']:.6g} {name}")]
    try:
        price = await _price(symbol)
        r = positions.pnl(pos, price)
        lines.append(f"Şu an {price:g} → {_pct_badge(r['pnl_yuzde'])} ({r['pnl_usd']:+,.2f} {cur})"
                     + (" · BIST ~15 dk gecikmeli" if mkt == "BIST" else ""))
    except Exception as e:
        lines.append(f"Şu anki fiyat alınamadı ({str(e)[:40]})")
    lines.append("Yüzde artış/düşüş her zaman: /portfoy")
    await update.message.reply_text("\n".join(lines), reply_markup=_undo_button(pos))


@authorized
async def sat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: /sat ID [FIYAT] [TARİH] [adet=N | yuzde=50]\n"
                                        "Fiyat yoksa şu anki fiyat; tarih: dün, 25.09 ya da 25.09 14:30 (yoksa şimdi).")
        return
    pos = positions.get(int(context.args[0]))
    if not pos or pos["durum"] != "acik":
        await update.message.reply_text("Açık pozisyon bulunamadı. /pozisyonlar")
        return
    if pos.get("piyasa") == "BIST" and len(context.args) < 2:
        await update.message.reply_text(f"BIST satışında gerçekleşen fiyat gerekli: /sat {pos['id']} FIYAT")
        return
    rest_args, kv = _opts(context.args[1:])
    price = _float(rest_args[0]) if rest_args else await _price(pos["symbol"])
    when = parse_when(" ".join(rest_args[1:])) if len(rest_args) > 1 else None
    if len(rest_args) > 1 and not when:
        await update.message.reply_text("Tarihi anlayamadım. Örnek: /sat 13 11,04 dün ya da /sat 13 11,04 25.09 14:30")
        return
    if when and when < pos.get("acilis", ""):
        await update.message.reply_text("Satış tarihi alış tarihinden önce olamaz.")
        return
    if "lot" in kv or "yuzde" in kv or "adet" in kv:
        qty = _float(kv.get("lot") or kv.get("adet")) if ("lot" in kv or "adet" in kv) else pos["adet"] * _float(kv["yuzde"]) / 100
        if pos.get("piyasa") == "BIST":
            qty = int(qty)
        if qty <= 0:
            await update.message.reply_text("Satılacak miktar 0 olamaz.")
            return
        part, rest = positions.partial_close(pos["id"], qty, price, "kısmi", when=when)
        r = positions.pnl(part, price)
        await update.message.reply_text(
            f"💰 #{pos['id']} {pos['pair']}: {qty:g} adet satıldı @ {price:g} → "
            f"{r['pnl_usd']:+.2f} {pos.get('para', 'USD')}"
            + (f"\nKalan: {rest['adet']:g} · stop {rest['stop']} · hedef {rest['hedef']}" if rest else " (pozisyon tamamen kapandı)"))
        await ask_sell_reason(update.message, [part["id"]])
        return
    pos = positions.close_position(pos["id"], price, "elle", when=when)
    r = positions.pnl(pos, price)
    await update.message.reply_text(f"💰 #{pos['id']} {pos['pair']} kapatıldı @ {price:g}: {r['pnl_usd']:+.2f} {pos.get('para', 'USD')}"
                                    + (f", {r['R']:+.2f}R" if r["R"] is not None else ""))
    await ask_sell_reason(update.message, [pos["id"]])


@authorized
async def kayitsil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("Kullanım: /kayitsil ID — hiç almadığın bir pozisyon kaydını siler (satış sayılmaz).\n"
                                        "Gerçekten sattıysan /sat ID FIYAT kullan.")
        return
    pos = positions.get(int(context.args[0]))
    if not pos:
        await update.message.reply_text("Bu ID'de kayıt yok. /pozisyonlar")
        return
    await update.message.reply_text(
        f"🗑 #{pos['id']} {pos['pair']} ({pos['durum']}) kaydı tamamen silinsin mi? K/Z, günlük ve disipline girmez.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Evet, sil", callback_data=f"psil|{pos['id']}|onay"),
                                            InlineKeyboardButton("❌ Vazgeç", callback_data="alno")]]))


@authorized
async def pozisyonlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = positions.open_positions()
    if not items:
        await update.message.reply_text("Açık pozisyon yok.")
        return
    lines, totals = [], {}
    for p in items:
        price = await _price(p["symbol"])
        currency = p.get("para", "USD")
        totals[currency] = totals.get(currency, 0) + positions.pnl(p, price)["pnl_usd"]
        lines.append(_position_line(p, price))
    await send_long(context.bot, update.effective_chat.id,
                    "\n\n".join(lines) + "\n\nToplam açık K/Z: " + ", ".join(f"{value:+.2f} {cur}" for cur, value in totals.items()))


@authorized
async def duzelt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args, kv = _opts(context.args)
    keys = {"giris": "giris", "miktar": "miktar_usd", "stop": "stop", "hedef": "hedef"}
    if "adet" in kv and "lot" not in kv:  # users write adet (1 lot = 1 share on BIST)
        kv["lot"] = kv.pop("adet")
    date_txt = kv.pop("tarih", None)
    if len(args) != 1 or not args[0].isdigit() or (not kv and not date_txt) or set(kv) - (set(keys) | {"lot"}):
        await update.message.reply_text("Kullanım: /duzelt ID [giris=X] [miktar=USD veya TL] [adet=N (BIST)] [stop=X] [hedef=X] "
                                        "[tarih=2025-03-01]\nAçık pozisyonda stop sadece yukarı çekilebilir.")
        return
    try:
        changes = {keys[k]: _float(v) for k, v in kv.items() if k in keys}
    except ValueError:
        await update.message.reply_text("Değerler sayı olmalı.")
        return
    if date_txt:
        try:
            day = datetime.strptime(date_txt.replace(".", "-"), "%Y-%m-%d").date()
        except ValueError:
            try:
                day = datetime.strptime(date_txt.replace(".", "-"), "%d-%m-%Y").date()
            except ValueError:
                day = None
        if day is None or day > alerts_store.now_tr().date():
            await update.message.reply_text("Tarih 2025-03-01 ya da 01.03.2025 biçiminde ve bugünden önce olmalı.")
            return
        changes.update(acilis=datetime(day.year, day.month, day.day, 10, 0, tzinfo=macro.TR).isoformat(), tarih_girildi=True)
    pos = positions.get(int(args[0]))
    if pos and pos.get("piyasa") == "BIST":
        entry = changes.get("giris", pos["giris"])
        if not math.isfinite(entry) or entry <= 0 or any(v is not None and not math.isfinite(v) for v in changes.values()):
            await update.message.reply_text("Fiyat ve tutarlar geçerli pozitif sayılar olmalı.")
            return
        if "lot" in kv:
            if "miktar" in kv or not kv["lot"].isdigit() or int(kv["lot"]) < 1:
                await update.message.reply_text("BIST için pozitif tam sayı adet gir; adet ve miktarı birlikte kullanma.")
                return
            changes["miktar_usd"] = entry * int(kv["lot"])
        elif "miktar_usd" in changes:
            lots = changes["miktar_usd"] / entry
            if lots < 1 or abs(lots - round(lots)) > 1e-6:
                await update.message.reply_text("BIST'te adet tam sayı olmalı. Örnek: /duzelt ID giris=320 adet=4")
                return
        elif "giris" in changes:
            changes["miktar_usd"] = entry * round(pos["adet"])
    elif "lot" in kv:
        await update.message.reply_text("adet=N yalnız BIST pozisyonlarında kullanılır.")
        return
    pos, err = positions.update(int(args[0]), **changes)
    await update.message.reply_text(f"❌ {err}" if err else f"✅ Güncellendi:\n{_position_line(pos)}")


@authorized
async def rapor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args and context.args[0].isdigit() else 7
    status = await update.message.reply_text(f"⏳ son {days} gün hesaplanıyor...")
    since = (alerts_store.now_tr() - timedelta(days=days)).isoformat()
    lines = [f"📊 RAPOR — son {days} gün"]

    closed = [p for p in positions.load() if p["durum"] == "kapali" and p["kapanis_zamani"] >= since]
    if closed:
        lines.append("\nKAPANAN İŞLEMLER")
        for currency in ("USD", "TL"):
            results = [(p, positions.pnl(p, p["kapanis_fiyat"])) for p in closed if p.get("para", "USD") == currency]
            if not results:
                continue
            wins = [x for x in results if x[1]["pnl_usd"] > 0]
            rs = [x[1]["R"] for x in results if x[1]["R"] is not None]
            best = max(results, key=lambda x: x[1]["pnl_usd"])
            worst = min(results, key=lambda x: x[1]["pnl_usd"])
            lines += [f"{currency}: işlem {len(results)} | kazanan {len(wins)} | isabet %{len(wins) / len(results) * 100:.0f}",
                      f"Toplam K/Z {sum(x[1]['pnl_usd'] for x in results):+.2f} {currency}"
                      + (f" | ort {sum(rs) / len(rs):+.2f}R | toplam {sum(rs):+.2f}R" if rs else ""),
                      f"En iyi: #{best[0]['id']} {best[0]['pair']} {best[1]['pnl_usd']:+.2f} {currency}",
                      f"En kötü: #{worst[0]['id']} {worst[0]['pair']} {worst[1]['pnl_usd']:+.2f} {currency}"]
    else:
        lines.append("\nKapanan işlem yok.")

    open_items = positions.open_positions()
    if open_items:
        unreal = {}
        for p in open_items:
            currency = p.get("para", "USD")
            unreal[currency] = unreal.get(currency, 0) + positions.pnl(p, await _price(p["symbol"]))["pnl_usd"]
        lines.append(f"\nAçık pozisyon {len(open_items)} | anlık K/Z "
                     + ", ".join(f"{value:+.2f} {cur}" for cur, value in unreal.items()))

    lines += ["", discipline.text(since), "", journal.text(journal.summary(since))]

    decisions = [d for d in positions.load_decisions() if d["zaman"] >= since][-30:]
    if decisions:
        groups: dict[str, dict[str, int]] = {}
        for d in decisions:
            try:
                res = (await backtest.evaluate_decision(d))["sonuc"]
            except Exception as e:
                log.warning("Decision %s eval failed: %s", d["id"], e)
                res = "veri yok"
            g = groups.setdefault(d["karar"], {})
            g[res] = g.get(res, 0) + 1
        lines.append("\nBOT KARARLARI (alarm sonrası fiyat ne yaptı, kapanışla)")
        for verdict, g in groups.items():
            detail = ", ".join(f"{k} {v}" for k, v in g.items())
            lines.append(f"{verdict}: {sum(g.values())} → {detail}")
        right = groups.get("AL", {}).get("hedef", 0) + groups.get("PAS", {}).get("stop", 0)
        judged = sum(groups.get("AL", {}).get(k, 0) + groups.get("PAS", {}).get(k, 0) for k in ("hedef", "stop"))
        if judged:
            lines.append(f"AL→hedef + PAS→stop isabeti: %{right / judged * 100:.0f} ({right}/{judged})")
        acted = [d for d in decisions if d["aksiyon"]]
        followed = sum((d["karar"] == "AL") == (d["aksiyon"] == "aldi") for d in acted)
        if acted:
            lines.append(f"Karara uyma: {followed}/{len(acted)}")
    else:
        lines.append("\nBu dönemde alarm kararı yok.")

    stats = gate.rule_stats([d for d in positions.load_decisions() if d["zaman"] >= since])
    lines.append("\nKURAL ETKİNLİĞİ (sonuçlanan kararlar, kapanışla)")
    if not stats:
        lines.append("Henüz hedef/stopla sonuçlanan karar fişi yok; birkaç hafta birikince anlamlı olur.")
    for r in stats:
        g, k = r["gectiginde"], r["kaldiginda"]
        fmt = lambda s: f"{s['n']} karar, hedef %{s['isabet_yuzde']}" if s["n"] else "veri yok"
        lines.append(f"{r['kural']}: geçtiğinde {fmt(g)} | kaldığında {fmt(k)}")
    if any(r["gectiginde"]["n"] + r["kaldiginda"]["n"] < 10 for r in stats):
        lines.append("(10 karardan az olan satırlar tesadüf olabilir.)")
    lines += gate.rule_advice(stats)

    await status.delete()
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines))


@authorized
async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usage = ("Kullanım: /backtest BTC/USDT ABOVE 84280 15m [iptal=83750] [hedef=85500] [gun=180] [komisyon=0.1] [kayma=0.05]\n"
             "iptal/hedef yoksa tetik anındaki ATR ile: iptal 1.5×ATR, hedef 2×ATR.\n"
             "Net sonuç her işlem tarafında komisyon + kayma (%) düşülerek hesaplanır.")
    args, kv = _opts(context.args)
    if len(args) != 4 or args[1].upper() not in ("ABOVE", "BELOW") or args[3] not in backtest.TF_MS:
        await update.message.reply_text(usage)
        return
    try:
        pair, direction, trigger, tf = args[0].upper(), args[1].upper(), _float(args[2]), args[3]
        stop, target = _float(kv.get("iptal")), _float(kv.get("hedef"))
        days = int(kv.get("gun", 180))
        fee, slip = _float(kv.get("komisyon")), _float(kv.get("kayma"))
    except ValueError:
        await update.message.reply_text(usage)
        return
    status = await update.message.reply_text("⏳ geçmiş mumlar çekiliyor...")
    try:
        res = await backtest.run(alerts_store.pair_to_symbol(pair), direction, trigger, tf, days, stop, target,
                                 fee_pct=fee, slippage_pct=slip)
        if "hata" not in res:  # the web panel's Backtest page shows the latest run
            positions.save_last_backtest({"pair": pair, "yon": direction, "tetik": trigger, "timeframe": tf,
                                          "iptal": stop, "hedef": target, "gun": days, **res})
    except market.SymbolNotFound:
        await status.edit_text(f"❌ Binance'te {pair} yok.")
        return
    if "hata" in res:
        await status.edit_text(f"❌ {res['hata']}")
        return

    def fmt(name, s):
        if not s["islem"]:
            return f"{name}: işlem yok"
        return (f"{name}: {s['islem']} tetik | hedef {s['hedef']} | stop {s['stop']} | açık {s['acik']}"
                f" | isabet %{s['isabet_yuzde']}\n   brüt: ort {s['ort_R']}R, toplam {s['toplam_R']}R"
                f" | net: ort {s['ort_R_net']}R, toplam {s['toplam_R_net']}R")

    lines = [f"🧪 BACKTEST {pair} KAPANIŞ {direction} {trigger:g} {tf}",
             f"{res['donem']} ({res['mum_sayisi']} mum)",
             "Seviyeler: " + ("ATR varsayılanı (iptal 1.5×ATR, hedef 2×ATR)" if res["atr_varsayilan"]
                              else f"iptal {stop:g} / hedef {target:g}"),
             f"Maliyet: komisyon %{res['maliyet']['komisyon_yuzde']:g} + kayma %{res['maliyet']['kayma_yuzde']:g} (her taraf)",
             "", fmt("Tümü", res["tum"]), fmt("Hacim teyitli", res["hacim_teyitli"]),
             fmt("Hacimsiz", res["hacimsiz"])]
    if res["son_islemler"]:
        lines.append("\nSon tetikler:")
        lines += [f"  {t['zaman']} giriş {t['giris']:g} → {t['sonuc']} ({t['mum']} mum, {t['R']}R brüt / {t['R_net']}R net)"
                  for t in res["son_islemler"]]
    lines.append("\nGeçmiş sonuç geleceği garanti etmez; kuralın karakterini gösterir.")
    await status.delete()
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines))


@authorized
async def vadeli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin = (context.args[0] if context.args else "BTC").upper().replace("/USDT", "")
    async with httpx.AsyncClient() as client:
        d = await derivatives.snapshot(client, coin)
    if "hata" in d:
        await update.message.reply_text(f"❌ {d['hata']}")
        return
    await update.message.reply_text(
        f"📈 {coin} vadeli (Binance USDT-M)\n"
        f"Funding: %{d['funding_son_yuzde']} / {d['funding_araligi_saat']}s (7g ort %{d['funding_7g_ort_yuzde']}, "
        f"yıllık ~%{d['funding_yillik_yuzde']}, son 100 kaydın %{d['funding_100_kayit_yuzdelik']} yüzdeliği)\n"
        f"Açık pozisyon: {d.get('acik_pozisyon_usd', 0) / 1e6:,.0f} M$ (24s {d.get('acik_pozisyon_24s_degisim_yuzde')}%)\n"
        f"Long/short hesap oranı: {d.get('long_short_hesap_orani')} (24s önce {d.get('long_short_24s_once')})\n"
        f"→ {d['yorum_ipucu']}")


def _g(x) -> str:
    return "—" if x is None else f"{x:.6g}"


async def send_buy_signal(bot, coin: str, buy: dict):
    """The plan's trigger and confirmation closed; say plainly whether every rule passes."""
    pair = f"{coin}/{config.QUOTE}"
    chart_url = f"{config.PUBLIC_URL}/app/grafik?kod={coin}&piyasa=KRIPTO"
    if not config.BUY_SIGNALS:
        await bot.send_message(config.ALLOWED_CHAT_ID,
                               f"📍 {pair}: planının tetik ve teyit mumları kapandı (15m kapanış {_g(buy['close'])}, "
                               f"iptal {_g(buy['iptal'])}, hedef {_g(buy['hedef'])}).\n{config.NO_SIGNAL_NOTE}",
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Grafiği aç", url=chart_url)]]),
                               disable_notification=silent())
        return
    if buy["ok"]:
        try:
            async with httpx.AsyncClient() as client:
                cdf = market.add_indicators(await market.fetch_klines(client, alerts_store.pair_to_symbol(pair), "15m"))
            await send_chart(bot, cdf, f"{pair} 15m", {k: buy.get(k) for k in ("iptal", "hedef")}, f"📈 {pair} 15m")
        except Exception:
            log.exception("Crypto chart failed")
    lines = [f"🟢 SİNYAL AKTİF (alım adayı) — {pair}" if buy["ok"] else f"🟡 {pair}: teyit geldi ama kurallar geçmedi",
             f"Kapanış {_g(buy['close'])} | iptal {_g(buy['iptal'])} | hedef {_g(buy['hedef'])}", "", *buy["maddeler"]]
    markup = None
    if buy["ok"]:
        risk = buy["kademe_usd"] * (buy["close"] - buy["iptal"]) / buy["close"]
        lines += ["", f"İlk kademe {buy['kademe_usd']:g} USD (risk ≈ {risk:.2f} USD). Ekleme: sonraki 15m kapanış da tetiğin üstündeyse."]
        if buy["kademe_notlari"]:
            lines.append("Kademe küçültüldü: " + "; ".join(buy["kademe_notlari"]))
        if buy["korelasyon"]:
            lines.append(f"⚠️ Açık pozisyon var ({', '.join(buy['korelasyon'])}): korelasyonlu, tek işlem sayılır.")
        lines += [*gate.card_lines(buy), signal_life.track_line("KRIPTO"),
                  f"⏳ Geçerlilik: {signal_life.LIFE_CANDLES['15m']} mum (2 saat); fiyat girişten %{signal_life.LATE_PCT['KRIPTO']:g} "
                  "yukarı kaçarsa GEÇ KALDIN. Karar senin; üstteki buton sinyalin güncel durumunu gösterir."]
        d = positions.log_decision({
            "pair": pair, "symbol": alerts_store.pair_to_symbol(pair), "timeframe": "15m", "yon": "ABOVE",
            "alarm_id": 0, "kapanis": buy["close"], "mum_ms": int(time.time() * 1000) - 900_000,
            "iptal": buy["iptal"], "hedef": buy["hedef"], "karar": "AL", "kademe_usd": float(buy["kademe_usd"]),
            "analiz": "\n".join(lines), "uyarilar": [m for m in buy["maddeler"] if not m.startswith("✅")],
            "kapi": {k: buy[k] for k in ("ok", "rr", "kademe_usd", "kademe_notlari", "risk_off", "hacim_ok", "acgozluluk",
                                         "kurallar", "kalan", "mum", "veri")},
            "kart": {"link": chart_url}})
        markup = signal_markup(d, None)
    else:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Web Panelinde Gör", url=chart_url)]])
    text = "\n".join(lines)
    msg = await bot.send_message(config.ALLOWED_CHAT_ID, text, reply_markup=markup, disable_notification=silent())
    if buy["ok"] and not isinstance(msg, HeldMessage):
        positions.update_decision(d["id"], mesaj_id=msg.message_id)
    if buy["ok"]:
        _spawn(run_council(bot, "KRIPTO", coin, d["id"], buy))


OKUL_MOVED = ("Okul modu yerine artık /sessizlik var: bildirim istemediğin saatleri kendin yazarsın.\n"
              "Örnek: /sessizlik hafta içi 09.00-16.00 ya da düz yazı: \"her hafta içi 12.00 14.30 arası bildirim atma\".\n"
              "Hiç bildirim istemezsen: /sessiz (açmak için /plan).")

QUIET_HELP = ("Örnekler:\n/sessizlik hafta içi 12.00-14.30\n/sessizlik her gün 23:00-07:30\n"
              "/sessizlik pazartesi çarşamba 09.00-12.00\nDüz yazı da olur: \"hafta sonu 10-13 arası bildirim atma\"\n"
              "Sil: /sessizlik sil 1 · hepsini sil: /sessizlik temizle")


@authorized
async def ne_yapayim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ne ASTOR — a staged plan for one holding (code) + a short explanation (model)."""
    if not context.args:
        await ask_advice(update.message)
        return
    await advice_reply(context.bot, update.effective_chat.id, context.args[0], " ".join(context.args))


async def ask_advice(message):
    groups = {}
    for p in positions.open_positions():
        if p.get("piyasa") != assets.MARKET:
            code = bist.ticker(p["symbol"]) if p.get("piyasa") == "BIST" else us.ticker(p["symbol"]) \
                if p.get("piyasa") == "ABD" else p["pair"].split("/")[0]
            groups[code] = True
    if not groups:
        await message.reply_text("Portföyünde danışılacak pozisyon yok.")
        return
    btns = [InlineKeyboardButton(c, callback_data=f"ne|{c}") for c in groups]
    await message.reply_text("Hangisi için plan istiyorsun? (ya da yaz: /ne ASTOR)",
                             reply_markup=InlineKeyboardMarkup([btns[i:i + 3] for i in range(0, len(btns), 3)]))


async def advice_reply(bot, chat_id: int, code: str, question: str):
    status = await bot.send_message(chat_id, f"⏳ {code.upper()} için plan hesaplanıyor...")
    try:
        res = await advisor.advise(code)
    except Exception as e:
        log.exception("Advice failed for %s", code)
        await status.edit_text(f"❌ {code.upper()} için veri alınamadı: {str(e)[:80]}")
        return
    await status.delete()
    if res is None:
        await bot.send_message(chat_id, f"{code.upper()} portföyünde yok (ya da yeterli fiyat geçmişi yok). Liste: /portfoy")
        return
    text, data = res
    await send_long(bot, chat_id, f"🤔 {code.upper()} — NE YAPAYIM?\n\n{text}")
    await run_analysis(bot, chat_id, f"[POZİSYON DANIŞMA] Kullanıcının sorusu: {question}", [], data=data,
                       buttons=None, allow_state_update=False)


@authorized
async def okul(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(OKUL_MOVED)


def quiet_list_text() -> str:
    items = quiet.windows()
    lines = ["🔕 Sessizlik saatlerin:" if items else "🔕 Sessizlik saati yok."]
    lines += [f"{i}. {quiet.describe(w)}" for i, w in enumerate(items, 1)]
    if quiet.is_muted_all():
        lines.append("\n/sessiz açık: şu an hiç bildirim gelmiyor. Açmak için /plan")
    lines.append("\nBu saatlerde otomatik bildirim gelmez; saat bitince birikenlerin özeti tek mesajla gelir. "
                 "Senin yazdığın komutlara cevap her zaman gelir.")
    return "\n".join(lines)


async def add_quiet_window(update, text: str) -> bool:
    w = quiet.parse_window(text)
    if not w:
        return False
    quiet.add_window(w)
    now = " Şu an bu aralıktasın: bildirimler bekletiliyor." if quiet.in_window(w, alerts_store.now_tr()) else ""
    await update.message.reply_text(f"✅ Tamam: {quiet.describe(w)} arası bildirim göndermeyeceğim.{now}\n\n" + quiet_list_text())
    return True


@authorized
async def sessizlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args).strip()
    low = raw.lower()
    if not raw:
        await update.message.reply_text(quiet_list_text() + "\n\n" + QUIET_HELP)
        return
    if low in ("temizle", "kapat", "sil hepsi", "hepsini sil"):
        quiet.clear_windows()
        await update.message.reply_text("🔔 Tüm sessizlik saatleri silindi.")
        await send_held(context.bot)
        return
    m = re.fullmatch(r"sil\s+(\d+)", low)
    if m:
        gone = quiet.remove_window(int(m[1]))
        await update.message.reply_text((f"🗑 Silindi: {quiet.describe(gone)}\n\n" if gone else "Bu numarada sessizlik yok.\n\n")
                                        + quiet_list_text())
        return
    if not await add_quiet_window(update, raw):
        await update.message.reply_text("Saatleri anlayamadım.\n" + QUIET_HELP)


@authorized
async def sessiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].lower() in ("kapat", "kapa", "off", "bitti"):
        quiet.set_muted_all(False)
        await update.message.reply_text("🔔 Sessiz mod kapandı.")
        await send_held(context.bot)
        return
    quiet.set_muted_all(True)
    await update.message.reply_text("🔕 Sessiz mod açık: hiçbir otomatik bildirim gelmeyecek (alarmlar, sinyaller, plan "
                                    "güncellemeleri). Olanlar biriktirilir.\nAçmak için /plan yaz; birikenlerin özeti gelir.")


async def send_held(bot):
    """Everything held while quiet, as one message (as soon as nothing is muted any more)."""
    if quiet.muted():
        return
    held = quiet.take_held()
    if held:
        await send_long(bot, config.ALLOWED_CHAT_ID, quiet.digest(held))


async def user_alarm_job(context: ContextTypes.DEFAULT_TYPE):
    """Site users' own alarms (checked by the web service on closed candles): deliver to their linked chat."""
    try:
        events = await web_sync.alarm_events()
    except Exception as e:
        log.warning("User alarm events not fetched: %s", e)
        return
    for ev in events:
        link = f"{config.PUBLIC_URL}/app/grafik?kod={ev['kod']}&piyasa={ev['piyasa']}"
        try:
            chat = ev.get("chat_id") or (config.ALLOWED_CHAT_ID if ev.get("sahip") else None)
            if not chat:
                continue
            if ev.get("kod"):
                text = ev["metin"] + "\nGerçek emir gönderilmedi; karar senin."
                buttons = [InlineKeyboardButton("📊 Grafiği aç", url=link),
                           InlineKeyboardButton("⏰ Alarmlarım", url=f"{config.PUBLIC_URL}/app/alarmlarim")]
            else:  # weekly summary
                text = ev["metin"]
                buttons = [InlineKeyboardButton("💼 Portföyüm", url=f"{config.PUBLIC_URL}/app/portfoyum")]
            await context.bot.send_message(chat, text, reply_markup=InlineKeyboardMarkup([buttons]))
        except BadRequest as e:  # chat gone / blocked the bot: do not retry forever
            log.warning("User alarm %s not delivered: %s", ev["id"], e)
        except Exception as e:
            log.warning("User alarm %s delivery failed, will retry: %s", ev["id"], e)
            continue
        try:
            await web_sync.alarm_event_sent(ev["id"])
        except Exception as e:
            log.warning("User alarm %s not marked sent: %s", ev["id"], e)


async def held_digest_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await send_held(context.bot)
    except Exception as e:
        log.warning("Held notification digest failed: %s", e)


@authorized
async def haber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin = context.args[0].upper().replace("/USDT", "") if context.args else None
    items = [n for n in await news.get_news() if n["kripto_ilgisi"] != "düşük"]
    if coin:
        items = [n for n in items if coin in n["coinler"]]
    if not items:
        await update.message.reply_text(f"Son haberlerde {coin or 'kripto'} ile ilgili başlık yok.")
        return
    lines = [f"📰 Son haberler{' — ' + coin if coin else ''} (kaynak güvenilirliği ≠ piyasa etkisi)"]
    for n in items[:12]:
        tags = [n["tur"]] + (n["coinler"] or []) + (["katalizör adayı"] if n["katalizor_adayi"] else [])
        lines.append(f"\n{n['zaman_tr']} · {', '.join(n['kaynaklar'])} ({n['kaynak_guvenilirligi']}, {n['dogrulama']})\n"
                     f"{n['baslik']}\n[{' · '.join(tags)}]")
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines))


@authorized
async def tara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = context.args[0].lower() if context.args else ""
    if arg in ("kapat", "kapali", "kapalı", "off"):
        scanner.set_enabled(False)
        await update.message.reply_text("⏹ Otomatik tarayıcı kapandı. Kendi planların ve alarmların çalışmaya devam eder.")
        return
    if arg in ("ac", "aç", "acik", "açık", "on") and not config.BUY_SIGNALS:
        await update.message.reply_text("Otomatik tarayıcı kapalı tutuluyor: geçmiş veri testinde kırılım kuralı "
                                        "ortalama −0,21R kaybettirdi. Kanıtlanmış bir kural gelince açılacak.")
        return
    if arg in ("ac", "aç", "acik", "açık", "on"):
        scanner.set_enabled(True)
        await update.message.reply_text("▶️ Otomatik tarayıcı açık: her 15 dk'da takip listesi taranır.")
        return
    chat = update.effective_chat.id
    if arg in ("", "kripto", "hepsi"):
        state = "açık" if scanner.enabled() else "kapalı"
        await update.message.reply_text(
            f"🪙 Kripto: {len(config.WATCHLIST)} coin son kapanan 15m mumda taranıyor (otomatik tarayıcı {state})...\n"
            "Aranan: 4h/1d direnç bölgesinin hacimli KAPANIŞLA kırılması (15m SMA50 üstünde, kovalama değil).")
        await run_scanner(context.bot, announce_empty_to=chat)
    if arg in ("", "bist", "hepsi"):
        await update.message.reply_text(
            f"🇹🇷 BIST: {len(bist.watchlist())} hisse son GÜNLÜK kapanışta taranıyor "
            "(orta/uzun vade: haftalık trend + kırılım ya da geri çekilme; giriş sonraki günlük kapanış teyidiyle)...")
        await run_bist_scan(context.bot, announce_to=chat)


async def tara_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    legacy = {"kapat", "kapali", "kapalı", "off", "ac", "aç", "acik", "açık", "on", "kripto", "bist", "hepsi"}
    if update.effective_chat.id == config.ALLOWED_CHAT_ID and (
            not context.args or context.args[0].casefold() in legacy):
        return await tara(update, context)
    if update.effective_chat.type != "private" or not context.args:
        await update.message.reply_text(f"Kayıtlı stratejin için: /tara StratejiAdı. Stratejiyi {config.PUBLIC_URL}/app/stratejiler sayfasında oluştur.")
        return
    if not chat_rate_ok(update.effective_chat.id, "public", 30, 600):
        await update.message.reply_text("Çok sık mesaj gönderdin; birkaç dakika sonra tekrar dene.")
        return
    try:
        cmd = await web_sync.telegram_run_strategy(update.effective_chat.id, " ".join(context.args))
        await update.message.reply_text(f"🔎 {', '.join(context.args)} taraması sıraya alındı. "
                                        "BIST 100 bilanço verileri ilk taramada zaman alabilir; sonuç buraya ve Son Analizlerim'e gelecek. "
                                        f"İstek: {cmd.get('request_id', '')}")
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception:
        log.exception("Telegram strategy request failed")
        await update.message.reply_text("Strateji taraması şu an başlatılamadı.")


async def kriz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not web_sync.enabled():
        return
    if not chat_rate_ok(update.effective_chat.id, "public", 30, 600):
        await update.message.reply_text("Çok sık mesaj gönderdin; birkaç dakika sonra tekrar dene.")
        return
    try:
        plan = await web_sync.telegram_risk_proposal(update.effective_chat.id)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception:
        log.exception("Telegram risk proposal failed")
        await update.message.reply_text("Kriz planı şu an hazırlanamadı; biraz sonra tekrar dene.")
        return
    count = len(plan.get("suggestions") or [])
    await update.message.reply_text(
        f"🛡 Kriz planı hazır: risk hedefi %{plan['old_target_pct']:g} → %{plan['new_target_pct']:g}; "
        f"{count} stop yükseltme önerisi. Hiçbir değişiklik uygulanmadı. Planı sitede inceleyip seçerek uygula.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Web Panelinde Gör", url=f"{config.PUBLIC_URL}/app/kriz")]]))


async def send_bist_signal(bot, sym: str, g: dict):
    """BIST gate result for a confirmed 1h close: ŞİMDİ AL with whole lots, or what failed."""
    tick = bist.ticker(sym)
    if not config.BUY_SIGNALS:
        await bot.send_message(config.ALLOWED_CHAT_ID,
                               f"📍 {tick} (BIST): planının kapanış teyidi geldi (kapanış {_g(g['giris'])} TL, iptal {_g(g['iptal'])}, "
                               f"hedef {_g(g['hedef'])}).\n{config.NO_SIGNAL_NOTE}", disable_notification=silent())
        return
    tf_label = "günlük" if (g.get("mum") or {}).get("zaman_dilimi") == "1d" else "1s"
    head = (f"🟢 ALIM ADAYI (BIST, orta/uzun vade) — {tick}" if g["ok"] and tf_label == "günlük" else
            f"🟢 SİNYAL AKTİF (BIST, alım adayı) — {tick}" if g["ok"] else f"🟡 {tick} (BIST): {tf_label} kapanış geldi ama kurallar geçmedi")
    lines = [head, f"Kapanış {_g(g['giris'])} TL (veri ~15 dk gecikmeli) | iptal {_g(g['iptal'])} | hedef {_g(g['hedef'])}",
             "", *g["maddeler"]]
    markup = None
    if g["ok"]:
        costs_per_lot = g["giris"] * 2 * (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT) / 100
        risk = g["lot"] * (g["giris"] - g["iptal"] + costs_per_lot)
        daily = (g.get("mum") or {}).get("zaman_dilimi") == "1d"
        lines += ["", f"Bütçe: {g['butce_tl']:,.0f} TL | ilk kademe: {g['lot']} adet ≈ {g['kademe_tl']:,.0f} TL "
                      f"(planlanan risk ≈ {risk:,.0f} TL). "
                      "Emirden önce aracı kurumda anlık fiyatı, makası ve tavanı kontrol et; fiyat kaçtıysa pas.",
                  ("Orta/uzun vade: günlük kapanış teyidi geldi. Girişi yarın seans içinde yap, açılış boşluğunu kovalama. "
                   "Hedef haftalar-aylar; çıkış haftalık kapanışla değerlendirilir. Ekleme: haftalık kapanış da seviyenin üstündeyse."
                   if daily else "Kesinlik yok: kurallar geçti demektir. Ekleme: günlük kapanış da seviyenin üstündeyse.")]
        d = positions.log_decision({
            "pair": sym, "symbol": sym, "timeframe": "1h", "yon": "ABOVE", "alarm_id": 0, "piyasa": "BIST",
            "kapanis": g["giris"], "mum_ms": g["mum_ms"], "iptal": g["iptal"], "hedef": g["hedef"],
            "karar": "AL", "kademe_usd": g["kademe_tl"], "lot": g["lot"], "analiz": "\n".join(lines),
            "gostergeler": g["gostergeler"], "gostergeler_tf": "1d",
            "uyarilar": [m for m in g["maddeler"] if not m.startswith("✅")],
            "kapi": {k: g.get(k) for k in ("ok", "rr", "kademe_tl", "lot", "kademe_notlari",
                                             "risk_off", "hacim_ok", "kurallar", "kalan", "mum")}})
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Aldım", callback_data=f"al|{d['id']}"),
                                        InlineKeyboardButton("⏭ Pas", callback_data=f"pas|{d['id']}")]])
    text = "\n".join(lines)
    await bot.send_message(config.ALLOWED_CHAT_ID, text, reply_markup=markup, disable_notification=silent())
    if g["ok"]:
        _spawn(run_council(bot, "BIST", tick, d["id"], g))


async def send_chart(bot, df, title: str, levels: dict, caption: str):
    """Candles + SMA20/50/200, RSI, ATR and volume panels with the plan levels drawn in."""
    try:
        png = await asyncio.to_thread(charts.render, df, title, levels)
        await bot.send_photo(config.ALLOWED_CHAT_ID, photo=png, caption=caption[:1000], disable_notification=silent())
    except Exception:
        log.exception("Chart failed for %s", title)


async def bist_alarm_fire(bot, pair: str, alert: dict, df):
    """A BIST close alarm fired: chart, BIST gate, and a DeepSeek comment (same shape as crypto alarms)."""
    tick = bist.ticker(pair)
    last = df.iloc[-1]
    close = float(last.close)
    op = ">" if alert["yon"] == "ABOVE" else "<"
    caption = (f"🔔 {tick} (BIST) {alert['timeframe']} KAPANIŞ {alert['yon']}\n"
               f"Tetik {alert['tetik']:g} | Kapanış {close:g} ({op} tetik) · veri ~15 dk gecikmeli")
    await send_chart(bot, df, f"{tick} {alert['timeframe']}", {k: alert.get(k) for k in ("tetik", "iptal", "hedef")}, caption)
    async with httpx.AsyncClient() as client:
        g = await bist_signals.evaluate(client, symbol=pair, entry=close, iptal=alert.get("iptal"), hedef=alert.get("hedef"),
                                        level=alert["tetik"], hour_bar=last if alert["timeframe"] == "1h" else None)
        data = await bist_market_data(client, tick)
    if alert["yon"] == "ABOVE":
        await send_bist_signal(bot, pair, g)
    data["ALARM"] = {"pair": pair, "zaman_dilimi": alert["timeframe"], "yon": alert["yon"], "tetik": alert["tetik"],
                     "iptal": alert.get("iptal"), "hedef": alert.get("hedef"), "kapanis": close,
                     "kapi": {"gecti": g["ok"], "kurallar": g["maddeler"]}}
    await run_analysis(bot, config.ALLOWED_CHAT_ID,
                       f"[BIST] {tick} alarmı tetiklendi ({alert['timeframe']} kapanış {close:g} {op} {alert['tetik']:g}). "
                       "Kod kapısı sonucunu değiştirme; ŞU AN → Tetik → Teyit → İptal → Hedef formatında kısa yorum.",
                       [], data=data, buttons=None, allow_state_update=False)


async def bist_alarm_cmd(update: Update, args: list[str]):
    usage = ("Kullanım: /bist alarm THYAO ABOVE 300 [1h|1d] [iptal=285] [hedef=330] [cd=1d]\n"
             "Sadece KAPANIŞ: 1h = saatlik kapanış (seans içinde), 1d = günlük kapanış (18:40). Veri ~15 dk gecikmeli.")
    pos, kv = _opts(args)
    if len(pos) < 3 or pos[1].upper() not in ("ABOVE", "BELOW") or set(kv) - {"iptal", "hedef", "cd"}:
        await update.message.reply_text(usage)
        return
    tf = pos[3].lower() if len(pos) > 3 else "1h"
    if tf not in ("1h", "1d"):
        await update.message.reply_text(usage)
        return
    tick, direction = bist.ticker(pos[0]), pos[1].upper()
    try:
        trigger, stop, target = _float(pos[2]), _float(kv.get("iptal")), _float(kv.get("hedef"))
    except ValueError:
        await update.message.reply_text(usage)
        return
    cooldown = kv.get("cd", "1d" if tf == "1d" else "4h").lower()
    above = direction == "ABOVE"
    errors = []
    if not alerts_store.parse_duration(cooldown):
        errors.append("cd 4h / 1d formatında olmalı")
    if stop is not None and (stop >= trigger if above else stop <= trigger):
        errors.append(f"{direction} için iptal tetiğin {'altında' if above else 'üstünde'} olmalı")
    if target is not None and (target <= trigger if above else target >= trigger):
        errors.append(f"{direction} için hedef tetiğin {'üstünde' if above else 'altında'} olmalı")
    try:
        async with httpx.AsyncClient() as client:
            price = await bist.last_price(client, tick)
    except Exception:
        errors.append(f"{tick} BIST'te bulunamadı")
    if errors:
        await update.message.reply_text("❌ " + "\n❌ ".join(errors) + "\n\n" + usage)
        return
    pair = bist.yahoo_symbol(tick)
    alert = alerts_store.add_alert(pair, {"tetik": trigger, "yon": direction, "timeframe": tf, "cooldown": cooldown,
                                          "iptal": stop, "hedef": target, "hacim_sart": True})
    rr = f" | R/R {abs(target - trigger) / abs(trigger - stop):.2f}" if stop and target else ""
    await update.message.reply_text(
        f"✅ BIST alarmı kuruldu: {pair} #{alert['id']} KAPANIŞ {direction} {trigger:g} {tf}{rr}\n"
        f"Şu an {price:g} TL. Tetiklenince grafik + BIST kapısı + yorum gelir.\n"
        f"Liste: /view_alerts · Silmek: /cancel_alert {pair} {alert['id']}")


async def bist_news_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, tick: str | None):
    items = await news.bist_news(tick)
    if not items:
        await update.message.reply_text("Haber bulunamadı.")
        return
    lines = [f"📰 BIST haberleri{' — ' + tick if tick else ''} (Google News; kaynak güvenilirliği ≠ piyasa etkisi)"]
    for n in items[:12]:
        tags = [n["tur"]] + (["katalizör adayı"] if n["katalizor_adayi"] else [])
        lines.append(f"\n{n['zaman_tr']} · {', '.join(n['kaynaklar'])} ({n['kaynak_guvenilirligi']}, {n['dogrulama']})\n"
                     f"{n['baslik']}\n[{' · '.join(tags)}]")
    lines.append("\nKAP bildiriminin aslını kap.org.tr'den kontrol et.")
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines))



async def bist_makro_text() -> str:
    """BIST version of /makro: index gate, lira, USD-based index, Turkish calendar, global regime."""
    async with httpx.AsyncClient() as client:
        g = await bist.index_gate(client)
    m = await macro.summary()
    rj = m.get("rejim", {})
    lines = [f"🇹🇷 BIST MAKRO — endeks kapısı: {g['durum']}",
             f"XU100 {g['xu100_kapanis']} | SMA50 {g['sma50']} | SMA200 {g['sma200']} | RSI {g['rsi14']}",
             f"20 gün: %{g['getiri_20g_yuzde']} TL · %{g.get('xu100_dolar_bazli_20g_yuzde', '—')} dolar bazlı",
             f"USD/TRY {g.get('usdtry')} (5 gün %{g.get('usdtry_5g_yuzde')})"
             + (" ⚠️ TL baskı altında: TL bazlı yükseliş dolar bazında zayıf olabilir" if g.get("usdtry_baski") else ""),
             f"Küresel rüzgar (FRED rejimi): {rj.get('etiket', 'hesaplanamadı')} ({rj.get('skor', '—')})",
             "", "📅 Türkiye takvimi (14 gün):"]
    evs = bist.tr_events(14)
    lines += [f"  {datetime.fromisoformat(e['tr_zaman']).strftime('%d.%m %H:%M')} {e['olay']} ({e['kalan_saat']:+g} sa)"
              for e in evs] or ["  yok"]
    risk = bist.tr_event_risk()
    lines.append("\n" + (f"❌ {risk['olay']} yakın: BIST'te yeni giriş yok." if risk else
                         "✅ 2 saat içinde TCMB/TÜİK verisi yok."))
    lines.append("Not: yabancı payı, açığa satış ve VİOP verisi ücretsiz kaynakta yok (kriptodaki /vadeli'nin BIST karşılığı yok).")
    return "\n".join(lines)


async def bist_market_data(client, tick: str) -> dict:
    budget = bist.budget_tl()
    return {"BIST_HISSE": await bist.snapshot(client, tick), "BIST100_KAPI": await bist.index_gate(client),
            "BIST_BUTCE": {"tl": budget, "ilk_kademe_yuzde": config.BIST_FIRST_TRANCHE_PCT,
                           "temkinli_kademe_yuzde": config.BIST_REDUCED_TRANCHE_PCT,
                           "acik_pozisyon_tl": bist_signals.open_bist_tl(),
                           "azami_stop_riski_yuzde": config.BIST_MAX_RISK_PCT},
            "BIST_HABERLER": await news.bist_for_model(tick),
            "TR_TAKVIM": bist.tr_events(7),
            "BIST_TEMEL": await _fundamentals_or_error(tick)}


async def _fundamentals_or_error(tick: str) -> dict:
    try:
        return await fundamentals.report(tick)
    except Exception as e:
        return {"hata": f"mali tablo alınamadı ({str(e)[:80]})"}


async def bist_hourly_job(context: ContextTypes.DEFAULT_TYPE):
    if not bist.session_open():
        return
    try:
        fired, notices = await bist_signals.check_alarms(("1h",))
        for pair, a, text in notices:
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())
        for pair, a, df in fired:
            await bist_alarm_fire(context.bot, pair, a, df)
    except Exception:
        log.exception("BIST 1h alarm check failed")
    try:
        events = await bist_signals.hourly_check()
    except Exception:
        log.exception("BIST hourly check failed")
        return
    await send_bist_events(context.bot, events, "1h")


async def send_bist_events(bot, events: list[dict], tf: str):
    """Plan events from the BIST follow-up (1h in short-term mode, 1d in the default medium-term mode)."""
    label = "günlük" if tf == "1d" else "1s"
    for e in events:
        tick = bist.ticker(e["sembol"])
        if e["tur"] == "kapi":
            try:
                async with httpx.AsyncClient() as client:
                    hdf = market.add_indicators(await bist.fetch(client, e["sembol"], tf))
                await send_chart(bot, hdf, f"{tick} {tf}",
                                 {k: e["kapi"].get(k) for k in ("iptal", "hedef")} | {"tetik": e["plan"].get("tetik")},
                                 f"📈 {tick} (BIST) {label} — tetik/iptal/hedef çizili")
            except Exception:
                log.exception("BIST chart failed")
            await send_bist_signal(bot, e["sembol"], e["kapi"])
            if e["kapi"]["ok"] and config.BUY_SIGNALS:
                async with httpx.AsyncClient() as client:
                    data = await bist_market_data(client, tick)
                await run_analysis(bot, config.ALLOWED_CHAT_ID,
                                   f"[BIST ŞİMDİ AL] {tick}: {label} kapanış teyidi geldi, kod kapısı GEÇTİ. "
                                   "Orta/uzun vade için kısa yorum yap.",
                                   [], data=data, buttons=None, allow_state_update=False)
        else:
            if e["tur"] == "yaklasiyor" and alerts_store.is_quiet():
                continue
            text = f"🇹🇷 {tick}: {'👀 YAKLAŞIYOR — ' if e['tur'] == 'yaklasiyor' else ''}{e['metin']}"
            await bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())


async def bist_daily_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        fired, notices = await bist_signals.check_alarms(("1d",))
        for pair, a, text in notices:
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())
        for pair, a, df in fired:
            await bist_alarm_fire(context.bot, pair, a, df)
    except Exception:
        log.exception("BIST 1d alarm check failed")
    if not bist.calendar_current():
        s = alerts_store.load_settings()
        if not s.get("bist_takvim_uyarildi"):
            await context.bot.send_message(config.ALLOWED_CHAT_ID,
                "BIST taraması durdu: 2027 BIST 30 listesi ve seans takvimi güncellenmeli.")
            s["bist_takvim_uyarildi"] = True
            alerts_store.save_settings(s)
        return
    if not bist.trading_day():
        return
    try:  # medium/long-term mode: yesterday's candidates and manual plans are confirmed on today's final close
        await send_bist_events(context.bot, await bist_signals.daily_check(), "1d")
    except Exception:
        log.exception("BIST daily plan check failed")
    if bist.budget_tl() is None or not alerts_store.load_settings().get("bist_tarayici", True):
        return
    await run_bist_scan(context.bot)


async def run_bist_scan(bot, announce_to: int | None = None):
    if bist.budget_tl() is None:
        if announce_to:
            await bot.send_message(announce_to, "Önce BIST bütçesini gir: /bist butce 5000")
        return
    try:
        found = await bist_signals.daily_scan()
    except Exception:
        log.exception("BIST daily scan failed")
        if announce_to:
            await bot.send_message(announce_to, "BIST taraması hata verdi, /get_logs.")
        return
    for c in found:
        touch = f" ({c['dokunma']} dokunma)" if c["dokunma"] is not None else ""
        await bot.send_message(config.ALLOWED_CHAT_ID,
            f"👀 BIST ADAY — {c['hisse']} | {c['strateji']}{touch}\n"
            f"Günlük kapanış {_g(c['kapanis'])} TL (%{c['degisim']:+.1f}); "
            f"hacim x{c['hacim_orani']:.2f}; BIST100'e göre 20g güç {c['rs']:+.1f} puan.\n"
            f"Plan: tetik {_g(c['tetik'])} | iptal {_g(c['iptal'])} | hedef {_g(c['hedef'])} ({c['hedef_turu']})\n"
            "Henüz AL değil: sonraki seansta 1 saatlik kapanış ve kod kapısı bekleniyor.",
            disable_notification=silent())
    if announce_to and not found:
        await bot.send_message(announce_to, "BIST taraması bitti: son günlük kapanışta yeni strateji adayı yok.")


async def bist_aldim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Record an actual BIST fill supplied by the user, with whole lots and a tracked stop/target."""
    usage = "Kullanım: /bist aldim THYAO 320 4 stop=300 hedef=360 (gerçek fiyat, tam sayı adet)"
    args, kv = _opts(context.args[1:])
    if len(args) != 3 or set(kv) != {"stop", "hedef"}:
        await update.message.reply_text(usage)
        return
    tick = bist.ticker(args[0])
    if not re.fullmatch(r"[A-Z0-9]{4,6}", tick) or not args[2].isdigit() or int(args[2]) < 1:
        await update.message.reply_text(usage)
        return
    try:
        entry, stop, target = _float(args[1]), _float(kv["stop"]), _float(kv["hedef"])
    except ValueError:
        await update.message.reply_text(usage)
        return
    if not all(math.isfinite(v) and v > 0 for v in (entry, stop, target)) or not stop < entry < target:
        await update.message.reply_text("Seviyeler pozitif ve stop < giriş < hedef olmalı.\n" + usage)
        return
    lots = int(args[2])
    amount = entry * lots
    before = bist_signals.open_bist_tl()
    budget = bist.budget_tl()
    symbol = bist.yahoo_symbol(tick)
    pos = positions.open_position(symbol, entry, amount, stop, target, "1h", source="BIST elle",
                                  market_name="BIST", symbol=symbol)
    state = store.load_state()
    if symbol in state["planlar"]:
        state["planlar"][symbol]["pozisyon"] = True
        store.save_state(state)
    warnings = []
    violations = []
    if budget is None:
        warnings.append("BIST bütçesi girilmedi; /bist butce 5000 ile sınırları etkinleştir")
    else:
        cap = budget * config.BIST_FIRST_TRANCHE_PCT / 100
        if before + amount > cap:
            violations.append(f"açık BIST ilk kademeleri {before + amount:,.0f} TL, {cap:,.0f} TL sınırını aşıyor")
        risk = lots * (entry - stop + entry * 2 * (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT) / 100)
        if risk > budget * config.BIST_MAX_RISK_PCT / 100:
            violations.append(f"planlanan stop riski {risk:,.0f} TL, bütçenin %{config.BIST_MAX_RISK_PCT:g} sınırını aşıyor")
    warnings.extend(violations)
    for warning in violations:
        positions.add_violation(pos["id"], warning, "limit")
    await update.message.reply_text(
        f"✅ BIST alımı kaydedildi: {_position_line(pos)}\n"
        "Stop ve hedef 1 saatlik kapanışla izlenir. Gerçekleşen fiyat/adet düzeltmesi: "
        f"/duzelt {pos['id']} giris=FIYAT adet=N"
        + ("\n⚠️ " + "; ".join(warnings) if warnings else ""))
    await ask_buy_reason(update.message, pos)


async def bist_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Historical test of a stated 1h level, not of the full daily BIST setup."""
    usage = "Kullanım: /bist backtest THYAO 320 stop=300 hedef=360 gun=90 (en çok 180 gün)"
    args, kv = _opts(context.args[1:])
    if len(args) != 2 or set(kv) - {"stop", "hedef", "gun"} or not {"stop", "hedef"} <= set(kv):
        await update.message.reply_text(usage)
        return
    tick = bist.ticker(args[0])
    if not re.fullmatch(r"[A-Z0-9]{4,6}", tick):
        await update.message.reply_text(usage)
        return
    try:
        trigger, stop, target = _float(args[1]), _float(kv["stop"]), _float(kv["hedef"])
        days = int(kv.get("gun", 90))
    except ValueError:
        await update.message.reply_text(usage)
        return
    if not all(math.isfinite(v) and v > 0 for v in (trigger, stop, target)) or not stop < trigger < target or not 1 <= days <= 180:
        await update.message.reply_text("Stop < tetik < hedef ve 1–180 gün olmalı.\n" + usage)
        return
    status = await update.message.reply_text("⏳ BIST saatlik mumları hesaplanıyor...")
    try:
        result = await backtest.run(bist.yahoo_symbol(tick), "ABOVE", trigger, "1h", days, stop, target,
                                    fee_pct=config.BIST_FEE_PCT, slippage_pct=config.BIST_SLIPPAGE_PCT,
                                    market_name="BIST")
    except market.SymbolNotFound:
        await status.edit_text(f"❌ {tick} Yahoo'da bulunamadı.")
        return
    except Exception:
        log.exception("BIST backtest failed for %s", tick)
        await status.edit_text("❌ BIST geçmiş verisi alınamadı. /get_logs")
        return
    if "hata" in result:
        await status.edit_text(f"❌ {result['hata']}")
        return
    total = result["tum"]
    vol = result["hacim_teyitli"]
    await status.edit_text(
        f"🧪 BIST SEVİYE TESTİ — {tick}, son {days} gün (1s kapanış)\n"
        f"Tetik {trigger:g} | stop {stop:g} | hedef {target:g} TL\n"
        f"{result['mum_sayisi']} mum | {total['islem']} tetik | hedef {total['hedef']} | stop {total['stop']} | açık {total['acik']}\n"
        f"Sonuçlananlarda hedef oranı %{total['isabet_yuzde'] if total['isabet_yuzde'] is not None else '—'}; "
        f"net toplam {total['toplam_R_net'] if total['toplam_R_net'] is not None else '—'}R\n"
        f"Hacim teyitli: {vol['islem']} tetik, hedef {vol['hedef']}, stop {vol['stop']}\n"
        f"Maliyet: her tarafta komisyon %{config.BIST_FEE_PCT:g} + kayma %{config.BIST_SLIPPAGE_PCT:g}.\n"
        "Bu yalnız belirtilen seviyenin kapanış testidir; günlük strateji, BIST 100 kapısı ve gerçek emir fiyatını içermez.")


@authorized
async def bist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = context.args[0].lower() if context.args else ""
    chat = update.effective_chat.id
    if arg in ("butce", "bütçe"):
        if len(context.args) == 1:
            current = bist.budget_tl()
            await update.message.reply_text(
                f"BIST bütçesi: {current:,.0f} TL" if current else
                "BIST bütçesi girilmedi. Kullanım: /bist butce 5000 (TL, pozitif tam sayı)")
            return
        raw = " ".join(context.args[1:]).strip()
        if not re.fullmatch(r"[1-9]\d*|[1-9]\d{0,2}(?:[. ]\d{3})+", raw):
            await update.message.reply_text("Bütçe pozitif tam TL olmalı. Örnek: /bist butce 5000")
            return
        budget = int(raw.replace(".", "").replace(" ", ""))
        if budget > 1_000_000_000:
            await update.message.reply_text("BIST bütçesi en fazla 1.000.000.000 TL olabilir.")
            return
        s = alerts_store.load_settings()
        s["bist_budget_tl"] = budget
        alerts_store.save_settings(s)
        open_tl = bist_signals.open_bist_tl()
        room = max(0, budget * config.BIST_FIRST_TRANCHE_PCT / 100 - open_tl)
        await update.message.reply_text(
            f"✅ BIST bütçesi {budget:,.0f} TL kaydedildi. Normal ilk kademe en fazla "
            f"{budget * config.BIST_FIRST_TRANCHE_PCT / 100:,.0f} TL; temkinli kademe "
            f"{budget * config.BIST_REDUCED_TRANCHE_PCT / 100:,.0f} TL; "
            f"azami işlem riski {budget * config.BIST_MAX_RISK_PCT / 100:,.0f} TL. "
            f"Açık pozisyonlar sonrası kademe alanı {room:,.0f} TL."
            + (" Mevcut pozisyonlar yeni sınırı aşıyor; yeni AL sinyali durur." if open_tl > budget * config.BIST_FIRST_TRANCHE_PCT / 100 else ""))
        return
    if arg == "aldim":
        await bist_aldim(update, context)
        return
    if arg == "makro":
        await update.message.reply_text(await bist_makro_text())
        return
    if arg == "alarm":
        await bist_alarm_cmd(update, context.args[1:])
        return
    if arg == "haber":
        await bist_news_cmd(update, context, bist.ticker(context.args[1]) if len(context.args) > 1 else None)
        return
    if arg in ("portfoy", "portföy"):
        sub = context.args[1].lower() if len(context.args) > 1 else ""
        if sub == "ekle":
            await portfolio_add(update, context.args[2:], market_name="BIST")
        elif sub == "analiz":
            await portfolio_ai(update, context, only="BIST")
        elif sub == "detay":
            await portfolio_show(update, context, only="BIST")
        else:
            await portfolio_summary(update, context, only="BIST")
        return
    if arg == "backtest":
        await bist_backtest(update, context)
        return
    if arg in ("kapat", "off"):
        s = alerts_store.load_settings(); s["bist_tarayici"] = False; alerts_store.save_settings(s)
        await update.message.reply_text("⏹ BIST günlük tarayıcı kapandı. /bist ac ile açılır.")
        return
    if arg in ("ac", "aç", "on"):
        s = alerts_store.load_settings(); s["bist_tarayici"] = True; alerts_store.save_settings(s)
        await update.message.reply_text("▶️ BIST günlük tarayıcı açık (hafta içi 18:35)."
                                        + (" Aday taraması için önce /bist butce 5000." if bist.budget_tl() is None else ""))
        return
    if arg == "tara":
        if bist.budget_tl() is None:
            await update.message.reply_text("Önce BIST bütçesini gir: /bist butce 5000")
            return
        await update.message.reply_text("🔎 BIST 30 son günlük kapanışta taranıyor...")
        await run_bist_scan(context.bot, announce_to=chat)
        return
    if arg:
        tick = bist.ticker(context.args[0])
        async with httpx.AsyncClient() as client:
            try:
                data = await bist_market_data(client, tick)
            except market.SymbolNotFound:
                await update.message.reply_text(f"❌ {tick} bulunamadı (Yahoo: {bist.yahoo_symbol(tick)}).")
                return
        await run_analysis(context.bot, chat, f"[BIST] {tick} analiz et.", [], data=data,
                           footer="BIST planı kaydedildiyse 1 saatlik kapanışlarla otomatik izlenir. Fiyat Yahoo'da gecikmelidir.",
                           buttons=None)
        return
    async with httpx.AsyncClient() as client:
        g = await bist.index_gate(client)
    plans = [(k, p) for k, p in store.load_state()["planlar"].items() if bist_signals.is_bist_plan(k)]
    budget = bist.budget_tl()
    open_tl = bist_signals.open_bist_tl()
    cap = budget * config.BIST_FIRST_TRANCHE_PCT / 100 if budget else 0
    candidate_count = sum(bool(p.get("bist_aday")) and not p.get("sinyal_verildi") for _, p in plans)
    held = [p for p in positions.open_positions() if p.get("piyasa") == "BIST"]
    lines = [f"🇹🇷 BIST — endeks kapısı: {g['durum']}",
             f"XU100 {g['xu100_kapanis']} | SMA50 {g['sma50']} | SMA200 {g['sma200']} | RSI {g['rsi14']}",
             f"20 gün: %{g['getiri_20g_yuzde']} (dolar bazlı %{g.get('xu100_dolar_bazli_20g_yuzde', '—')})",
             f"USD/TRY {g.get('usdtry')} (5 gün %{g.get('usdtry_5g_yuzde')})" + (" ⚠️ TL baskı altında" if g.get("usdtry_baski") else ""),
             f"Seans: {'AÇIK' if bist.session_open() else 'KAPALI'} (hafta içi 10:00–18:00, veri ~15 dk gecikmeli)",
             f"Bütçe: {f'{budget:,.0f} TL' if budget else 'GİRİLMEDİ — /bist butce 5000'}",
             f"İlk kademe tavanı {cap:,.0f} TL | açık {open_tl:,.0f} TL | kalan {max(0, cap - open_tl):,.0f} TL",
             f"İşlem başı azami planlanan risk: {budget * config.BIST_MAX_RISK_PCT / 100:,.0f} TL" if budget else "Bütçe girilene kadar AL sinyali yok.",
             f"Planlar: {', '.join(k for k, _ in plans) if plans else 'yok'} | aday {candidate_count} | açık pozisyon {len(held)}",
             "Stratejiler: hacimli direnç kırılımı; SMA20 trend geri çekilmesi. Günlük kurulum → sonraki seans saatlik kapanış → karar kapısı.",
             "", "Komutlar: /bist butce TL · /bist THYAO · /bist tara · /bist backtest HISSE TETIK stop=X hedef=Y · /bist aldim HISSE FIYAT ADET stop=X hedef=Y · /bist kapat|ac",
             "Takip: /plan · /pozisyonlar · /rapor · /sat ID FIYAT"]
    if not bist.calendar_current():
        lines.insert(1, "❌ 2027 BIST 30 listesi ve seans takvimi güncellenene kadar otomatik sinyal kapalı.")
    if g["durum"] == "KAPALI":
        lines.insert(1, "❌ Endeks SMA50 ve SMA200 altında: BIST'te ŞİMDİ AL verilmez.")
    await update.message.reply_text("\n".join(lines))


# --- portfolio & exit analysis (crypto and BIST share one engine) -------------------------------

async def _detect_market(tick: str) -> str | None:
    """KRIPTO if Binance lists TICK/USDT, BIST if Yahoo lists TICK.IS (".IS" forces BIST)."""
    t = tick.upper()
    if assets.normalize(t):
        return assets.MARKET
    if t.endswith(".US"):
        return "ABD"
    async with httpx.AsyncClient() as client:
        if not t.endswith(".IS"):
            try:
                await market.order_filters(client, t + config.QUOTE)
                return "KRIPTO"
            except Exception:
                pass
        try:
            await bist.last_price(client, t)
            return "BIST"
        except Exception:
            pass
        try:
            return "ABD" if not t.endswith(".IS") and await us.is_us_ticker(client, t) else None
        except Exception:
            return None


async def _suggest_levels(pos_like: dict) -> tuple[float | None, float | None, str]:
    """Stop under the nearest support zone and target at the nearest resistance, from real zones."""
    async with httpx.AsyncClient() as client:
        sig, htf, tf = await exits.frames(client, pos_like)
    last = sig.iloc[-1]
    atr = float(last.atr14) if last.atr14 == last.atr14 else float(last.close) * 0.03
    price = float(last.close)
    z = market.sr_zones(sig, htf, price, atr, top=1)
    stop = z["destekler"][0]["alt"] - 0.25 * atr if z["destekler"] else price - 2 * atr
    target = z["direncler"][0]["orta"] if z["direncler"] else price + 3 * atr
    digits = 2 if price >= 10 else 4 if price >= 0.1 else 6  # tick-sized, not float noise
    return round(stop, digits), round(target, digits), f"{exits.TF_LABEL.get(tf, tf)} destek/direnç bölgelerinden önerildi"


async def portfolio_add(update: Update, args: list[str], market_name: str | None = None):
    usage = ("Kullanım: /portfoy ekle KOD ADET MALIYET [stop=X] [hedef=Y]\n"
             "Örnek: /portfoy ekle THYAO 10 285.5   ·   /portfoy ekle BTC 0.002 84000 stop=81000\n"
             "BIST'te adet (tam sayı), kriptoda coin adedi. Stop/hedef yazmazsan bölgelerden önerilir.")
    pos_args, kv = _opts(args)
    if len(pos_args) != 3 or set(kv) - {"stop", "hedef"}:
        await update.message.reply_text(usage)
        return
    tick = pos_args[0].upper()
    try:
        qty, cost = _float(pos_args[1]), _float(pos_args[2])
        stop, target = _float(kv.get("stop")), _float(kv.get("hedef"))
    except ValueError:
        await update.message.reply_text(usage)
        return
    mkt = market_name or await _detect_market(tick)
    if mkt is None:
        await update.message.reply_text(f"❌ {tick} ne Binance'te ({tick}/USDT) ne BIST'te ({tick}.IS) bulundu.")
        return
    if mkt == "BIST" and (qty != int(qty) or qty < 1):
        await update.message.reply_text("BIST'te adet tam sayı olmalı (ör. 10).")
        return
    if qty <= 0 or cost <= 0:
        await update.message.reply_text(usage)
        return
    if mkt == assets.MARKET:
        symbol = assets.normalize(tick) or tick
        pos = positions.open_position(symbol, cost, qty * cost, None, None, "1d", source="portföy",
                                      market_name=mkt, symbol=symbol)
        positions.update(pos["id"], adet=qty, stop_ilk=None, para="TL")
        pos = positions.get(pos["id"])
        await update.message.reply_text(
            f"✅ Portföye eklendi (altın/döviz):\n{_position_line(pos)}\n\n"
            "Birikim varlığı: TUT/SAT uyarısı gelmez; değeri, günlük ve toplam değişimi /portfoy'da izlenir. "
            "Gram altın uluslararası ons × USD/TRY ile hesaplanır; kuyumcu/banka fiyatı makas kadar farklıdır.")
        return
    if mkt == "ABD":
        symbol = us.key(tick)
        pair, tf = symbol, "1d"
    elif mkt == "BIST":
        symbol = bist.yahoo_symbol(tick)
        pair, tf = symbol, "1h"
    else:
        pair, tf = f"{tick}/{config.QUOTE}", "4h"
        symbol = alerts_store.pair_to_symbol(pair)
    note = ""
    if stop is None or target is None:
        s2, t2, why = await _suggest_levels({"piyasa": mkt, "symbol": symbol})
        stop = stop if stop is not None else s2
        target = target if target is not None else t2
        note = f"\nℹ️ Stop/hedef {why}. Değiştirmek için: /duzelt ID stop=X hedef=Y"
    pos = positions.open_position(pair, cost, qty * cost, stop, target, tf, source="portföy",
                                  market_name=mkt, symbol=symbol)
    # An imported holding had no plan when it was bought, so R (profit in units of planned risk) is
    # meaningless for it: without stop_ilk, R stays empty instead of showing e.g. "+7R".
    positions.update(pos["id"], adet=qty, stop_ilk=None)
    pos = positions.get(pos["id"])
    reviewed = await exits.review(pos)
    body = reviewed[1] if reviewed else _position_line(pos)
    await update.message.reply_text(f"✅ Portföye eklendi ({'BIST' if mkt == 'BIST' else 'kripto'}):\n{body}{note}\n\n"
                                    "Bundan sonra bot bu pozisyon için stop/hedef ve TUT/KISMİ SAT/SAT kontrolünü "
                                    + ("her iş günü 18:40'ta" if mkt == "BIST" else "her 4 saatlik kapanışta") + " yapar.")


def exit_buttons(pos: dict, a: dict):
    price = a["fiyat"]
    rows = []
    if a["karar"] == "SAT":
        rows.append([InlineKeyboardButton(f"💰 Sattım @ {price:g}", callback_data=f"sat|{pos['id']}|{price}|cikis"),
                     InlineKeyboardButton("✋ Tutuyorum", callback_data=f"tut|{pos['id']}|cikis")])
    elif a["karar"] == "KISMİ SAT":
        rows.append([InlineKeyboardButton(f"½ Yarısını sattım @ {price:g}", callback_data=f"yari|{pos['id']}|{price}"),
                     InlineKeyboardButton("💰 Hepsini sattım", callback_data=f"sat|{pos['id']}|{price}|cikis")])
    if a["stop_onerisi"]:
        lvl = a["stop_onerisi"]["seviye"]
        rows.append([InlineKeyboardButton(f"🔒 Stopu {lvl:.6g} yap", callback_data=f"stopcek|{pos['id']}|{lvl}")])
    if a["karar"] == "KISMİ SAT":
        rows.append([InlineKeyboardButton("✋ Şimdilik tut", callback_data=f"tutk|{pos['id']}")])
    return InlineKeyboardMarkup(rows) if rows else None


async def portfolio_show(update: Update, context: ContextTypes.DEFAULT_TYPE, only: str | None = None):
    items = [p for p in positions.open_positions() if only is None or p.get("piyasa", "KRIPTO") == only]
    if not items:
        await update.message.reply_text("Portföy boş. Eklemek için: /portfoy ekle THYAO 10 285.5 ya da /portfoy ekle BTC 0.002 84000")
        return
    status = await update.message.reply_text(f"⏳ {len(items)} pozisyon inceleniyor (çıkış/tepe analizi)...")
    totals, counts = {}, {"TUT": 0, "KISMİ SAT": 0, "SAT": 0}
    for p in items:
        reviewed = await exits.review(p)
        if not reviewed:
            await context.bot.send_message(update.effective_chat.id, _position_line(p) + "\n(veri alınamadı)")
            continue
        a, body = reviewed
        counts[a["karar"]] += 1
        cur = p.get("para", "USD")
        totals[cur] = totals.get(cur, 0.0) + (a["fiyat"] - p["giris"]) * p["adet"]
        await context.bot.send_message(update.effective_chat.id, body, reply_markup=exit_buttons(p, a))
    await status.delete()
    total_txt = " | ".join(f"{v:+,.2f} {k}" for k, v in totals.items())
    await context.bot.send_message(update.effective_chat.id,
        f"📊 Portföy: {len(items)} pozisyon · 🟢 TUT {counts['TUT']} · 🟠 KISMİ SAT {counts['KISMİ SAT']} · "
        f"🔴 SAT {counts['SAT']}\nAnlık K/Z: {total_txt}\nDetaylı yorum: /portfoy analiz")


async def portfolio_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, only: str | None = None):
    items = [p for p in positions.open_positions() if only is None or p.get("piyasa", "KRIPTO") == only]
    if not items:
        await update.message.reply_text("Portföy boş.")
        return
    rows = []
    for p in items:
        reviewed = await exits.review(p)
        if reviewed:
            a = reviewed[0]
            rows.append({"id": p["id"], "varlik": p["pair"], "piyasa": p.get("piyasa", "KRIPTO"), "para": p.get("para", "USD"),
                         "birikim": bool(p.get("birikim")),
                         "adet": p["adet"], "maliyet": p["giris"], "stop": p.get("stop"), "hedef": p.get("hedef"),
                         "cikis_analizi": {k: a[k] for k in ("karar", "sinyaller", "stop_onerisi", "olasi_tepe",
                                                             "kapanis", "fiyat", "zaman_dilimi", "R", "kar_yuzde", "rsi")}})
    data = {"PORTFOY": rows}
    if any(r["piyasa"] == "BIST" for r in rows):
        async with httpx.AsyncClient() as client:
            data["BIST100_KAPI"] = await bist.index_gate(client)
    await run_analysis(context.bot, update.effective_chat.id,
                       "[PORTFÖY] Portföyümü değerlendir: her pozisyon için TUT / KISMİ SAT / SAT ve nedeni.",
                       [], data=data, buttons=None, allow_state_update=False)


def _money(x: float, cur: str) -> str:
    return f"{x:,.2f} {cur}".replace(",", " ")


def _pct_badge(x: float | None) -> str:
    return "—" if x is None else f"{'🟢' if x > 0 else '🔴' if x < 0 else '⚪'} %{x:+.2f}"


# --- easy portfolio: buttons + plain text, no command syntax to remember -----------------------
FILLER_WORDS = {"LOT", "ADET", "TANE", "TL", "USD", "USDT", "ALDIM", "ALDİM", "EKLE", "TEN", "DEN", "TAN", "DAN",
                "FIYAT", "FİYAT", "MALIYET", "MALİYET", "HISSE", "HİSSE", "COIN", "VE", "SAT", "SATTIM"}
PORTFOLIO_BUTTONS = InlineKeyboardMarkup([
    [InlineKeyboardButton("➕ Ekle", callback_data="pf|ekle"), InlineKeyboardButton("💰 Sat", callback_data="pf|sat")],
    [InlineKeyboardButton("📋 Detay (TUT/SAT)", callback_data="pf|detay"), InlineKeyboardButton("🔄 Yenile", callback_data="pf|yenile")],
    [InlineKeyboardButton("📊 Grafik", callback_data="pf|grafik"), InlineKeyboardButton("⚖️ Risk", callback_data="pf|risk")],
    [InlineKeyboardButton("💰 Bakiye / K-Z", callback_data="pf|bakiye"), InlineKeyboardButton("🤔 Ne yapayım?", callback_data="pf|ne")]])


def parse_holdings(text: str) -> list[tuple[str, float, float | None]]:
    """Lines like "THYAO 10 285", "10 adet THYAO 285'ten", "BTC 0,002 84000", "ASELS 3" -> (ticker, qty, cost)."""
    out = []
    for line in re.split(r"[\n;]+", text):
        words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-z0-9ÇĞİÖŞÜçğıöşü.]*|\d+(?:[.,]\d+)?", line)
        ticks = [w.upper().removesuffix(".IS") + (".IS" if w.upper().endswith(".IS") else "")
                 for w in words if not w[0].isdigit() and w.upper() not in FILLER_WORDS and len(w) >= 2]
        nums = [float(w.replace(",", ".")) for w in words if w[0].isdigit()]
        if ticks and nums:
            out.append((ticks[0], nums[0], nums[1] if len(nums) > 1 else None))
    return out


def _shim(update: Update):
    """Handlers written for commands also work from a button press."""
    msg = update.message or update.callback_query.message
    return types.SimpleNamespace(message=msg, effective_chat=update.effective_chat)


async def add_holdings(update, context, text: str) -> bool:
    rows = parse_holdings(text)
    if not rows:
        return False
    context.user_data.pop("bekleyen", None)
    for tick, qty, cost in rows:
        if cost is None:  # no cost given: use today's price so the holding still gets tracked
            mkt = await _detect_market(tick)
            if mkt is None:
                await update.message.reply_text(f"❌ {tick} bulunamadı (ne Binance ne BIST).")
                continue
            cost = await _price(bist.yahoo_symbol(tick) if mkt == "BIST" else tick + config.QUOTE)
            await update.message.reply_text(f"ℹ️ {tick} için maliyet yazılmadı, şu anki fiyat {cost:g} kullanıldı "
                                            "(sonra /duzelt ID giris=FIYAT ile değiştirebilirsin).")
        await portfolio_add(update, [tick, repr(qty), repr(cost)])  # repr: no 6-digit rounding (SHIB)
    await update.message.reply_text("Portföyün:", reply_markup=PORTFOLIO_BUTTONS)
    return True


async def ask_sell(query, context):
    items = positions.open_positions()
    if not items:
        await query.message.reply_text("Satacak pozisyon yok.")
        return
    groups = {}
    for p in items:
        g = groups.setdefault((p.get("piyasa", "KRIPTO"), p["symbol"]), {"pair": p["pair"], "adet": 0.0})
        g["adet"] += p["adet"]
    def label(mkt, sym, g):
        if mkt == "BIST":
            return f"🇹🇷 {bist.ticker(sym)} — {g['adet']:.0f} adet"
        if mkt == assets.MARKET:
            return f"🥇 {assets.name(sym)} — {g['adet']:g} {assets.ASSETS[sym]['birim']}"
        return f"🪙 {g['pair']} — {g['adet']:.6g}"

    rows = [[InlineKeyboardButton(label(mkt, sym, g), callback_data=f"pfsat|{mkt}|{sym}")]
            for (mkt, sym), g in groups.items()]
    await query.message.reply_text("Hangisini sattın?", reply_markup=InlineKeyboardMarkup(rows))


async def sell_holding(update, context, mkt: str, sym: str, text: str = "", when: str | None = None,
                       qty: float | None = None, price: float | None = None) -> bool:
    """Answer to "how much, at what price": "5 300", "hepsi", "yarısı 305", "5" (price = now).
    when: the time of the real sale (ISO), default now."""
    items = sorted((p for p in positions.open_positions() if p["symbol"] == sym), key=lambda p: p["id"])
    if not items:
        context.user_data.pop("bekleyen", None)
        await update.message.reply_text("Bu varlıkta açık pozisyon kalmamış.")
        return True
    total = sum(p["adet"] for p in items)
    low = text.lower()
    nums = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", text)]
    if qty is not None:  # from the dialog: exact numbers, never through text (1.2e+06 would parse as 1.2 and 6)
        pass
    elif "hepsi" in low or "tamamı" in low or "tamami" in low:
        qty, price = total, (nums[0] if nums else None)
    elif "yarı" in low or "yari" in low:
        qty, price = total / 2, (nums[0] if nums else None)
    elif nums:
        qty, price = nums[0], (nums[1] if len(nums) > 1 else None)
    else:
        return False
    if mkt == "BIST":
        qty = int(qty)
    if total < qty <= total * (1 + 1e-9):
        qty = total  # "Hepsi" after a float round trip
    if qty <= 0 or qty > total + 1e-12:
        await update.message.reply_text(f"Miktar 0 ile {_qty(total)} arasında olmalı.")
        return True
    if price is None:
        price = await _price(sym)
    context.user_data.pop("bekleyen", None)
    left, realized, sold_ids = qty, 0.0, []
    for p in items:  # FIFO: oldest buys are sold first
        if left <= 1e-12:
            break
        take = min(left, p["adet"])
        part, _ = positions.partial_close(p["id"], take, price, "elle", when=when)
        realized += positions.pnl(part, price)["pnl_usd"]
        sold_ids.append(part["id"])
        left -= take
    cur = "USD" if mkt == "KRIPTO" else "TL"
    unit = assets.ASSETS[sym]["birim"] if mkt == assets.MARKET else "adet"
    await update.message.reply_text(
        f"💰 {bist.ticker(sym) if mkt == 'BIST' else assets.name(sym) if mkt == assets.MARKET else sym}: {_qty(qty)} {unit} satıldı @ {_px(price)} → "
        f"{realized:+,.2f} {cur} gerçekleşen K/Z. Kalan {_qty(max(total - qty, 0))} {unit}."
        + (f"\nSatış zamanı: {datetime.fromisoformat(when).strftime('%d.%m %H:%M')}" if when else "")
        + "\nSitedeki portföy 1 dakika içinde güncellenir.",
        reply_markup=PORTFOLIO_BUTTONS)
    if any(positions.is_trade(p) for p in items):
        await ask_sell_reason(update.message, sold_ids)
    return True

# --- step-by-step portfolio wizard: market -> asset -> quantity -> cost -> confirm -------------
CANCEL_ROW = [InlineKeyboardButton("❌ İptal", callback_data="wz|iptal")]


def _icon(mkt: str) -> str:
    return {"BIST": "🇹🇷", assets.MARKET: "🥇", "ABD": "🇺🇸"}.get(mkt, "🪙")


def _grid(labels: list[str], prefix: str, cols: int) -> list[list[InlineKeyboardButton]]:
    btns = [InlineKeyboardButton(x, callback_data=f"{prefix}|{x}") for x in labels]
    return [btns[i:i + cols] for i in range(0, len(btns), cols)]


INVEST_VERBS = ("yatırdım", "yatirdim", "aldım", "aldim", "koydum", "girdim", "bastım", "bastim", "yatırıyorum")
INVEST_STOP = {"YATIRDIM", "ALDIM", "KOYDUM", "GIRDIM", "GİRDİM", "BASTIM", "DOLAR", "DOLARLIK", "LIRA", "LİRA", "TL",
               "USD", "USDT", "BEN", "SIMDI", "ŞİMDİ", "KANKA", "KNK", "ILE", "İLE", "DAHA", "BIR", "BİR", "PARA",
               "PORTFOYE", "PORTFÖYE", "BUGUN", "BUGÜN", "DUN", "DÜN", "YATIRIYORUM"}


async def amount_intent(update, context, text: str) -> bool:
    """"hype'a 60 dolar yatırdım" -> portfolio wizard with the amount filled in, asks only the price."""
    low = text.lower()
    if not any(v in low for v in INVEST_VERBS):
        return False
    m = re.search(r"(\$\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*(?:\$|dolar\w*|usdt?|tl|lira|₺))", text, re.I)
    if not m:
        return False
    amount = parse_amount(m.group(1))
    if not amount:
        return False
    rest = (text[:m.start()] + " " + text[m.end():]).replace("'", " ").replace("’", " ")
    words = [w for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]{2,10}", rest)
             if w.upper() not in INVEST_STOP and w.upper() not in FILLER_WORDS and not w.isdigit()]
    known = set(config.WATCHLIST) | set(bist.watchlist()) | {bist.ticker(p["symbol"]) for p in positions.open_positions()}
    code = next((w.upper() for w in words if w.upper() in known), None)
    mkt = None
    if code is None:
        for w in words[:3]:
            mkt = await _detect_market(w)
            if mkt and mkt != assets.MARKET:
                code = w.upper()
                break
        else:
            mkt = None
    if code is None:
        if amount[1] == "USD":  # "500 dolar aldım" = bought dollars
            context.user_data.pop("satis", None)
            context.user_data["sihirbaz"] = {"adim": "kod", "piyasa": assets.MARKET}
            await wizard_set_asset(update.message, context, "USD")
            await wizard_set_qty(update.message, context, f"{amount[0]:g}")
            return True
        return False
    mkt = mkt or ("BIST" if code in bist.watchlist() else await _detect_market(code))
    if mkt is None:
        return False
    context.user_data.pop("satis", None)
    context.user_data["sihirbaz"] = {"adim": "kod", "piyasa": mkt}
    await wizard_set_asset(update.message, context, code, ask=False)
    if context.user_data.get("sihirbaz", {}).get("adim") == "adet":
        await wizard_set_qty(update.message, context, f"{amount[0]:g}{'$' if amount[1] == 'USD' else ' tl'}")
    return True


async def wizard_start(msg, context):
    context.user_data["sihirbaz"] = {"adim": "piyasa"}
    context.user_data.pop("satis", None)
    await msg.reply_text("➕ Portföye ne ekleyelim?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🇹🇷 BIST hissesi", callback_data="wz|piyasa|BIST"),
         InlineKeyboardButton("🪙 Kripto", callback_data="wz|piyasa|KRIPTO")],
        [InlineKeyboardButton("🇺🇸 ABD hissesi", callback_data="wz|piyasa|ABD"),
         InlineKeyboardButton("🥇 Altın/Döviz", callback_data=f"wz|piyasa|{assets.MARKET}")], CANCEL_ROW]))


PICK_PAGE = {"BIST": 25, "KRIPTO": 24, "ABD": 24}
PICK_COLS = {"BIST": 5, "KRIPTO": 4, "ABD": 4}


def _pick_names(mkt: str) -> list[str]:
    """Held assets first, then the validated universe (BIST ~200 names, popular coins)."""
    if mkt == "BIST":
        held = sorted({bist.ticker(p["symbol"]) for p in positions.open_positions() if p.get("piyasa") == "BIST"})
        return list(dict.fromkeys(held + universe.bist_names()))
    if mkt == "ABD":
        held = sorted({us.ticker(p["symbol"]) for p in positions.open_positions() if p.get("piyasa") == "ABD"})
        return list(dict.fromkeys(held + sorted(us.SP100)))
    held = sorted({p["pair"].split("/")[0] for p in positions.open_positions() if p.get("piyasa", "KRIPTO") == "KRIPTO"})
    return list(dict.fromkeys(held + universe.crypto_names()))


def _pick_keyboard(w: dict) -> InlineKeyboardMarkup:
    mkt = w["piyasa"]
    names, size, cols = _pick_names(mkt), PICK_PAGE[mkt], PICK_COLS[mkt]
    pages = max(1, -(-len(names) // size))
    page = min(w.get("sayfa", 0), pages - 1)
    chosen = w.setdefault("secili", [])
    btns = [InlineKeyboardButton(("✅" if n in chosen else "") + n, callback_data=f"wz|sec|{n}")
            for n in names[page * size:(page + 1) * size]]
    rows = [btns[i:i + cols] for i in range(0, len(btns), cols)]
    if pages > 1:
        rows.append([InlineKeyboardButton("◀", callback_data=f"wz|sayfa|{(page - 1) % pages}"),
                     InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="wz|yok"),
                     InlineKeyboardButton("▶", callback_data=f"wz|sayfa|{(page + 1) % pages}")])
    rows.append([InlineKeyboardButton(f"➡️ Devam ({len(chosen)} seçili)" if chosen else "Seç, sonra Devam'a bas",
                                      callback_data="wz|devam")])
    return InlineKeyboardMarkup(rows + [CANCEL_ROW])


async def wizard_ask_asset(msg, context):
    w = context.user_data["sihirbaz"]
    w["adim"] = "kod"
    if w["piyasa"] == assets.MARKET:
        rows = [[InlineKeyboardButton(f"{a['emoji']} {a['ad']}", callback_data=f"wz|kod|{k}")] for k, a in assets.ASSETS.items()]
        await msg.reply_text("🥇 Hangisi?", reply_markup=InlineKeyboardMarkup(rows + [CANCEL_ROW]))
        return
    w.update(sayfa=0, secili=[])
    what = "coin" if w["piyasa"] == "KRIPTO" else "hisse"
    await msg.reply_text(
        f"{_icon(w['piyasa'])} Hangi {what}ler? Birden fazla seçebilirsin (✅), sonra ➡️ Devam.\n"
        f"Listede yoksa kodunu yaz, birden fazlaysa boşlukla: {'THYAO ASELS' if w['piyasa'] == 'BIST' else 'AAPL NVDA' if w['piyasa'] == 'ABD' else 'BTC PEPE'}\n"
        "💼 elindekiler başta.", reply_markup=_pick_keyboard(w))


async def wizard_next_in_queue(msg, context, w: dict) -> bool:
    """After one asset is saved, start the next selected one."""
    queue = w.get("kuyruk") or []
    if not queue:
        return False
    nxt, rest = queue[0], queue[1:]
    total = w.get("kuyruk_toplam", len(queue) + 1)
    context.user_data["sihirbaz"] = {"adim": "kod", "piyasa": w["piyasa"], "kuyruk": rest, "kuyruk_toplam": total}
    await msg.reply_text(f"➡️ Sıradaki: {nxt} ({total - len(rest)}/{total})")
    await wizard_set_asset(msg, context, nxt)
    return True


async def wizard_start_queue(msg, context, codes: list[str]):
    w = context.user_data["sihirbaz"]
    codes = list(dict.fromkeys(c.upper() for c in codes))
    w["kuyruk"], w["kuyruk_toplam"] = codes[1:], len(codes)
    if len(codes) > 1:
        await msg.reply_text(f"📝 {len(codes)} varlık: {', '.join(codes)}. Sırayla adet/tutar ve fiyat soracağım.")
    await wizard_set_asset(msg, context, codes[0])


async def wizard_set_asset(msg, context, code: str, ask: bool = True):
    w = context.user_data["sihirbaz"]
    if w["piyasa"] == assets.MARKET:
        sym = assets.normalize(code)
        if not sym:
            await msg.reply_text("Gram altın, dolar ya da euro seç:", reply_markup=InlineKeyboardMarkup([CANCEL_ROW]))
            return
        async with httpx.AsyncClient() as client:
            q = await assets.quote(client, sym)
        a = assets.ASSETS[sym]
        w.update(kod=sym, fiyat=q["fiyat"], adim="adet")
        day = (q["fiyat"] / q["onceki_kapanis"] - 1) * 100 if q.get("onceki_kapanis") else None
        await msg.reply_text(f"{a['emoji']} {a['ad']} — şu an {q['fiyat']:,.2f} TL" + (f" (%{day:+.2f})" if day is not None else "")
                             + f"\n\nKaç {a['birim']}? (ör. 10 ya da 2,5)", reply_markup=InlineKeyboardMarkup([CANCEL_ROW]))
        return
    code = code.strip().upper().removesuffix(".IS").removesuffix(".US").removesuffix("/USDT").removesuffix("USDT")
    if not re.fullmatch(r"[A-Z0-9\-]{1,10}", code):
        await msg.reply_text("Kod sadece harf/rakam olmalı (ör. THYAO, AAPL ya da BTC). Tekrar yaz:")
        return
    try:
        async with httpx.AsyncClient() as client:
            if w["piyasa"] == "BIST":
                q = await bist.day_quote(client, code)
            elif w["piyasa"] == "ABD":
                if not await us.is_us_ticker(client, code):
                    raise market.SymbolNotFound(code)
                q = await us.day_quote(client, code)
            else:
                q = await market.ticker_24h(client, code + config.QUOTE)
    except Exception:
        where = (f"BIST'te ({code}.IS)" if w["piyasa"] == "BIST" else f"ABD borsalarında" if w["piyasa"] == "ABD"
                 else f"Binance'te ({code}/USDT)")
        await msg.reply_text(f"❌ {code} {where} bulunamadı. Kodu kontrol edip tekrar yaz:",
                             reply_markup=InlineKeyboardMarkup([CANCEL_ROW]))
        return
    w.update(kod=code, fiyat=q["fiyat"], adim="adet")
    day = (q["fiyat"] / q["onceki_kapanis"] - 1) * 100 if q.get("onceki_kapanis") else None
    unit, cur = ("adet", "TL") if w["piyasa"] == "BIST" else ("adet", "USD")
    question = ("Kaç adet aldın? (tam sayı, ör. 10) — ya da tutar yaz: 5000 tl" if w["piyasa"] == "BIST"
                else "Kaç hisse aldın? (kesirli olabilir, ör. 2.5) — ya da tutar yaz: 500$" if w["piyasa"] == "ABD"
                else "Kaç adet aldın? (ör. 0.002) — ya da yatırdığın tutarı yaz: 60$")
    await msg.reply_text(f"{_icon(w['piyasa'])} {code} — şu an {q['fiyat']:,.6g} {cur}"
                         + (f" (bugün %{day:+.2f})" if day is not None else "")
                         + (" · BIST ~15 dk gecikmeli" if w["piyasa"] == "BIST" else "") + (f"\n\n{question}" if ask else ""),
                         reply_markup=InlineKeyboardMarkup([CANCEL_ROW]) if ask else None)


AMOUNT_RE = re.compile(r"^\s*(?:\$\s*(?P<a>\d+(?:[.,]\d+)?)|(?P<b>\d+(?:[.,]\d+)?)\s*"
                       r"(?P<cur>\$|dolar\w*|usdt?|tl|lira|₺))\s*$", re.I)


def parse_amount(text: str) -> tuple[float, str] | None:
    """"60$", "$60", "60 dolar", "1000 tl" -> (60.0, "USD") / (1000.0, "TL"). Pure."""
    m = AMOUNT_RE.match(text.replace("'", " "))
    if not m:
        return None
    value = float((m.group("a") or m.group("b")).replace(",", "."))
    cur = (m.group("cur") or "$").lower()
    return value, "TL" if cur in ("tl", "lira", "₺") else "USD"


async def wizard_set_qty(msg, context, text: str):
    w = context.user_data["sihirbaz"]
    amount = parse_amount(text) if w["piyasa"] != assets.MARKET or w.get("kod") != "USD" else None
    if amount:
        value, cur = amount
        want = "USD" if w["piyasa"] in ("KRIPTO", "ABD") else "TL"
        note = ""
        if cur != want:
            async with httpx.AsyncClient() as client:
                fx = await bist.last_price(client, bist.FX)
            value = value / fx if want == "USD" else value * fx
            note = f" (≈ {value:,.2f} {want}, kur {fx:.4g})"
        if value <= 0:
            await msg.reply_text("Pozitif bir tutar yaz (ör. 60$):")
            return
        w.update(tutar=value, adim="maliyet")
        await msg.reply_text(
            f"💵 {amount[0]:g} {cur} yatırdın{note}.\nHangi fiyattan aldın? (borsada gördüğün ortalama alış fiyatı)\n"
            f"Adedi biliyorsan 'adet 1.52' yaz — en doğrusu bu, komisyon da içinde olur. Bilmiyorsan şu anki fiyat:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Şu anki fiyat: {w['fiyat']:,.6g} {want}", callback_data="wz|maliyet|simdi")],
                CANCEL_ROW]))
        return
    try:
        qty = float(text.strip().replace(",", "."))
    except ValueError:
        qty = -1
    if qty <= 0 or (w["piyasa"] == "BIST" and qty != int(qty)):
        await msg.reply_text("BIST'te pozitif tam sayı adet yaz (ör. 10) ya da tutar (ör. 5000 tl):" if w["piyasa"] == "BIST"
                             else "Adet (ör. 0.002) ya da yatırdığın tutarı (ör. 60$) yaz:")
        return
    w.update(adet=qty, adim="maliyet")
    cur = "USD" if w["piyasa"] in ("KRIPTO", "ABD") else "TL"
    await msg.reply_text(f"Ortalama alış fiyatın kaç {cur}? ({'gram/birim' if w['piyasa'] == assets.MARKET else 'hisse/coin'} başına, ör. 285,5)\n"
                         "Bilmiyorsan şu anki fiyatı kullan:",
                         reply_markup=InlineKeyboardMarkup([
                             [InlineKeyboardButton(f"Şu anki fiyat: {w['fiyat']:,.6g} {cur}", callback_data="wz|maliyet|simdi")],
                             CANCEL_ROW]))


async def wizard_set_cost(msg, context, text: str):
    w = context.user_data["sihirbaz"]
    qty_given = re.match(r"^\s*adet\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*$", text, re.I)
    if qty_given and w.get("tutar"):
        qty = float(qty_given.group(1).replace(",", "."))
        if qty <= 0 or (w["piyasa"] == "BIST" and qty != int(qty)):
            await msg.reply_text("Geçerli bir adet yaz (BIST'te tam sayı).")
            return
        w["adet"] = qty
        cost = w["tutar"] / qty
    elif text == "simdi":
        cost = w["fiyat"]
    else:
        try:
            cost = float(text.strip().replace(" ", "").replace(",", "."))
        except ValueError:
            cost = -1
    if cost <= 0:
        await msg.reply_text("Pozitif bir fiyat yaz (ör. 285,5)" + (" ya da 'adet 1.52'" if w.get("tutar") else "") + ":")
        return
    if w.get("tutar") and not qty_given:
        qty = w["tutar"] / cost
        if w["piyasa"] == "BIST":
            qty = float(int(qty))
            if qty < 1:
                await msg.reply_text(f"{w['tutar']:,.2f} TL bu fiyattan 1 adete yetmiyor. Fiyatı kontrol et:")
                return
        w["adet"] = qty
    w.update(maliyet=cost, adim="onay")
    cur = "USD" if w["piyasa"] in ("KRIPTO", "ABD") else "TL"
    unit = assets.ASSETS[w["kod"]]["birim"] if w["piyasa"] == assets.MARKET else "adet"
    total = w["adet"] * cost
    now_pct = (w["fiyat"] / cost - 1) * 100
    await msg.reply_text(
        f"📝 Özet\n{_icon(w['piyasa'])} {assets.name(w['kod']) if w['piyasa'] == assets.MARKET else w['kod']} — {w['adet']:g} {unit} × {cost:,.6g} = {total:,.2f} {cur}\n"
        f"Şu an {w['fiyat']:,.6g} → toplam %{now_pct:+.2f} ({w['adet'] * (w['fiyat'] - cost):+,.2f} {cur})\n"
        + ("Stop ve hedefi bot destek/direnç bölgelerinden önerecek." if w["piyasa"] != assets.MARKET
         else "Birikim varlığı: stop/hedef yok, değeri izlenir."),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Kaydet — bugün aldım", callback_data="wz|kaydet|bugun")],
            [InlineKeyboardButton("✅ Kaydet — daha önce aldım", callback_data="wz|kaydet")], CANCEL_ROW]))


async def wizard_save(update, context, today: bool = False):
    w = context.user_data.pop("sihirbaz", None)
    if not w or w.get("adim") != "onay":
        return
    before = max((p["id"] for p in positions.load()), default=0)
    await portfolio_add(_shim(update), [w["kod"], repr(float(w["adet"])), repr(float(w["maliyet"]))], market_name=w["piyasa"])
    if today:
        for p in positions.load():
            if p["id"] > before:
                positions.update(p["id"], tarih_girildi=True)
    else:
        await _shim(update).message.reply_text("📅 Alış tarihini de gir, dolar bazlı getiri ve /kiyas doğru olsun: "
                                               "/duzelt ID tarih=2025-03-01")
    if await wizard_next_in_queue(_shim(update).message, context, w):
        return
    await _shim(update).message.reply_text("Başka var mı?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(f"➕ Bir {'hisse' if w['piyasa'] == 'BIST' else 'coin' if w['piyasa'] == 'KRIPTO' else 'varlık'} daha",
                              callback_data=f"wz|piyasa|{w['piyasa']}"),
         InlineKeyboardButton("➕ Diğer piyasadan", callback_data="pf|ekle")],
        [InlineKeyboardButton("💼 Portföyü göster", callback_data="pf|yenile")]]))


async def wizard_text(update, context, text: str) -> bool:
    """Route a typed answer to the current wizard step. True if the wizard used it."""
    w = context.user_data.get("sihirbaz")
    if not w:
        return False
    if text.strip().lower() in ("iptal", "vazgeç", "vazgec", "dur"):
        context.user_data.pop("sihirbaz", None)
        await update.message.reply_text("❌ İptal edildi.", reply_markup=PORTFOLIO_BUTTONS)
        return True
    step = w["adim"]
    if step == "piyasa":
        low = text.strip().lower()
        if "bist" in low or "hisse" in low or "borsa" in low:
            w["piyasa"] = "BIST"
        elif "kripto" in low or "coin" in low:
            w["piyasa"] = "KRIPTO"
        else:
            await update.message.reply_text("BIST mi kripto mu? Butona bas ya da 'BIST' / 'kripto' yaz.")
            return True
        await wizard_ask_asset(update.message, context)
    elif step == "kod":
        codes = [c for c in re.findall(r"[A-Za-z0-9ÇĞİÖŞÜçğıöşü/.]{2,12}", text) if c.upper() not in FILLER_WORDS]
        if len(codes) > 1 and w["piyasa"] != assets.MARKET:
            await wizard_start_queue(update.message, context, codes)
        else:
            await wizard_set_asset(update.message, context, text)
    elif step == "adet":
        await wizard_set_qty(update.message, context, text)
    elif step == "maliyet":
        await wizard_set_cost(update.message, context, text)
    elif step == "onay":
        await update.message.reply_text("Kaydetmek için ✅ Kaydet'e bas, vazgeçmek için 'iptal' yaz.")
    return True


async def sell_ask_price(msg, context):
    s = context.user_data["satis"]
    cur = "USD" if s["mkt"] == "KRIPTO" else "TL"
    price = await _price(s["sym"])
    s.update(adim="fiyat", fiyat=price)
    await msg.reply_text(f"Hangi fiyattan sattın? ({cur})",
                         reply_markup=InlineKeyboardMarkup([
                             [InlineKeyboardButton(f"Şu anki fiyat: {_px(price)} {cur}", callback_data="st|fiyat|simdi")],
                             [InlineKeyboardButton("❌ İptal", callback_data="st|iptal")]]))


STALE_SELL_BUTTON_S = 20 * 60  # an older "Sattım @ X" button asks for the real price first


def parse_when(text: str) -> str | None:
    """'az önce' / 'bugün' / 'dün' / '25.09' / '25.09 14:30' / '25.09.2026 14:30' -> ISO time (TR). None = not a time."""
    t = text.strip().lower()
    now = alerts_store.now_tr()
    if t in ("simdi", "şimdi", "az önce", "az once", "bugün", "bugun"):
        return now.isoformat()
    if t in ("dün", "dun"):
        return (now - timedelta(days=1)).isoformat()
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?:\s+(\d{1,2})[:.](\d{2}))?", t)
    if not m:
        return None
    year = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else now.year
    try:
        when = now.replace(year=year, month=int(m[2]), day=int(m[1]),
                           hour=int(m[4]) if m[4] else 12, minute=int(m[5]) if m[5] else 0, second=0)
    except ValueError:
        return None
    if when > now:
        when = when.replace(year=when.year - 1) if not m[3] else when
    return when.isoformat() if when <= now else None


async def sell_ask_when(msg, context):
    context.user_data["satis"]["adim"] = "zaman"
    await msg.reply_text("Ne zaman sattın? (butona bas ya da yaz: 25.09 veya 25.09 14:30)",
                         reply_markup=InlineKeyboardMarkup([
                             [InlineKeyboardButton("Az önce", callback_data="st|zaman|simdi"),
                              InlineKeyboardButton("Dün", callback_data="st|zaman|dun")],
                             [InlineKeyboardButton("❌ İptal", callback_data="st|iptal")]]))


async def sell_text(update, context, text: str) -> bool:
    s = context.user_data.get("satis")
    if not s:
        return False
    if text.strip().lower() in ("iptal", "vazgeç", "vazgec"):
        context.user_data.pop("satis", None)
        await update.message.reply_text("❌ Satış iptal.", reply_markup=PORTFOLIO_BUTTONS)
        return True
    if s["adim"] == "zaman":
        when = parse_when(text)
        if not when:
            await update.message.reply_text("Tarihi anlayamadım. Örnek: 25.09 ya da 25.09 14:30 ya da dün")
            return True
        context.user_data.pop("satis", None)
        await sell_holding(update, context, s["mkt"], s["sym"], when=when, qty=s["adet"], price=s["satis_fiyati"])
        return True
    try:
        num = float(text.strip().replace(",", "."))
    except ValueError:
        await update.message.reply_text("Bir sayı yaz ya da butona bas.")
        return True
    if s["adim"] == "adet":
        if num <= 0 or num > s["toplam"] + 1e-12 or (s["mkt"] == "BIST" and num != int(num)):
            await update.message.reply_text(f"0 ile {_qty(s['toplam'])} arasında {'tam sayı ' if s['mkt'] == 'BIST' else ''}bir miktar yaz.")
            return True
        s["adet"] = num
        await sell_ask_price(update.message, context)
    else:
        if num <= 0:
            await update.message.reply_text("Fiyat 0'dan büyük olmalı.")
            return True
        s["satis_fiyati"] = num
        await sell_ask_when(update.message, context)
    return True

def _date_unknown(p: dict) -> bool:
    """Holdings typed into /portfoy were bought on an unknown day (acilis = the day they were entered)."""
    return p.get("kaynak") == "portföy" and not p.get("tarih_girildi")


async def collect_portfolio(only: str | None = None, verdicts: bool = True) -> dict:
    """Holdings grouped per asset: price, value, daily/total change, dividends, dollar/inflation return,
    concentration. Several buys of one asset become one row with an average cost."""
    items = [p for p in positions.open_positions() if only is None or p.get("piyasa", "KRIPTO") == only]
    groups: dict[tuple, dict] = {}
    for p in items:
        g = groups.setdefault((p.get("piyasa", "KRIPTO"), p["symbol"]),
                              {"piyasa": p.get("piyasa", "KRIPTO"), "symbol": p["symbol"], "pair": p["pair"],
                               "adet": 0.0, "maliyet": 0.0, "ids": [], "poz": []})
        g["adet"] += p["adet"]
        g["maliyet"] += p["adet"] * p["giris"]
        g["ids"].append(p["id"])
        g["poz"].append(p)
    out, errors = [], []
    async with httpx.AsyncClient() as client:
        try:
            fx = await corporate.usdtry_series(client)
        except Exception as e:
            log.warning("USD/TRY series failed: %s", e)
            fx = None
        cpi = await corporate.cpi_series(client)
        for g in groups.values():
            mkt, sym = g["piyasa"], g["symbol"]
            try:
                q = await (bist.day_quote(client, sym) if mkt == "BIST" else assets.quote(client, sym)
                           if mkt == assets.MARKET else us.day_quote(client, sym) if mkt == "ABD" else market.ticker_24h(client, sym))
            except Exception as e:
                errors.append(f"{g['pair']}: fiyat alınamadı ({str(e)[:40]})")
                continue
            price, prev = q["fiyat"], q["onceki_kapanis"]
            cur = "USD" if mkt in ("KRIPTO", "ABD") else "TL"
            g.update(fiyat=price, para=cur, deger=g["adet"] * price,
                     gun_yuzde=(price / prev - 1) * 100 if prev else None,
                     gun_tutar=g["adet"] * (price - prev) if prev else 0.0,
                     gun_etiket="24s" if mkt == "KRIPTO" else "Günlük" if mkt == assets.MARKET else
                     ("Bugün" if q.get("bugun_islem") else f"Son seans ({q.get('gun')})"),
                     temettu=0.0, temettu_bilgi=None, karar=None,
                     satirlar=[{"acilis": p["acilis"], "maliyet": p["adet"] * p["giris"], "deger": p["adet"] * price,
                                "para": cur, "tarih_yok": _date_unknown(p)} for p in g["poz"]])
            g["tarih_yok"] = [p["id"] for p in g["poz"] if _date_unknown(p)]
            known = [r for r in g["satirlar"] if not r["tarih_yok"]]
            g["reel"] = corporate.real_returns(known, fx, cpi) if known else {}
            if mkt == "BIST":
                try:
                    ev = await corporate.events(client, sym)
                    g["temettu"] = sum(d["toplam"] for p in g["poz"] for d in corporate.dividends_received(p, ev))
                    g["temettu_bilgi"] = corporate.dividend_outlook(ev, price)
                except Exception as e:
                    log.warning("Dividends failed for %s: %s", sym, e)
            if verdicts and mkt != assets.MARKET:
                found = []
                for p in g["poz"]:
                    if p.get("birikim"):
                        continue  # accumulation buys are long-term: no TUT/SAT verdict
                    reviewed = await exits.review(p)
                    if reviewed:
                        found.append(reviewed[0]["karar"])
                g["karar"] = max(found, key=exits.VERDICT_RANK.get) if found else None
            out.append(g)
    totals: dict[str, dict] = {}
    for g in out:
        t = totals.setdefault(g["piyasa"], {"deger": 0.0, "maliyet": 0.0, "gun": 0.0, "temettu": 0.0,
                                            "para": g["para"], "satirlar": []})
        t["deger"] += g["deger"]
        t["maliyet"] += g["maliyet"]
        t["gun"] += g["gun_tutar"]
        t["temettu"] += g["temettu"]
        t["satirlar"] += g["satirlar"]
    for t in totals.values():
        known = [r for r in t.pop("satirlar") if not r["tarih_yok"]]
        t["reel"] = corporate.real_returns(known, fx, cpi) if known else {}
    usdtry = fx.get("son") if fx else None
    return {"gruplar": out, "hatalar": errors, "toplam": totals, "usdtry": usdtry, "tufe": cpi is not None,
            "yogunlasma": risk.concentration(out, usdtry)}


def _real_text(r: dict, cur: str) -> str:
    parts = []
    if cur == "TL" and r.get("usd_yuzde") is not None:
        parts.append(f"$ bazında %{r['usd_yuzde']:+.2f}")
    if cur == "USD" and r.get("tl_yuzde") is not None:
        parts.append(f"TL bazında %{r['tl_yuzde']:+.2f}")
    if r.get("reel_yuzde") is not None:
        parts.append(f"enflasyondan arındırılmış %{r['reel_yuzde']:+.2f}")
    return " · ".join(parts)


def _dividend_text(g: dict) -> str | None:
    parts = []
    if g["temettu"]:
        parts.append(f"temettü alındı {g['temettu']:,.2f} TL brüt")
    info = g.get("temettu_bilgi") or {}
    for d in info.get("gecen_yil_ayni_donem", [])[:1]:
        parts.append(f"beklenen ~{d['tahmini'][8:10]}.{d['tahmini'][5:7]} (geçen yıl hisse başı {d['tutar']:.4g} TL, KAP'tan teyit et)")
    if info.get("verim_yuzde"):
        parts.append(f"12 ay verim %{info['verim_yuzde']:g}")
    return "💰 " + " · ".join(parts) if parts else None


def _qty(x: float) -> str:
    """5047971 -> 5,047,971 · 46.198 -> 46.198 (never scientific notation, never rounds a fractional lot away)."""
    return f"{round(x):,}" if abs(x - round(x)) < 1e-9 else f"{x:,.6f}".rstrip("0").rstrip(".")


def _px(x: float) -> str:
    """0.00000594 -> 0.00000594 · 416.28 -> 416.28 · 84176.5 -> 84,176.5"""
    return f"{x:.10f}".rstrip("0").rstrip(".") if abs(x) < 0.01 else f"{x:,.6g}" if abs(x) < 1000 else f"{x:,.2f}".rstrip("0").rstrip(".")


async def portfolio_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, only: str | None = None):
    """One-screen portfolio: quantity, cost, price, value, daily and total change, real return, verdict."""
    if not [p for p in positions.open_positions() if only is None or p.get("piyasa", "KRIPTO") == only]:
        await update.message.reply_text("💼 Portföyün boş. Hadi ekleyelim, adım adım soracağım.")
        await wizard_start(update.message, context)
        return
    status = await update.message.reply_text("⏳ portföy hesaplanıyor...")
    pf = await collect_portfolio(only)
    blocks = {"BIST": [], "KRIPTO": [], "ABD": [], assets.MARKET: []}
    for g in pf["gruplar"]:
        mkt, cur = g["piyasa"], g["para"]
        avg = g["maliyet"] / g["adet"]
        icon = {"TUT": "🟢 TUT", "KISMİ SAT": "🟠 KISMİ SAT", "SAT": "🔴 SAT"}.get(g["karar"], "—")
        if any(p.get("birikim") for p in g["poz"]) and not g["karar"]:
            icon = "🏦 birikim"
        qty = (f"{_qty(g['adet'])} adet" if mkt == "BIST" else f"{g['adet']:g} {assets.ASSETS[g['symbol']]['birim']}"
               if mkt == assets.MARKET else f"{_qty(g['adet'])} hisse" if mkt == "ABD" else f"{_qty(g['adet'])} adet")
        if mkt == assets.MARKET:
            icon = "🏦 birikim"
        real = _real_text(g["reel"], cur)
        lines = [f"{_icon(mkt)} {risk.name(g)} — {qty} · ort. maliyet {_px(avg)} → {_px(g['fiyat'])}",
                 f"   Değer {_money(g['deger'], cur)} · {g['gun_etiket']} {_pct_badge(g['gun_yuzde'])} ({g['gun_tutar']:+,.2f})",
                 f"   Toplam {_pct_badge((g['deger'] / g['maliyet'] - 1) * 100)} ({g['deger'] - g['maliyet']:+,.2f} {cur}) · {icon}"
                 + (f" · #{', #'.join(map(str, g['ids']))}" if len(g["ids"]) > 1 else f" · #{g['ids'][0]}")]
        if real:
            lines.append(f"   {real}")
        div = _dividend_text(g)
        if div:
            lines.append(f"   {div}")
        blocks[mkt].append("\n".join(lines))
    for err in pf["hatalar"]:
        head = err.split(":")[0]
        blocks["KRIPTO" if "/" in head else assets.MARKET if head in assets.ASSETS else "ABD" if head.endswith(".US") else "BIST"].append(err)
    await status.delete()
    lines = ["💼 PORTFÖY"]
    for mkt, title in (("BIST", "🇹🇷 BIST"), ("KRIPTO", "🪙 Kripto"), ("ABD", "🇺🇸 ABD"), (assets.MARKET, "🥇 Altın/Döviz")):
        if not blocks[mkt]:
            continue
        lines += ["", title, *blocks[mkt]]
        t = pf["toplam"].get(mkt)
        if t and t["maliyet"]:
            start = t["deger"] - t["gun"]
            lines.append(f"   ── Toplam {_money(t['deger'], t['para'])} · "
                         f"{'24s' if mkt == 'KRIPTO' else 'son seans' if alerts_store.now_tr().weekday() >= 5 else 'bugün'} {_pct_badge(t['gun'] / start * 100 if start else None)} ({t['gun']:+,.2f}) · "
                         f"toplam {_pct_badge((t['deger'] / t['maliyet'] - 1) * 100)} ({t['deger'] - t['maliyet']:+,.2f} {t['para']})"
                         + (f" · temettü +{t['temettu']:,.2f} TL" if t["temettu"] else ""))
            real = _real_text(t["reel"], t["para"])
            if real:
                lines.append(f"   ── {real}")
    conc = pf["yogunlasma"]
    if conc["uyarilar"]:
        lines += ["", *[f"⚖️ {w}" for w in conc["uyarilar"]], "Ayrıntı: /risk"]
    unknown = [i for g in pf["gruplar"] for i in g.get("tarih_yok", [])]
    if unknown:
        lines += ["", f"📅 Alış tarihi girilmemiş: #{', #'.join(map(str, unknown[:8]))}. Dolar/enflasyon bazlı getiri ve "
                      f"/kiyas için tarih ekle: /duzelt {unknown[0]} tarih=2025-03-01"]
    lines += ["", "BIST ~15 dk gecikmeli · kripto 24 saatlik değişim · yorum: /portfoy analiz"]
    if not pf["tufe"]:
        lines.append("Enflasyon sütunu için .env'ye EVDS_API_KEY ekle (ücretsiz: evds3.tcmb.gov.tr).")
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines), reply_markup=PORTFOLIO_BUTTONS)


@authorized
async def portfoy_turkish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """"/portföy ..." — Telegram commands can't contain "ö", so this arrives as plain text."""
    rest = re.sub(r"^/portf[öo]y(@\w+)?\s*", "", update.message.text.strip(), flags=re.I)
    if rest:
        await natural_holdings(update, context, rest)
    else:
        await portfolio_summary(update, context)


@authorized
async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub = context.args[0].lower() if context.args else ""
    if sub == "ekle" and len(context.args) == 1:
        await wizard_start(update.message, context)
    elif sub == "ekle":
        if not await add_holdings(update, context, " ".join(context.args[1:])):
            await portfolio_add(update, context.args[1:])
    elif sub == "analiz":
        await portfolio_ai(update, context)
    elif sub == "detay":
        which = context.args[1].lower() if len(context.args) > 1 else ""
        await portfolio_show(update, context, only={"bist": "BIST", "kripto": "KRIPTO"}.get(which))
    elif sub in ("bist", "kripto"):
        await portfolio_summary(update, context, only="BIST" if sub == "bist" else "KRIPTO")
    elif context.args:  # "/portfoy astordan 4 tane var 260 tl iken almıştım ..."
        await natural_holdings(update, context, " ".join(context.args))
    else:
        await portfolio_summary(update, context)


async def exit_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled exit check for one market (job.data): notify only when something new happens."""
    mkt = context.job.data
    if mkt == "BIST" and not bist.trading_day():
        return
    for p in [p for p in positions.open_positions() if p.get("piyasa", "KRIPTO") == mkt and not p.get("birikim")]:
        reviewed = await exits.review(p)
        if not reviewed:
            continue
        a, body = reviewed
        sugg = a["stop_onerisi"]["seviye"] if a["stop_onerisi"] else None
        key = f"{a['karar']}|{a['mum']}"
        prev = p.get("son_cikis") or {}
        new_verdict = a["karar"] != "TUT" and prev.get("anahtar") != key and prev.get("karar") != a["karar"]
        new_stop = sugg is not None and (prev.get("stop_onerisi") or 0) < sugg
        positions.update(p["id"], son_cikis={"anahtar": key, "karar": a["karar"],
                                              "stop_onerisi": max(sugg or 0, prev.get("stop_onerisi") or 0)})
        if not (new_verdict or new_stop):
            continue
        await context.bot.send_message(config.ALLOWED_CHAT_ID, body, reply_markup=exit_buttons(p, a),
                                       disable_notification=silent() or a["karar"] == "TUT")


# --- risk, chart, sentiment, discipline, journal, weekly summary, calculator, accumulation, dividends ----

@authorized
async def risk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await risk_report(_shim(update), context)


async def risk_report(update, context):
    if not positions.open_positions():
        await update.message.reply_text("Portföy boş: yoğunlaşma hesaplanacak bir şey yok.")
        return
    status = await update.message.reply_text("⏳ ağırlıklar ve 30 günlük korelasyon hesaplanıyor...")
    pf = await collect_portfolio(verdicts=False)
    rep = await risk.full_report(pf["gruplar"], pf["usdtry"])
    await status.delete()
    lines = [f"⚖️ RİSK / YOĞUNLAŞMA — toplam ≈ {_money(rep['toplam_tl'], 'TL')}"
             + (f" (USD/TRY {pf['usdtry']:.4g})" if pf["usdtry"] else ""), "", "Varlıklar:"]
    lines += [f"  {a['ad']} %{a['yuzde']:g} · {a['sektor']}" for a in rep["varliklar"]]
    lines += ["Sektörler: " + " · ".join(f"{s['sektor']} %{s['yuzde']:g}" for s in rep["sektorler"])]
    corr = rep["korelasyon"]
    if corr["ciftler"]:
        lines.append(f"\nKorelasyon ({corr['gun']} günlük getiri):")
        lines += [f"  {p['a']}–{p['b']}: {p['r']:+.2f}" for p in corr["ciftler"][:8]]
        if corr.get("kripto_ort") is not None:
            lines.append(f"  Kripto ortalaması: {corr['kripto_ort']:+.2f}")
    else:
        lines.append("\nKorelasyon için en az 2 varlık ve 15 ortak gün gerekir.")
    lines.append("")
    lines += [f"⚠️ {w}" for w in rep["uyarilar"]] or ["✅ Aşırı yoğunlaşma yok."]
    lines.append(f"\nSınırlar: tek varlık %{config.MAX_ASSET_PCT}, sektör %{config.MAX_SECTOR_PCT}, "
                 f"korelasyon {config.HIGH_CORR}. 0.8 üstü korelasyonlu varlıklar tek pozisyon gibi düşünülür.")
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines))


@authorized
async def grafik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await portfolio_chart(_shim(update), context)


async def portfolio_chart(update, context, chat_id: int | None = None, bot=None):
    bot = bot or context.bot
    chat_id = chat_id or update.effective_chat.id
    if not positions.open_positions():
        await bot.send_message(chat_id, "Portföy boş: grafik yok.")
        return
    status = await bot.send_message(chat_id, "⏳ grafik çiziliyor (son 90 gün)...", disable_notification=True)
    try:
        pf = await collect_portfolio(verdicts=False)
        hist = await risk.value_history(positions.load(), days=90)
        png = await asyncio.to_thread(charts.portfolio, pf["yogunlasma"]["varliklar"], hist, "Portföy — son 90 gün")
        last = hist[-1] if hist else None
        caption = (f"💼 Toplam ≈ {_money(pf['yogunlasma']['toplam_tl'], 'TL')}"
                   + (f" · maliyet {_money(last['maliyet_tl'], 'TL')}" if last else "")
                   + "\nKripto değerleri günün USD/TRY kuruyla TL'ye çevrildi.")
        await bot.send_photo(chat_id, photo=png, caption=caption, disable_notification=silent())
    except Exception:
        log.exception("Portfolio chart failed")
        await bot.send_message(chat_id, "❌ Grafik çizilemedi. /get_logs")
    await status.delete()


@authorized
async def duygu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(sentiment.text(await sentiment.summary(force=True)))


@authorized
async def disiplin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = context.args[0].lower() if context.args else ""
    if arg == "sifirla":
        discipline.forgive()
        await update.message.reply_text("🛡 Zarar serisi sıfırlandı, yeni sinyaller açık. Bu elle müdahale kural olayı "
                                        "olarak kaydedildi (/rapor ve haftalık özette görünür).")
        return
    if arg in ("kapat", "ac", "aç"):
        discipline.set_enabled(arg != "kapat")
        await update.message.reply_text("🛡 Disiplin kalkanı " + ("açıldı." if arg != "kapat" else
                                        "KAPATILDI (kayda geçti). Açmak için: /disiplin ac"))
        return
    since = (alerts_store.now_tr() - timedelta(days=7)).isoformat()
    await update.message.reply_text(
        discipline.text(since) + f"\n\nKurallar: üst üste {config.LOSS_STREAK} zarar = {config.COOLDOWN_HOURS} saat yeni AL yok; "
        f"günlük gerçekleşen zarar bütçenin %{config.DAILY_LOSS_PCT:g}'ünü geçerse o piyasada gün biter. "
        f"Kripto bütçesi {config.CRYPTO_BUDGET_USD} USD, BIST bütçesi /bist butce.\n"
        "/disiplin sifirla — seriyi affet · /disiplin kapat|ac")


# journal: ask why after a buy and after a sell

async def ask_buy_reason(msg, pos: dict):
    rows = [[InlineKeyboardButton(label, callback_data=f"gn|al|{pos['id']}|{code}")]
            for code, label in journal.BUY_REASONS.items()]
    rows.append([InlineKeyboardButton("Atla", callback_data=f"gn|al|{pos['id']}|atla")])
    await msg.reply_text(f"📓 #{pos['id']} {pos['pair']}: neden aldın? (günlüğe yazılır, haftalık özette "
                         "hangi nedenin kazandırdığı görünür)", reply_markup=InlineKeyboardMarkup(rows))


async def ask_sell_reason(msg, ids: list[int]):
    key = "-".join(map(str, ids[:6]))
    rows = [[InlineKeyboardButton(label, callback_data=f"gn|sat|{key}|{code}")]
            for code, label in journal.SELL_REASONS.items()]
    rows.append([InlineKeyboardButton("Atla", callback_data=f"gn|sat|{key}|atla")])
    await msg.reply_text("📓 Neden sattın?", reply_markup=InlineKeyboardMarkup(rows))


async def journal_button(query, context, side: str, key: str, code: str):
    await query.edit_message_reply_markup(None)
    if code == "atla":
        return
    ids = [int(x) for x in key.split("-")]
    if code == "diger":
        context.user_data["gunluk_not"] = {"ids": ids, "taraf": side}
        await query.message.reply_text("✍️ Kısaca yaz (tek mesaj):")
        return
    for i in ids:
        journal.set_reason(i, side, code)
    labels = journal.BUY_REASONS if side == "al" else journal.SELL_REASONS
    extra = ""
    if code in ("fomo", "tavsiye"):
        extra = "\n⚠️ Bu nedenle açılan işlemler haftalık özette ayrıca izlenir. Stop koyduysan ona sadık kal."
    await query.message.reply_text(f"📓 Kaydedildi: {labels[code]}{extra}")


async def journal_text(update, context, text: str) -> bool:
    j = context.user_data.pop("gunluk_not", None)
    if not j:
        return False
    for i in j["ids"]:
        journal.set_reason(i, j["taraf"], "diger", text)
    await update.message.reply_text("📓 Not günlüğe yazıldı.")
    return True


@authorized
async def gunluk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args and context.args[0].isdigit() else 30
    since = (alerts_store.now_tr() - timedelta(days=days)).isoformat()
    await update.message.reply_text(f"(son {days} gün)\n" + journal.text(journal.summary(since)))


# weekly summary (Sunday 20:00 TR, or /haftalik)

async def weekly_summary(bot, chat_id: int):
    now = alerts_store.now_tr()
    since = (now - timedelta(days=7)).isoformat()
    lines = [f"🗓 HAFTALIK ÖZET — {(now - timedelta(days=7)).strftime('%d.%m')}–{now.strftime('%d.%m')}"]
    trades = [t for t in discipline.closed_trades() if t["zaman"] >= since]
    week = {}
    for t in trades:
        w = week.setdefault(t["para"], {"n": 0, "kazanan": 0, "pnl": 0.0})
        w["n"] += 1
        w["kazanan"] += t["pnl"] > 0
        w["pnl"] += t["pnl"]
    lines.append("\nKAPANAN İŞLEMLER")
    lines += [f"{cur}: {w['n']} işlem, {w['kazanan']} kazanan, {w['pnl']:+,.2f} {cur}" for cur, w in week.items()] \
        or ["Bu hafta kapanan işlem yok."]
    pf = await collect_portfolio(verdicts=False) if positions.open_positions() else None
    if pf:
        lines.append("\nPORTFÖY")
        for mkt, t in pf["toplam"].items():
            real = _real_text(t["reel"], t["para"])
            lines.append(f"{'🇹🇷 BIST' if mkt == 'BIST' else '🪙 Kripto'}: {_money(t['deger'], t['para'])} · toplam "
                         f"%{(t['deger'] / t['maliyet'] - 1) * 100:+.2f}" + (f" · {real}" if real else ""))
        lines += [f"⚖️ {w}" for w in pf["yogunlasma"]["uyarilar"]]
    lines += ["", discipline.text(since), "", journal.text(journal.summary(since))]
    await shadow.refresh(shadow.signals(since))
    shadow_sum = shadow.summary(since)
    lines += ["", shadow.text(shadow_sum, 7)]
    bench = None
    if pf:
        try:
            async with httpx.AsyncClient() as client:
                bench = benchmark.compare(benchmark.rows_from_portfolio(pf), await benchmark.benchmark_series(client),
                                          benchmark.deposit_rate())
            lines += ["", benchmark.text(bench, benchmark.skipped_count(pf))]
        except Exception as e:
            log.warning("Weekly benchmark failed: %s", e)
    senti = await sentiment.summary()
    f = senti.get("korku_acgozluluk", {})
    data = {"HAFTA": {"islemler": week, "portfoy": {k: {kk: vv for kk, vv in v.items()} for k, v in (pf or {}).get("toplam", {}).items()},
                      "yogunlasma_uyarilari": (pf or {}).get("yogunlasma", {}).get("uyarilar", []),
                      "disiplin": discipline.status(), "gunluk": journal.summary(since),
                      "golge_portfoy": {k: {kk: vv for kk, vv in v.items() if kk != "islemler"} for k, v in shadow_sum.items()},
                      "kiyas": bench},
            "DUYGU": senti}
    lines.append("\nPİYASA")
    if "deger" in f:
        lines.append(f"Kripto duygu: {f['deger']} ({f['etiket']}, 7g {f['7g_degisim']:+d})")
    try:
        m = await macro.summary()
        reg = m.get("rejim", {})
        if "skor" in reg:
            lines.append(f"ABD makro rejim: {reg['skor']:+g} · {reg.get('etiket', '')}")
        data["MAKRO_REJIM"] = reg
        async with httpx.AsyncClient() as client:
            g = await bist.index_gate(client)
        data["BIST100_KAPI"] = g
        lines.append(f"BIST 100 kapısı: {g['durum']} · USD/TRY {g.get('usdtry')}")
    except Exception as e:
        log.warning("Weekly market part failed: %s", e)
    try:
        us = macro.upcoming(await macro.calendar(), 7 * 24)
    except Exception:
        us = []
    tr = bist.tr_events(7)
    data["GELECEK_HAFTA"] = {"abd": us, "turkiye": tr}
    lines.append("\nGELECEK HAFTA")
    events_ = sorted([(e["tr_zaman"], e["olay"] + " (ABD)") for e in us] + [(e["tr_zaman"], e["olay"] + " (TR)") for e in tr])
    lines += [f"{datetime.fromisoformat(t).strftime('%a %d.%m %H:%M')}  {o}" for t, o in events_[:10]] or ["Önemli veri yok."]
    await send_long(bot, chat_id, "\n".join(lines))
    if pf:
        await portfolio_chart(None, None, chat_id=chat_id, bot=bot)
    await run_analysis(bot, chat_id, "[HAFTALIK ÖZET] Haftayı değerlendir ve gelecek hafta için plan çıkar.",
                       [], data=data, buttons=None, allow_state_update=False)


async def weekly_job(context: ContextTypes.DEFAULT_TYPE):
    await weekly_summary(context.bot, config.ALLOWED_CHAT_ID)


@authorized
async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await weekly_summary(context.bot, update.effective_chat.id)


# position size calculator

@authorized
async def hesap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usage = ("Kullanım: /hesap KOD [FIYAT] [stop=X] [hedef=Y]\n"
             "Örnek: /hesap THYAO 320 stop=300 hedef=360 · /hesap BTC stop=81000\n"
             "Fiyat yazmazsan şu anki fiyat; stop/hedef yazmazsan destek/direnç bölgelerinden önerilir.")
    args, kv = _opts(context.args)
    if not args or len(args) > 2 or set(kv) - {"stop", "hedef"}:
        await update.message.reply_text(usage)
        return
    tick = args[0].upper().removesuffix("/USDT")
    try:
        price = _float(args[1]) if len(args) > 1 else None
        stop, target = _float(kv.get("stop")), _float(kv.get("hedef"))
    except ValueError:
        await update.message.reply_text(usage)
        return
    mkt = "BIST" if tick.endswith(".IS") or tick in bist.watchlist() else await _detect_market(tick)
    if mkt is None:
        await update.message.reply_text(f"❌ {tick} ne Binance'te ne BIST'te bulundu.")
        return
    symbol = bist.yahoo_symbol(tick) if mkt == "BIST" else tick + config.QUOTE
    pair = symbol if mkt == "BIST" else f"{tick}/{config.QUOTE}"
    price = price or await _price(symbol)
    note = ""
    if stop is None or target is None:
        s2, t2, why = await _suggest_levels({"piyasa": mkt, "symbol": symbol})
        stop, target = stop if stop is not None else s2, target if target is not None else t2
        note = f"ℹ️ Yazılmayan stop/hedef {why}."
    if not (stop < price < target):
        await update.message.reply_text(f"Stop < fiyat < hedef olmalı (stop {stop:g}, fiyat {price:g}, hedef {target:g}).")
        return
    lines, fails = [], []
    if mkt == "BIST":
        budget = bist.budget_tl()
        if budget is None:
            await update.message.reply_text("BIST bütçesi girilmedi: önce /bist butce 5000")
            return
        async with httpx.AsyncClient() as client:
            try:
                g = await bist.index_gate(client)
                risk_off = g["durum"] != "AÇIK" or bool(g.get("usdtry_baski"))
            except Exception:
                risk_off = True
        tl, notes = bist.tranche_tl(risk_off, True, bist_signals.open_bist_tl())
        cost_lot = price * 2 * (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT) / 100
        risk_lot = price - stop + cost_lot
        room = budget * config.BIST_MAX_RISK_PCT / 100
        lots = min(bist.lots_for(tl, price), int(room // risk_lot))
        rr = (target - price - cost_lot) / risk_lot
        lines = [f"🧮 {tick} (BIST) — fiyat {price:g} · stop {stop:g} (%{(stop / price - 1) * 100:.1f}) · hedef {target:g} (%{(target / price - 1) * 100:+.1f})",
                 f"Bütçe {budget:,} TL · ilk kademe {tl:,.0f} TL" + (f" ({'; '.join(notes)})" if notes else ""),
                 f"Adet: {lots} (kademe {bist.lots_for(tl, price)} adet, risk sınırı %{config.BIST_MAX_RISK_PCT:g} = {room:,.0f} TL → {int(room // risk_lot)} adet)",
                 f"Tutar {lots * price:,.2f} TL · stop olursa ≈ −{lots * risk_lot:,.2f} TL · hedefte ≈ +{lots * (target - price - cost_lot):,.2f} TL",
                 f"Net R/R {rr:.2f} (komisyon+kayma dahil, eşik {config.BIST_MIN_RR:g})"]
        if rr < config.BIST_MIN_RR:
            fails.append(f"net R/R {rr:.2f} < {config.BIST_MIN_RR:g}")
        if lots < 1:
            fails.append("bütçe/risk 1 adete bile yetmiyor")
    else:
        async with httpx.AsyncClient() as client:
            try:
                exchange_min = (await market.order_filters(client, symbol))["min_tutar_usd"]
            except Exception:
                exchange_min = 0.0
        try:
            reg = (await macro.summary()).get("rejim", {})
            risk_off = "skor" not in reg or reg["skor"] <= -2
        except Exception:
            risk_off = True
        greed = sentiment.greed_note(await sentiment.summary())
        usd, notes = positions.tranche_usd(pair, risk_off, True, exchange_min, greed=greed)
        cost = price * 2 * (config.BACKTEST_FEE_PCT + config.BACKTEST_SLIPPAGE_PCT) / 100
        rr = (target - price - cost) / (price - stop + cost)
        min_rr = 1.5 if risk_off else 1.0
        qty = usd / price if usd else 0
        lines = [f"🧮 {pair} — fiyat {price:g} · stop {stop:g} (%{(stop / price - 1) * 100:.1f}) · hedef {target:g} (%{(target / price - 1) * 100:+.1f})",
                 f"İlk kademe {usd:g} USD" + (f" ({'; '.join(notes)})" if notes else "") + (" · RİSK-OFF" if risk_off else ""),
                 f"Miktar ≈ {qty:.6g} {tick} · stop olursa ≈ −{qty * (price - stop + cost):.2f} USD · hedefte ≈ +{qty * (target - price - cost):.2f} USD",
                 f"Net R/R {rr:.2f} (komisyon+kayma dahil, eşik {min_rr:g})"]
        if rr < min_rr:
            fails.append(f"net R/R {rr:.2f} < {min_rr:g}")
        if usd <= 0:
            fails.append("kademe limiti dolu")
    d_ok, d_detail = discipline.check(mkt)
    if not d_ok:
        fails.append(d_detail)
    lines.append(("✅ Sayılar kurallara uyuyor." if not fails else "❌ " + "; ".join(fails))
                 + " Bu bir hesap, AL sinyali değil: giriş için kapanış teyidi yine şart.")
    if note:
        lines.append(note)
    await update.message.reply_text("\n".join(lines))


# accumulation plans

@authorized
async def birikim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usage = ("Kullanım:\n/birikim — planlar ve ortalama maliyet\n"
             "/birikim ekle BTC 50 gun=5 — her ayın 5'i 50 USD BTC\n"
             "/birikim ekle THYAO 1000 gun=15 — her ayın 15'i 1000 TL THYAO\n/birikim sil ID")
    sub = context.args[0].lower() if context.args else ""
    if sub == "ekle":
        args, kv = _opts(context.args[1:])
        try:
            day = int(kv.get("gun", 1))
            amount = _float(args[1]) if len(args) == 2 else None
        except ValueError:
            amount = None
        if not amount or amount <= 0 or not 1 <= day <= 28 or set(kv) - {"gun"}:
            await update.message.reply_text(usage + "\n(gün 1–28 arası)")
            return
        tick = args[0].upper().removesuffix("/USDT")
        mkt = "BIST" if tick.endswith(".IS") or tick in bist.watchlist() else await _detect_market(tick)
        if mkt is None:
            await update.message.reply_text(f"❌ {tick} bulunamadı.")
            return
        if mkt == assets.MARKET:
            await update.message.reply_text("Altın/döviz birikimi için şimdilik /portfoy → Ekle kullan.")
            return
        symbol = bist.yahoo_symbol(tick) if mkt == "BIST" else us.key(tick) if mkt == "ABD" else tick + config.QUOTE
        pair = symbol if mkt in ("BIST", "ABD") else f"{tick}/{config.QUOTE}"
        p = dca.add_plan(bist.ticker(tick) if mkt == "BIST" else us.ticker(tick) if mkt == "ABD" else tick, mkt, symbol, pair, amount, day)
        await update.message.reply_text(f"🏦 Birikim planı kuruldu: {dca.label(p)}.\n"
                                        f"O gün {config.DCA_REMIND_HOUR[0]:02d}:{config.DCA_REMIND_HOUR[1]:02d}'te hatırlatırım"
                                        + (" (BIST: iş günü)" if mkt == "BIST" else "")
                                        + "; alırsan 'Aldım'a bas. Bu alımlar uzun vadeli sayılır: kısa vade kademe "
                                          "limitine ve TUT/SAT uyarılarına girmez.")
        return
    if sub == "sil" and len(context.args) == 2 and context.args[1].isdigit():
        ok = dca.remove_plan(int(context.args[1]))
        await update.message.reply_text("🗑 Plan silindi (alınan pozisyonlar portföyde kalır)." if ok else "Plan bulunamadı.")
        return
    items = dca.plans()
    if not items:
        await update.message.reply_text("Birikim planı yok.\n" + usage)
        return
    lines = ["🏦 BİRİKİM PLANLARI"]
    for p in items:
        h = dca.holdings(p)
        try:
            price = await _price(p["symbol"])
        except Exception:
            price = None
        line = dca.label(p)
        if h["adet"] and price:
            line += (f"\n   {h['alim']} alım · {h['adet']:g} adet · ort. {h['ortalama']:,.6g} → {price:,.6g} "
                     f"({(price / h['ortalama'] - 1) * 100:+.2f}%) · değer {h['adet'] * price:,.2f} {p['para']}")
        else:
            line += "\n   henüz alım yok"
        lines.append(line)
    await update.message.reply_text("\n".join(lines) + "\n\n" + usage)


async def dca_job(context: ContextTypes.DEFAULT_TYPE):
    """Daily: plan-day reminders and (once a month) extra-tranche hints on dips."""
    today = alerts_store.now_tr().date()
    month = today.strftime("%Y-%m")
    for p in dca.plans():
        try:
            async with httpx.AsyncClient() as client:
                if p["piyasa"] == "BIST":
                    price = await bist.last_price(client, p["symbol"])
                    closes = (await bist.fetch(client, p["symbol"], "1d")).close.tail(30)
                elif p["piyasa"] == "ABD":
                    price = await us.last_price(client, p["symbol"])
                    closes = (await us.fetch(client, p["symbol"], "1d")).close.tail(30)
                else:
                    price = await market.last_price(client, p["symbol"])
                    closes = (await market.fetch_klines(client, p["symbol"], "1d")).close.tail(30)
        except Exception as e:
            log.warning("DCA price failed for %s: %s", p["varlik"], e)
            continue
        trading = bist.trading_day() if p["piyasa"] == "BIST" else True
        name = dca.asset_name(p)
        if dca.due(p, today, trading):
            qty = dca.quantity(p, price)
            dca.mark(p["id"], son_hatirlatma=today.isoformat())
            if qty <= 0:
                await context.bot.send_message(config.ALLOWED_CHAT_ID,
                    f"🏦 Birikim günü: {name} {price:,.6g} — {p['tutar']:,.2f} {p['para']} 1 adete yetmiyor. Tutarı artır.")
                continue
            h = dca.holdings(p)
            await context.bot.send_message(
                config.ALLOWED_CHAT_ID,
                f"🏦 Birikim günü: {name} — {p['tutar']:,.2f} {p['para']} → {qty:g} adet @ {price:,.6g}"
                + (f"\nŞu ana kadar {h['adet']:g} adet, ort. {h['ortalama']:,.6g} ({(price / h['ortalama'] - 1) * 100:+.2f}%)" if h["adet"] else "")
                + "\nPlan zamanlamaya bakmaz: fiyat ne olursa olsun düzenli alım. Aldıysan bas:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Aldım ({qty:g} @ {price:.6g})", callback_data=f"dca|al|{p['id']}|{price}|{qty}"),
                                                    InlineKeyboardButton("⏭ Bu ay atla", callback_data=f"dca|atla|{p['id']}")]]),
                disable_notification=silent())
            continue
        if (p.get("son_ekstra") or "")[:7] == month or (p["piyasa"] == "BIST" and not trading):
            continue
        why = dca.dip_reason(p, price, float(closes.max()) if len(closes) else None)
        if why:
            qty = dca.quantity({**p, "tutar": p["tutar"] / 2}, price)
            dca.mark(p["id"], son_ekstra=today.isoformat())
            if qty > 0:
                await context.bot.send_message(
                    config.ALLOWED_CHAT_ID,
                    f"📉 Birikim fırsatı: {name} {price:,.6g} — {why}.\nEkstra kademe önerisi: planın yarısı "
                    f"({p['tutar'] / 2:,.2f} {p['para']} ≈ {qty:g} adet). Ayda en fazla bir kez önerilir; zorunlu değil.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Ekstra aldım ({qty:g})", callback_data=f"dca|ekstra|{p['id']}|{price}|{qty}")]]),
                    disable_notification=silent())


async def dca_button(query, rest: list[str]):
    await query.edit_message_reply_markup(None)
    action, plan_id = rest[0], int(rest[1])
    p = next((x for x in dca.plans() if x["id"] == plan_id), None)
    if not p:
        await query.message.reply_text("Plan artık yok.")
        return
    if action == "atla":
        await query.message.reply_text(f"⏭ {dca.asset_name(p)}: bu ay atlandı.")
        return
    price, qty = float(rest[2]), float(rest[3])
    pos = dca.record_buy(p, price, qty, extra=action == "ekstra")
    h = dca.holdings(p)
    await query.message.reply_text(
        f"🏦 Kaydedildi #{pos['id']}: {dca.asset_name(p)} {qty:g} adet @ {price:,.6g}. Toplam {h['adet']:g} adet, "
        f"ort. {h['ortalama']:,.6g}. Gerçek fiyat farklıysa /duzelt {pos['id']} giris=FIYAT")


# dividends and corporate actions

@authorized
async def temettu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].lower() in ("gelir", "plan"):
        await update.message.reply_text("⏳ Temettü geçmişi alınıyor...")
        await update.message.reply_text(tools.dividend_text(await tools.dividend_plan(force=True)))
        return
    ticks = [bist.ticker(context.args[0])] if context.args else sorted(
        {bist.ticker(p["symbol"]) for p in positions.open_positions() if p.get("piyasa") == "BIST"})
    if not ticks:
        await update.message.reply_text("Portföyde BIST hissesi yok. Bir hisse için: /temettu THYAO")
        return
    lines = ["💰 TEMETTÜ / BÖLÜNME (Yahoo, son 2 yıl; gelecek tarihleri KAP belirler)"]
    async with httpx.AsyncClient() as client:
        for t in ticks[:10]:
            try:
                ev = await corporate.events(client, t)
                price = await bist.last_price(client, t)
            except market.SymbolNotFound:
                lines.append(f"\n{t}: bulunamadı")
                continue
            except Exception as e:
                lines.append(f"\n{t}: veri alınamadı ({str(e)[:40]})")
                continue
            info = corporate.dividend_outlook(ev, price)
            lines.append(f"\n{t} ({price:g} TL)")
            if info["son12ay"]:
                lines.append("  Son 12 ay: " + ", ".join(f"{d['tarih'][8:10]}.{d['tarih'][5:7]}.{d['tarih'][:4]} {d['tutar']:.4g} TL"
                                                         for d in info["son12ay"])
                             + f" · toplam {info['son12ay_toplam']:.4g} TL (%{info['verim_yuzde']:g} verim)")
            else:
                lines.append("  Son 12 ayda temettü yok.")
            for d in info["gecen_yil_ayni_donem"]:
                lines.append(f"  Geçen yıl {d['tarih']} {d['tutar']:.4g} TL → bu yıl benzer tarih olabilir (~{d['tahmini']}), tahmin")
            held = [p for p in positions.open_positions() if p.get("piyasa") == "BIST" and bist.ticker(p["symbol"]) == t]
            got = sum(d["toplam"] for p in held for d in corporate.dividends_received(p, ev))
            if got:
                lines.append(f"  Pozisyonun aldığı temettü: {got:,.2f} TL brüt")
            for s in ev["bolunmeler"]:
                lines.append(f"  ✂️ Bölünme/bedelsiz {s['tarih']} ({s['metin']}, ×{s['oran']:g} adet)")
    lines.append("\nHak kullanım günü fiyat temettü kadar düşer; bedelsizde adet artar, fiyat bölünür. "
                 "Bot açık pozisyonları bölünmede otomatik düzeltir.")
    await send_long(context.bot, update.effective_chat.id, "\n".join(lines))


async def corporate_job(context: ContextTypes.DEFAULT_TYPE):
    """Before the session: rescale positions for splits, report dividends that went ex."""
    try:
        msgs = await corporate.apply_splits() + await corporate.new_dividend_notices()
    except Exception:
        log.exception("Corporate actions check failed")
        return
    for m in msgs:
        await context.bot.send_message(config.ALLOWED_CHAT_ID, m, disable_notification=silent())


# --- shadow portfolio, benchmarks, after-sale, BIST end of day, rule scorecard, risky news, panel ------

@authorized
async def golge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args and context.args[0].isdigit() else 30
    since = (alerts_store.now_tr() - timedelta(days=days)).isoformat()
    status = await update.message.reply_text("⏳ sinyallerin sonucu kapanışlarla hesaplanıyor...")
    await shadow.refresh(shadow.signals(since))
    await status.delete()
    await send_long(context.bot, update.effective_chat.id, shadow.text(shadow.summary(since), days))


@authorized
async def kiyas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 2 and context.args[0].lower() == "faiz":
        try:
            rate = _float(context.args[1].replace("%", ""))
        except ValueError:
            rate = None
        if not rate or not 0 < rate < 200:
            await update.message.reply_text("Yıllık mevduat faizini yüzde olarak yaz: /kiyas faiz 45")
            return
        benchmark.set_deposit_rate(rate)
        await update.message.reply_text(f"🏦 Mevduat kıyası yıllık %{rate:g} (brüt, günlük bileşik) olarak kaydedildi.")
        return
    if not positions.open_positions():
        await update.message.reply_text("Portföy boş: kıyas yok.")
        return
    status = await update.message.reply_text("⏳ BIST 100, BTC, altın ve dolar aynı tarihlerle hesaplanıyor...")
    pf = await collect_portfolio(verdicts=False)
    async with httpx.AsyncClient() as client:
        res = benchmark.compare(benchmark.rows_from_portfolio(pf), await benchmark.benchmark_series(client),
                                benchmark.deposit_rate())
    await status.delete()
    await update.message.reply_text(benchmark.text(res, benchmark.skipped_count(pf)) + "\n\nMevduat faizini değiştir: /kiyas faiz 45")


@authorized
async def gunsonu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await update.message.reply_text("⏳ BIST gün sonu hazırlanıyor...")
    text = await eod.report()
    await status.delete()
    await send_long(context.bot, update.effective_chat.id,
                    text or "BIST'te pozisyonun, plan listende hisse ya da BIST planı yok. Ekle: /plan ekle THYAO")


async def eod_job(context: ContextTypes.DEFAULT_TYPE):
    if not bist.trading_day():
        return
    text = await eod.report()
    if text:
        await send_long(context.bot, config.ALLOWED_CHAT_ID, text)


@authorized
async def karne(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await update.message.reply_text("⏳ karar sonuçları güncelleniyor...")
    decided = [d for d in positions.load_decisions() if (d.get("kapi") or {}).get("kurallar") or d.get("konsey") or d.get("model")]
    await shadow.refresh(decided, limit=30)
    await status.delete()
    await send_long(context.bot, update.effective_chat.id,
                    gate.rule_scorecard(positions.load_decisions()) + "\n\n" + model_score.text())


async def after_sale_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        msgs = await benchmark.after_sale_check()
    except Exception:
        log.exception("After-sale check failed")
        return
    for m in msgs:
        await context.bot.send_message(config.ALLOWED_CHAT_ID, m, disable_notification=True)


async def risk_news_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        msgs = await risk_news.check()
    except Exception:
        log.exception("Risk news check failed")
        return
    for m in msgs:
        await context.bot.send_message(config.ALLOWED_CHAT_ID, m, disable_notification=silent(),
                                       disable_web_page_preview=True)


# natural-language alarms: "THYAO 300 üstünde kapanırsa haber ver"

ALARM_TRIGGERS = ("haber ver", "alarm", "uyar", "bildir", "haberim olsun", "söyle", "haber et")
ALARM_STOP = {"HABER", "VER", "ALARM", "KUR", "UYAR", "BILDIR", "BİLDİR", "EGER", "EĞER", "OLURSA", "OLUNCA", "USTU",
              "ÜSTÜ", "USTUNDE", "ÜSTÜNDE", "ÜSTÜNE", "UZERI", "ÜZERİ", "ÜZERİNDE", "ALTI", "ALTINA", "ALTINDA", "KAPANIRSA",
              "KAPANIŞ", "KAPANIS", "GECERSE", "GEÇERSE", "DUSERSE", "DÜŞERSE", "KIRARSA", "BENI", "BENİ", "BANA", "LUTFEN",
              "LÜTFEN", "SAATLIK", "SAATLİK", "GUNLUK", "GÜNLÜK", "DAKIKA", "DAKİKA", "SAAT", "FIYAT", "FİYAT", "DK", "BI",
              "BİR", "HABERIM", "HABERİM", "OLSUN", "SÖYLE", "SOYLE", "ET", "YUKARI", "AŞAĞI", "ASAGI", "SEVIYE",
              "SEVİYE", "SEVİYESİ", "ÇIKARSA", "CIKARSA", "İNERSE", "INERSE", "MUMU", "MUM"}


def parse_natural_alarm(text: str) -> dict | None:
    """{"kod", "fiyat", "yon", "tf"} from Turkish free text, or None. Pure (no network)."""
    low = text.lower()
    if not any(w in low for w in ALARM_TRIGGERS):
        return None
    body = re.sub(r"\b\d+\s*(saat|dk|dakika|gün|gun)\w*", " ", text, flags=re.I)  # "4 saatlik" is a timeframe
    m = re.search(r"(\d+(?:[.,]\d+)?)", body)
    if not m:
        return None
    price = float(m.group(1).replace(",", "."))
    words = [w for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2,10}", body[:m.start()] + " " + body[m.end():])
             if w.upper() not in ALARM_STOP and w.upper() not in FILLER_WORDS]
    if not words:
        return None
    up = any(k in low for k in ("üst", "üzer", "uzer", "ust", "geçer", "gecer", "çıkar", "cikar", "yukarı", "yukari"))
    down = any(k in low for k in ("alt", "düş", "dus", "iner", "aşağı", "asagi"))
    if not up and not down:
        return None  # a question with a number in it, not an alarm request
    if up and down:
        return {"kod": words[0].upper(), "fiyat": price, "yon": None, "tf": None}
    tf = None
    if "günlük" in low or "gunluk" in low:
        tf = "1d"
    elif re.search(r"4\s*saat", low):
        tf = "4h"
    elif "saatlik" in low or re.search(r"1\s*saat", low):
        tf = "1h"
    elif re.search(r"15\s*(dk|dakika)", low):
        tf = "15m"
    return {"kod": words[0].upper(), "fiyat": price, "yon": "ABOVE" if up else "BELOW", "tf": tf}


async def natural_alarm(update, context, text: str) -> bool:
    a = parse_natural_alarm(text)
    if not a:
        return False
    if a["yon"] is None:
        await update.message.reply_text("Alarm yönünü anlayamadım: 'üstünde kapanırsa' mı 'altına düşerse' mi?")
        return True
    key = await plan_key(a["kod"])
    if key is None:
        return False  # not an asset: let the text go to the analysis as usual
    is_bist = bist_signals.is_bist_plan(key)
    tf = a["tf"] or ("1h" if is_bist else "15m")
    if is_bist and tf not in ("1h", "1d"):
        tf = "1h"
    if key.endswith(".US"):
        tf = "1d"  # US stocks are followed on daily closes
    context.user_data["alarm_onay"] = {"key": key, "fiyat": a["fiyat"], "yon": a["yon"], "tf": tf}
    name = plan_key_name(key)
    tf_txt = {"15m": "15 dk", "1h": "1 saatlik", "4h": "4 saatlik", "1d": "günlük"}.get(tf, tf)
    await update.message.reply_text(
        f"⏰ {name}: {tf_txt} mum {a['fiyat']:g} {'ÜSTÜNDE' if a['yon'] == 'ABOVE' else 'ALTINDA'} KAPANIRSA haber vereyim mi?\n"
        "(dokunma sayılmaz, sadece kapanış)",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Kur", callback_data="nal|kur"),
                                            InlineKeyboardButton("❌ Vazgeç", callback_data="nal|iptal")]]))
    return True


async def natural_alarm_confirm(update, context, ok: bool):
    a = context.user_data.pop("alarm_onay", None)
    msg = _shim(update)
    if not ok or not a:
        await msg.message.reply_text("❌ Alarm kurulmadı." if a or not ok else "Bu onayın süresi geçti, tekrar yaz.")
        return
    if a["key"].endswith(".US"):
        alert = alerts_store.add_alert(a["key"], {"tetik": a["fiyat"], "yon": a["yon"], "timeframe": "1d", "cooldown": "1d",
                                                  "iptal": None, "hedef": None, "hacim_sart": False})
        await msg.message.reply_text(f"✅ ABD alarmı kuruldu: {us.ticker(a['key'])} #{alert['id']} GÜNLÜK KAPANIŞ "
                                     f"{'ÜSTÜNDE' if a['yon'] == 'ABOVE' else 'ALTINDA'} {a['fiyat']:g} $ (New York kapanışından sonra kontrol edilir)")
    elif bist_signals.is_bist_plan(a["key"]):
        await bist_alarm_cmd(msg, [bist.ticker(a["key"]), a["yon"], f"{a['fiyat']:g}", a["tf"]])
    else:
        await new_alert(msg, types.SimpleNamespace(args=[f"{a['key']}/{config.QUOTE}", "KAPANIS", a["yon"], f"{a['fiyat']:g}",
                                                         a["tf"], "1h"], bot=context.bot))


# --- takip listesi (watchlist): asked every 30 minutes, never analyzed on its own -----------

TAKIP_PAGE, TAKIP_COLS = 24, 4


def takip_prompt_text() -> str:
    lists = watchlist.load()
    weekend = alerts_store.now_tr().weekday() >= 5
    return ("👀 Takip listene bakmak ister misin?\n"
            f"🪙 {len(lists.get('KRIPTO', []))} coin · 🇹🇷 {len(lists.get('BIST', []))} hisse · 🇺🇸 {len(lists.get('ABD', []))} hisse\n"
            "Piyasa seç, sonra tek ya da birden çok kod seç (✅). Hiç seçmezsen hepsine bakar.\n"
            "📊 Durum = kodla hesaplanır (ücretsiz) · 🧠 Analiz = yapay zekâ yorumu"
            + ("\n📅 Hafta sonu: BIST ve ABD kapalı, günlük % son seansın değişimi." if weekend else ""))


def takip_menu() -> InlineKeyboardMarkup:
    lists = watchlist.load()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{label} ({len(lists.get(m, []))})", callback_data=f"tk|kat|{m}")
         for m, label in watchlist.MARKETS.items()],
        [InlineKeyboardButton("📋 Hepsinin hızlı durumu", callback_data="tk|hepsi")],
        [InlineKeyboardButton("🙅 Şimdi değil", callback_data="tk|hayir"),
         InlineKeyboardButton("🔕 Sormayı kapat", callback_data="tk|kapat")]])


def takip_picker(w: dict) -> InlineKeyboardMarkup:
    names = watchlist.load().get(w["piyasa"], [])
    pages = max(1, -(-len(names) // TAKIP_PAGE))
    page = min(w.get("sayfa", 0), pages - 1)
    chosen = w["secili"]
    btns = [InlineKeyboardButton(("✅" if n in chosen else "") + n, callback_data=f"tk|sec|{n}")
            for n in names[page * TAKIP_PAGE:(page + 1) * TAKIP_PAGE]]
    rows = [btns[i:i + TAKIP_COLS] for i in range(0, len(btns), TAKIP_COLS)]
    if pages > 1:
        rows.append([InlineKeyboardButton("◀", callback_data=f"tk|sayfa|{(page - 1) % pages}"),
                     InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="tk|yok"),
                     InlineKeyboardButton("▶", callback_data=f"tk|sayfa|{(page + 1) % pages}")])
    n = len(chosen)
    what = str(n) if n else "hepsi"
    rows.append([InlineKeyboardButton("⬜ Seçimi temizle" if names and n >= len(names) else "☑️ Hepsini seç",
                                      callback_data="tk|tumu")])
    rows.append([InlineKeyboardButton(f"📊 Durum ({what})", callback_data="tk|goster"),
                 InlineKeyboardButton(f"🧠 Analiz ({what})", callback_data="tk|analiz")])
    rows.append([InlineKeyboardButton("◀ Piyasalar", callback_data="tk|geri")])
    return InlineKeyboardMarkup(rows)


async def send_lines(bot, chat_id: int, text: str, reply_markup=None):
    """Like send_long but splits on line ends (a long list never breaks mid-row)."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > 3800:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    chunks.append(cur)
    for i, chunk in enumerate(chunks):
        await bot.send_message(chat_id, chunk.rstrip() or "—", reply_markup=reply_markup if i == len(chunks) - 1 else None,
                               disable_notification=silent())


async def takip_rows(groups: dict[str, list[str]]) -> dict[str, list[dict]]:
    return {m: await watchlist.rows(m, codes) for m, codes in groups.items() if codes}


async def takip_show(update, context, groups: dict[str, list[str]]):
    """Code-only quick status (price, day/week %, trend, RSI, nearest zones) for the chosen codes."""
    chat = update.effective_chat.id
    total = sum(len(c) for c in groups.values())
    status = await context.bot.send_message(chat, f"⏳ {total} kodun durumu hesaplanıyor...", disable_notification=True)
    try:
        res = await takip_rows(groups)
    except Exception as e:
        log.exception("Watchlist status failed")
        await status.edit_text(f"❌ Durum alınamadı: {str(e)[:120]}")
        return
    await status.delete()
    context.user_data["takip_grup"] = groups
    context.user_data["takip_sonuc"] = {"zaman": time.time(), "grup": groups, "satirlar": res}
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Yapay zekâ yorumu", callback_data="tk|yorum"),
                                InlineKeyboardButton("🔄 Yenile", callback_data="tk|yenile")]])
    items = list(res.items())
    for i, (m, rs) in enumerate(items):
        await send_lines(context.bot, chat, watchlist.text(m, rs), reply_markup=kb if i == len(items) - 1 else None)


async def takip_ai(update, context, groups: dict[str, list[str]]):
    """One code: the full engine for that market. Several: one comparative comment on the code-computed rows."""
    flat = [(m, c) for m, codes in groups.items() for c in codes]
    if len(flat) == 1:
        m, code = flat[0]
        if m == "KRIPTO":
            await run_analysis(context.bot, update.effective_chat.id, f"{code} analiz et.", [code])
        elif m == "BIST":
            await incele_ticker(_shim(update), context, code)
        else:
            await us_analysis(_shim(update), context, code)
        return
    cached = context.user_data.get("takip_sonuc")
    if cached and cached["grup"] == groups and time.time() - cached["zaman"] < 15 * 60:
        res = cached["satirlar"]
    else:
        res = await takip_rows(groups)
    await run_analysis(context.bot, update.effective_chat.id,
                       f"[TAKİP] Kullanıcı takip listesinden {len(flat)} koda bakmak istiyor. Kodla hesaplanmış hızlı durum "
                       "[PİYASA VERİSİ].TAKIP_LISTESI içinde.",
                       [], data={"TAKIP_LISTESI": res}, buttons=None, allow_state_update=False)


async def takip_button(update, context, rest: list[str]):
    q = update.callback_query
    act = rest[0]
    if q.message and q.message.message_id == watchlist.settings().get("mesaj_id"):
        watchlist.set_settings(mesaj_id=None)  # the user is using this prompt: never auto-delete it
    w = context.user_data.setdefault("takip", {"piyasa": "KRIPTO", "secili": [], "sayfa": 0})
    lists = watchlist.load()
    if act == "kat":
        w.update(piyasa=rest[1], secili=[], sayfa=0)
        await q.edit_message_text(f"{watchlist.MARKETS[rest[1]]} takip listesi: tek ya da birden çok seç (✅). "
                                  "Hiç seçmezsen hepsine bakar.", reply_markup=takip_picker(w))
    elif act == "sec":
        if rest[1] in w["secili"]:
            w["secili"].remove(rest[1])
        else:
            w["secili"].append(rest[1])
        await q.edit_message_reply_markup(takip_picker(w))
    elif act == "sayfa":
        w["sayfa"] = int(rest[1])
        await q.edit_message_reply_markup(takip_picker(w))
    elif act == "tumu":
        names = lists.get(w["piyasa"], [])
        w["secili"] = [] if len(w["secili"]) >= len(names) else list(names)
        await q.edit_message_reply_markup(takip_picker(w))
    elif act == "geri":
        await q.edit_message_text(takip_prompt_text(), reply_markup=takip_menu())
    elif act in ("goster", "analiz"):
        groups = {w["piyasa"]: list(w["secili"]) or lists.get(w["piyasa"], [])}
        await (takip_show if act == "goster" else takip_ai)(update, context, groups)
    elif act == "hepsi":
        await takip_show(update, context, lists)
    elif act in ("yenile", "yorum"):
        groups = context.user_data.get("takip_grup")
        if not groups:
            await q.message.reply_text("Önce listeden seç: /takip")
            return
        await (takip_show if act == "yenile" else takip_ai)(update, context, groups)
    elif act == "hayir":
        try:
            await q.message.delete()
        except Exception:
            await q.edit_message_reply_markup(None)
    elif act == "kapat":
        watchlist.set_settings(aktif=False)
        await q.edit_message_text("🔕 Takip listesi soruları kapandı. Liste duruyor: istediğinde /takip. "
                                  "Tekrar açmak için: /takip ac")


async def takip_job(context: ContextTypes.DEFAULT_TYPE):
    """Every N minutes (default 30): ask, silently, whether to look at the watchlist. Nothing is analyzed here."""
    st = watchlist.settings()
    now = alerts_store.now_tr()
    if not st.get("aktif", True) or alerts_store.is_quiet() or now.hour < 8:
        return
    if time.time() - st.get("son_sorma", 0) < st.get("aralik_dk", 30) * 60 - 90:
        return
    if st.get("mesaj_id"):  # the previous prompt was ignored: replace it instead of stacking prompts
        try:
            await context.bot.delete_message(config.ALLOWED_CHAT_ID, st["mesaj_id"])
        except Exception:
            pass
    msg = await context.bot.send_message(config.ALLOWED_CHAT_ID, takip_prompt_text(), reply_markup=takip_menu(),
                                         disable_notification=True)
    watchlist.set_settings(mesaj_id=msg.message_id, son_sorma=time.time())


def _takip_code(a: str) -> str:
    a = a.upper().strip(",").split("/")[0]
    if a.endswith(config.QUOTE) and len(a) > len(config.QUOTE) + 1:
        a = a[:-len(config.QUOTE)]
    return a.removesuffix(".IS").removesuffix(".US")


@authorized
async def takip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    sub = args[0].lower() if args else ""
    lists = watchlist.load()
    if not args:
        await update.message.reply_text(takip_prompt_text(), reply_markup=takip_menu())
    elif sub in ("liste", "list"):
        st = watchlist.settings()
        await send_lines(context.bot, update.effective_chat.id,
                         "📋 Takip listem\n\n" + "\n\n".join(f"{watchlist.MARKETS[m]} ({len(c)}): {', '.join(c)}"
                                                           for m, c in lists.items())
                         + f"\n\n⏰ Soru: {'her ' + str(st.get('aralik_dk', 30)) + ' dk (sessiz bildirim, 08:00 öncesi ve sessiz saatte sormaz)' if st.get('aktif', True) else 'kapalı (/takip ac)'}"
                         + "\nEkle: /takip ekle PEPE THYAO · Çıkar: /takip cikar PEPE")
    elif sub in ("kapat", "ac", "aç"):
        watchlist.set_settings(aktif=sub != "kapat")
        await update.message.reply_text("🔕 30 dk'lık soru kapandı; liste duruyor (/takip)." if sub == "kapat"
                                        else f"🔔 Takip listesi sorusu açık: her {watchlist.settings().get('aralik_dk', 30)} dk.")
    elif sub == "kural":
        kv = _parse_kv(args[1:])
        if len(args) > 1 and args[1].lower() in ("kapat", "ac", "aç"):
            r = features.set_watch_rules(aktif=args[1].lower() != "kapat")
        elif kv:
            r = features.set_watch_rules(destek_yakin=kv.get("destek"), rsi_alti=kv.get("rsi_alti"), rsi_ustu=kv.get("rsi_ustu"),
                                         hacim_kat=kv.get("hacim"))
        else:
            r = features.watch_rules()
        await update.message.reply_text(
            f"🔔 Takip listesi kuralları: {'açık' if r['aktif'] else 'kapalı'} (30 dk'da bir, her kod+kural günde 1 kez)\n"
            f"• desteğe %{r['destek_yakin']:g} yakın\n• RSI ≤ {r['rsi_alti']:g} (çok satılmış)\n• RSI ≥ {r['rsi_ustu']:g} (ısınmış)\n"
            f"• hacim ≥ ortalamanın {r['hacim_kat']:g} katı\n"
            "Değiştir: /takip kural destek=1.5 rsi_alti=30 rsi_ustu=75 hacim=2 · /takip kural kapat|ac (0 = o kural kapalı)")
    elif sub == "aralik" and len(args) > 1 and args[1].isdigit():
        watchlist.set_settings(aralik_dk=max(15, int(args[1])))
        await update.message.reply_text(f"⏰ Takip sorusu artık her {max(15, int(args[1]))} dk.")
    elif sub == "ekle" and len(args) > 1:
        forced = {"kripto": "KRIPTO", "bist": "BIST", "abd": "ABD"}.get(args[1].lower())
        added, bad = [], []
        for a in args[2 if forced else 1:]:
            code = _takip_code(a)
            mkt = forced or await _detect_market(code)
            if mkt not in watchlist.MARKETS:
                bad.append(code)
                continue
            if watchlist.add(mkt, [code]):
                added.append(f"{code} ({watchlist.MARKETS[mkt]})")
        await update.message.reply_text(("✅ Eklendi: " + ", ".join(added) if added else "Yeni kod eklenmedi (zaten listede olabilir).")
                                        + (f"\n❌ Bulunamadı: {', '.join(bad)} (piyasa zorlamak için: /takip ekle bist KOD)" if bad else ""))
    elif sub in ("cikar", "çıkar", "sil") and len(args) > 1:
        gone = watchlist.remove([_takip_code(a) for a in args[1:]])
        await update.message.reply_text("🗑 Çıkarıldı: " + ", ".join(gone) if gone else "Bu kodlar listede yok.")
    else:
        codes = [_takip_code(a) for a in args]
        groups = {m: [c for c in codes if c in lists.get(m, [])] for m in watchlist.MARKETS}
        missing = [c for c in codes if not any(c in g for g in groups.values())]
        if missing:
            await update.message.reply_text(f"Listede yok: {', '.join(missing)}. Eklemek için: /takip ekle {' '.join(missing)}")
        if any(groups.values()):
            await takip_show(update, context, {m: g for m, g in groups.items() if g})


# --- panel-era features: analysis/plans/opportunity from the panel, targets, calendar, KAP, rules, paper, lesson ---

async def panel_analysis(bot, piyasa: str, kodlar: list[str], cmd: dict | None = None) -> str | None:
    """Analysis asked from the panel: the same engines as Telegram; the answer goes to the asking user's panel,
    and to Telegram when that user linked one. cmd: the queued command (user_id, role, request_id, telegram_chat_id);
    None or role "owner" = the owner (personal context, ALLOWED_CHAT_ID)."""
    owner = not cmd or cmd.get("role", "owner") == "owner"
    chat = config.ALLOWED_CHAT_ID if owner else cmd.get("telegram_chat_id")
    extra = {} if owner else {"personal": False, "allow_state_update": False, "buttons": None}
    if cmd and cmd.get("request_id"):
        from urllib.parse import quote
        # The destination still requires the user's site session; no analysis text is in the URL.
        analysis_id = f"an_{cmd['request_id']}_{kodlar[0].upper()}" if kodlar else ""
        url = f"{config.PUBLIC_URL}/app/analizlerim?id={quote(analysis_id)}"
        extra["buttons"] = lambda _reply, _codes: InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Web panelinde gör", url=url)]])
    if not owner and cmd.get("own_keys"):
        try:  # the user's own API keys, fetched for this analysis only and kept in memory
            keys = await web_sync.user_keys(cmd["user_id"])
        except Exception as e:
            log.warning("User keys unavailable for %s: %s", cmd.get("user_id"), e)
            keys = None
        if not keys:
            now = alerts_store.now_tr()
            await web_sync.push_docs("analyses", [{
                "id": f"an_{cmd.get('request_id')}", "user_id": cmd["user_id"], "request_id": cmd.get("request_id"),
                "kodlar": [k.upper() for k in kodlar if k][:10], "piyasa": piyasa, "zaman": now.isoformat(),
                "metin": "❌ Kayıtlı API anahtarın kullanılamadı. Hesap sayfasından anahtarını kontrol edip tekrar dene."}])
            return None
        extra["keys"] = keys
    kodlar = [k.upper() for k in kodlar if k][:10]
    if not kodlar:
        return None
    if len(kodlar) > 1:
        res = await takip_rows({piyasa: kodlar})
        reply = await run_analysis(bot, chat, f"[TAKİP] Panelden {len(kodlar)} kod için karşılaştırma istendi. Kodla hesaplanmış "
                                   "hızlı durum [PİYASA VERİSİ].TAKIP_LISTESI içinde.", [], data={"TAKIP_LISTESI": res},
                                   **{"buttons": None, "allow_state_update": False, **extra})
    elif piyasa == "KRIPTO":
        reply = await run_analysis(bot, chat, f"{kodlar[0]} analiz et.", [kodlar[0]], **extra)
    elif piyasa == "BIST":
        async with httpx.AsyncClient() as client:
            data = await bist_market_data(client, kodlar[0])
        reply = await run_analysis(bot, chat, f"[BIST] {kodlar[0]} analiz et.", [], data=data,
                                   footer="Fiyat Yahoo'dan, ~15 dk gecikmeli.", **{"buttons": None, **extra})
    else:
        data = await us_signals.market_data(kodlar[0])
        reply = await run_analysis(bot, chat, f"[ABD] {kodlar[0]} analiz et.", [], data=data, **{"buttons": None, **extra})
    if reply and web_sync.enabled():
        now = alerts_store.now_tr()
        doc = {"id": f"an_{int(now.timestamp())}_{kodlar[0]}", "kodlar": kodlar, "piyasa": piyasa,
               "zaman": now.isoformat(), "metin": reply}
        if cmd and cmd.get("user_id"):
            doc.update(id=f"an_{cmd.get('request_id') or int(now.timestamp())}_{kodlar[0]}", user_id=cmd["user_id"],
                       request_id=cmd.get("request_id"))
        await web_sync.push_docs("analyses", [doc])
    return reply


async def weekly_lesson(bot) -> str | None:
    """The week's lesson: code computes, the AI writes at most five sentences. Stored for the panel."""
    data = features.lesson_data(7)
    reply = await run_analysis(bot, config.ALLOWED_CHAT_ID,
                               "[DERS] Bu haftanın dersi. Kodla hesaplanmış veri [PİYASA VERİSİ].HAFTALIK_DERS içinde.",
                               [], data={"HAFTALIK_DERS": data}, buttons=None, allow_state_update=False)
    if reply:
        s = alerts_store.load_settings()
        s["son_ders"] = {"zaman": alerts_store.now_tr().isoformat(), "metin": reply, "veri": {k: v for k, v in data.items() if k != "kural_istatistik"}}
        alerts_store.save_settings(s)
    return reply


async def lesson_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await weekly_lesson(context.bot)
    except Exception as e:
        log.warning("Weekly lesson failed: %s", e)


async def calendar_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await features.refresh_calendar(watchlist.load())
        text = features.calendar_reminders()
        if text:
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())
    except Exception as e:
        log.warning("Company calendar failed: %s", e)


def _held_bist() -> set[str]:
    return {bist.ticker(p["symbol"]) for p in positions.open_positions() if p.get("piyasa") == "BIST"}


async def kap_job(context: ContextTypes.DEFAULT_TYPE):
    if not 8 <= alerts_store.now_tr().hour < 23:
        return
    try:
        new = await features.kap_new(_held_bist())
        if new:
            await context.bot.send_message(config.ALLOWED_CHAT_ID, features.kap_text(new), disable_web_page_preview=True,
                                           disable_notification=silent())
    except Exception as e:
        log.warning("KAP check failed: %s", e)


async def allocation_job(context: ContextTypes.DEFAULT_TYPE):
    if not features.target() or not positions.open_positions():
        return
    try:
        text = features.allocation_text(features.allocation(await collect_portfolio(verdicts=False)))
        if text:
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())
    except Exception as e:
        log.warning("Allocation check failed: %s", e)


async def watch_rules_job(context: ContextTypes.DEFAULT_TYPE):
    if alerts_store.is_quiet() or alerts_store.now_tr().hour < 8:
        return
    try:
        rows = (await watchlist.panel_rows()).get("piyasalar", {})
        text = features.check_watch_rules(rows)
        if text:
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=True)
    except Exception as e:
        log.warning("Watchlist rules failed: %s", e)


def _parse_kv(args: list[str]) -> dict[str, str]:
    return {a.split("=", 1)[0].lower(): a.split("=", 1)[1] for a in args if "=" in a}


@authorized
async def hedef(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hedef                          -> current vs target allocation
    /hedef BIST 50 KRIPTO 20 ABD 20 NAKIT 10 [tolerans=5]  -> set the target"""
    args = context.args
    if args:
        nums, kv = {}, _parse_kv(args)
        plain = [a for a in args if "=" not in a]
        for name, val in zip(plain[::2], plain[1::2]):
            key = {"BIST": "BIST", "KRIPTO": "KRIPTO", "KRİPTO": "KRIPTO", "ABD": "ABD", "NAKIT": "NAKIT", "NAKİT": "NAKIT"}.get(name.upper())
            if key:
                nums[key] = float(val.replace(",", ".").replace("%", ""))
        if not nums:
            await update.message.reply_text("Kullanım: /hedef BIST 50 KRIPTO 20 ABD 20 NAKIT 10 [tolerans=5]\n"
                                            "Yüzdeler toplamı 100 olmazsa oranlanır.")
            return
        t = features.set_target(nums, float(kv.get("tolerans", 5)))
        await update.message.reply_text("🎯 Hedef dağılım kaydedildi: " + " · ".join(f"{k} %{t[k]:g}" for k in features.TARGET_KEYS)
                                        + f" · tolerans ±{t['tolerans']:g} puan\nSapma olursa her akşam 19:15'te haber veririm.")
        return
    if not positions.open_positions():
        await update.message.reply_text("Portföy boş.")
        return
    a = features.allocation(await collect_portfolio(verdicts=False))
    if not a:
        await update.message.reply_text("Dolar kuru alınamadı; biraz sonra tekrar dene.")
        return
    name = {"BIST": "BIST", "KRIPTO": "Kripto", "ABD": "ABD", "NAKIT": "Nakit"}
    lines = [f"⚖️ DAĞILIM (toplam ₺{a['toplam_tl']:,.0f})"]
    for r in a["satirlar"]:
        goal = "" if r["hedef"] is None else f" · hedef %{r['hedef']:g} ({r['sapma']:+.1f} puan)"
        lines.append(f"{name[r['piyasa']]}: %{r['gercek']:g} (₺{r['deger_tl']:,.0f}){goal}")
    if not a["hedef_var"]:
        lines.append("\nHedef yok. Koy: /hedef BIST 50 KRIPTO 20 ABD 20 NAKIT 10")
    elif a["asanlar"]:
        lines.append(f"\nTolerans (±{a['tolerans']:g}) dışında: " + ", ".join(name[r['piyasa']] for r in a["asanlar"]))
    lines.append("Nakit: /bakiye nakit ile girilen tutarlar. Bu bir öneri değildir.")
    await update.message.reply_text("\n".join(lines))


@authorized
async def sanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sanal · /sanal al KOD FIYAT TUTAR (ya da adet=N) · /sanal sat ID [FIYAT]"""
    args = context.args
    sub = args[0].lower() if args else ""
    if sub == "al" and len(args) >= 3:
        code = _takip_code(args[1])
        mkt = await _detect_market(code)
        if mkt not in ("KRIPTO", "BIST", "ABD"):
            await update.message.reply_text(f"❌ {code} bulunamadı (kripto, BIST ya da ABD olmalı).")
            return
        price = float(args[2].replace(",", "."))
        if not math.isfinite(price) or price <= 0:
            await update.message.reply_text("❌ Alış fiyatı sıfırdan büyük olmalı.")
            return
        kv = _parse_kv(args[3:])
        if "adet" in kv:
            qty = float(kv["adet"].replace(",", "."))
        elif len(args) >= 4 and "=" not in args[3]:
            qty = float(args[3].replace(",", ".").lower().removesuffix("tl").removesuffix("$")) / price
        else:
            await update.message.reply_text("Kullanım: /sanal al KOD FIYAT TUTAR · örnek: /sanal al THYAO 290 5000 · /sanal al NVDA 225 adet=3")
            return
        if not math.isfinite(qty):
            await update.message.reply_text("❌ Adet geçerli bir sayı olmalı.")
            return
        if mkt == "BIST" and "adet" not in kv:
            qty = math.floor(qty)
        if qty <= 0:
            await update.message.reply_text("❌ Fiyat ve adet sıfırdan büyük olmalı; BIST için en az 1 tam hisse gerekir.")
            return
        p = features.paper_open(mkt, code, price, qty, kv.get("not", ""))
        await update.message.reply_text(f"🧪 Sanal alım #{p['id']}: {code} ({mkt}) {qty:.6g} adet @ {price:g}. "
                                        "Gerçek portföyde sayılmaz. Durum: /sanal")
        return
    if sub == "sat" and len(args) >= 2:
        pid = int(args[1].lstrip("#"))
        row = next((r for r in features.paper_all() if r["id"] == pid), None)
        if not row:
            await update.message.reply_text("Bu ID'de sanal işlem yok. /sanal")
            return
        price = float(args[2].replace(",", ".")) if len(args) >= 3 else None
        if price is None:
            async with httpx.AsyncClient() as client:
                price = await features.last_price(client, row["piyasa"], row["kod"])
        p = features.paper_close(pid, price)
        if not p:
            await update.message.reply_text("Bu sanal işlem zaten kapalı.")
            return
        await update.message.reply_text(f"🧪 Sanal satış #{pid} {p['kod']} @ {price:g}: {(price - p['giris']) * p['adet']:+,.2f} "
                                        f"({(price / p['giris'] - 1) * 100:+.2f}%)")
        return
    await update.message.reply_text(features.paper_text(await features.paper_view()))


@authorized
async def ders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await weekly_lesson(context.bot)


@authorized
async def kap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new = await features.kap_new(_held_bist())
    recent = features.kap_for_panel()
    if not recent:
        await update.message.reply_text("📢 Bugün portföyündeki BIST hisseleri için KAP bildirimi yok. Yeni bildirim gelince haber veririm.")
        return
    await update.message.reply_text(features.kap_text(recent[:8]) if not new else features.kap_text(new), disable_web_page_preview=True)


@authorized
async def olaylar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await features.refresh_calendar(watchlist.load())
    items = features.calendar_for_panel(45)
    if not items:
        await update.message.reply_text("📅 Önümüzdeki 45 günde portföy ve takip listende bilanço/temettü tarihi görünmüyor.")
        return
    lines = ["📅 ŞİRKET OLAYLARI (45 gün · Yahoo, kesin tarih için KAP)"]
    for i in items[:40]:
        lines.append(f"{i['tarih'][8:10]}.{i['tarih'][5:7]} {'💼 ' if i['portfoyde'] else ''}{i['kod']} ({i['piyasa']}) · {i['etiket']}")
    await send_lines(context.bot, update.effective_chat.id, "\n".join(lines))


# panel -> bot actions (queued by the panel, applied here with the same functions as Telegram)

# ---------------------------------------------------------------- decision tools (tools.py) ------------------------

async def _code_market(arg: str, forced: str | None = None) -> tuple[str, str]:
    code = _takip_code(arg)
    mkt = forced if forced in tools.MARKETS else await _detect_market(arg)
    if mkt not in tools.MARKETS:
        raise ValueError(f"{code} kripto, BIST ya da ABD'de bulunamadı")
    return code, mkt


@authorized
async def kontrol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kontrol KOD [GİRİŞ] [STOP] [HEDEF] [piyasa=BIST]: the market's decision gate for a hand-planned buy."""
    pos, kv = _opts(context.args)
    if not pos:
        await update.message.reply_text("Kullanım: /kontrol KOD [GİRİŞ] [STOP] [HEDEF]\n"
                                        "Örnek: /kontrol THYAO 290 280 310 · /kontrol BTC (şu anki fiyat, stop/hedef bölgelerden)\n"
                                        "Aynı kod kapısı: GEÇTİ ise kurallara uygun adet ve risk yazılır. Bot işlem yapmaz.")
        return
    try:
        code, mkt = await _code_market(pos[0], (kv.get("piyasa") or "").upper() or None)
        nums = [_float(x) for x in pos[1:4]]
        nums += [None] * (3 - len(nums))
        await update.message.reply_text(f"⏳ {code} ({mkt}) kapıdan geçiriliyor...")
        r = await tools.pre_trade(mkt, code, *nums)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    await web_sync.push_docs("sonuclar", [{"id": "kontrol", "tur": "kontrol", **r}])
    await update.message.reply_text(tools.pre_trade_text(r))


@authorized
async def galarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/galarm · /galarm KOD GÖSTERGE YÖN [DEĞER] TF · /galarm sil ID"""
    args = [a.lower() for a in context.args]
    if not args or args[0] in ("liste", "list"):
        await update.message.reply_text(tools.ind_text())
        return
    if args[0] == "sil" and len(args) == 2:
        hit = tools.ind_delete(int(args[1].lstrip("#")))
        await update.message.reply_text(f"🗑 Silindi: {tools.ind_label(hit)}" if hit else "❌ Bu ID yok. Liste: /galarm")
        return
    usage = ("Kullanım: /galarm KOD GÖSTERGE YÖN [DEĞER] ZAMAN\n"
             "Gösterge: sma20, sma50, sma200, rsi, hacim · yön: ustu / alti · zaman: kripto 1h 4h 1d, BIST/ABD 1d 1wk\n"
             "Örnek: /galarm THYAO sma50 ustu 1d · /galarm BTC rsi alti 30 4h · /galarm NVDA hacim 2 1d")
    try:
        code, mkt = await _code_market(context.args[0])
        ind = args[1]
        rest = args[2:]
        direction = "ustu" if ind == "hacim" else rest.pop(0).replace("üstü", "ustu").replace("altı", "alti")
        value = _float(rest.pop(0)) if ind in ("rsi", "hacim") else None
        tf = rest.pop(0) if rest else ("1d" if mkt != "KRIPTO" else "4h")
        a = tools.ind_create(mkt, code, ind, direction, tf, value)
    except (IndexError, ValueError) as e:
        await update.message.reply_text((f"❌ {e}\n" if str(e) and not isinstance(e, IndexError) else "") + usage)
        return
    await update.message.reply_text(f"📈 Kuruldu: {tools.ind_label(a)}\nYalnız kapanmış mumla, her yeni kesişmede bir kez haber veririm. "
                                    "Bu bir AL sinyali değildir.")


@authorized
async def karsilastir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/karsilastir KOD KOD [KOD KOD]: BIST or US stocks side by side."""
    if not 2 <= len(context.args) <= 4:
        await update.message.reply_text("Kullanım: /karsilastir THYAO PGSUS [EREGL] [ASELS] · ABD: /karsilastir NVDA AMD\n"
                                        "2-4 hisse, aynı piyasadan. Temel skor, büyüme, marj, borç, değerleme, trend.")
        return
    try:
        first, mkt = await _code_market(context.args[0])
        await update.message.reply_text(f"⏳ {len(context.args)} hisse karşılaştırılıyor (bilançolar indiriliyor, ~20-60 sn)...")
        c = await tools.compare(mkt, [first] + [_takip_code(a) for a in context.args[1:]])
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    await web_sync.push_docs("sonuclar", [{"id": "karsilastirma", "tur": "karsilastirma", **c, "en_iyi": tools.best_of(c["satirlar"])}])
    await update.message.reply_text(tools.compare_text(c))


async def cloud_state_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.to_thread(cloud_store.sync)
    except Exception as e:
        log.warning("Cloud state sync failed: %s", e)


async def backup_job(context: ContextTypes.DEFAULT_TYPE):
    """03:30 TR: whole database to a gzip file on the server (Atlas M0 keeps no backups)."""
    try:
        path, counts = await asyncio.to_thread(db_backup.run)
        if not path.stat().st_size or not counts:
            raise RuntimeError("boş yedek")
    except Exception as e:
        log.exception("Database backup failed")
        await context.bot.send_message(config.ALLOWED_CHAT_ID, f"⚠️ Günlük veritabanı yedeği alınamadı: {type(e).__name__}. "
                                       "Ayrıntı sunucu loglarında; site çalışmaya devam ediyor.")


async def ind_alarm_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        for text in await tools.check_ind_alerts():
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())
    except Exception as e:
        log.warning("Indicator alarms failed: %s", e)


def register_panel_actions(bot):
    async def analysis(p):
        piyasa = p.get("piyasa", "KRIPTO")
        kodlar = p.get("kodlar") or [p.get("kod")]
        await panel_analysis(bot, piyasa, kodlar, p.get("_komut"))
        return f"🧠 Panelden analiz: {', '.join(k for k in kodlar if k)} ({piyasa}) — cevap yukarıda ve panelde."

    async def strategy_scan(p):
        meta = p.get("_komut") or {}
        strategy = ({"id": "builtin:quality_momentum", "user_id": meta.get("user_id"),
                     "name": "Kalite + Momentum", "rules": {}}
                    if p["strategy_id"] == "builtin:quality_momentum" else
                    await web_sync.get_strategy(p["strategy_id"]))
        if strategy["user_id"] != meta.get("user_id"):
            return "❌ Strateji hesabı uyuşmuyor; tarama yapılmadı."
        chat = meta.get("telegram_chat_id")
        status = None
        if chat:  # honest progress instead of a promise of seconds
            try:
                status = await bot.send_message(chat, f"⏳ {strategy['name']}: BIST 100 verisi hazırlanıyor…", disable_notification=True)
            except Exception:
                status = None

        async def progress(done, total):
            if status:
                await status.edit_text(f"⏳ {strategy['name']}: şirket verileri toplanıyor {done}/{total} "
                                       "(ilk tarama birkaç dakika sürebilir, sonrakiler günlük önbellekten gelir)")
        data = await quant_scan.snapshot(progress)
        if status:
            try:
                await status.delete()
            except Exception:
                pass
        ranked = quant_scan.rank(data, strategy["rules"])
        top = ranked[:max(1, min(10, int(p.get("top_n") or 3)))]
        lines = [f"🔎 {strategy['name']} — BIST 100", f"Taranan: {data['universe_count']} · veri eksikliği nedeniyle dışlanan: {data['excluded']}",
                 f"Hesap: {data['calculated_at'][:16]} UTC · 3 aylık endekse göre momentum", ""]
        if top:
            for i, row in enumerate(top, 1):
                lines.append(f"{i}. {row['kod']} · kalite {row['kalite']}/100 · göreli momentum %{row['momentum_goreli']:+g} "
                             f"· F/K {row['fk'] if row['fk'] is not None else 'yok'} · birleşik puan {row['birlesik_skor']}/100")
        else:
            lines.append("Koşulları geçen hisse yok.")
        lines.extend(["", "Kalite; kârlılık, finansal kalite, bilanço ve nakit akışı bileşenlerinden hesaplanır. "
                       "Puan getiri olasılığı değildir. F/K olmayan hisse, F/K koşulunu geçmez.",
                      f"Kaynak: {data['source']}. Bilanço: İş Yatırım; fiyat: Yahoo (gecikmeli)."])
        message = "\n".join(lines)
        now = alerts_store.now_tr().isoformat()
        request_id = meta.get("request_id") or str(int(time.time()))
        record_id = f"an_{request_id}_strategy"
        await web_sync.push_docs("analyses", [{"id": record_id, "user_id": meta["user_id"], "request_id": request_id,
            "kodlar": [row["kod"] for row in top], "piyasa": "BIST", "zaman": now, "metin": message,
            "strategy_id": strategy["id"], "strategy_name": strategy["name"], "rules": strategy["rules"], "rows": top,
            "universe_count": data["universe_count"], "excluded": data["excluded"],
            "elenen": quant_scan.eliminated(data, strategy["rules"]), "gecen": len(ranked),
            "hesap_zamani": data["calculated_at"], "xu100": data.get("xu100"), "xu100_tarih": data.get("xu100_tarih"),
            "tur": "strateji"}])
        return message + f"\n\n📊 {config.PUBLIC_URL}/app/analizlerim?id={record_id}"

    async def plan_add_(p):
        key = await plan_key(str(p.get("kod", "")))
        if not key:
            return f"❌ Panel: {p.get('kod')} bulunamadı (plan listesi)"
        save_plan_list(plan_list() + [key])
        return f"✅ Panelden plan listesine eklendi: {plan_key_name(key)}"

    async def plan_remove(p):
        key = p.get("key")
        save_plan_list([k for k in plan_list() if k != key])
        return f"🗑 Panelden plan listesinden çıkarıldı: {plan_key_name(key or '')}"

    async def firsat_run(p):
        res = await opportunities.collect()
        await web_sync.push_docs("firsat", [{"id": "firsat", **res, "metin": opportunities.text(res)}], replace=True)
        return f"🔎 Panelden fırsat taraması: {len(res['alinabilir'])} alınabilir, {len(res['kalemler'])} kalem incelendi."

    async def target_set(p):
        t = features.set_target({k: p.get(k) for k in features.TARGET_KEYS}, float(p.get("tolerans") or 5))
        return "🎯 Panelden hedef dağılım: " + " · ".join(f"{k} %{t[k]:g}" for k in features.TARGET_KEYS)

    async def rules_set(p):
        r = features.set_watch_rules(**{k: p.get(k) for k in features.RULE_DEFAULTS})
        return ("🔔 Takip kuralları " + ("açık" if r["aktif"] else "kapalı") + f": desteğe %{r['destek_yakin']:g}, RSI ≤{r['rsi_alti']:g}, "
                f"RSI ≥{r['rsi_ustu']:g}, hacim ≥{r['hacim_kat']:g}×")

    async def paper_open_(p):
        code = _takip_code(str(p.get("kod", "")))
        mkt = p.get("piyasa") or await _detect_market(code)
        price = float(p["fiyat"])
        if price <= 0 or not code or mkt not in ("BIST", "KRIPTO", "ABD"):
            return "❌ Panel: sanal işlem için geçerli piyasa, kod ve pozitif fiyat gerekli"
        async with httpx.AsyncClient() as client:
            await features.last_price(client, mkt, code)  # verify the symbol in the selected market
        qty = float(p["adet"]) if p.get("adet") else float(p["tutar"]) / price
        if mkt == "BIST" and not p.get("adet"):
            qty = math.floor(qty)
        row = features.paper_open(mkt, code, price, qty, p.get("not") or "")
        return f"🧪 Panelden sanal alım #{row['id']}: {code} {qty:.6g} adet @ {price:g}"

    async def paper_close_(p):
        row = next((r for r in features.paper_all() if r["id"] == int(p["id"])), None)
        if not row:
            return "❌ Panel: sanal işlem yok"
        price = p.get("fiyat")
        if not price:
            async with httpx.AsyncClient() as client:
                price = await features.last_price(client, row["piyasa"], row["kod"])
        done = features.paper_close(row["id"], float(price))
        return f"🧪 Panelden sanal satış #{row['id']} {row['kod']} @ {float(price):g}" if done else "ℹ️ Sanal işlem zaten kapalı"

    async def lesson(p):
        await weekly_lesson(bot)
        return "📘 Panelden haftalık ders istendi — cevap yukarıda ve panelde."

    async def check_req(p):
        try:
            code, mkt = await _code_market(str(p.get("kod", "")), p.get("piyasa"))
            num = lambda k: float(p[k]) if p.get(k) not in (None, "") else None
            r = await tools.pre_trade(mkt, code, num("giris"), num("stop"), num("hedef"))
        except ValueError as e:
            await web_sync.push_docs("sonuclar", [{"id": "kontrol", "tur": "kontrol", "hata": str(e),
                                                   "zaman": alerts_store.now_tr().isoformat()}])
            return f"❌ Panel kontrol: {e}"
        await web_sync.push_docs("sonuclar", [{"id": "kontrol", "tur": "kontrol", **r}])
        return "Panelden " + tools.pre_trade_text(r)

    async def ind_create_(p):
        try:
            code, mkt = await _code_market(str(p.get("kod", "")), p.get("piyasa"))
            v = p.get("deger")
            a = tools.ind_create(mkt, code, str(p.get("gosterge", "")), str(p.get("yon", "ustu")), str(p.get("tf", "1d")),
                                 float(v) if v not in (None, "") else None)
        except ValueError as e:
            return f"❌ Panel gösterge alarmı: {e}"
        return f"📈 Panelden gösterge alarmı kuruldu: {tools.ind_label(a)}"

    async def ind_delete_(p):
        hit = tools.ind_delete(int(p.get("id", 0)))
        return f"🗑 Panelden gösterge alarmı silindi: {tools.ind_label(hit)}" if hit else "❌ Panel: gösterge alarmı yok"

    async def compare_req(p):
        try:
            mkt = p.get("piyasa")
            c = await tools.compare(mkt, [_takip_code(str(k)) for k in (p.get("kodlar") or [])])
        except ValueError as e:
            await web_sync.push_docs("sonuclar", [{"id": "karsilastirma", "tur": "karsilastirma", "hata": str(e),
                                                   "zaman": alerts_store.now_tr().isoformat()}])
            return f"❌ Panel karşılaştırma: {e}"
        await web_sync.push_docs("sonuclar", [{"id": "karsilastirma", "tur": "karsilastirma", **c,
                                               "en_iyi": tools.best_of(c["satirlar"])}])
        return f"⚖️ Panelden karşılaştırma: {', '.join(c['kodlar'])} — sonuç panelde."

    async def dividend_refresh(p):
        plan = await tools.dividend_plan(force=True)
        return "💰 Panelden temettü planı yenilendi.\n" + tools.dividend_text(plan)

    async def backtest_req(p):
        """Same engine as /backtest; the panel's Backtest page shows the latest run."""
        pair = str(p.get("pair", "")).upper().replace("-", "/")
        if "/" not in pair:
            pair = f"{pair}/{config.QUOTE}"
        direction, tf = str(p.get("yon", "ABOVE")).upper(), str(p.get("tf", "15m"))
        num = lambda k: float(p[k]) if p.get(k) not in (None, "") else None
        trigger, stop, target = num("tetik"), num("iptal"), num("hedef")
        days = int(p.get("gun") or 180)
        if direction not in ("ABOVE", "BELOW") or tf not in backtest.TF_MS or not trigger or trigger <= 0 or not 7 <= days <= 365:
            return "❌ Panel backtest: parite, yön (ABOVE/BELOW), tetik > 0, zaman dilimi ve 7-365 gün gerekli"
        try:
            res = await backtest.run(alerts_store.pair_to_symbol(pair), direction, trigger, tf, days, stop, target)
        except market.SymbolNotFound:
            return f"❌ Panel backtest: Binance'te {pair} yok"
        if "hata" in res:
            return f"❌ Panel backtest: {res['hata']}"
        positions.save_last_backtest({"pair": pair, "yon": direction, "tetik": trigger, "timeframe": tf,
                                      "iptal": stop, "hedef": target, "gun": days, **res})
        t = res["tum"]
        return (f"🧪 Panelden backtest {pair} KAPANIŞ {direction} {trigger:g} {tf}: {t['islem']} tetik, "
                f"isabet %{t['isabet_yuzde']}, net toplam {t['toplam_R_net']}R (sonuç panelde)")

    async def settings_set(p):
        """Only the few settings that are safe to change from the panel. Rules stay fixed in code."""
        s = alerts_store.load_settings()
        done = []
        if p.get("ai_mod") in ("sira", "deepseek", "kimi", "glm"):
            s["ai_mod"] = p["ai_mod"]
            done.append(f"yapay zekâ: {p['ai_mod']}")
        for key, name, cast in (("bist_butce", "bist_budget_tl", int), ("abd_butce", "abd_butce_usd", float)):
            if p.get(key) not in (None, ""):
                v = cast(float(p[key]))
                if not 0 < v <= 100_000_000:
                    return f"❌ Panel ayarı: {key} sıfırdan büyük olmalı"
                s[name] = v
                done.append(f"{key} {v:,}")
        if not done:
            return "❌ Panel ayarı: değişiklik yok"
        alerts_store.save_settings(s)
        return "⚙️ Panelden ayar: " + ", ".join(done)

    async def fundamentals_req(p):
        """/temel from the panel: BIST (İş Yatırım) or US (SEC + Yahoo) fundamentals, no AI."""
        tick = bist.ticker(str(p.get("kod", ""))).removesuffix(".US")
        mkt = p.get("piyasa") or ("BIST" if tick in universe.bist_names() else await _detect_market(tick))
        try:
            if mkt == "ABD":
                f = await us_fund.report(tick)
                text = us_fund.text(f)
                label = f["puan"].get("durum")
                flags = (f.get("uyarilar") or [])[:6]
                good = (f.get("olumlular") or [])[:6]
            elif mkt == "BIST":
                f = await fundamentals.report(tick)
                text = fundamentals.text(f)
                label = f["puan"].get("etiket")
                flags = (f.get("kirmizi_bayraklar") or [])[:6]
                good = []
            else:
                return f"❌ Panel temel analiz: {tick} BIST ya da ABD hissesi değil"
        except Exception as e:
            await web_sync.push_docs("sonuclar", [{"id": "temel", "tur": "temel", "hata": f"{tick}: {str(e)[:150]}",
                                                   "zaman": alerts_store.now_tr().isoformat()}])
            return f"❌ Panel temel analiz {tick}: {str(e)[:150]}"
        await web_sync.push_docs("sonuclar", [{"id": "temel", "tur": "temel", "kod": tick, "piyasa": mkt,
                                               "zaman": alerts_store.now_tr().isoformat(), "fiyat": f.get("fiyat"),
                                               "skor": f["puan"]["skor"], "etiket": label, "parcalar": f["puan"]["parcalar"],
                                               "not": f["puan"].get("not"), "uyarilar": flags, "olumlular": good,
                                               "metin": text, "kaynak": f.get("kaynak")}])
        return f"📚 Panelden temel analiz {tick}: skor {f['puan']['skor']}/100, {label} (ayrıntı panelde)"

    web_sync.EXTRA_HANDLERS.update({
        "analysis.request": analysis, "strategy.scan": strategy_scan, "plan.add": plan_add_, "plan.remove": plan_remove, "firsat.run": firsat_run,
        "target.set": target_set, "watch.rules": rules_set, "paper.open": paper_open_, "paper.close": paper_close_,
        "lesson.request": lesson,
        "check.request": check_req, "ind.create": ind_create_, "ind.delete": ind_delete_, "compare.request": compare_req,
        "dividend.refresh": dividend_refresh,
        "backtest.run": backtest_req, "settings.set": settings_set, "fundamentals.request": fundamentals_req,
    })


# web panel: one "extras" document with the portfolio-level features (every 15 minutes)

async def build_extras() -> dict:
    since7 = (alerts_store.now_tr() - timedelta(days=7)).isoformat()
    since30 = (alerts_store.now_tr() - timedelta(days=30)).isoformat()
    doc = {"id": "extras", "guncelleme": alerts_store.now_tr().isoformat()}
    pf = await collect_portfolio(verdicts=False) if positions.open_positions() else None
    if pf:
        doc["portfoy"] = [{"ad": risk.name(g), "piyasa": g["piyasa"], "adet": g["adet"], "para": g["para"],
                           "maliyet": round(g["maliyet"], 2), "deger": round(g["deger"], 2), "fiyat": g["fiyat"],
                           "gun_yuzde": None if g["gun_yuzde"] is None else round(g["gun_yuzde"], 2),
                           "toplam_yuzde": round((g["deger"] / g["maliyet"] - 1) * 100, 2) if g["maliyet"] else None,
                           "usd_yuzde": g["reel"].get("usd_yuzde"), "tl_yuzde": g["reel"].get("tl_yuzde"),
                           "reel_yuzde": g["reel"].get("reel_yuzde"), "temettu": round(g["temettu"], 2)}
                          for g in pf["gruplar"]]
        doc["yogunlasma"] = pf["yogunlasma"]
        doc["usdtry"] = pf.get("usdtry")
        features.record_history(pf)
        doc["dagilim"] = features.allocation(pf)
        try:
            async with httpx.AsyncClient() as client:
                doc["kiyas"] = benchmark.compare(benchmark.rows_from_portfolio(pf), await benchmark.benchmark_series(client),
                                                 benchmark.deposit_rate())
        except Exception as e:
            log.warning("Panel benchmark failed: %s", e)
    await shadow.refresh(shadow.signals(since30))
    doc["golge"] = {k: {kk: vv for kk, vv in v.items() if kk != "islemler"} for k, v in shadow.summary(since30).items()}
    st = discipline.status()
    doc["disiplin"] = {"aktif": st["aktif"], "seri": st["seri"], "bekleme_bitis": st["bekleme_bitis"],
                       "seri_sinir": config.LOSS_STREAK, "bekleme_saat": config.COOLDOWN_HOURS,
                       "gunluk_zarar_yuzde": config.DAILY_LOSS_PCT,
                       "piyasa": st["piyasa"], "olaylar": {discipline.VIOLATION_LABELS.get(k, k): len(v)
                                                            for k, v in discipline.violations(since7).items()}}
    doc["gunluk"] = journal.summary(since30)
    doc["birikim"] = [{**dca.label_dict(p), **dca.holdings(p)} for p in dca.plans()]
    doc["plan_listesi"] = [plan_key_name(k) for k in plan_list()]
    doc["duygu"] = await sentiment.summary()
    doc["karne"] = gate.rule_advice(gate.rule_stats(positions.load_decisions()))
    try:
        doc["takip_listesi"] = await watchlist.panel_rows()
    except Exception as e:
        log.warning("Panel watchlist failed: %s", e)
    for key, fn in (("planlar", lambda: features.plans_for_panel(plan_list())), ("geriye", lambda: features.backfill_history(90)),
                    ("sanal", features.paper_view)):
        try:
            doc[key] = await fn()
        except Exception as e:
            log.warning("Panel %s failed: %s", key, e)
    doc["gecmis"] = features.history_for_panel()["gunluk"]
    doc["hedef"] = features.target()
    doc["takvim"] = features.calendar_for_panel(45)
    doc["kap"] = features.kap_for_panel()
    doc["takip_kurallari"] = features.watch_rules()
    doc["ders"] = alerts_store.load_settings().get("son_ders")
    doc["gosterge_alarmlari"] = [a for a in tools.ind_alerts() if a["durum"] == "aktif"]
    try:
        doc["temettu_plani"] = await tools.dividend_plan()
    except Exception as e:
        log.warning("Panel dividend plan failed: %s", e)
    return doc


async def extras_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await web_sync.push_extras(await build_extras())
    except Exception as e:
        log.warning("Panel extras push failed: %s", e)


@authorized
async def bakiye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = [a.lower() for a in context.args]
    if args[:2] == ["nakit", "abd"] and len(args) >= 3:
        try:
            value = float(args[2].replace("$", "").replace(",", "."))
        except ValueError:
            value = None
        if value is None or value < 0:
            await update.message.reply_text("Kullanım: /bakiye nakit abd 1000 (USD)")
            return
        balance.set_cash("ABD", value)
        await update.message.reply_text(f"💵 ABD nakdi {value:,.2f} USD kaydedildi.")
        await balance_report(update, context, only="ABD")
        return
    if args[:1] == ["nakit"]:
        text = " ".join(args[1:])
        amount = parse_amount(text) if text else None
        if not amount:
            await update.message.reply_text("Kullanım: /bakiye nakit 5000 tl · /bakiye nakit 120 usdt (0 yazarsan sıfırlanır)")
            return
        value, cur = amount
        mkt = balance.CASH_MARKET[cur]
        balance.set_cash(mkt, value)
        await update.message.reply_text(f"💵 {'BIST' if mkt == 'BIST' else 'Kripto'} nakdi {value:,.2f} "
                                        f"{'TL' if cur == 'TL' else 'USDT'} kaydedildi.")
        await balance_report(update, context, only=mkt)
        return
    only = {"bist": "BIST", "kripto": "KRIPTO", "abd": "ABD", "altin": "DIGER", "altın": "DIGER"}.get(args[0]) if args else None
    await balance_report(update, context, only=only)


async def balance_report(update, context, only: str | None = None):
    status = await update.message.reply_text("⏳ bakiye ve kâr/zarar hesaplanıyor...")
    pf = (await collect_portfolio(only=only, verdicts=False) if positions.open_positions()
          else {"gruplar": [], "usdtry": None})
    week_ago = (alerts_store.now_tr() - timedelta(days=7)).date().isoformat()
    starts = {}
    async with httpx.AsyncClient() as client:
        for g in pf["gruplar"]:
            try:
                closes = await risk.daily_closes(client, g)
                older = closes[closes.index <= week_ago]
                starts[g["symbol"]] = float(older.iloc[-1]) if len(older) else None
            except Exception as e:
                log.warning("Week start price for %s failed: %s", g["symbol"], e)
                starts[g["symbol"]] = None
    res = balance.summarize(pf["gruplar"], starts)
    await status.delete()
    if not res and not balance.cash():
        await update.message.reply_text("Portföy ve nakit boş. Ekle: /aldim HYPE/USDT 92.7 60 · /bakiye nakit 5000 tl")
        return
    await update.message.reply_text(balance.text(res, balance.cash(), only), reply_markup=PORTFOLIO_BUTTONS)


async def universe_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await universe.refresh()
    except Exception as e:
        log.warning("Universe refresh failed: %s", e)


OPPORTUNITY_PHRASES = ("alabileceğim", "alabilecegim", "alınabilecek", "alinabilecek", "ne alayım", "ne alayim",
                       "ne alsam", "alınır mı", "alinir mi", "fırsat var", "firsat var", "tetiklenen", "tetiklendi mi",
                       "alım fırsatı", "alim firsati", "girilebilecek", "girebileceğim", "girebilecegim", "ne alınır",
                       "alınacak bir şey", "alinacak bir sey", "alım var mı", "alim var mi")


def wants_opportunities(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in OPPORTUNITY_PHRASES)


@authorized
async def firsat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await opportunity_report(update, context)


async def opportunity_report(update, context):
    """"Şu an alabileceğim tetiklenen bir hisse ya da coin var mı?" — code check across both markets."""
    status = await update.message.reply_text("⏳ Bütün planlar, son sinyaller, tarayıcı ve iki piyasanın kapıları kontrol "
                                             "ediliyor (canlı fiyat + kod kapısı)...")
    try:
        res = await opportunities.collect()
    except Exception as e:
        log.exception("Opportunity check failed")
        await status.edit_text(f"❌ Kontrol yapılamadı: {str(e)[:120]}")
        return
    context.user_data["firsat"] = res
    await status.delete()
    kb = [[InlineKeyboardButton("🧠 Yapay zekâ yorumu", callback_data="firsat|yorum"),
           InlineKeyboardButton("🔄 Yenile", callback_data="firsat|yenile")]]
    for i in res["alinabilir"][:3]:
        if i.get("karar_id"):
            kb.append([InlineKeyboardButton(f"✅ {i['kod']} aldım", callback_data=f"al|{i['karar_id']}")])
    await send_long(context.bot, update.effective_chat.id, opportunities.text(res), reply_markup=InlineKeyboardMarkup(kb))


async def opportunity_ai(update, context):
    res = context.user_data.get("firsat")
    if not res:
        await _shim(update).message.reply_text("Önce kontrolü çalıştır: /firsat")
        return
    await run_analysis(context.bot, update.effective_chat.id,
                       "[FIRSAT] Kullanıcı soruyor: şu an alabileceğim tetiklenen bir hisse ya da coin var mı? "
                       "Kodun sonucu [PİYASA VERİSİ].FIRSAT_TARAMASI içinde.",
                       [], data={"FIRSAT_TARAMASI": res}, buttons=None, allow_state_update=False)


@authorized
async def temel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: /temel THYAO — bilanço, büyüme (USD), marj, nakit, borç, ROE, "
                                        "F/K, FD/FAVÖK, kırmızı bayraklar, Stage ve yatırım skoru")
        return
    tick = bist.ticker(context.args[0]).removesuffix(".US")
    if tick not in universe.bist_names() and await _detect_market(tick) == "ABD":
        await us_fundamentals_cmd(update, context, tick)
        return
    status = await update.message.reply_text(f"⏳ {tick} mali tabloları çekiliyor (İş Yatırım)...")
    try:
        f = await fundamentals.report(tick)
    except Exception as e:
        await status.edit_text(f"❌ {tick}: {str(e)[:150]}")
        return
    await status.delete()
    await send_long(context.bot, update.effective_chat.id, fundamentals.text(f),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Yatırım tezi (yapay zekâ)", callback_data=f"temel|{tick}")]]))


async def fundamentals_ai(update, context, tick: str):
    async with httpx.AsyncClient() as client:
        data = await bist_market_data(client, tick)
    await run_analysis(context.bot, update.effective_chat.id,
                       f"[BIST TEMEL] {tick} için orta/uzun vadeli yatırım tezi çıkar.", [], data=data,
                       buttons=None, allow_state_update=False)


# --- US stocks: /abd, fundamentals, ranking, plan follow-up after the New York close -----------------------

@authorized
async def abd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    sub = args[0].lower() if args else ""
    if sub == "butce":
        try:
            value = float(args[1].replace("$", "").replace(",", "."))
        except (IndexError, ValueError):
            await update.message.reply_text("Kullanım: /abd butce 1000 (USD) — ilk kademe bütçenin %"
                                            f"{config.US_FIRST_TRANCHE_PCT}'i, işlem başı azami risk %{config.US_MAX_RISK_PCT:g}")
            return
        s = alerts_store.load_settings()
        s["abd_butce_usd"] = value
        alerts_store.save_settings(s)
        await update.message.reply_text(f"🇺🇸 ABD bütçesi {value:,.0f} USD. İlk kademe ≈ {value * config.US_FIRST_TRANCHE_PCT / 100:,.0f} USD, "
                                        f"işlem başı azami planlı zarar {value * config.US_MAX_RISK_PCT / 100:,.0f} USD.")
        return
    if sub == "guc":
        await us_ranking(update, context)
        return
    if sub == "temel" and len(args) > 1:
        await us_fundamentals_cmd(update, context, args[1].upper())
        return
    if sub:
        await us_analysis(update, context, sub.upper())
        return
    status = await update.message.reply_text("⏳ S&P 500, Nasdaq-100, VIX, 10Y faiz, dolar endeksi...")
    async with httpx.AsyncClient() as client:
        reg = await us.regime(client)
    await status.delete()
    usage = us.tiingo_usage()
    lines = [f"🇺🇸 ABD PİYASASI — kapı {reg['kapi']}", reg["seans"]]
    for sym in us.INDEXES:
        r = reg[sym]
        lines.append(f"{r['ad']}: {r.get('kapanis')} · {r.get('durum', r.get('hata'))} (SMA50 {r.get('sma50')}, SMA200 {r.get('sma200')}, 3 ay %{r.get('getiri_3a_yuzde')})")
    for name in ("VIX", "ABD 10Y faiz", "Dolar endeksi"):
        r = reg.get(name) or {}
        lines.append(f"{name}: {r.get('son')} (20 gün önce {r.get('20g_once')})" + (f" · {reg['vix_yorum']}" if name == "VIX" and reg.get("vix_yorum") else ""))
    budget = us_signals.budget_usd()
    lines += ["", f"Bütçe: {budget:,.0f} USD · açık {us_signals.open_us_usd():,.0f} USD" if budget else "Bütçe girilmedi: /abd butce 1000",
              f"Veri: {'Tiingo (bugün ' + str(usage.get('istek', 0)) + '/900 istek)' if config.TIINGO_API_KEY else 'Yahoo (Tiingo anahtarı .env: TIINGO_API_KEY)'} + SEC EDGAR",
              "", "/abd AAPL — analiz · /temel AAPL — temel · /abd guc — S&P 100 güç sıralaması · /abd butce 1000"]
    await update.message.reply_text("\n".join(lines))


async def us_analysis(update, context, t: str):
    status = await update.message.reply_text(f"⏳ {t}: SEC bilançoları, analist tahminleri, teknik ve piyasa rejimi hazırlanıyor...")
    try:
        data = await us_signals.market_data(t)
    except Exception as e:
        await status.edit_text(f"❌ {t}: {str(e)[:150]}")
        return
    await status.delete()
    await run_analysis(context.bot, update.effective_chat.id, f"[ABD] {t} analiz et.", [], data=data,
                       footer="ABD planı kaydedilirse New York kapanışından sonra günlük kapanışla izlenir.")


async def us_fundamentals_cmd(update, context, t: str):
    status = await update.message.reply_text(f"⏳ {t}: SEC EDGAR + analist tahminleri...")
    try:
        f = await us_fund.report(t)
    except Exception as e:
        await status.edit_text(f"❌ {t}: {str(e)[:150]}")
        return
    await status.delete()
    await send_long(context.bot, update.effective_chat.id, us_fund.text(f),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧠 Yatırım tezi (yapay zekâ)", callback_data=f"abdtez|{t}")]]))


async def us_thesis(update, context, t: str):
    data = await us_signals.market_data(t)
    await run_analysis(context.bot, update.effective_chat.id, f"[ABD TEMEL] {t} için orta/uzun vadeli yatırım tezi çıkar.",
                       [], data=data, buttons=None, allow_state_update=False)


async def us_ranking(update, context, chat_id: int | None = None, bot=None):
    """S&P 100 on weekly closes (Yahoo, no Tiingo quota) + the investment score of the top 10."""
    bot = bot or context.bot
    chat_id = chat_id or update.effective_chat.id
    msg = await bot.send_message(chat_id, "⏳ S&P 100 haftalık kapanışla sıralanıyor (~1 dk)...", disable_notification=True)
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient() as client:
        spy = await us.fetch(client, "SPY", "1wk", bulk=True)

        async def one(t):
            async with sem:
                try:
                    return t, strength.metrics(market.add_indicators(await us.fetch(client, t, "1wk", bulk=True)), spy)
                except Exception:
                    return t, None
        rows = {t: m for t, m in await asyncio.gather(*(one(t) for t in us.SP100)) if m}
    ranked = strength.rank(rows)[:10]

    async def score(t):
        async with sem:
            try:
                f = await us_fund.report(t)
                return f"{f['puan']['skor']}/100 {f['puan']['durum']}"
            except Exception:
                return "temel —"
    scores = await asyncio.gather(*(score(r["hisse"]) for r in ranked))
    lines = [f"💪 ABD GÜÇ SIRALAMASI — S&P 100 ({len(rows)} hisse, haftalık kapanış, S&P 500'e göre)"]
    for i, (r, sc) in enumerate(zip(ranked, scores), start=1):
        lines.append(f"{i:>2}. {r['hisse']} skor {r['skor']:.0f} · 13h SPY'ye göre {r['rs13']:+.1f} puan · zirveye {r['tepe_uzaklik']:+.1f}% · "
                     f"trend {'✅' * int(r['trend'] or 0) or '—'} · temel {sc}")
    lines.append("\nBir sıralama, AL sinyali değil. Ayrıntı: /abd KOD · /temel KOD")
    await msg.delete()
    await send_long(bot, chat_id, "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ İlk 5'i plan listeme ekle", callback_data="abdguc|ekle")]]))
    context_store = alerts_store.load_settings()
    context_store["abd_guc_son"] = [r["hisse"] for r in ranked]
    alerts_store.save_settings(context_store)


async def us_weekly_job(context: ContextTypes.DEFAULT_TYPE):
    await us_ranking(None, context, chat_id=config.ALLOWED_CHAT_ID, bot=context.bot)


async def us_daily_job(context: ContextTypes.DEFAULT_TYPE):
    """After the New York close: US alarms and plan confirmations on the final daily close."""
    if not us.trading_day():
        return
    try:
        fired, _ = await us_signals.check_alarms()
        for pair, a, df in fired:
            text = (f"🔔 {us.ticker(pair)} (ABD) alarm #{a['id']}: günlük kapanış {float(df.close.iloc[-1]):g} $ "
                    f"{'ÜSTÜNDE' if a['yon'] == 'ABOVE' else 'ALTINDA'} {a['tetik']:g}. Kapanış alarmı: dokunma değil, kapanış.")
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())
    except Exception:
        log.exception("US alarm check failed")
    try:
        events = await us_signals.daily_check()
    except Exception:
        log.exception("US plan check failed")
        return
    for e in events:
        t = us.ticker(e["sembol"])
        if e["tur"] != "kapi":
            await context.bot.send_message(config.ALLOWED_CHAT_ID, f"🇺🇸 {t}: {e['metin']}", disable_notification=silent())
            continue
        g = e["kapi"]
        if not config.BUY_SIGNALS:
            await context.bot.send_message(config.ALLOWED_CHAT_ID,
                                           f"📍 {t} (ABD): planının günlük kapanış teyidi geldi (kapanış {g['giris']:g} $).\n"
                                           f"{config.NO_SIGNAL_NOTE}", disable_notification=silent())
            continue
        lines = [f"🟢 AL (ABD, orta/uzun vade) — {t}" if g["ok"] else f"🟡 {t} (ABD): günlük kapanış teyidi geldi ama AL değil",
                 f"Kapanış {g['giris']:g} $ | iptal {g['iptal']} | hedef {g['hedef']} | R/R {g['rr']}", "", *g["maddeler"]]
        markup = None
        if g["ok"]:
            lines += ["", f"İlk kademe {g['kademe_usd']:,.0f} USD ≈ {g['adet']:g} hisse. Girişi yarın seans içinde yap, açılış boşluğunu kovalama; "
                          "bilanço tarihlerini takip et. Bot işlem yapmaz."]
            d = positions.log_decision({"pair": e["sembol"], "symbol": e["sembol"], "timeframe": "1d", "yon": "ABOVE", "alarm_id": 0,
                                        "piyasa": "ABD", "kapanis": g["giris"], "mum_ms": g["mum_ms"], "iptal": g["iptal"],
                                        "hedef": g["hedef"], "karar": "AL", "kademe_usd": g["kademe_usd"], "analiz": "\n".join(lines),
                                        "kapi": {k: g.get(k) for k in ("ok", "rr", "kademe_usd", "risk_off", "kurallar", "kalan")}})
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Aldım", callback_data=f"al|{d['id']}"),
                                            InlineKeyboardButton("⏭ Pas", callback_data=f"pas|{d['id']}")]])
        await context.bot.send_message(config.ALLOWED_CHAT_ID, "\n".join(lines), reply_markup=markup, disable_notification=silent())


@authorized
async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = context.args[0].lower() if context.args else ""
    if arg in ("sira", "sıra", "deepseek", "kimi", "glm"):
        s = alerts_store.load_settings()
        s["ai_mod"] = "sira" if arg in ("sira", "sıra") else arg
        alerts_store.save_settings(s)
    now = datetime.now(macro.TR)
    slot_end = now.replace(second=0, microsecond=0) + timedelta(minutes=config.AI_SLOT_MINUTES - now.minute % config.AI_SLOT_MINUTES)
    order = llm.pick_model(now)
    lines = [f"🧠 Şu an cevap veren: {llm.MODEL_NAMES[order[0]]}"
             + (f" (yedek: {', '.join(llm.MODEL_NAMES[m] for m in order[1:])})" if len(order) > 1 else ""),
             f"Mod: {'sırayla, 15 dakikada bir değişir' if llm.mode() == 'sira' else llm.MODEL_NAMES[llm.mode()] + ' sabit'}"]
    if llm.mode() == "sira":
        nxt = [slot_end + timedelta(minutes=config.AI_SLOT_MINUTES * i) for i in range(3)]
        lines.append("Sıradaki: " + " · ".join(f"{t.strftime('%H:%M')} {llm.MODEL_NAMES[llm.slot_model(t)]}" for t in nxt))
    missing = [n for m, n in llm.MODEL_NAMES.items() if m not in llm.available()]
    if missing:
        lines.append("⚠️ Anahtar yok: " + ", ".join(missing)
                     + (" — .env'de KIMI_API_KEY= / GLM_API_KEY= satırlarına anahtarı yapıştır (build.nvidia.com)"
                        if {"Kimi K3", "GLM 5.3"} & set(missing) else ""))
    lines.append("Değiştir: /model sira · /model kimi · /model deepseek · /model glm")
    await update.message.reply_text("\n".join(lines))


# --- AI council, BIST strength ranking, portfolio alarms ---------------------------------------------------

_background: set = set()


def _spawn(coro):
    """Run in the background without blocking the job; keep a reference so the task isn't garbage-collected."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def run_council(bot, market_name: str, code: str, dec_id: int, gate_result: dict):
    """Every model votes on a signal that passed the gate. Runs in the background after the signal message."""
    try:
        if market_name == "BIST":
            async with httpx.AsyncClient() as client:
                data = await bist_market_data(client, bist.ticker(code))
            question = (f"[BIST] {bist.ticker(code)}: günlük kapanış teyidi geldi ve kod kapısı GEÇTİ. "
                        "Orta/uzun vade için şimdi AL mı, BEKLE mi, PAS mı?")
        else:
            data, _ = await build_market_data([code])
            question = f"{code}/USDT: 15m teyit mumu kapandı ve kod kapısı GEÇTİ. Şimdi AL mı, BEKLE mi, PAS mı?"
        data["KOD_KAPISI"] = {"maddeler": gate_result.get("maddeler"), "rr": gate_result.get("rr")}
        votes = await llm.council(question, data)
    except Exception:
        log.exception("Council failed for %s", code)
        return
    if not votes:
        return
    positions.update_decision(dec_id, konsey=votes)
    al = sum(v["karar"] == "AL" for v in votes.values())
    majority = max(("AL", "BEKLE", "PAS"), key=lambda k: sum(v["karar"] == k for v in votes.values()))
    icon = {"AL": "🟢", "BEKLE": "🟡", "PAS": "🔴"}
    lines = [f"🗳 KONSEY — {bist.ticker(code) if market_name == 'BIST' else code}: {al}/{len(votes)} AL · çoğunluk {majority}"]
    lines += [f"{icon[v['karar']]} {llm.MODEL_NAMES[m]}: {v['karar']} — {v['neden']}" for m, v in votes.items()]
    lines.append("Kod kapısı geçti; konsey ikinci görüş. Oylar sonradan kapanışla puanlanır: /karne")
    await bot.send_message(config.ALLOWED_CHAT_ID, "\n".join(lines), disable_notification=True)


@authorized
async def guc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = strength.load()
    if not res or time.time() - res.get("zaman", 0) > 24 * 3600 or (context.args and context.args[0] == "yenile"):
        status = await update.message.reply_text(f"⏳ {len(universe.bist_names())} BIST hissesi haftalık kapanışla sıralanıyor (~1 dk)...")
        res = await strength.run()
        await status.delete()
    await send_long(context.bot, update.effective_chat.id, strength.text(res) + await _top_fundamentals(res),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ İlk 5'i plan listeme ekle", callback_data="guc|ekle")]]))


async def _top_fundamentals(res: dict, n: int = 10) -> str:
    """Investment score next to the strongest names: strong chart + good company = the best combination."""
    top = [r["hisse"] for r in res.get("sirali", [])[:n]]
    sem = asyncio.Semaphore(4)

    async def one(t):
        async with sem:
            try:
                f = await fundamentals.report(t)
                return f"{t} {f['puan']['skor']}/100 {f['puan']['etiket'].split(' (')[0]}"
            except Exception:
                return f"{t} —"
    rows = await asyncio.gather(*(one(t) for t in top))
    return "\n\n🏢 Temel skor (ilk 10): " + " · ".join(rows) + "\nAyrıntı: /temel KOD"


async def strength_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        res = await strength.run()
    except Exception:
        log.exception("Strength ranking failed")
        return
    await send_long(context.bot, config.ALLOWED_CHAT_ID, strength.text(res),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ İlk 5'i plan listeme ekle", callback_data="guc|ekle")]]))


async def market_balances() -> dict[str, float]:
    """Holdings + cash per market (BIST TL, KRIPTO USDT, DIGER TL)."""
    out = dict.fromkeys(("BIST", "KRIPTO", "DIGER"), 0.0)
    if positions.open_positions():
        pf = await collect_portfolio(verdicts=False)
        for g in pf["gruplar"]:
            out[g["piyasa"]] = out.get(g["piyasa"], 0.0) + g["deger"]
    for mkt, c in balance.cash().items():
        out[mkt] = out.get(mkt, 0.0) + c
    return out


@authorized
async def palarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usage = ("Kullanım:\n/palarm kripto %-10 — kripto bakiyem şimdiye göre %10 düşerse\n"
             "/palarm bist 20000 — BIST bakiyem 20.000 TL'yi geçerse (ya da altına inerse)\n"
             "/palarm — alarmlar · /palarm sil ID\nBakiye = varlık + nakit (/bakiye).")
    args = context.args
    if args[:1] == ["sil"] and len(args) == 2 and args[1].isdigit():
        await update.message.reply_text("🗑 Silindi." if pf_alarm.remove(int(args[1])) else "Bu ID'de alarm yok.")
        return
    if not args:
        items = pf_alarm.load()
        await update.message.reply_text(("🔔 PORTFÖY ALARMLARI\n" + "\n".join(pf_alarm.label(a) for a in items))
                                        if items else "Portföy alarmı yok.\n\n" + usage)
        return
    await add_portfolio_alarm(update, " ".join(args), usage)


async def add_portfolio_alarm(update, text: str, usage: str = "") -> bool:
    a = pf_alarm.parse(text)
    if not a:
        if usage:
            await update.message.reply_text(usage)
        return False
    bal = (await market_balances()).get(a["piyasa"], 0.0)
    if not bal and a["tur"] == "yuzde":
        await update.message.reply_text("Bu piyasada bakiye yok; yüzde alarmı için önce varlık ya da nakit gir (/bakiye).")
        return True
    new = pf_alarm.add(a, bal)
    await update.message.reply_text(f"🔔 Kuruldu: {pf_alarm.label(new)}\nŞu an {bal:,.2f} {pf_alarm.UNITS[a['piyasa']]}. "
                                    "15 dakikada bir kontrol edilir, bir kez haber verir.")
    return True


async def pf_alarm_job(context: ContextTypes.DEFAULT_TYPE):
    if not any(a["durum"] == "aktif" for a in pf_alarm.load()):
        return
    try:
        msgs = pf_alarm.check(await market_balances())
    except Exception:
        log.exception("Portfolio alarm check failed")
        return
    for m in msgs:
        await context.bot.send_message(config.ALLOWED_CHAT_ID, m, disable_notification=silent())


@authorized
async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await update.message.reply_text("⏳ kaynaklar kontrol ediliyor...")
    rows = await freshness.collect()
    await status.delete()
    await update.message.reply_text(freshness.text(rows))


@authorized
async def maliyet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(costs.summary_text())


async def position_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        events = await watcher.check_positions()
    except Exception:
        log.exception("Position check failed")
        return
    for kind, p, close in events:
        if kind == "stop":
            text = (f"🛑 #{p['id']} {p['pair']} STOP kapanışla kırıldı: {p['timeframe']} kapanış {close:g} < stop {p['stop']:g}.\n"
                    "Kural: sat. Goalpost yasağı: stop aşağı çekilmez.")
            kb = [[InlineKeyboardButton(f"💰 Sattım @ {close:g}", callback_data=f"sat|{p['id']}|{close}|stop"),
                   InlineKeyboardButton("✋ Tutuyorum", callback_data=f"tut|{p['id']}")]]
        else:
            text = (f"🎯 #{p['id']} {p['pair']} HEDEF kapanışla görüldü: {close:g} ≥ {p['hedef']:g}.\n"
                    "Kâr al ya da stopu girişe çek, risk sıfırlansın.")
            kb = [[InlineKeyboardButton(f"💰 Sattım @ {close:g}", callback_data=f"sat|{p['id']}|{close}|hedef"),
                   InlineKeyboardButton("🔒 Tut, stop girişe", callback_data=f"be|{p['id']}")]]
        if p.get("piyasa") == "BIST":
            kb = [[kb[0][1]]]
            text += f"\nSatış yaptıysan gerçekleşen fiyatla kaydet: /sat {p['id']} FIYAT (TL)."
        kb.append([InlineKeyboardButton("🗑 Hiç almadım, kaydı sil", callback_data=f"psil|{p['id']}")])
        r = positions.pnl(p, close)
        text += f"\nK/Z: {r['pnl_usd']:+.2f} {p.get('para', 'USD')}" + (f", {r['R']:+.2f}R" if r["R"] is not None else "")
        await context.bot.send_message(config.ALLOWED_CHAT_ID, text, reply_markup=InlineKeyboardMarkup(kb),
                                       disable_notification=silent())


# --- web panel sync ---------------------------------------------------------------

async def web_push_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        await web_sync.push_all()
    except Exception as e:
        log.warning("Web sync push failed: %s", e)


async def web_command_job(context: ContextTypes.DEFAULT_TYPE):
    async def notify(text: str, cmd: dict | None = None):
        """Owner commands report to the owner's chat; another user's result goes only to their own linked chat."""
        if not cmd or cmd.get("role", "owner") == "owner":
            await context.bot.send_message(config.ALLOWED_CHAT_ID, text, disable_notification=silent())
        elif cmd.get("telegram_chat_id"):
            await context.bot.send_message(cmd["telegram_chat_id"], text, disable_notification=True)
    try:
        if await web_sync.process_commands(engine.refresh, notify):
            await web_sync.push_all()  # show the result in the panel right away
            await web_sync.push_extras(await build_extras())
    except Exception as e:
        log.warning("Web command poll failed: %s", e)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Any unhandled handler exception: log it and tell the user instead of staying silent."""
    if isinstance(context.error, NetworkError) and not isinstance(context.error, BadRequest):
        log.warning("Telegram connection problem (handled, polling continues): %s", context.error)
        return
    log.error("Unhandled error", exc_info=context.error)
    chat = getattr(update, "effective_chat", None)
    if chat is None or chat.id != config.ALLOWED_CHAT_ID:
        return
    try:
        await context.bot.send_message(chat.id, f"❌ Bir hata oldu: {str(context.error)[:200]}\nAyrıntı: /get_logs")
    except Exception:
        log.exception("Could not report the error to the user")


def main():
    if not config.TELEGRAM_BOT_TOKEN or not config.DEEPSEEK_API_KEY:
        raise SystemExit(".env içinde TELEGRAM_BOT_TOKEN ve DEEPSEEK_API_KEY olmalı.")
    cloud_store.restore()  # cloud: bring data/ back from MongoDB before anything reads it (no-op on this PC)

    global engine

    async def start_engine(app: Application):
        try:
            await app.bot.set_my_commands([BotCommand(c, d) for c, d in BOT_MENU])
        except Exception as e:
            log.warning("Could not set the Telegram command menu: %s", e)
        if config.ALLOWED_CHAT_ID:
            app.bot_data["engine_task"] = asyncio.create_task(engine.run())
        register_panel_actions(app.bot)

    async def stop_engine(app: Application):
        task = app.bot_data.get("engine_task")
        if task:
            task.cancel()
        try:
            await asyncio.to_thread(cloud_store.sync)
        except Exception as e:
            log.warning("Cloud state sync at shutdown failed: %s", e)

    request = HTTPXRequest(connection_pool_size=16, connect_timeout=20, read_timeout=30, write_timeout=30, pool_timeout=10)
    bot = RetryBot(token=config.TELEGRAM_BOT_TOKEN, request=request,
                   get_updates_request=HTTPXRequest(connect_timeout=20, read_timeout=40))
    app = Application.builder().bot(bot).post_init(start_engine).post_stop(stop_engine).build()
    engine = AlertEngine(on_trigger=lambda *a: on_alert_trigger(app.bot, *a),
                         on_notice=lambda *a: on_alert_notice(app.bot, *a))
    app.add_handler(TypeHandler(Update, mark_user_turn), group=-1)
    app.add_handler(CommandHandler(["start", "yardim"], start))
    app.add_handler(CommandHandler(["komutlar", "komut", "help"], komutlar))
    app.add_handler(CommandHandler("analiz", analiz))
    app.add_handler(CommandHandler("plan", plan))
    app.add_handler(CommandHandler("pozisyon", pozisyon))
    app.add_handler(CommandHandler("sil", sil))
    app.add_handler(CommandHandler("sifirla", sifirla))
    app.add_handler(CommandHandler("makro", makro))
    app.add_handler(CommandHandler("takvim", takvim))
    app.add_handler(CommandHandler("new_alert", new_alert))
    app.add_handler(CommandHandler("view_alerts", view_alerts))
    app.add_handler(CommandHandler("cancel_alert", cancel_alert))
    app.add_handler(CommandHandler("get_logs", get_logs))
    app.add_handler(CommandHandler("set_config", set_config))
    app.add_handler(CommandHandler("aldim", aldim))
    app.add_handler(CommandHandler("sat", sat))
    app.add_handler(CommandHandler("pozisyonlar", pozisyonlar))
    app.add_handler(CommandHandler("kayitsil", kayitsil))
    app.add_handler(CommandHandler("duzelt", duzelt))
    app.add_handler(CommandHandler("rapor", rapor))
    app.add_handler(CommandHandler("backtest", backtest_cmd))
    app.add_handler(CommandHandler("vadeli", vadeli))
    app.add_handler(CommandHandler("maliyet", maliyet))
    app.add_handler(CommandHandler("durum", durum))
    app.add_handler(CommandHandler("tara", tara_router))
    app.add_handler(CommandHandler("kriz", kriz))
    app.add_handler(CommandHandler("quant", quant_cmd))
    app.add_handler(CommandHandler("bist", bist_cmd))
    app.add_handler(CommandHandler("incele", incele))
    app.add_handler(CommandHandler("portfoy", portfoy))
    app.add_handler(CommandHandler("haber", haber))
    app.add_handler(CommandHandler("okul", okul))
    app.add_handler(CommandHandler("sessizlik", sessizlik))
    app.add_handler(CommandHandler("sessiz", sessiz))
    app.add_handler(CommandHandler(["ne", "neyapayim"], ne_yapayim))
    app.add_handler(CommandHandler("risk", risk_cmd))
    app.add_handler(CommandHandler("grafik", grafik))
    app.add_handler(CommandHandler("duygu", duygu))
    app.add_handler(CommandHandler("disiplin", disiplin))
    app.add_handler(CommandHandler("gunluk", gunluk))
    app.add_handler(CommandHandler("haftalik", haftalik))
    app.add_handler(CommandHandler("hesap", hesap))
    app.add_handler(CommandHandler("birikim", birikim))
    app.add_handler(CommandHandler("temettu", temettu))
    app.add_handler(CommandHandler("golge", golge))
    app.add_handler(CommandHandler("kiyas", kiyas))
    app.add_handler(CommandHandler("gunsonu", gunsonu))
    app.add_handler(CommandHandler("karne", karne))
    app.add_handler(CommandHandler("bakiye", bakiye))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler(["firsat", "simdi"], firsat))
    app.add_handler(CommandHandler("guc", guc))
    app.add_handler(CommandHandler("temel", temel))
    app.add_handler(CommandHandler("abd", abd))
    app.add_handler(CommandHandler("palarm", palarm))
    app.add_handler(CommandHandler("takip", takip))
    app.add_handler(CommandHandler("hedef", hedef))
    app.add_handler(CommandHandler("sanal", sanal))
    app.add_handler(CommandHandler("ders", ders))
    app.add_handler(CommandHandler("kap", kap))
    app.add_handler(CommandHandler("olaylar", olaylar))
    app.add_handler(CommandHandler("kontrol", kontrol))
    app.add_handler(CommandHandler("bagla", bagla))
    app.add_handler(CommandHandler("ekle", web_ekle))
    app.add_handler(CommandHandler("galarm", galarm))
    app.add_handler(CommandHandler("karsilastir", karsilastir))
    app.add_error_handler(on_error)
    app.add_handler(CallbackQueryHandler(quant_callback, pattern=r"^quant\|"))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_message))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^/portf[öo]y(@\w+)?(\s|$)"), portfoy_turkish))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, site_or_owner_text_message))

    if config.ALLOWED_CHAT_ID:
        now = time.time()
        first = config.CHECK_INTERVAL - now % config.CHECK_INTERVAL + config.CHECK_DELAY
        app.job_queue.run_repeating(watch_job, interval=config.CHECK_INTERVAL, first=first)
        app.job_queue.run_repeating(position_job, interval=config.CHECK_INTERVAL, first=first + 10)
        log.info("Watcher starts in %.0f s", first)
        app.job_queue.run_daily(brief_job, dtime(config.BRIEF_HOUR, config.BRIEF_MINUTE, tzinfo=macro.TR))
        app.job_queue.run_once(lambda ctx: schedule_events(ctx.application), when=5)
        schedule_quiet_summary(app)
        app.job_queue.run_repeating(held_digest_job, interval=60, first=30, name="bekleyen_bildirim")
        app.job_queue.run_repeating(signal_life_job, interval=300, first=90, name="sinyal_omru")
        # BIST: 1h bars close at :30 (+~16 min data delay) -> check every 15 min; daily scan after the final close.
        app.job_queue.run_repeating(bist_hourly_job, interval=15 * 60, first=first + 40)
        app.job_queue.run_daily(bist_daily_job, dtime(18, 35, tzinfo=macro.TR), name="bist_daily")
        # Exit/top analysis: crypto on each 4h close, BIST after the final daily close.
        four_h = 4 * 3600
        app.job_queue.run_repeating(exit_job, interval=four_h, first=four_h - time.time() % four_h + 60,
                                    data="KRIPTO", name="exit_crypto")
        app.job_queue.run_daily(exit_job, dtime(18, 40, tzinfo=macro.TR), data="BIST", name="exit_bist")
        # Splits/dividends before the session (and once at startup), accumulation reminders, weekly summary.
        app.job_queue.run_daily(corporate_job, dtime(9, 45, tzinfo=macro.TR), name="corporate")
        app.job_queue.run_once(corporate_job, when=60, name="corporate_start")
        app.job_queue.run_daily(dca_job, dtime(*config.DCA_REMIND_HOUR, tzinfo=macro.TR), name="birikim")
        app.job_queue.run_daily(weekly_job, dtime(20, 0, tzinfo=macro.TR), days=(0,), name="haftalik")  # 0 = Sunday
        app.job_queue.run_daily(eod_job, dtime(18, 45, tzinfo=macro.TR), name="bist_gunsonu")
        app.job_queue.run_once(universe_job, when=30, name="evren_ilk")
        # US: after the New York close (16:20 ET, DST handled by the time zone) and a Saturday ranking
        app.job_queue.run_daily(us_daily_job, dtime(16, 20, tzinfo=us.NY), name="abd_gunluk")
        app.job_queue.run_daily(us_weekly_job, dtime(10, 0, tzinfo=macro.TR), days=(6,), name="abd_guc")  # 6 = Saturday
        app.job_queue.run_daily(strength_job, dtime(19, 0, tzinfo=macro.TR), days=(5,), name="bist_guc")  # 5 = Friday
        app.job_queue.run_repeating(pf_alarm_job, interval=15 * 60, first=first + 50, name="portfoy_alarm")
        app.job_queue.run_daily(universe_job, dtime(9, 30, tzinfo=macro.TR), name="evren")
        app.job_queue.run_daily(after_sale_job, dtime(19, 0, tzinfo=macro.TR), name="satis_sonrasi")
        app.job_queue.run_repeating(risk_news_job, interval=30 * 60, first=120, name="risk_haber")
        app.job_queue.run_repeating(takip_job, interval=5 * 60, first=180, name="takip_sor")  # asks every 30 min (/takip aralik)
        app.job_queue.run_repeating(watch_rules_job, interval=30 * 60, first=600, name="takip_kural")
        app.job_queue.run_repeating(kap_job, interval=15 * 60, first=240, name="kap")
        app.job_queue.run_repeating(ind_alarm_job, interval=15 * 60, first=300, name="gosterge_alarm")
        app.job_queue.run_daily(calendar_job, dtime(8, 45, tzinfo=macro.TR), name="sirket_takvimi")
        app.job_queue.run_daily(calendar_job, dtime(20, 0, tzinfo=macro.TR), name="sirket_takvimi_aksam")
        app.job_queue.run_once(calendar_job, when=150, name="sirket_takvimi_ilk")
        app.job_queue.run_daily(allocation_job, dtime(19, 15, tzinfo=macro.TR), name="hedef_dagilim")
        app.job_queue.run_daily(lesson_job, dtime(20, 10, tzinfo=macro.TR), days=(0,), name="haftalik_ders")  # 0 = Sunday
        if web_sync.enabled():
            app.job_queue.run_repeating(extras_job, interval=15 * 60, first=90, name="panel_ekstra")
        if alerts_store.load_settings().get("plan_takip"):
            start_plan_follow(app)  # /plan follow-up survives a restart
        if web_sync.enabled():
            app.job_queue.run_repeating(web_push_job, interval=config.WEB_SYNC_INTERVAL, first=10)
            app.job_queue.run_repeating(web_command_job, interval=config.WEB_COMMAND_INTERVAL, first=20)
            log.info("Web panel sync enabled: %s", config.WEB_URL)
            app.job_queue.run_repeating(user_alarm_job, interval=60, first=40, name="kullanici_alarmlari")
        if cloud_store.enabled():
            app.job_queue.run_repeating(cloud_state_job, interval=60, first=60, name="bulut_durum")
            app.job_queue.run_daily(backup_job, dtime(3, 30, tzinfo=macro.TR), name="db_backup")
    else:
        log.warning("ALLOWED_CHAT_ID empty: send /start to the bot to get your chat id.")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
