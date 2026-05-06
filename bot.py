# ============================================================
# bot.py — SoDEX Testnet Auto Trading Bot
# Jalankan: python bot.py
# ============================================================
import random
import time
import logging
from datetime import datetime

from config import (
    PRIVATE_KEY, WALLET_ADDRESS,
    TARGET_ASSETS, QUOTE_ASSET, MIN_PAIRS_REQUIRED,
    ORDER_HOLD_MIN, ORDER_HOLD_MAX,
    CYCLE_DELAY_MIN, CYCLE_DELAY_MAX,
    SYMBOL_REFRESH_EVERY, STATUS_PRINT_EVERY,
    PRICE_OFFSET_TICKS, TIME_IN_FORCE,
    BOT_MODE, HYBRID_MARKET_EVERY,
    MARKET_ORDER_USDC, MARKET_SLIPPAGE_RATIO,
    BASE_URL,
)
from api import (
    get_symbols, get_orderbook, get_tickers,
    get_balances, place_batch_orders, cancel_batch_orders,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("sodex_bot.log"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# SYMBOL AUTO-DETECTION
# Ambil nama pair yang benar langsung dari API, bukan hardcode.
# ══════════════════════════════════════════════════════════════

def detect_trading_pairs(all_symbols: list) -> list:
    """
    Cocokkan TARGET_ASSETS dengan symbol yang benar dari API.
    Strategi matching (urut prioritas):
      1. Cari exact match: BTC → BTC_USDC, USDC_BTC, vBTC_vUSDC, dll
      2. Cari partial match: nama mengandung asset DAN quote
      3. Fallback: pakai semua pair yang quote-nya USDC
    Return: list nama symbol yang valid dari API.
    """
    if not all_symbols:
        return []

    available = {s["symbol"]: s for s in all_symbols if s.get("symbol")}
    matched   = []
    used      = set()

    quote_upper = QUOTE_ASSET.upper()

    for asset in TARGET_ASSETS:
        asset_upper = asset.upper()
        found       = None

        # Pass 1: exact patterns yang umum dipakai
        candidates = [
            f"{asset_upper}_{quote_upper}",          # BTC_USDC
            f"v{asset_upper}_v{quote_upper}",         # vBTC_vUSDC
            f"{asset_upper}_{quote_upper.lower()}",   # BTC_usdc
            f"{asset_upper}USDC",                     # BTCUSDC
            f"{quote_upper}_{asset_upper}",           # USDC_BTC (reversed)
        ]
        for c in candidates:
            if c in available and c not in used:
                found = c
                break

        # Pass 2: partial match — cari symbol yang mengandung keduanya
        if not found:
            for sym in available:
                sym_up = sym.upper()
                if (asset_upper in sym_up and quote_upper in sym_up
                        and sym not in used):
                    found = sym
                    break

        if found:
            matched.append(found)
            used.add(found)

    # Fallback: kalau kurang dari MIN_PAIRS_REQUIRED, ambil semua USDC pairs
    if len(matched) < MIN_PAIRS_REQUIRED:
        log.warning(f"  Auto-detect hanya dapat {len(matched)} pairs, "
                    f"fallback ke semua {quote_upper} pairs...")
        for sym in available:
            if quote_upper in sym.upper() and sym not in used:
                matched.append(sym)
                used.add(sym)
                if len(matched) >= 20:   # cap 20 pairs
                    break

    return matched


def log_symbol_mapping(target_assets: list, detected_pairs: list):
    """Log hasil mapping asset → symbol yang terdeteksi."""
    log.info(f"  Auto-detected {len(detected_pairs)} trading pairs:")
    for sym in detected_pairs:
        log.info(f"    ✓ {sym}")
    if len(detected_pairs) < len(target_assets):
        missing = len(target_assets) - len(detected_pairs)
        log.warning(f"  ⚠️  {missing} asset tidak ditemukan pasangannya di API")


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def make_order_id(prefix: str) -> str:
    ts   = str(int(time.time() * 1000))[-10:]
    rand = str(random.randint(1000, 9999))
    return f"{prefix}-{ts}-{rand}"[:36]


def get_symbol_info(symbol: str, all_symbols: list) -> dict:
    for s in all_symbols:
        if s.get("symbol") == symbol:
            return s
    return None


def get_last_price(symbol: str) -> float:
    try:
        tickers = get_tickers(symbol)
        if tickers:
            return float(tickers[0].get("lastPrice", 0))
    except Exception:
        pass
    return 0.0


def round_to_precision(value: float, precision: int) -> str:
    return str(round(value, precision))


def calc_limit_price(orderbook: dict, side: str, symbol_info: dict) -> str:
    tick   = float(symbol_info.get("tickSize", "0.01"))
    prec   = int(symbol_info.get("pricePrecision", 2))
    offset = tick * PRICE_OFFSET_TICKS
    try:
        if side == "BUY":
            bids = orderbook.get("bids", [])
            if not bids:
                return None
            price = float(bids[0][0]) - offset
        else:
            asks = orderbook.get("asks", [])
            if not asks:
                return None
            price = float(asks[0][0]) + offset
        return round_to_precision(max(price, tick), prec)
    except Exception as e:
        log.error(f"calc_limit_price: {e}")
        return None


def calc_min_quantity(symbol_info: dict) -> str:
    try:
        min_qty   = float(symbol_info.get("minQuantity",  "0"))
        step_size = float(symbol_info.get("stepSize",     "0.001"))
        qty_prec  = int(symbol_info.get("quantityPrecision", 3))
        qty       = max(min_qty, step_size) if min_qty > 0 else step_size
        return round_to_precision(qty, qty_prec)
    except Exception as e:
        log.error(f"calc_min_quantity: {e}")
        return None


def calc_market_quantity(symbol_info: dict, last_price: float) -> str:
    try:
        usdc_amount = float(MARKET_ORDER_USDC)
        step_size   = float(symbol_info.get("stepSize", "0.001"))
        qty_prec    = int(symbol_info.get("quantityPrecision", 3))
        min_qty     = float(symbol_info.get("minQuantity", "0"))
        if last_price <= 0:
            return None
        qty = (usdc_amount / last_price // step_size) * step_size
        qty = round(qty, qty_prec)
        if min_qty > 0 and qty < min_qty:
            qty = min_qty
        return str(qty)
    except Exception as e:
        log.error(f"calc_market_quantity: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# LIMIT MODE
# ══════════════════════════════════════════════════════════════

def trade_limit(symbol: str, all_symbols: list, cycle: int) -> bool:
    sym_info = get_symbol_info(symbol, all_symbols)
    if not sym_info:
        log.warning(f"    Symbol info tidak ditemukan: {symbol}")
        return False

    ob = get_orderbook(symbol)
    if not ob:
        log.warning(f"    Orderbook kosong: {symbol}")
        return False

    buy_price  = calc_limit_price(ob, "BUY",  sym_info)
    sell_price = calc_limit_price(ob, "SELL", sym_info)
    qty        = calc_min_quantity(sym_info)

    if not all([buy_price, sell_price, qty]):
        log.warning(f"    Tidak bisa hitung harga/qty: {symbol}")
        return False

    if float(buy_price) <= 0 or float(sell_price) <= 0:
        log.warning(f"    Harga tidak valid: buy={buy_price} sell={sell_price}")
        return False

    buy_id  = make_order_id("LB")
    sell_id = make_order_id("LS")

    results = place_batch_orders({
        "accountID": 0,
        "symbolID":  sym_info.get("symbolID", 0),
        "orders": [
            {"clOrdID": buy_id,  "modifier": 1, "side": 1, "type": 1,
             "timeInForce": TIME_IN_FORCE, "price": buy_price,  "quantity": qty},
            {"clOrdID": sell_id, "modifier": 1, "side": 2, "type": 1,
             "timeInForce": TIME_IN_FORCE, "price": sell_price, "quantity": qty},
        ],
    })

    placed = []
    for r in results:
        if r.get("code") == 0:
            placed.append(r["clOrdID"])
            log.info(f"    ✓ [LIMIT] {r['clOrdID']}  orderID={r.get('orderID')}")
        else:
            log.warning(f"    ✗ [LIMIT] {r.get('clOrdID')}: {r.get('error')}")

    if not placed:
        return False

    hold = random.uniform(ORDER_HOLD_MIN, ORDER_HOLD_MAX)
    log.info(f"    ⏳ Hold {hold:.1f}s lalu cancel...")
    time.sleep(hold)

    cancel_results = cancel_batch_orders({
        "accountID": 0,
        "symbolID":  sym_info.get("symbolID", 0),
        "orders":    [{"clOrdID": oid} for oid in placed],
    })
    for r in cancel_results:
        if r.get("code") == 0:
            log.info(f"    ✓ Cancelled {r.get('origClOrdID')}")
        else:
            log.info(f"    ℹ Sudah terisi: {r.get('clOrdID')}")

    return True


# ══════════════════════════════════════════════════════════════
# MARKET MODE
# ══════════════════════════════════════════════════════════════

def trade_market(symbol: str, all_symbols: list, cycle: int) -> bool:
    sym_info = get_symbol_info(symbol, all_symbols)
    if not sym_info:
        log.warning(f"    Symbol info tidak ditemukan: {symbol}")
        return False

    last_price = get_last_price(symbol)
    if last_price <= 0:
        ob = get_orderbook(symbol, limit=1)
        if ob:
            asks = ob.get("asks", [])
            if asks:
                last_price = float(asks[0][0])

    if last_price <= 0:
        log.warning(f"    Tidak bisa ambil harga {symbol}")
        return False

    qty = calc_market_quantity(sym_info, last_price)
    if not qty or float(qty) <= 0:
        log.warning(f"    Qty tidak valid: {symbol} (price={last_price})")
        return False

    price_prec = int(sym_info.get("pricePrecision", 2))

    buy_price_limit = None
    if MARKET_SLIPPAGE_RATIO:
        bp = last_price * (1 + MARKET_SLIPPAGE_RATIO)
        buy_price_limit = round_to_precision(bp, price_prec)

    log.info(f"    💸 [MARKET] BUY {qty} {symbol} ~{MARKET_ORDER_USDC} USDC")

    buy_order = {"clOrdID": make_order_id("MB"), "modifier": 1,
                 "side": 1, "type": 2, "timeInForce": 2, "quantity": qty}
    if buy_price_limit:
        buy_order["price"] = buy_price_limit

    buy_results = place_batch_orders({
        "accountID": 0, "symbolID": sym_info.get("symbolID", 0),
        "orders": [buy_order],
    })

    buy_ok = False
    for r in buy_results:
        if r.get("code") == 0:
            log.info(f"    ✓ BUY filled  orderID={r.get('orderID')}")
            buy_ok = True
        else:
            log.warning(f"    ✗ BUY gagal: {r.get('error')}")

    if not buy_ok:
        return False

    pause = random.uniform(2, 8)
    log.info(f"    ⏳ Jeda {pause:.1f}s sebelum SELL...")
    time.sleep(pause)

    log.info(f"    💸 [MARKET] SELL {qty} {symbol}")

    sell_order = {"clOrdID": make_order_id("MS"), "modifier": 1,
                  "side": 2, "type": 2, "timeInForce": 2, "quantity": qty}
    if MARKET_SLIPPAGE_RATIO:
        sp = last_price * (1 - MARKET_SLIPPAGE_RATIO)
        sell_order["price"] = round_to_precision(sp, price_prec)

    sell_results = place_batch_orders({
        "accountID": 0, "symbolID": sym_info.get("symbolID", 0),
        "orders": [sell_order],
    })
    for r in sell_results:
        if r.get("code") == 0:
            log.info(f"    ✓ SELL filled  orderID={r.get('orderID')}")
        else:
            log.warning(f"    ✗ SELL gagal: {r.get('error')}")

    log.info(f"    📊 Volume ~{float(qty) * last_price * 2:.2f} USDC")
    return True


# ══════════════════════════════════════════════════════════════
# DISPATCHER
# ══════════════════════════════════════════════════════════════

def trade_pair(symbol: str, all_symbols: list, cycle: int) -> bool:
    log.info(f"  → {symbol}  (siklus #{cycle})")
    if BOT_MODE == "market":
        return trade_market(symbol, all_symbols, cycle)
    elif BOT_MODE == "limit":
        return trade_limit(symbol, all_symbols, cycle)
    elif BOT_MODE == "hybrid":
        if cycle % HYBRID_MARKET_EVERY == 0:
            log.info(f"    🔀 [HYBRID] Siklus market order")
            return trade_market(symbol, all_symbols, cycle)
        else:
            log.info(f"    🔀 [HYBRID] Siklus limit order")
            return trade_limit(symbol, all_symbols, cycle)
    else:
        log.error(f"BOT_MODE tidak dikenal: '{BOT_MODE}'")
        return False


# ══════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════

def print_status():
    log.info("─" * 55)
    log.info("📊 STATUS AKUN")
    bal = get_balances()
    if bal:
        for b in (bal.get("balances") or []):
            coin  = b.get("coin",  "?")
            free  = b.get("free",  "0")
            total = b.get("total", "0")
            if float(total) > 0:
                log.info(f"   {coin:<12} free={free:<20} total={total}")
    else:
        log.info("   (tidak bisa ambil balance)")
    log.info("─" * 55)


# ══════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════

def main():
    log.info("=" * 55)
    log.info("🤖  SoDEX Testnet Bot  —  START")
    log.info(f"    Wallet   : {WALLET_ADDRESS}")
    log.info(f"    Mode     : {BOT_MODE.upper()}")
    log.info(f"    Endpoint : {BASE_URL}")
    if BOT_MODE in ("market", "hybrid"):
        log.info(f"    USDC/siklus market: {MARKET_ORDER_USDC}")
    if BOT_MODE == "hybrid":
        log.info(f"    Market setiap: {HYBRID_MARKET_EVERY} siklus")
    log.info("=" * 55)

    if not PRIVATE_KEY:
        log.error("❌  PRIVATE_KEY tidak ada di .env — berhenti.")
        return
    if not WALLET_ADDRESS:
        log.error("❌  WALLET_ADDRESS tidak ada di .env — berhenti.")
        return

    # Ambil symbol list dari API
    all_symbols = get_symbols()
    if not all_symbols:
        log.error("❌  Tidak bisa ambil symbol list. Cek koneksi VPS.")
        return

    log.info(f"    Symbol list dari API : {len(all_symbols)} symbols")

    # ── AUTO-DETECT TRADING PAIRS ─────────────────────────────
    trading_pairs = detect_trading_pairs(all_symbols)
    if not trading_pairs:
        log.error("❌  Tidak ada pair yang cocok ditemukan. Cek TARGET_ASSETS di config.py.")
        return

    log_symbol_mapping(TARGET_ASSETS, trading_pairs)
    log.info(f"    Pairs aktif: {len(trading_pairs)}")
    # ──────────────────────────────────────────────────────────

    print_status()

    cycle      = 0
    pair_index = 0

    while True:
        cycle += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"\n{'='*55}")
        log.info(f"🔄  SIKLUS #{cycle}   —   {now}")

        # Refresh symbol list dan re-detect pairs berkala
        if cycle % SYMBOL_REFRESH_EVERY == 1 and cycle > 1:
            fresh = get_symbols()
            if fresh:
                all_symbols   = fresh
                trading_pairs = detect_trading_pairs(all_symbols)
                log.info(f"    Refreshed: {len(all_symbols)} symbols, "
                         f"{len(trading_pairs)} pairs aktif")

        # Round-robin
        symbol = trading_pairs[pair_index % len(trading_pairs)]
        pair_index += 1

        ok = trade_pair(symbol, all_symbols, cycle)
        log.info(f"  {'✅' if ok else '⏭️ '}  {symbol}  {'selesai' if ok else 'diskip'}")

        if cycle % STATUS_PRINT_EVERY == 0:
            print_status()

        delay = random.uniform(CYCLE_DELAY_MIN, CYCLE_DELAY_MAX)
        log.info(f"  💤  Jeda {delay:.1f}s...")
        time.sleep(delay)


if __name__ == "__main__":
    main()
