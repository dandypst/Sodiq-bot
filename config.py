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

# ── Pairs yang akan di-trade ──────────────────────────────────
# Minimal 10 pair berbeda untuk memenuhi syarat points
TRADING_PAIRS = [
    "vBTC_vUSDC",
    "vETH_vUSDC",
    "vSOL_vUSDC",
    "vBNB_vUSDC",
    "vARB_vUSDC",
    "vOP_vUSDC",
    "vDOGE_vUSDC",
    "vAVAX_vUSDC",
    "vMATIC_vUSDC",
    "vLINK_vUSDC",
    "vUNI_vUSDC",
    "vSUI_vUSDC",
]

# ── Mode Bot ──────────────────────────────────────────────────
#
# "limit"  → Place & cancel limit order (GTX post-only)
#             - Aman, tidak ada biaya taker
#             - Volume nambah hanya kalau order kebetulan terisi
#             - Cocok untuk jalan lama tanpa khawatir saldo habis
#
# "market" → Place market order kecil, langsung terisi
#             - Volume nambah cepat setiap siklus
#             - Ada biaya taker tiap order (kecil tapi ada)
#             - Saldo USDC akan berkurang pelan-pelan
#             - Cocok untuk sprint naikin volume sebelum snapshot
#
# "hybrid" → Campur keduanya: tiap N siklus sekali pakai market,
#             sisanya pakai limit. Seimbang antara volume & efisiensi.
#
BOT_MODE = "hybrid"   # "limit" | "market" | "hybrid"

# Khusus mode "hybrid": seberapa sering pakai market order
# Contoh: 5 = setiap 5 siklus, 1 siklus pakai market, 4 pakai limit
HYBRID_MARKET_EVERY = 5

# ── Limit Order Settings ──────────────────────────────────────
# Berapa tick di luar spread untuk limit order
# (makin besar = makin kecil kemungkinan terisi = lebih aman)
PRICE_OFFSET_TICKS = 2

# timeInForce: 1=GTC, 2=IOC, 3=GTX (post-only/maker)
# GTX = order tidak akan langsung terisi sebagai taker
TIME_IN_FORCE = 3

# ── Market Order Settings ─────────────────────────────────────
# Berapa USDC yang dipakai per siklus market order
# Bot akan BUY dulu, lalu langsung SELL balik (round-trip)
# Makin besar = volume makin cepat, tapi saldo makin cepat berkurang
MARKET_ORDER_USDC = "10"   # dalam USDC (sebagai string)

# Slippage tolerance untuk market order (2% = cukup aman)
# Bot set price limit = last_price * (1 + ratio) untuk BUY
# Set ke None untuk tidak pakai price limit
MARKET_SLIPPAGE_RATIO = 0.02

# ── Timing ────────────────────────────────────────────────────
# Jeda tahan limit order sebelum cancel (detik)
ORDER_HOLD_MIN = 8
ORDER_HOLD_MAX = 20

# Jeda antar siklus trading (detik)
CYCLE_DELAY_MIN = 5
CYCLE_DELAY_MAX = 30

# Seberapa sering refresh symbol list (per N siklus)
SYMBOL_REFRESH_EVERY = 50

# Seberapa sering print status akun di log (per N siklus)
STATUS_PRINT_EVERY = 20

# ── Monitor Settings ──────────────────────────────────────────
# Interval refresh monitor.py (detik)
MONITOR_INTERVAL = 60
