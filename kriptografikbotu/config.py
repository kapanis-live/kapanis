import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# Only this chat may use the bot. Empty = /start prints your chat id, everything else is refused.
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID") or 0)
# Macro data sources. Each is optional; a missing key disables only that source.
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
BLS_API_KEY = os.getenv("BLS_API_KEY", "")
CFTC_APP_TOKEN = os.getenv("CFTC_APP_TOKEN", "")
# TCMB EVDS (free key: evds3.tcmb.gov.tr -> Profil -> API Anahtarı). Only for inflation-adjusted returns.
EVDS_API_KEY = os.getenv("EVDS_API_KEY", "")
EVDS_CPI_SERIES = os.getenv("EVDS_CPI_SERIES", "TP.FG.J0")  # TÜFE general index

# Main analysis model (OpenAI-compatible API)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")  # DeepSeek-V4.1-Flash; "deepseek-v4-pro" for Pro
DEEPSEEK_MAX_TOKENS = 32000  # thinking mode: reasoning tokens count toward this limit

# Second analysis model: Kimi K3 through NVIDIA's OpenAI-compatible API (build.nvidia.com key).
# The two models take turns in 15-minute slots (see llm.pick_model); if one fails the other answers.
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
# Separate keys per model are optional; each falls back to NVIDIA_API_KEY.
KIMI_API_KEY = os.getenv("KIMI_API_KEY") or NVIDIA_API_KEY
GLM_API_KEY = os.getenv("GLM_API_KEY") or NVIDIA_API_KEY
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshotai/kimi-k3")
KIMI_MAX_TOKENS = int(os.getenv("KIMI_MAX_TOKENS") or 32000)
KIMI_TIMEOUT = 300           # seconds; hosted thinking models can be slow
KIMI_HISTORY_TURNS = 80      # Kimi has a 1M-token context: it gets far more conversation than DeepSeek
# Third analysis model: GLM 5.3 (Z.ai), also through NVIDIA with the same key.
GLM_MODEL = os.getenv("GLM_MODEL", "z-ai/glm-5.3")
GLM_MAX_TOKENS = int(os.getenv("GLM_MAX_TOKENS") or 32000)
GLM_HISTORY_TURNS = 40
# USD per 1M tokens for the NVIDIA-hosted models (0 = free developer credits). Set in .env if you pay.
KIMI_PRICES = {"hit": float(os.getenv("KIMI_PRICE_HIT") or 0), "miss": float(os.getenv("KIMI_PRICE_IN") or 0),
               "out": float(os.getenv("KIMI_PRICE_OUT") or 0)}
GLM_PRICES = {"hit": float(os.getenv("GLM_PRICE_HIT") or 0), "miss": float(os.getenv("GLM_PRICE_IN") or 0),
              "out": float(os.getenv("GLM_PRICE_OUT") or 0)}
AI_SLOT_MINUTES = 15

# --- US stocks (us.py, us_fund.py) ---
TIINGO_API_KEY = os.getenv("TIINGO_API_KEY", "")   # tiingo.com free key: prices; without it Yahoo is used
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "Kapanis kisisel bot kapanis-bot@example.com")  # SEC asks for a contact
US_FIRST_TRANCHE_PCT = 25     # share of the US budget (/abd butce) for a first tranche
US_MAX_RISK_PCT = 2.0         # planned stop loss as a share of the US budget
US_MIN_RR = 2.0               # medium/long term, gap risk around earnings
US_EARNINGS_BLOCK_DAYS = 5    # no new entry this many days before an earnings report (gap risk)
AI_ROTATION = ["kimi", "deepseek", "glm"]  # slot % 3: 11:15 Kimi, 11:30 DeepSeek, 11:45 GLM, 12:00 Kimi...

# Local pre-filter model (Ollama)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
QWEN_MODEL = "qwen3:30b-a3b"
QWEN_TIMEOUT = 180  # seconds; first call loads 18 GB into memory

WATCHLIST = ["BTC", "ETH", "SOL", "NEAR", "ONDO", "HYPE", "AAVE", "UNI",
             "BCH", "XRP", "LINK", "AVAX", "ARB"]
