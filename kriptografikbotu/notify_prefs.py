"""Which markets may send PROACTIVE messages to a chat. One switch per market, independent of each other.

Off means: nothing the bot starts by itself for that market reaches the chat (alarms, signals, level digests, exit
warnings, scheduled reports). It does not switch the market off: every command the user types is answered as before,
saved alarms and plans stay saved, and the checks keep running. A suppressed message is dropped, not queued: turning
a market back on delivers only what fires from then on.

One gate for every sender: main.RetryBot asks blocked() before each send_message / send_photo. A sender says which
market a message belongs to in one of two ways:
  with notify_prefs.scope(KRIPTO): ...          everything sent inside belongs to that market
  notify_prefs.tag(text, KRIPTO)                one message, for producers that return a list of mixed texts
A message with no market (macro brief, portfolio totals, system notices) is never suppressed here; a message that
mixes markets (morning brief, weekly summary, company calendar, watch-list rules) is still sent, but its producer
leaves out the part of a market that is off: it asks market_filter(chat_id) / model_scope(chat_id).

Stored per chat in settings.json under "bildirim_tercihleri"; in the cloud that file is kept in MongoDB by
cloud_store, so the choice survives restarts and deploys.
"""
import contextlib
import contextvars
import logging

import alerts_store
import config
import lang

log = logging.getLogger(__name__)

KRIPTO, BIST, ABD = "KRIPTO", "BIST", "ABD"
MARKETS = (KRIPTO, BIST, ABD)
DEFAULTS = {KRIPTO: False, BIST: True, ABD: True}      # the owner's chat (the owner asked for crypto off)
OTHERS = {KRIPTO: True, BIST: True, ABD: True}          # a site user's linked chat: their own alarms, all on
LABELS = {KRIPTO: "🪙 Kripto", BIST: "🇹🇷 BIST", ABD: "🇺🇸 ABD"}
KEY = "bildirim_tercihleri"
ON_WORDS, OFF_WORDS = {"ac", "aç", "on", "acik", "açık"}, {"kapat", "kapa", "off", "kapali", "kapalı"}
SUPPRESSED_BY_PREFERENCE = "SUPPRESSED_BY_PREFERENCE"

_market: contextvars.ContextVar[str | None] = contextvars.ContextVar("notify_market", default=None)
suppressed_log: list[dict] = []     # the last suppressed messages (audit, in memory)


class Tagged(str):
    """A message text that knows its market."""
    piyasa: str | None = None


def tag(text: str, market: str | None) -> str:
    t = Tagged(text)
    t.piyasa = normalize(market)
    return t


def normalize(market: str | None) -> str | None:
    m = str(market or "").upper()
    return {"CRYPTO": KRIPTO, "US": ABD}.get(m, m) if m in MARKETS or m in ("CRYPTO", "US") else None


@contextlib.contextmanager
def scope(market: str | None):
    token = _market.set(normalize(market))
    try:
        yield
    finally:
        _market.reset(token)


def enter(market: str | None):
    """Mark every later message of the CURRENT task as this market's (a job that walks items of several markets)."""
    _market.set(normalize(market))


def scoped(market: str):
    """Decorator for a scheduled job whose every message belongs to one market."""
    def wrap(job):
        async def run(*args, **kwargs):
            with scope(market):
                return await job(*args, **kwargs)
        run.__name__ = getattr(job, "__name__", "job")
        return run
    return wrap


def defaults(chat_id) -> dict:
    return DEFAULTS if str(chat_id) == str(config.ALLOWED_CHAT_ID) else OTHERS


def prefs(chat_id) -> dict:
    saved = (alerts_store.load_settings().get(KEY) or {}).get(str(chat_id)) or {}
    base = defaults(chat_id)
    return {m: bool(saved.get(m, base[m])) for m in MARKETS}


def notifications_enabled(chat_id, market: str | None) -> bool:
    m = normalize(market)
    return True if m is None else prefs(chat_id)[m]


