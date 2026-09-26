"""Pick lists for the portfolio wizard: a wide BIST list and popular Binance coins.

The lists below are candidates. Once a day they are checked against the data sources (Yahoo for BIST,
Binance ticker list for crypto) and only names that actually return data are offered, so a renamed or
delisted ticker never shows up as a button. Anything not listed can still be typed.
"""
import asyncio
import json
import logging
import time

import httpx

import bist
import config
import market

log = logging.getLogger(__name__)

FILE = config.DATA_DIR / "universe.json"
TTL = 24 * 3600

BIST_CANDIDATES = """
ADEL AEFES AGESA AGHOL AGROT AHGAZ AKBNK AKCNS AKFGY AKFYE AKSA AKSEN AKSGY ALARK ALBRK ALFAS ALGYO ALKIM ALTNY
ANELE ANHYT ANSGR ARASE ARCLK ARDYZ ASELS ASTOR ASUZU ATAKP AVPGY AYDEM AYGAZ BAGFS BALSU BANVT BASGZ BERA BIENY
BIMAS BINHO BIOEN BJKAS BOBET BORLS BOSSA BRISA BRSAN BRYAT BSOKE BTCIM BUCIM CANTE CCOLA CEMTS CIMSA CLEBI
CVKMD CWENE DAPGM DESA DEVA DOAS DOCO DOHOL DSTKF ECILC ECZYT EFORC EGEEN EGGUB EKGYO ENERY ENJSA ENKAI ENSRI
ERBOS EREGL ESEN EUPWR EUREN FENER FROTO FZLGY GARAN GENIL GESAN GLRMK GLYHO GOLTS GOZDE GRSEL GRTHO GSDHO
GSRAY GUBRF GWIND HALKB HEKTS HLGYO HTTBT ICBCT IEYHO INDES INVEO IPEKE ISCTR ISDMR ISGYO ISMEN IZENR IZMDC
JANTS KARSN KATMR KAYSE KCAER KCHOL KLKIM KLSER KMPUR KONTR KONYA KORDS KOZAA KRDMD KTLEV KZBGY LIDER LMKDC
LOGO MAGEN MAVI MEDTR MGROS MIATK MPARK NETAS NTHOL NUHCM OBAMS ODAS ORGE OTKAR OYAKC PAPIL PASEU PATEK PENTA
PETKM PGSUS PNLSN PRKAB PRKME PSGYO QUAGR RALYH REEDR RYGYO SAHOL SARKY SASA SAYAS SDTTR SELEC SISE SKBNK
SMRTG SNGYO SOKM SUNTK SUWEN TABGD TATEN TAVHL TCELL THYAO TKFEN TKNSA TMSN TOASO TRALT TRENJ TRGYO TRMET
TSKB TSPOR TTKOM TTRAK TUKAS TUPRS TUREX TURSG ULKER ULUUN VAKBN VAKKO VESBE VESTL YATAS YEOTK YKBNK YYLGD
ZOREN ZRGYO
""".split()

CRYPTO_CANDIDATES = """
BTC ETH BNB SOL XRP DOGE ADA TRX TON AVAX LINK DOT BCH LTC NEAR UNI APT ARB OP SUI SEI TIA INJ AAVE MKR
ATOM ETC FIL ICP HBAR XLM VET ALGO RENDER FET TAO WLD PEPE SHIB FLOKI BONK WIF ORDI JUP PYTH ENA ONDO
HYPE STX IMX GRT SAND MANA AXS GALA CRV LDO PENDLE RUNE THETA EGLD KAS TRUMP JTO STRK ZK EIGEN
""".split()


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


async def refresh(force: bool = False) -> dict:
    """Validate the candidate lists (once a day). Keeps the previous result when a source is down."""
    cached = _load()
    if not force and time.time() - cached.get("zaman", 0) < TTL:
        return cached
    out = {"zaman": time.time(), "bist": cached.get("bist"), "kripto": cached.get("kripto")}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{market.BINANCE_BASES[0]}/api/v3/ticker/price", timeout=20)
            r.raise_for_status()
            listed = {x["symbol"] for x in r.json()}
            out["kripto"] = [c for c in dict.fromkeys(config.WATCHLIST + CRYPTO_CANDIDATES) if c + config.QUOTE in listed]
        except Exception as e:
            log.warning("Crypto universe check failed: %s", e)
        sem = asyncio.Semaphore(8)

        async def ok(t: str) -> str | None:
            async with sem:
                try:
                    await bist.last_price(client, t)
                    return t
                except Exception:
                    return None

        names = list(dict.fromkeys(bist.watchlist() + BIST_CANDIDATES))
        found = [t for t in await asyncio.gather(*(ok(t) for t in names)) if t]
        if len(found) >= len(names) // 2:  # a mostly failing check means Yahoo was down, not the tickers
            out["bist"] = found
    FILE.write_text(json.dumps(out), encoding="utf-8")
    return out


def bist_names() -> list[str]:
    names = _load().get("bist") or list(dict.fromkeys(bist.watchlist() + BIST_CANDIDATES))
    return sorted(set(names) | set(bist.watchlist()))


def crypto_names() -> list[str]:
    names = _load().get("kripto") or list(dict.fromkeys(config.WATCHLIST + CRYPTO_CANDIDATES))
    return list(dict.fromkeys(config.WATCHLIST + names))
