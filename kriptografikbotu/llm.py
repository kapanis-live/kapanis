"""Analysis models: Kimi K3, DeepSeek (V4.1 Flash by default) and GLM 5.3 (Kimi and GLM via NVIDIA), taking turns
every 15 minutes; if one fails the next one in the rotation answers.
Local qwen3 (Ollama) is the cheap pre-filter."""
import json
import logging
import pathlib
import re
from datetime import datetime

import httpx
from openai import AsyncOpenAI

import config
import conversation_store as store
import costs
import macro
import news
import positions
from system_prompt import QWEN_PROMPT, SYSTEM_PROMPT

log = logging.getLogger(__name__)

_clients: dict[str, AsyncOpenAI] = {}
MODEL_NAMES = {"deepseek": "DeepSeek V4.1 Flash" if config.DEEPSEEK_MODEL == "deepseek-flash" else "DeepSeek V4 Pro",
               "kimi": "Kimi K3", "glm": "GLM 5.3"}
NVIDIA_MODELS = ("kimi", "glm")

# Kimi gets the same rules plus the project handbook: its 1M context makes this cheap, and the constant
# prefix (system prompt + handbook) is what a prompt cache can reuse between calls.
_HANDBOOK = pathlib.Path(__file__).with_name("PROJE.md")
KIMI_SYSTEM = SYSTEM_PROMPT + (
    "\n\n## Botun mimarisi ve kuralları (PROJE.md — sistem el kitabı, sadece referans)\n"
    "Bu bölüm kodun nasıl çalıştığını anlatır: kapılar, destek/direnç bölgeleri, BIST orta/uzun vade kuralları, "
    "disiplin kalkanı, portföy. Kararlarını yukarıdaki kurallara göre ver; buradaki sayılar ayar değerleridir.\n\n"
    + _HANDBOOK.read_text(encoding="utf-8") if _HANDBOOK.exists() else "")


def _client(model: str) -> AsyncOpenAI:
    if model not in _clients:
        if model in NVIDIA_MODELS:
            _clients[model] = AsyncOpenAI(api_key=config.KIMI_API_KEY if model == "kimi" else config.GLM_API_KEY,
                                          base_url=config.NVIDIA_BASE_URL, timeout=config.KIMI_TIMEOUT)
        else:
            _clients[model] = AsyncOpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    return _clients[model]


def available() -> list[str]:
    return [m for m, key in (("kimi", config.KIMI_API_KEY), ("deepseek", config.DEEPSEEK_API_KEY),
                             ("glm", config.GLM_API_KEY)) if key]


def mode() -> str:
    """"sira" (take turns every 15 minutes), "deepseek", "kimi" or "glm" — set with /model."""
    import alerts_store
    return alerts_store.load_settings().get("ai_mod", "sira")


def slot_model(when: datetime | None = None) -> str:
    """Which model owns this 15-minute slot: 11:15 Kimi, 11:30 DeepSeek, 11:45 GLM, 12:00 Kimi..."""
    when = when or datetime.now(macro.TR)
    slot = (when.hour * 60 + when.minute) // config.AI_SLOT_MINUTES
    return config.AI_ROTATION[slot % len(config.AI_ROTATION)]


def pick_model(when: datetime | None = None) -> list[str]:
    """Models to try in order: the chosen one first, the other as fallback. Only those with a key."""
    have = available()
    m = mode()
    first = m if m in MODEL_NAMES else slot_model(when)
    rot = config.AI_ROTATION
    start = rot.index(first)
    order = rot[start:] + rot[:start]  # fallback follows the rotation
    return [x for x in order if x in have] or ["deepseek"]


def _wide_context() -> str:
    """Extra context only Kimi receives (1M window): recent decisions with outcomes and closed trades."""
    decisions = [{k: d.get(k) for k in ("id", "zaman", "pair", "karar", "kapanis", "iptal", "hedef", "aksiyon")}
                 | {"sonuc": (d.get("sonuc") or {}).get("sonuc"), "kalan_kurallar": (d.get("kapi") or {}).get("kalan")}
                 for d in positions.load_decisions()[-40:]]
    closed = [{k: p.get(k) for k in ("id", "pair", "piyasa", "giris", "kapanis_fiyat", "adet", "acilis",
                                     "kapanis_zamani", "neden", "kaynak")}
              for p in positions.load() if p["durum"] == "kapali"][-30:]
    return (f"\n\n[GENİŞ BAĞLAM — son kararlar ve kapanan işlemler]\n"
            f"{json.dumps({'kararlar': decisions, 'kapanan_islemler': closed}, ensure_ascii=False)}")