QUOTE = "USDT"

# Timeframes sent to the analysis model: big picture -> entry timing
TIMEFRAMES = ["1w", "1d", "4h", "1h", "15m"]
KLINE_LIMIT = 300  # enough for SMA(200)
RECENT_CANDLES = 6  # last closed 15m candles sent raw

# Watcher
CHECK_INTERVAL = 15 * 60
CHECK_DELAY = 20  # seconds after the 15m close, so Binance has the closed candle
PROXIMITY_ATR = 0.5  # "near a level" = within this many 15m ATRs
PROXIMITY_COOLDOWN = 2 * 3600  # don't re-check the same coin within this window
# Who decides if a near-level move is worth a DeepSeek call: "kod" (deterministic rule)
# or "qwen" (local model, same rule in QWEN_PROMPT). In tests qwen misjudged 1 of 4 cases.
PREFILTER = "kod"

# All runtime data lives in one folder so Docker can mount it as a volume.
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
DATA_DIR.mkdir(exist_ok=True)
if DATA_DIR == BASE_DIR / "data":  # never move project files into an overridden DATA_DIR
    for _name in ("history.json", "state.json", "macro_cache.json"):
        if (BASE_DIR / _name).exists() and not (DATA_DIR / _name).exists():
            (BASE_DIR / _name).replace(DATA_DIR / _name)  # one-time move from the old location

HISTORY_LIMIT = 15           # turns sent to DeepSeek (every token is paid)
HISTORY_STORE_TURNS = 100    # turns kept on disk (Kimi reads up to KIMI_HISTORY_TURNS of them)
HISTORY_FILE = DATA_DIR / "history.json"
STATE_FILE = DATA_DIR / "state.json"
MACRO_CACHE_FILE = DATA_DIR / "macro_cache.json"
ALERTS_FILE = DATA_DIR / "alerts.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
POSITIONS_FILE = DATA_DIR / "positions.json"
DECISIONS_FILE = DATA_DIR / "decisions.json"
# First-tranche sizing (positions.tranche_usd). The LLM never picks the amount.
DEFAULT_TRANCHE_USD = 25
REDUCED_TRANCHE_USD = 15        # RİSK-OFF, unverifiable macro, or no volume confirmation
TOTAL_FIRST_TRANCHE_USD = 25    # correlated coins count as one trade
MIN_TRANCHE_USD = 10            # practical floor; the pair's exchange minimum applies if higher
CRYPTO_BUDGET_USD = 100         # short-term crypto trading budget (daily loss limit is a share of it)

# --- Discipline shield (discipline.py) ---
LOSS_STREAK = 2                 # this many losing trades in a row...
COOLDOWN_HOURS = 24             # ...silence new AL signals for this long
DAILY_LOSS_PCT = 3.0            # realized loss today above this share of the market's budget = done for today

# --- Crypto sentiment (sentiment.py): alternative.me Fear & Greed, CoinGecko global ---
GREED_EXTREME = 80              # at or above: first tranche reduced like a missing volume confirmation
FEAR_EXTREME = 20               # at or below: warning only (breakouts fail more often, bottoms form here)

# --- Concentration (risk.py) ---
MAX_ASSET_PCT = 40              # one asset above this share of the whole portfolio = warning
MAX_SECTOR_PCT = 50
MAX_COIN_PCT = 30               # one coin above this share of the open crypto book = warning on every new signal
HIGH_CORR = 0.8                 # 30-day daily-return correlation treated as "the same position"

# --- Accumulation plans (dca.py) ---
DCA_DIP_PCT = 10                # price this far below the plan's average cost -> extra tranche hint
DCA_DRAWDOWN_PCT = 15           # or this far below the 30-day high
DCA_REMIND_HOUR = (10, 15)      # TR time; BIST reminders only on trading days
# --- Borsa İstanbul (bist.py) ---
BIST_WATCHLIST = ["AEFES", "AKBNK", "ASELS", "ASTOR", "BIMAS", "DSTKF", "EKGYO", "ENKAI", "EREGL", "FROTO",
                  "GARAN", "GUBRF", "ISCTR", "KCHOL", "KRDMD", "MGROS", "PETKM", "PGSUS", "SAHOL", "SASA",
                  "SISE", "TAVHL", "TCELL", "THYAO", "TOASO", "TRALT", "TTKOM", "TUPRS", "VAKBN", "YKBNK"]  # BIST 30, Q3 2026
