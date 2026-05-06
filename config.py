# ============================================================
# config.py — Edit bagian ini sesuai kebutuhan kamu
# ============================================================
import os
from dotenv import load_dotenv

load_dotenv()

# ── Kredensial (dari file .env) ───────────────────────────────
PRIVATE_KEY    = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "").lower()

# ── Network ───────────────────────────────────────────────────
TESTNET_CHAIN_ID = 138565
BASE_URL         = "https://testnet-gw.sodex.dev/api/v1/spot"

# ── Target Asset ──────────────────────────────────────────────
# Nama base coin sesuai API SoDEX (field "baseCoin")
TARGET_ASSETS = [
    "vBTC", "vETH", "vSOL", "vBNB", "vAVAX",
    "vDOGE", "vLINK", "vUNI", "vADA", "vXRP",
    "vLTC", "vAAVE",
]

# Quote coin sesuai API SoDEX (field "quoteCoin")
QUOTE_ASSET = "vUSDC"

# Kalau auto-detect kurang dari ini, fallback ke semua vUSDC pairs
MIN_PAIRS_REQUIRED = 5

# ── Mode Bot ──────────────────────────────────────────────────
# "limit"  → Place & cancel limit order (GTX post-only), aman
# "market" → Buy & sell market order, volume cepat, saldo berkurang
# "hybrid" → Campur keduanya (rekomendasi)
BOT_MODE = "hybrid"

# Khusus hybrid: seberapa sering pakai market order
HYBRID_MARKET_EVERY = 5

# ── Limit Order Settings ──────────────────────────────────────
PRICE_OFFSET_TICKS = 2   # Tick di luar spread
TIME_IN_FORCE      = 3   # 1=GTC, 2=IOC, 3=GTX (post-only)

# ── Market Order Settings ─────────────────────────────────────
MARKET_ORDER_USDC     = "10"   # USDC per siklus market order
MARKET_SLIPPAGE_RATIO = 0.02   # 2% slippage tolerance

# ── Timing ────────────────────────────────────────────────────
ORDER_HOLD_MIN       = 8
ORDER_HOLD_MAX       = 20
CYCLE_DELAY_MIN      = 5
CYCLE_DELAY_MAX      = 30
SYMBOL_REFRESH_EVERY = 50
STATUS_PRINT_EVERY   = 20

# ── Monitor Settings ──────────────────────────────────────────
MONITOR_INTERVAL = 60