def _visible(text: str) -> str:
    """Some hosted thinking models put their reasoning inside <think> tags in the content."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


STATE_RE = re.compile(r"<STATE>\s*(.*?)\s*</STATE>", re.DOTALL)


def split_state(text: str) -> tuple[str, dict | None]:
    """Strip the <STATE> block from the reply and parse it."""
    match = STATE_RE.search(text)
    if not match:
        return text.strip(), None
    visible = (text[:match.start()] + text[match.end():]).strip()
    if not match.group(1).strip():  # an empty <STATE></STATE> means "no change"
        return visible, None
    try:
        # raw_decode reads the first complete object and ignores trailing junk (e.g. an extra "}").
        return visible, json.JSONDecoder().raw_decode(match.group(1))[0]
    except json.JSONDecodeError:
        log.warning("Unparseable STATE block: %s", match.group(1)[:300])
        return visible, None


async def analyze(user_text: str, market_data: dict, *, allow_state_update: bool = True) -> tuple[str, list[str], list[str]]:
    """Send one turn to DeepSeek with history, current state and fresh market data.

    Returns the visible reply, state-merge warnings and coins whose plan this reply set
    (tetik + iptal present). History stores only
    the user's text (not the bulky market data) to keep later requests cheap.
    """
    state = store.load_state()
    state["acik_pozisyonlar"] = [
        {k: p[k] for k in ("id", "pair", "giris", "miktar_usd", "stop", "hedef", "acilis")}
        for p in positions.open_positions()]
    try:
        macro_data = await macro.summary()
    except Exception as e:
        log.warning("Macro summary failed: %s", e)
        macro_data = {"hata": str(e)}
    coins = [k for k in market_data if k.isupper() and k.isalpha()]
    if isinstance(market_data.get("alarm"), dict):
        coins.append(market_data["alarm"]["pair"].split("/")[0])
    try:
        headlines = news.for_model(await news.get_news(), coins)
    except Exception as e:
        log.warning("News failed: %s", e)
        headlines = {"hata": str(e)}
    content = (f"{user_text}\n\n[GÜNCEL DURUM]\n{json.dumps(state, ensure_ascii=False)}"
               f"\n\n[MAKRO]\n{json.dumps(macro_data, ensure_ascii=False)}"
               f"\n\n[HABERLER]\n{json.dumps(headlines, ensure_ascii=False)}"
               f"\n\n[PİYASA VERİSİ]\n{json.dumps(market_data, ensure_ascii=False)}")
    history = store.load_history()
    errors, used, resp = [], None, None
    for model in pick_model():
        if model in NVIDIA_MODELS:  # large context: handbook + long history + recent decisions/trades
            turns = config.KIMI_HISTORY_TURNS if model == "kimi" else config.GLM_HISTORY_TURNS
            messages = [{"role": "system", "content": KIMI_SYSTEM},
                        *history[-turns * 2:],
                        {"role": "user", "content": content + _wide_context()}]
            name = config.KIMI_MODEL if model == "kimi" else config.GLM_MODEL
            max_tokens = config.KIMI_MAX_TOKENS if model == "kimi" else config.GLM_MAX_TOKENS
        else:
            messages = [{"role": "system", "content": SYSTEM_PROMPT},
                        *history[-config.HISTORY_LIMIT * 2:],
                        {"role": "user", "content": content}]
            name, max_tokens = config.DEEPSEEK_MODEL, config.DEEPSEEK_MAX_TOKENS
        try:
            resp = await _client(model).chat.completions.create(model=name, messages=messages, max_tokens=max_tokens)
            if not _visible(resp.choices[0].message.content):
                raise ValueError("boş cevap")
            used = model
            break
        except Exception as e:
            log.warning("%s failed, trying the other model: %s", MODEL_NAMES[model], e)
            errors.append(f"{MODEL_NAMES[model]}: {str(e)[:120]}")
    if used is None:
        raise RuntimeError("İki model de cevap vermedi — " + " | ".join(errors))
    usage = resp.usage
    if usage:
        details = getattr(usage, "prompt_tokens_details", None)
        hit = getattr(usage, "prompt_cache_hit_tokens", None)
        if hit is None and details is not None:
            hit = getattr(details, "cached_tokens", None)
        miss = getattr(usage, "prompt_cache_miss_tokens", None)
        if miss is None and hit is not None:
            miss = usage.prompt_tokens - hit
        if hit is None or miss is None:  # no cache breakdown: bill everything as a miss
            hit, miss = 0, usage.prompt_tokens
        log.info("%s tokens: prompt %s (cache hit %s, miss %s), completion %s",
                 MODEL_NAMES[used], usage.prompt_tokens, hit, miss, usage.completion_tokens)
        costs.record(hit, miss, usage.completion_tokens, user_text, model=used)
    reply, update = split_state(_visible(resp.choices[0].message.content))
    warnings = store.apply_update(update) if update and allow_state_update else []
    store.append_history(user_text, reply)
    plans = ((update or {}).get("planlar") or {}) if allow_state_update else {}
    plan_coins = [c.upper() for c, p in plans.items()
                  if isinstance(p, dict) and p.get("tetik") is not None and p.get("iptal") is not None]
    tag = f"🧠 {MODEL_NAMES[used]}" + (f" (yedek: {', '.join(e.split(':')[0] for e in errors)} hata verdi)" if errors else "")
    return f"{reply}\n\n{tag}", warnings, plan_coins


async def qwen_should_alert(coin: str, facts: dict) -> tuple[bool, str] | None:
    """Ask local qwen whether a near-level situation is worth escalating. None on failure."""
    payload = {
        "model": config.QWEN_MODEL,
        "messages": [
            {"role": "system", "content": QWEN_PROMPT},
            {"role": "user", "content": json.dumps({"coin": coin, **facts}, ensure_ascii=False)},
        ],
        "format": {"type": "object",
                   "properties": {"bildir": {"type": "boolean"}, "neden": {"type": "string"}},
                   "required": ["bildir", "neden"]},
        "think": False,
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=config.QWEN_TIMEOUT) as client:
            r = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            answer = json.loads(r.json()["message"]["content"])
        return bool(answer.get("bildir")), str(answer.get("neden", ""))
    except Exception as e:
        log.warning("qwen pre-filter failed for %s: %s", coin, e)
        return None


# --- council: every model votes on the same signal -------------------------------------------------

VOTE_RULE = ("\n\n[KONSEY OYU] Bu bir oylama. Yukarıdaki kurallara ve verilere göre SADECE şu JSON'u yaz, başka hiçbir şey "
             "yazma, <STATE> bloğu yazma:\n{\"karar\": \"AL\" | \"BEKLE\" | \"PAS\", \"neden\": \"en fazla 20 kelime Türkçe\"}")


def _json_obj(text: str) -> dict | None:
    m = re.search(r"\{.*\}", _visible(text), re.DOTALL)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(m.group(0))[0]
    except json.JSONDecodeError:
        return None


async def vote(model: str, question: str, data: dict) -> dict | None:
    """One model's vote (karar + neden) on a signal, or None if it failed."""
    nvidia = model in NVIDIA_MODELS
    name = {"kimi": config.KIMI_MODEL, "glm": config.GLM_MODEL}.get(model, config.DEEPSEEK_MODEL)
    messages = [{"role": "system", "content": KIMI_SYSTEM if nvidia else SYSTEM_PROMPT},
                {"role": "user", "content": f"{question}\n\n[PİYASA VERİSİ]\n{json.dumps(data, ensure_ascii=False, default=str)}"
                                            + VOTE_RULE}]
    try:
        resp = await _client(model).chat.completions.create(model=name, messages=messages, max_tokens=8000)
    except Exception as e:
        log.warning("Council vote %s failed: %s", MODEL_NAMES[model], e)
        return None
    if resp.usage:
        costs.record(0, resp.usage.prompt_tokens, resp.usage.completion_tokens, "konsey " + question[:30], model=model)
    obj = _json_obj(resp.choices[0].message.content or "")
    if not obj or str(obj.get("karar", "")).upper() not in ("AL", "BEKLE", "PAS"):
        return None
    return {"karar": str(obj["karar"]).upper(), "neden": str(obj.get("neden", ""))[:160]}


