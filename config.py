# ============================================================
# config.py — Edit bagian ini sesuai kebutuhan kamu
# ============================================================
import os
from dotenv import load_dotenv

load_dotenv()

# ── Kredensial (dari file .env) ───────────────────────────────
PRIVATE_KEY    = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "").strip()

# ── API Key ───────────────────────────────────────────────────
# Nama API key yang terdaftar di SoDEX (cek di /accounts/{address}/api-keys)
# Gunakan 'default' untuk sign dengan private key wallet utama
API_KEY_NAME = "default"

# ── Network ───────────────────────────────────────────────────
TESTNET_CHAIN_ID = 138565
BASE_URL         = "https://testnet-gw.sodex.dev/api/v1/spot"

# ── Target Asset ──────────────────────────────────────────────
TARGET_ASSETS = [
    "vBTC", "vETH", "vSOL", "vBNB", "vAVAX",
    "vDOGE", "vLINK", "vUNI", "vADA", "vXRP",
    "vLTC", "vAAVE",
]
QUOTE_ASSET        = "vUSDC"
MIN_PAIRS_REQUIRED = 5

# ── Mode Bot ──────────────────────────────────────────────────
# "limit"  → Place & cancel limit order (GTX post-only), aman
# "market" → Buy & sell market order, volume cepat
# "hybrid" → Campur keduanya (rekomendasi)
BOT_MODE            = "hybrid"
HYBRID_MARKET_EVERY = 5

# ── Order Size ────────────────────────────────────────────────
# Berapa persen dari saldo vUSDC yang dipakai per order
# Contoh: 0.02 = 2% dari saldo vUSDC per siklus
# Bot akan hitung qty otomatis dari saldo aktual
# Minimum tetap mengikuti minQuantity dari API
ORDER_SIZE_PCT = 0.02   # 2% dari saldo vUSDC

# Maksimum USDC per order (safety cap) — set 0 untuk tidak ada limit
ORDER_MAX_USDC = 50.0   # max 50 USDC per order

# ── Limit Order Settings ──────────────────────────────────────
PRICE_OFFSET_TICKS = 2
TIME_IN_FORCE      = 3   # 1=GTC, 2=IOC, 3=GTX (post-only)

# ── Market Order Settings ─────────────────────────────────────
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