BIST_FIRST_TRANCHE_PCT = 25     # share of the user-entered TL budget; also caps open first tranches
BIST_REDUCED_TRANCHE_PCT = 15   # cautious index gate or missing volume confirmation
# BIST is traded medium/long-term (weeks to months), never short-term: the weekly trend must point up,
# a DAILY close confirms the entry, targets are at least BIST_MIN_TARGET_PCT away, exits use weekly closes.
BIST_CONFIRM_TF = "1d"          # "1d" = medium/long-term; "1h" = the old short-term mode
BIST_MIN_RR = 2.0               # net of costs; also covers overnight/weekend gaps
BIST_MIN_TARGET_PCT = 8.0       # a medium-term target is at least this far above the entry
BIST_MAX_RISK_PCT = 2.0         # planned stop loss as a share of the user-entered TL budget
BIST_MAX_DAILY_CHANGE_PCT = 8   # don't chase a stock this close to its +10% ceiling
BIST_FX_STRESS_PCT = 2.0        # USD/TRY up more than this in 5 days = lira under pressure
BIST_FEE_PCT = 0.15             # commission + BSMV per side
BIST_SLIPPAGE_PCT = 0.05

# Net backtest costs per side (Binance spot taker fee, conservative slippage), in percent
BACKTEST_FEE_PCT = 0.10
BACKTEST_SLIPPAGE_PCT = 0.05
LOG_FILE = DATA_DIR / "bot.log"

# Alert engine
BINANCE_WS_URLS = ["wss://stream.binance.com:9443/stream?streams=",
                   "wss://data-stream.binance.vision/stream?streams="]
ALERT_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
CHART_CANDLES = 120
ALERT_ANALYSIS_CANDLES = 30

# Daily macro brief, Turkey time
# 08:30 TR = 05:30 UTC, before DeepSeek's weekday peak window (06:00-10:00 UTC)
BRIEF_HOUR, BRIEF_MINUTE = 8, 30
# Warn this many minutes before a high-impact release
EVENT_WARN_MINUTES = 60

# DeepSeek prices, USD per 1M tokens (api-docs.deepseek.com/quick_start/pricing, checked 2026-09-26).
# Peak = Mon-Fri 01:00-04:00 and 06:00-10:00 UTC; everything else is off-peak (half price).
# Chinese public holidays are also off-peak but are not modeled here, so those days read high.
_DEEPSEEK_PRICE_TABLE = {
    "deepseek-flash": {"peak": {"hit": 0.006, "miss": 0.30, "out": 1.20},
                       "offpeak": {"hit": 0.003, "miss": 0.15, "out": 0.60}},
    "deepseek-v4-pro": {"peak": {"hit": 0.044, "miss": 1.32, "out": 3.96},
                        "offpeak": {"hit": 0.022, "miss": 0.66, "out": 1.98}},
}
DEEPSEEK_PRICES = _DEEPSEEK_PRICE_TABLE.get(DEEPSEEK_MODEL, _DEEPSEEK_PRICE_TABLE["deepseek-v4-pro"])
USD_TRY = float(os.getenv("USD_TRY") or 48.9)  # update in .env when the rate moves
USAGE_FILE = DATA_DIR / "usage.jsonl"

# Web panel (Kapanış). Empty = sync disabled.
WEB_URL = os.getenv("WEB_URL", "").rstrip("/")
# Address people open in a browser (links in Telegram messages); defaults to WEB_URL
PUBLIC_URL = (os.getenv("PUBLIC_URL") or WEB_URL or "https://kapanis.live").rstrip("/")
BOT_API_KEY = os.getenv("BOT_API_KEY", "")
WEB_SYNC_INTERVAL = 60      # seconds between full data pushes
WEB_COMMAND_INTERVAL = 15   # seconds between command-queue polls