async def council(question: str, data: dict) -> dict[str, dict]:
    """All models with a key vote in parallel. {model: {karar, neden}} for those that answered."""
    import asyncio
    models = available()
    votes = await asyncio.gather(*(vote(m, question, data) for m in models))
    return {m: v for m, v in zip(models, votes) if v}


def model_of(reply: str) -> str | None:
    """Which model wrote a reply, from the 🧠 tag at its end."""
    m = re.search(r"🧠 ([^\n(]+)", reply or "")
    if not m:
        return None
    name = m.group(1).strip()
    if name.startswith("DeepSeek"):  # V4 Pro and V4.1 Flash both count as the DeepSeek slot
        return "deepseek"
    return next((k for k, n in MODEL_NAMES.items() if n == name), None)


# --- screenshots: holdings from a brokerage/exchange screen (Kimi K3 reads images) ----------------------

VISION_PROMPT = ("Bu bir aracı kurum ya da borsa uygulaması ekran görüntüsü. İçindeki portföy/varlık satırlarını çıkar. "
                 "SADECE JSON yaz: {\"varliklar\": [{\"kod\": \"THYAO\", \"adet\": 25, \"maliyet\": 281.40, "
                 "\"piyasa\": \"BIST\" | \"KRIPTO\" | \"bilinmiyor\"}], \"not\": \"kısa not\"}. "
                 "kod: hisse kodu ya da coin sembolü (USDT ekleme). adet: sayı. maliyet: birim başı ortalama alış fiyatı; "
                 "ekranda yoksa null. Türkçe sayı biçimini (281,40 / 1.250) doğru çevir. Tahmin etme; okuyamadığın satırı yazma. "
                 "Portföy yoksa varliklar boş liste.")