def market_filter(chat_id, user_turn: bool = False):
    """market -> bool for the producer of a mixed message: False = leave that market's lines out.

    A report the user asked for by command (user_turn) shows every market, like any other command."""
    p = prefs(chat_id)
    return lambda market: user_turn or p.get(normalize(market), True)


MODEL_NAMES = {KRIPTO: "kripto (BTC ve coinler)", BIST: "BIST ve Türkiye hisseleri", ABD: "ABD hisseleri"}


def model_scope(chat_id, user_turn: bool = False) -> str:
    """A line appended to a model request for a mixed message: which markets the answer must leave out ("" = none)."""
    is_open = market_filter(chat_id, user_turn)
    off = [MODEL_NAMES[m] for m in MARKETS if not is_open(m)]
    return ("\n\n[KAPSAM] Bu sohbette şu piyasaların bildirimi kapalı: " + "; ".join(off)
            + ". Bu piyasalar hakkında hiçbir şey yazma (seviye, yorum, plan, haber yok); yalnız açık piyasaları anlat.") if off else ""


def set_enabled(chat_id, market: str, on: bool) -> dict:
    m = normalize(market)
    if m is None:
        raise ValueError(f"bilinmeyen piyasa: {market}")
    s = alerts_store.load_settings()
    table = s.setdefault(KEY, {})
    row = {**defaults(chat_id), **(table.get(str(chat_id)) or {})}
    row[m] = bool(on)
    row["guncelleme"] = alerts_store.now_tr().isoformat(timespec="seconds")
    table[str(chat_id)] = row
    alerts_store.save_settings(s)
    return prefs(chat_id)


def blocked(chat_id, text=None, user_turn: bool = False) -> bool:
    """True when this send is a proactive message of a market the chat switched off. Called by the send gate."""
    if user_turn:
        return False                      # the answer to something the user just typed or pressed
    market = _market.get() or getattr(text, "piyasa", None)
    if market is None or notifications_enabled(chat_id, market):
        return False
    suppressed_log.append({"olay": "notification_suppressed", "market": market, "reason": "user_preference", "chat_id": chat_id,
                           "zaman": alerts_store.now_tr().isoformat(timespec="seconds"), "ozet": str(text or "")[:60]})
    del suppressed_log[:-200]
    log.info("notification_suppressed market=%s reason=user_preference chat=%s", market, chat_id)
    return True


def text(chat_id) -> str:
    p = prefs(chat_id)
    if lang.get(chat_id) == "en":
        names = {KRIPTO: "🪙 Crypto", BIST: "🇹🇷 BIST", ABD: "🇺🇸 US"}
        return ("🔔 Notification settings\n\n" + "\n".join(f"{names[m]}: {'ON' if p[m] else 'OFF'}" for m in MARKETS)
                + "\n\nA market that is off sends no automatic messages; commands you type are still answered and saved alerts are kept."
                  "\nChange: /kripto ac · /kripto kapat · /bist ac · /bist kapat · /abd ac · /abd kapat")
    return ("🔔 Bildirim tercihleri\n\n" + "\n".join(f"{LABELS[m]}: {'AÇIK' if p[m] else 'KAPALI'}" for m in MARKETS)
            + "\n\nKapalı piyasadan otomatik mesaj gelmez; yazdığın komutlar yine cevaplanır, kayıtlı alarmlar silinmez."
              "\nDeğiştir: /kripto ac · /kripto kapat · /bist ac · /bist kapat · /abd ac · /abd kapat")


def command(chat_id, market: str, args) -> str | None:
    """The reply to "/<market> ac|kapat", or None when the arguments are not a preference command."""
    word = str(args[0]).casefold() if args and len(args) == 1 else ""
    if word not in ON_WORDS | OFF_WORDS:
        return None
    set_enabled(chat_id, market, word in ON_WORDS)
    return text(chat_id)