async def read_holdings(image: bytes, mime: str = "image/jpeg") -> dict:
    """Holdings from a screenshot via Kimi K3. Raises if no vision model is available or the call fails."""
    import base64
    if not config.KIMI_API_KEY:
        raise RuntimeError("Görsel okuma için Kimi K3 anahtarı (KIMI_API_KEY) gerekli")
    import asyncio
    b64 = base64.b64encode(image).decode()
    content = [{"type": "text", "text": VISION_PROMPT},
               {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
    last_error = "cevap yok"
    # The hosted model sometimes returns an empty answer for the same image; a retry usually works.
    for attempt in range(4):
        try:
            resp = await _client("kimi").chat.completions.create(
                model=config.KIMI_MODEL, max_tokens=4000, temperature=0.6, messages=[{"role": "user", "content": content}])
        except Exception as e:
            last_error = str(e)[:120]
            await asyncio.sleep(6 if "429" in last_error else 2)  # 429 = NVIDIA rate limit: wait a little
            continue
        if resp.usage:
            costs.record(0, resp.usage.prompt_tokens, resp.usage.completion_tokens, "ekran görüntüsü", model="kimi")
        obj = _json_obj(resp.choices[0].message.content or "")
        if obj is not None:
            return obj
        last_error = "boş/okunamayan cevap"
        await asyncio.sleep(1)
    raise ValueError(f"Kimi 4 denemede okunabilir liste döndürmedi ({last_error})")


# --- natural-language portfolio entry: "astordan 4 tane var 260 tl iken almıştım" -------------------------

HOLDINGS_PROMPT = """Kullanıcının Türkçe mesajındaki portföy varlıklarını çıkar. SADECE JSON yaz:
{"varliklar": [{"kod": "ASTOR", "adet": 4, "maliyet": 260, "tutar": null, "piyasa": "BIST"}], "not": ""}
Kurallar:
- kod: BIST hisse kodu, coin sembolü ya da GRAM_ALTIN / USD / EUR. Şirket adı yazılmışsa BIST kodunu bul
  (ör. Europower → EUPWR, Astor → ASTOR, Türk Hava Yolları → THYAO, Aselsan → ASELS, Ford Otosan → FROTO).
  Türkçe ekleri at: "astordan" → ASTOR, "thy'den" → THYAO, "hype'a" → HYPE.
- piyasa: "BIST", "KRIPTO" ya da "ALTIN_DOVIZ".
- adet: miktar (tane/adet/lot/gram). maliyet: birim başı alış fiyatı ("260 tl iken almıştım", "260'tan").
- Sadece toplam tutar verilmişse ("1000 TL'lik aldım") adet null, tutar o sayı.
- Bilmediğin/emin olmadığın satırı yazma, uydurma. Hiç varlık yoksa boş liste.
Geçerli BIST kodları (seçerken buna uy): {kodlar}"""


async def parse_holdings_text(text: str, bist_codes: list[str]) -> dict:
    """Holdings from free Turkish text. Cheap/fast model first (DeepSeek Flash), NVIDIA models as fallback."""
    system = HOLDINGS_PROMPT.replace("{kodlar}", " ".join(bist_codes))
    order = [m for m in ("deepseek", "kimi", "glm") if m in available()]
    last = "model yok"
    for model in order:
        name = {"kimi": config.KIMI_MODEL, "glm": config.GLM_MODEL}.get(model, config.DEEPSEEK_MODEL)
        try:
            resp = await _client(model).chat.completions.create(
                model=name, max_tokens=3000,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
        except Exception as e:
            last = f"{MODEL_NAMES[model]}: {str(e)[:80]}"
            continue
        if resp.usage:
            costs.record(0, resp.usage.prompt_tokens, resp.usage.completion_tokens, "portföy yazısı", model=model)
        obj = _json_obj(resp.choices[0].message.content or "")
        if obj is not None:
            return obj
        last = f"{MODEL_NAMES[model]}: okunamayan cevap"
    raise RuntimeError(f"Mesaj ayrıştırılamadı ({last})")
